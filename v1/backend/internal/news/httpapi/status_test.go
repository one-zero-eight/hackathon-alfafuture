package httpapi

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/testdb"
)

func TestPostgresStatusUsageCoverageAndPause(t *testing.T) {
	db, _ := testdb.New(t)
	if err := store.Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	router, api, err := New(db)
	if err != nil {
		t.Fatal(err)
	}
	read := func() StatusOutput {
		t.Helper()
		out := get(t, router, "/v1/status", 200)
		validateResponse(t, api, "/v1/status", out)
		if strings.Contains(out.Body.String(), "PRIVATE_TRACE") {
			t.Fatal("status exposed a saved request or raw response")
		}
		var decoded StatusOutput
		if err := json.Unmarshal(out.Body.Bytes(), &decoded.Body); err != nil {
			t.Fatal(err)
		}
		return decoded
	}
	empty := read()
	if empty.Body.Articles != (ArticleCounts{}) || empty.Body.Usage != (UsageTotals{}) || empty.Body.BudgetPauseUntil != nil || empty.Body.TaggingPaused {
		t.Fatalf("empty status invented values: %+v", empty.Body)
	}
	now := time.Now().UTC().Truncate(time.Microsecond)
	if err := store.RegisterSources(t.Context(), db, []store.Source{{ID: "fixture", Name: "Fixture", FeedURL: "https://example.com/feed"}}, now); err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"retry", "processing"} {
		article, _, err := store.InsertArticle(t.Context(), db, store.Article{
			SourceID: "fixture", SourceItemID: id, URL: "https://example.com/" + id,
			CollectedAt: now, Text: "Synthetic text.", TextProvenance: store.TextFromRSSDescription,
		})
		if err != nil {
			t.Fatal(err)
		}
		attempt, err := store.StartAttempt(t.Context(), db, store.TaggingAttempt{
			ArticleID: article.ID, Version: "v1", PromptVersion: "fixture", Model: "deepseek/deepseek-v4.1-flash",
			InputText: article.Text, Request: `{"messages":[],"private":"PRIVATE_TRACE"}`, StartedAt: now,
		})
		if err != nil {
			t.Fatal(err)
		}
		if id == "retry" {
			prompt := int64(9)
			if err := store.FinishAttempt(t.Context(), db, attempt.ID, store.AttemptCompletion{
				FinishedAt: now, Response: "PRIVATE_TRACE", Error: "provider budget exhausted", FailureStatus: store.StatusPending, PromptTokens: &prompt,
			}); err != nil {
				t.Fatal(err)
			}
		}
	}
	for _, duration := range []time.Duration{time.Hour, -time.Hour} {
		until := now.Add(duration)
		if err := store.SetBudgetPause(t.Context(), db, &until); err != nil {
			t.Fatal(err)
		}
		got := read()
		usage := got.Body.Usage
		if got.Body.Articles != (ArticleCounts{Pending: 1, Processing: 1}) || got.Body.BudgetPauseUntil == nil || !got.Body.BudgetPauseUntil.Equal(until) || got.Body.TaggingPaused != (duration > 0) {
			t.Fatalf("wrong stored status: %+v", got.Body)
		}
		if usage.Attempts != 2 || usage.PromptTokens == nil || *usage.PromptTokens != 9 || usage.PromptTokensKnownAttempts != 1 || usage.CompletionTokens != nil || usage.TotalTokens != nil || usage.CompletionTokensKnownAttempts != 0 || usage.TotalTokensKnownAttempts != 0 {
			t.Fatalf("partial usage became a complete/zero bill: %+v", usage)
		}
		persisted, err := store.LoadBudgetPause(t.Context(), db)
		if err != nil || persisted == nil || !persisted.Equal(until) {
			t.Fatal("read-only status cleared or changed the pause")
		}
	}
}
