package tagging

import (
	"context"
	"database/sql/driver"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net"
	"strings"
	"time"
	_ "time/tzdata"

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/vocabulary"
	"github.com/openai/openai-go/v3"
	"gorm.io/gorm"
)

const maxAttempts = 3

var retryDelays = [...]time.Duration{10 * time.Second, 30 * time.Second}

type chatClient interface {
	Model() string
	Chat(context.Context, openai.ChatCompletionNewParams) (*openai.ChatCompletion, error)
}

type Worker struct {
	db      *gorm.DB
	client  chatClient
	v       vocabulary.Vocabulary
	timeout time.Duration
	now     func() time.Time
	moscow  *time.Location
}

func NewWorker(ctx context.Context, db *gorm.DB, client chatClient, timeout time.Duration) (*Worker, error) {
	if db == nil || client == nil || timeout <= 0 {
		return nil, errors.New("tagging worker requires a database, client and positive timeout")
	}
	seed, err := vocabulary.Load()
	if err != nil {
		return nil, errors.New("cannot read tagging vocabulary version")
	}
	v, err := store.LoadVocabulary(ctx, db, seed.Version)
	if err != nil {
		return nil, errors.New("cannot load tagging vocabulary")
	}
	moscow, err := time.LoadLocation("Europe/Moscow")
	if err != nil {
		return nil, errors.New("cannot load Moscow time zone")
	}
	return &Worker{db: db, client: client, v: v, timeout: timeout, now: time.Now, moscow: moscow}, nil
}

// Run owns a session lock until shutdown; a second worker cannot recover or replay live work.
func (w *Worker) Run(ctx context.Context) error {
	if ctx.Err() != nil {
		return nil
	}
	pool, err := w.db.DB()
	if err != nil {
		return errors.New("cannot access worker database pool")
	}
	conn, err := pool.Conn(ctx)
	if err != nil {
		if ctx.Err() != nil {
			return nil
		}
		return errors.New("cannot open worker lock connection")
	}
	defer func() { _ = conn.Close() }()
	var acquired bool
	if err := conn.QueryRowContext(ctx, "SELECT pg_try_advisory_lock(hashtextextended(current_schema() || ':news-tagging', 0))").Scan(&acquired); err != nil {
		if ctx.Err() != nil {
			return nil
		}
		return errors.New("cannot acquire tagging worker lock")
	}
	if !acquired {
		return errors.New("tagging worker is already running")
	}
	defer func() {
		cleanup, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if _, err := conn.ExecContext(cleanup, "SELECT pg_advisory_unlock(hashtextextended(current_schema() || ':news-tagging', 0))"); err != nil {
			// Do not return a possibly still-locked connection to the pool.
			_ = conn.Raw(func(any) error { return driver.ErrBadConn })
		}
	}()
	if err := w.recover(ctx); err != nil {
		if ctx.Err() != nil {
			return nil
		}
		return err
	}
	for ctx.Err() == nil {
		if err := conn.PingContext(ctx); err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return errors.New("tagging worker lock connection lost")
		}
		delay, err := w.step(ctx)
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return err
		}
		if delay <= 0 {
			continue
		}
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return nil
		case <-timer.C:
		}
	}
	return nil
}

func (w *Worker) recover(ctx context.Context) error {
	attempts, err := store.ProcessingAttempts(ctx, w.db)
	if err != nil {
		return errors.New("cannot load interrupted tagging attempts")
	}
	for _, attempt := range attempts {
		at := w.now().UTC()
		if at.Before(attempt.StartedAt) {
			at = attempt.StartedAt
		}
		status := store.StatusPending
		if attempt.Number >= maxAttempts {
			status = store.StatusFailed
		}
		if err := store.FinishAttempt(ctx, w.db, attempt.ID, store.AttemptCompletion{
			FinishedAt: at, Error: "tagging request interrupted; outcome and usage unknown", FailureStatus: status,
		}); err != nil {
			return errors.New("cannot recover interrupted tagging attempt")
		}
	}
	return nil
}

