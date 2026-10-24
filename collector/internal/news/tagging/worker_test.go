package tagging

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/testdb"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/llm"
	"github.com/openai/openai-go/v3"
	"gorm.io/gorm"
)

type fakeChat struct {
	calls atomic.Int32
	call  func(context.Context, openai.ChatCompletionNewParams) (*openai.ChatCompletion, error)
}

func (f *fakeChat) Model() string { return llm.DefaultModel }
func (f *fakeChat) Chat(ctx context.Context, p openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
	f.calls.Add(1)
	return f.call(ctx, p)
}

func workerFixture(t *testing.T) (*Worker, *fakeChat, string, *time.Time) {
	t.Helper()
	db, dsn := testdb.New(t)
	if err := store.Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	reply := fixtureReply(t, completionBody())
	client := &fakeChat{call: func(context.Context, openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
		return reply, nil
	}}
	w, err := NewWorker(t.Context(), db, client, 2*time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 10, 23, 9, 1, 0, 0, time.UTC)
	w.now = func() time.Time { return now }
	return w, client, dsn, &now
}

func queueArticle(t *testing.T, db *gorm.DB, id, text string) store.Article {
	t.Helper()
	now := time.Date(2026, 10, 23, 8, 0, 0, 0, time.UTC)
	if err := store.RegisterSources(t.Context(), db, []store.Source{{ID: "rbc", Name: "РБК", FeedURL: "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"}}, now); err != nil {
		t.Fatal(err)
	}
	provenance := ""
	if text != "" {
		provenance = store.TextFromRSSFullText
	}
	a, _, err := store.InsertArticle(t.Context(), db, store.Article{SourceID: "rbc", SourceItemID: id, URL: "https://www.rbc.ru/fixture", Text: text, TextProvenance: provenance, CollectedAt: now})
	if err != nil {
		t.Fatal(err)
	}
	return a
}

