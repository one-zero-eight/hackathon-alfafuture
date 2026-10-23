package tagging

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/config"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/feed"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/httpapi"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/testdb"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/llm"
)

func TestLivePublisherWorker(t *testing.T) {
	if os.Getenv("LIVE_LLM_TEST") != "1" || os.Getenv("LIVE_RSS_TEST") != "1" {
		t.Skip("set LIVE_LLM_TEST=1 and LIVE_RSS_TEST=1 for up to two real publisher/LLM checks")
	}
	cfg, err := config.Load()
	if err != nil {
		t.Fatal(err)
	}
	client, err := llm.NewFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	for _, source := range []store.Source{
		{ID: "rbc", Name: "РБК", FeedURL: cfg.RBCFeedURL},
		{ID: "cbr", Name: "Банк России", FeedURL: cfg.CBRFeedURL},
	} {
		if !t.Run(source.ID, func(t *testing.T) {
			db, dsn := testdb.New(t)
			if err := store.Bootstrap(t.Context(), db); err != nil {
				t.Fatal(err)
			}
			now := time.Now().UTC()
			if err := store.RegisterSources(t.Context(), db, []store.Source{source}, now); err != nil {
				t.Fatal(err)
			}
			publisher, err := feed.New(source.ID, source.FeedURL, cfg.FetchTimeout, cfg.FetchMaxBytes)
			if err != nil {
				t.Fatal(err)
			}
			discovery, err := publisher.Discover(t.Context())
			if err != nil {
				t.Fatal("live RSS discovery failed", err)
			}
			var selected *feed.Entry
			for _, entry := range discovery.Entries {
				if entry.PublishedAt != nil && entry.PublishedAt.Before(now.Add(-24*time.Hour)) {
					continue
				}
				if source.ID == "rbc" && (entry.Text == "" || len(entry.Text) > 16_000) {
					continue
				}
				selected = &entry
				break
			}
			if selected == nil {
				t.Fatal("no current item suitable for the bounded smoke test; no paid call made")
			}
			input := store.Article{
				SourceID: selected.SourceID, SourceItemID: selected.SourceItemID, URL: selected.URL, Title: selected.Title,
				PublishedAt: selected.PublishedAt, CollectedAt: now, Text: selected.Text,
				TextProvenance: selected.TextProvenance, TextError: selected.TextError,
			}
			article, inserted, err := store.InsertArticle(t.Context(), db, input)
			if err != nil || !inserted {
				t.Fatal("cannot insert the selected article", err)
			}
			if source.ID == "cbr" {
				entry, err := publisher.FetchText(t.Context(), *selected)
				if err != nil {
					t.Fatal("live CBR extraction failed", err)
				}
				article, err = store.RecordArticleText(t.Context(), db, article.ID, entry.Text, entry.TextProvenance, nil)
				if err != nil {
					t.Fatal(err)
				}
			}
			if article.Text == "" || len(article.Text) > 16_000 {
				t.Fatal("selected article is empty or exceeds the smoke-test size limit; no paid call made")
			}
			if err := store.RecordSourcePoll(t.Context(), db, source.ID, time.Now(), nil); err != nil {
				t.Fatal(err)
			}
			t.Logf("source=%s url=%s text_bytes=%d provenance=%s", source.ID, article.URL, len(article.Text), article.TextProvenance)
			ctx, cancel := context.WithTimeout(t.Context(), 3*time.Minute)
			defer cancel()
			bounded := &oneRequestClient{client: client, cancel: cancel}
			worker, err := NewWorker(ctx, db, bounded, cfg.LLMTimeout)
			if err != nil {
				t.Fatal(err)
			}
			if err := worker.Run(ctx); err != nil {
				t.Fatal(err)
			}
			if bounded.callErr != nil {
				t.Logf("call_error_type=%T (raw diagnostic omitted)", bounded.callErr)
			}
			attempts, err := store.LoadAttempts(t.Context(), db, article.ID)
			if err != nil || len(attempts) != 1 || bounded.calls.Load() != 1 {
				t.Fatal("expected exactly one saved request", err)
			}
			a := attempts[0]
			t.Logf("model=%s calls=1 request_bytes=%d response_bytes=%d tags=%d events=%d prompt_tokens=%v completion_tokens=%v total_tokens=%v", a.Model, len(a.Request), len(a.Response), len(a.Assignments), len(a.Events), counterValue(a.PromptTokens), counterValue(a.CompletionTokens), counterValue(a.TotalTokens))
			if a.Status != store.StatusCompleted {
				t.Fatalf("live tagging outcome not completed: %s (raw trace kept only in temporary DB)", a.Error)
			}
			before, err := store.LoadArticle(t.Context(), db, article.ID)
			if err != nil {
				t.Fatal(err)
			}
			sources, err := store.ListSources(t.Context(), db)
			if err != nil {
				t.Fatal(err)
			}
			pool, err := db.DB()
			if err != nil || pool.Close() != nil {
				t.Fatal("cannot close initial database pool")
			}
			reopened, err := store.Open(t.Context(), dsn)
			if err != nil {
				t.Fatal(err)
			}
			testdb.Close(t, reopened)
			if err := store.Bootstrap(t.Context(), reopened); err != nil {
				t.Fatal(err)
			}
			if err := store.RegisterSources(t.Context(), reopened, []store.Source{source}, now.Add(time.Hour)); err != nil {
				t.Fatal(err)
			}
			after, inserted, err := store.InsertArticle(t.Context(), reopened, input)
			if err != nil || inserted || !reflect.DeepEqual(before, after) {
				t.Fatal("replayed discovery changed the persisted article", err)
			}
			afterAttempts, err := store.LoadAttempts(t.Context(), reopened, article.ID)
			if err != nil || !reflect.DeepEqual(attempts, afterAttempts) {
				t.Fatal("attempt trace or results changed after reconnect", err)
			}
			afterSources, err := store.ListSources(t.Context(), reopened)
			if err != nil || !reflect.DeepEqual(sources, afterSources) {
				t.Fatal("source cutoff or history changed after reconnect", err)
			}
			worker, err = NewWorker(t.Context(), reopened, bounded, cfg.LLMTimeout)
			if err != nil {
				t.Fatal(err)
			}
			if stepOK(t, worker) != time.Second || bounded.calls.Load() != 1 {
				t.Fatal("completed article was queued again")
			}
			gin.SetMode(gin.ReleaseMode)
			router, _, err := httpapi.New(reopened)
			if err != nil {
				t.Fatal(err)
			}
			server := httptest.NewServer(router)
			defer server.Close()
			read := func(path string, target any) {
				t.Helper()
				response, err := server.Client().Get(server.URL + path)
				if err != nil {
					t.Fatal(err)
				}
				defer func() { _ = response.Body.Close() }()
				if response.StatusCode != http.StatusOK || json.NewDecoder(response.Body).Decode(target) != nil {
					t.Fatal("HTTP read failed", path, response.StatusCode)
				}
			}
			var detail httpapi.NewsDetailOutput
			read(fmt.Sprintf("/v1/news/%d", article.ID), &detail.Body)
			got := detail.Body.Article
			if got.ID != article.ID || got.URL != article.URL || got.Text != article.Text || got.ProcessingStatus != store.StatusCompleted || got.Tagging == nil || len(detail.Body.Attempts) != 1 || len(got.Tagging.Tags) != len(a.Assignments) || len(got.Tagging.Events) != len(a.Events) {
				t.Fatal("HTTP detail lost the completed snapshot or tagging")
			}
			var page httpapi.ListNewsOutput
			read("/v1/news?source_id="+source.ID, &page.Body)
			if len(page.Body.Items) != 1 || !reflect.DeepEqual(page.Body.Items[0], got) {
				t.Fatal("HTTP list and detail disagree")
			}
			t.Log("reconnect=ok replay=deduplicated worker_replay=none HTTP_list_detail=ok")
		}) {
			return
		}
	}
}