func (w *Worker) step(ctx context.Context) (time.Duration, error) {
	now := w.now().UTC()
	pause, err := store.LoadBudgetPause(ctx, w.db)
	if err != nil {
		return 0, errors.New("cannot read tagging budget pause")
	}
	if pause != nil {
		if pause.After(now) {
			return pause.Sub(now), nil
		}
		if err := store.SetBudgetPause(ctx, w.db, nil); err != nil {
			return 0, errors.New("cannot clear tagging budget pause")
		}
	}
	// shortcut: oldest-item retries hold the queue; schedule by due time if throughput needs fairness.
	article, err := store.NextArticleForTagging(ctx, w.db)
	if errors.Is(err, gorm.ErrRecordNotFound) {
		return time.Second, nil
	}
	if err != nil {
		return 0, errors.New("cannot read tagging queue")
	}
	attempts, err := store.LoadAttempts(ctx, w.db, article.ID)
	if err != nil {
		return 0, errors.New("cannot read tagging attempt history")
	}
	if len(attempts) > 0 {
		last := attempts[len(attempts)-1]
		if last.Number >= maxAttempts {
			if err := store.FailPendingArticle(ctx, w.db, article.ID); err != nil {
				return 0, errors.New("cannot close exhausted tagging article")
			}
			return 0, nil
		}
		if last.FinishedAt == nil {
			return 0, errors.New("pending article has an unfinished attempt")
		}
		if due := last.FinishedAt.Add(retryDelays[last.Number-1]); due.After(now) {
			return due.Sub(now), nil
		}
	}
	request, err := BuildRequest(w.v, article.Text, w.client.Model())
	if err != nil {
		return 0, err
	}
	raw, err := json.Marshal(request)
	if err != nil {
		return 0, errors.New("cannot serialize tagging request")
	}
	attempt, err := store.StartAttempt(ctx, w.db, store.TaggingAttempt{
		ArticleID: article.ID, Version: w.v.Version, PromptVersion: PromptVersion, Model: request.Model,
		InputText: article.Text, Request: string(raw), StartedAt: now,
	})
	if errors.Is(err, store.ErrArticleNotPending) {
		return 0, nil
	}
	if err != nil {
		return 0, errors.New("cannot start tagging attempt")
	}
	callCtx, cancel := context.WithTimeout(ctx, w.timeout)
	reply, callErr := w.client.Chat(callCtx, request)
	cancel()
	// A received paid response should still be saved during graceful cancellation.
	saveCtx, saveCancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
	defer saveCancel()
	at := w.now().UTC()
	if at.Before(attempt.StartedAt) {
		at = attempt.StartedAt
	}
	var outcome store.AttemptCompletion
	if callErr == nil {
		outcome, err = FinishCompletion(saveCtx, w.db, attempt.ID, reply, at)
	} else {
		failure := classifyFailure(callErr)
		if ctx.Err() != nil && errors.Is(callErr, ctx.Err()) {
			failure.diagnostic, failure.retryable = "tagging request interrupted; outcome and usage unknown", true
		}
		status := store.StatusFailed
		if (failure.retryable || failure.budget) && attempt.Number < maxAttempts {
			status = store.StatusPending
		}
		outcome = store.AttemptCompletion{FinishedAt: at, Response: failure.response, Error: failure.diagnostic, FailureStatus: status}
		if failure.budget {
			local := at.In(w.moscow)
			until := time.Date(local.Year(), local.Month(), local.Day(), 3, 0, 0, 0, w.moscow)
			if !until.After(local) {
				until = until.AddDate(0, 0, 1)
			}
			err = store.FinishBudgetAttempt(saveCtx, w.db, attempt.ID, outcome, until)
		} else {
			err = store.FinishAttempt(saveCtx, w.db, attempt.ID, outcome)
		}
	}
	if err != nil {
		return 0, errors.New("cannot save tagging outcome; request must not be replayed in this process")
	}
	slog.Info("tagging attempt finished", "article_id", article.ID, "attempt", attempt.Number,
		"completed", outcome.Result != nil, "error", outcome.Error, "prompt_tokens", outcome.PromptTokens,
		"completion_tokens", outcome.CompletionTokens, "total_tokens", outcome.TotalTokens)
	return 0, nil
}

type callFailure struct {
	response, diagnostic string
	retryable, budget    bool
}

func classifyFailure(err error) callFailure {
	failure := callFailure{diagnostic: "LLM request failed"}
	var apiErr *openai.Error
	if errors.As(err, &apiErr) {
		failure.response = apiErr.RawJSON()
		if apiErr.Response != nil && apiErr.Response.Body != nil {
			body, _ := io.ReadAll(apiErr.Response.Body)
			_ = apiErr.Response.Body.Close()
			if len(body) > 0 {
				failure.response = string(body)
			}
		}
		failure.budget = strings.Contains(apiErr.Message, "Budget has been exceeded") || strings.Contains(failure.response, "Budget has been exceeded")
		failure.retryable = apiErr.StatusCode == 408 || apiErr.StatusCode == 429 || (apiErr.StatusCode >= 500 && apiErr.StatusCode <= 599)
		failure.diagnostic = fmt.Sprintf("LLM returned HTTP %d", apiErr.StatusCode)
		if failure.budget {
			failure.diagnostic = "provider budget exhausted"
		}
		return failure
	}
	var networkErr net.Error
	failure.retryable = errors.As(err, &networkErr) || errors.Is(err, context.DeadlineExceeded) || errors.Is(err, io.EOF) || errors.Is(err, io.ErrUnexpectedEOF)
	return failure
}