func stepOK(t *testing.T, w *Worker) time.Duration {
	t.Helper()
	delay, err := w.step(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	return delay
}

func apiFailure(status int, body string) error {
	return &openai.Error{StatusCode: status, Response: &http.Response{Body: io.NopCloser(strings.NewReader(body))}}
}

func TestClassifyFailureDoesNotExposeProviderOrTransportText(t *testing.T) {
	for _, status := range []int{400, 401, 403, 408, 409, 429, 500, 503, 599} {
		failure := classifyFailure(apiFailure(status, "sk-PRIVATE response"))
		want := status == 408 || status == 429 || status >= 500
		if failure.retryable != want || failure.budget || strings.Contains(failure.diagnostic, "PRIVATE") || failure.response != "sk-PRIVATE response" {
			t.Fatalf("incorrect HTTP error policy: %d %+v", status, failure)
		}
	}
	for _, err := range []error{context.DeadlineExceeded, io.EOF, io.ErrUnexpectedEOF, &net.OpError{Op: "dial", Err: errors.New("sk-PRIVATE")}} {
		if failure := classifyFailure(err); !failure.retryable || strings.Contains(failure.diagnostic, "PRIVATE") {
			t.Fatal("transient network failure mishandled")
		}
	}
	if failure := classifyFailure(errors.New("sk-PRIVATE invalid request")); failure.retryable || strings.Contains(failure.diagnostic, "PRIVATE") {
		t.Fatal("unexpected errors must not be blindly retried")
	}
}

func TestPostgresWorkerPersistsRequestBeforeCallAndSkipsFinishedRows(t *testing.T) {
	w, client, _, _ := workerFixture(t)
	a := queueArticle(t, w.db, "ready", completionText)
	queueArticle(t, w.db, "empty", "")
	reply := fixtureReply(t, completionBody())
	client.call = func(ctx context.Context, p openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
		if _, ok := ctx.Deadline(); !ok {
			return nil, errors.New("missing LLM timeout")
		}
		trace, err := store.LoadAttempts(ctx, w.db, a.ID)
		raw, marshalErr := json.Marshal(p)
		if err != nil || marshalErr != nil || len(trace) != 1 || trace[0].Status != store.StatusProcessing || trace[0].Request != string(raw) || trace[0].InputText != completionText {
			return nil, errors.New("request not saved before API call")
		}
		return reply, nil
	}
	stepOK(t, w)
	stored, err := store.LoadArticle(t.Context(), w.db, a.ID)
	if err != nil || stored.ProcessingStatus != store.StatusCompleted || client.calls.Load() != 1 {
		t.Fatalf("article not completed: %+v %v", stored, err)
	}
	if delay := stepOK(t, w); delay != time.Second || client.calls.Load() != 1 {
		t.Fatal("finished or empty article was processed again")
	}
}

func TestPostgresWorkerBackoffSurvivesReconnectAndCapsRetries(t *testing.T) {
	w, client, dsn, clock := workerFixture(t)
	a := queueArticle(t, w.db, "retry", completionText)
	reply := fixtureReply(t, completionBody())
	client.call = func(context.Context, openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
		if client.calls.Load() < 3 {
			return nil, apiFailure(503, "temporary sk-PRIVATE")
		}
		return reply, nil
	}
	stepOK(t, w)
	if stepOK(t, w) != 10*time.Second || client.calls.Load() != 1 {
		t.Fatal("first retry was not delayed")
	}
	pool, _ := w.db.DB()
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}
	db, err := store.Open(t.Context(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	testdb.Close(t, db)
	w, err = NewWorker(t.Context(), db, client, 2*time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	w.now = func() time.Time { return *clock }
	*clock = clock.Add(9 * time.Second)
	if stepOK(t, w) != time.Second || client.calls.Load() != 1 {
		t.Fatal("restart reset saved backoff")
	}
	*clock = clock.Add(time.Second)
	stepOK(t, w)
	if stepOK(t, w) != 30*time.Second || client.calls.Load() != 2 {
		t.Fatal("second retry was not delayed")
	}
	*clock = clock.Add(30 * time.Second)
	stepOK(t, w)
	traces, err := store.LoadAttempts(t.Context(), db, a.ID)
	if err != nil || len(traces) != 3 || traces[2].Status != store.StatusCompleted || traces[0].PromptTokens != nil || traces[0].Response != "temporary sk-PRIVATE" || strings.Contains(traces[0].Error, "PRIVATE") {
		t.Fatal("retry trace lost or incorrect")
	}
	a = queueArticle(t, db, "exhaust", completionText)
	client.call = func(context.Context, openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
		return nil, apiFailure(500, "down")
	}
	for _, advance := range []time.Duration{0, 10 * time.Second, 30 * time.Second} {
		*clock = clock.Add(advance)
		stepOK(t, w)
	}
	stored, err := store.LoadArticle(t.Context(), db, a.ID)
	if err != nil || stored.ProcessingStatus != store.StatusFailed || client.calls.Load() != 6 {
		t.Fatalf("more than two retries: %+v calls=%d %v", stored, client.calls.Load(), err)
	}
	stepOK(t, w)
	if client.calls.Load() != 6 {
		t.Fatal("exhausted article retried again")
	}
}

func TestPostgresWorkerPermanentAndInvalidRepliesAreTerminal(t *testing.T) {
	w, client, _, _ := workerFixture(t)
	for _, invalidReply := range []bool{false, true} {
		a := queueArticle(t, w.db, time.Now().String(), completionText)
		body := completionBody()
		choice(body)["finish_reason"] = "length"
		reply := fixtureReply(t, body)
		client.call = func(context.Context, openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
			if invalidReply {
				return reply, nil
			}
			return nil, apiFailure(401, "sk-PRIVATE")
		}
		stepOK(t, w)
		stored, err := store.LoadArticle(t.Context(), w.db, a.ID)
		if err != nil || stored.ProcessingStatus != store.StatusFailed {
			t.Fatal("permanent failure was not terminal")
		}
	}
	stepOK(t, w)
	if client.calls.Load() != 2 {
		t.Fatal("invalid replies were repaired with extra calls")
	}
}

func TestPostgresWorkerRecoversInterruptedAttemptsWithinSameLimit(t *testing.T) {
	for _, number := range []int{1, 3} {
		t.Run(string(rune('0'+number)), func(t *testing.T) {
			w, client, _, clock := workerFixture(t)
			a := startCompletionAttempt(t, w.db, "interrupted")
			for n := 1; n < number; n++ {
				if err := store.FinishAttempt(t.Context(), w.db, a.ID, store.AttemptCompletion{FinishedAt: *clock, Error: "transient", FailureStatus: store.StatusPending}); err != nil {
					t.Fatal(err)
				}
				a.ID = 0
				a.StartedAt = *clock
				var err error
				a, err = store.StartAttempt(t.Context(), w.db, a)
				if err != nil {
					t.Fatal(err)
				}
			}
			if err := w.recover(t.Context()); err != nil {
				t.Fatal(err)
			}
			trace, err := store.LoadAttempt(t.Context(), w.db, a.ID)
			if err != nil || trace.Status != store.StatusFailed || trace.PromptTokens != nil || !strings.Contains(trace.Error, "unknown") {
				t.Fatal("interrupted attempt not preserved as unknown")
			}
			if number == 1 {
				if stepOK(t, w) != 10*time.Second {
					t.Fatal("recovered retry skipped delay")
				}
				*clock = clock.Add(10 * time.Second)
				stepOK(t, w)
				if client.calls.Load() != 1 {
					t.Fatal("recovered article not retried")
				}
			} else {
				stepOK(t, w)
				if client.calls.Load() != 0 {
					t.Fatal("restart allowed a fourth attempt")
				}
			}
		})
	}
}

func TestPostgresWorkerBudgetPauseIsDurableAndResumesAtMoscowReset(t *testing.T) {
	for _, tc := range []struct {
		name, body           string
		hour, minute, second int
	}{
		{"plain before reset", "Budget has been exceeded", 2, 59, 50},
		{"JSON at reset", `{"error":{"message":"Budget has been exceeded"}}`, 3, 0, 0},
		{"JSON after reset", `{"error":{"message":"Budget has been exceeded"}}`, 12, 0, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			w, client, _, clock := workerFixture(t)
			*clock = time.Date(2026, 10, 23, tc.hour, tc.minute, tc.second, 0, w.moscow)
			queueArticle(t, w.db, "budget", completionText)
			reply := fixtureReply(t, completionBody())
			client.call = func(context.Context, openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
				if client.calls.Load() == 1 {
					return nil, apiFailure(403, tc.body)
				}
				return reply, nil
			}
			stepOK(t, w)
			pause, err := store.LoadBudgetPause(t.Context(), w.db)
			if err != nil || pause == nil || pause.In(w.moscow).Hour() != 3 || !pause.After(*clock) {
				t.Fatalf("incorrect reset: %v %v", pause, err)
			}
			if tc.hour >= 3 && pause.In(w.moscow).Day() != 24 {
				t.Fatal("reset at/past03:00 must use next day")
			}
			restarted, err := NewWorker(t.Context(), w.db, client, 2*time.Minute)
			if err != nil {
				t.Fatal(err)
			}
			restarted.now = func() time.Time { return *clock }
			if stepOK(t, restarted) != pause.Sub(*clock) || client.calls.Load() != 1 {
				t.Fatal("restart ignored saved budget pause")
			}
			*clock = *pause
			stepOK(t, restarted)
			if client.calls.Load() != 2 {
				t.Fatal("did not resume at reset")
			}
			if pause, err := store.LoadBudgetPause(t.Context(), w.db); err != nil || pause != nil {
				t.Fatal("expired pause not cleared")
			}
		})
	}
}

func TestPostgresBudgetPauseAndAttemptRollbackTogether(t *testing.T) {
	w, _, _, clock := workerFixture(t)
	a := startCompletionAttempt(t, w.db, "budget-rollback")
	err := store.FinishBudgetAttempt(t.Context(), w.db, a.ID, store.AttemptCompletion{FinishedAt: *clock, Error: "provider budget exhausted", FailureStatus: store.StatusPending}, time.Time{})
	if err == nil {
		t.Fatal("invalid pause accepted")
	}
	stored, err := store.LoadAttempt(t.Context(), w.db, a.ID)
	if err != nil || stored.Status != store.StatusProcessing || stored.FinishedAt != nil {
		t.Fatal("failed pause left partial completed attempt")
	}
	if pause, err := store.LoadBudgetPause(t.Context(), w.db); err != nil || pause != nil {
		t.Fatal("failed budget transaction changed pause")
	}
}

func TestPostgresWorkerLockAndGracefulCancellation(t *testing.T) {
	w, client, _, _ := workerFixture(t)
	w.now = time.Now
	a := queueArticle(t, w.db, "cancel", completionText)
	started := make(chan struct{})
	client.call = func(ctx context.Context, _ openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
		close(started)
		<-ctx.Done()
		return nil, ctx.Err()
	}
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- w.Run(ctx) }()
	select {
	case <-started:
	case <-time.After(5 * time.Second):
		t.Fatal("worker did not start immediately")
	}
	other, err := NewWorker(t.Context(), w.db, client, 2*time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if err := other.Run(t.Context()); err == nil || !strings.Contains(err.Error(), "already running") {
		t.Fatalf("second worker could recover live work: %v", err)
	}
	cancel()
	select {
	case err := <-done:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("worker failed to stop")
	}
	trace, err := store.LoadAttempts(t.Context(), w.db, a.ID)
	if err != nil || len(trace) != 1 || trace[0].Status != store.StatusFailed || trace[0].PromptTokens != nil || !strings.Contains(trace[0].Error, "unknown") {
		t.Fatal("cancelled attempt not saved before shutdown")
	}
	ctx2, cancel2 := context.WithTimeout(t.Context(), 30*time.Millisecond)
	defer cancel2()
	if err := other.Run(ctx2); err != nil {
		t.Fatalf("worker lock was not released: %v", err)
	}
	if client.calls.Load() != 1 {
		t.Fatal("restarting bypassed persisted delay")
	}
}

func TestPostgresWorkerTimeoutAndReceivedResponseDuringShutdown(t *testing.T) {
	w, client, _, _ := workerFixture(t)
	w.timeout = 10 * time.Millisecond
	queueArticle(t, w.db, "timeout", completionText)
	client.call = func(ctx context.Context, _ openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
		<-ctx.Done()
		return nil, ctx.Err()
	}
	stepOK(t, w)
	if stepOK(t, w) != 10*time.Second || client.calls.Load() != 1 {
		t.Fatal("deadline was not treated as delayed transient failure")
	}
	// A known paid result is more useful than replaying after graceful shutdown.
	w2, client2, _, _ := workerFixture(t)
	a := queueArticle(t, w2.db, "received", completionText)
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	reply := fixtureReply(t, completionBody())
	client2.call = func(context.Context, openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
		cancel()
		return reply, nil
	}
	if _, err := w2.step(ctx); err != nil {
		t.Fatal(err)
	}
	stored, err := store.LoadArticle(t.Context(), w2.db, a.ID)
	if err != nil || stored.ProcessingStatus != store.StatusCompleted {
		t.Fatal("known response lost during cancellation")
	}
	w3, client3, _, _ := workerFixture(t)
	a3 := queueArticle(t, w3.db, "known-error", completionText)
	ctx3, cancel3 := context.WithCancel(t.Context())
	defer cancel3()
	client3.call = func(context.Context, openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
		cancel3()
		return nil, apiFailure(401, "confirmed provider error")
	}
	if _, err := w3.step(ctx3); err != nil {
		t.Fatal(err)
	}
	traces, err := store.LoadAttempts(t.Context(), w3.db, a3.ID)
	stored3, loadErr := store.LoadArticle(t.Context(), w3.db, a3.ID)
	if err != nil || loadErr != nil || len(traces) != 1 || traces[0].Error != "LLM returned HTTP 401" || stored3.ProcessingStatus != store.StatusFailed {
		t.Fatal("known HTTP failure was mislabeled as an unknown cancelled request")
	}
}
