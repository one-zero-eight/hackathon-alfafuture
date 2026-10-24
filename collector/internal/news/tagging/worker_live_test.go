package tagging

import (
	"context"
	"errors"
	"os"
	"sync/atomic"
	"testing"
	"time"

	"github.com/joho/godotenv"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/testdb"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/llm"
	"github.com/openai/openai-go/v3"
)

type oneRequestClient struct {
	client  *llm.Client
	cancel  context.CancelFunc
	calls   atomic.Int32
	callErr error
}

func (c *oneRequestClient) Model() string { return c.client.Model() }
func (c *oneRequestClient) Chat(ctx context.Context, p openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
	if c.calls.Add(1) != 1 {
		return nil, errors.New("live test call limit reached")
	}
	// Cancel after the response so the worker saves it but cannot make a paid retry.
	defer c.cancel()
	reply, err := c.client.Chat(ctx, p)
	c.callErr = err
	return reply, err
}

func TestLiveWorker(t *testing.T) {
	if os.Getenv("LIVE_LLM_TEST") != "1" {
		t.Skip("set LIVE_LLM_TEST=1 for one real approved LLM request with PostgreSQL")
	}
	if path := os.Getenv("ENV_FILE"); path != "" {
		if err := godotenv.Load(path); err != nil {
			t.Fatal("cannot load live-test ENV_FILE")
		}
	}
	client, err := llm.NewFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	db, _ := testdb.New(t)
	if err := store.Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	article := queueArticle(t, db, "live-synthetic", "Банк России сообщил о сохранении ключевой ставки. Регулятор ожидает замедления инфляции.")
	ctx, cancel := context.WithTimeout(t.Context(), 3*time.Minute)
	defer cancel()
	bounded := &oneRequestClient{client: client, cancel: cancel}
	w, err := NewWorker(ctx, db, bounded, 2*time.Minute)
	if err != nil {
		t.Fatal(err)
	}
	if err := w.Run(ctx); err != nil {
		t.Fatal(err)
	}
	traces, err := store.LoadAttempts(t.Context(), db, article.ID)
	if err != nil || len(traces) != 1 || bounded.calls.Load() != 1 {
		t.Fatalf("live test expected exactly one saved request, calls=%d err=%v", bounded.calls.Load(), err)
	}
	a := traces[0]
	t.Logf("model=%s calls=1 request_bytes=%d response_bytes=%d prompt_tokens=%v completion_tokens=%v total_tokens=%v", a.Model, len(a.Request), len(a.Response), counterValue(a.PromptTokens), counterValue(a.CompletionTokens), counterValue(a.TotalTokens))
	if a.Status != store.StatusCompleted {
		t.Fatalf("live outcome not completed: %s (raw response kept only in temporary DB)", a.Error)
	}
	fact, forecast := false, false
	for _, event := range a.Events {
		if event.Status == nil {
			continue
		}
		fact = fact || event.TagID == "event:monetary_policy_decision" && *event.Status == "observed"
		forecast = forecast || event.TagID == "event:inflation" && *event.Status == "forecast"
	}
	if !fact || !forecast {
		t.Fatal("live model did not distinguish the monetary decision from the inflation forecast")
	}
}

func counterValue(n *int64) any {
	if n == nil {
		return "unknown"
	}
	return *n
}
