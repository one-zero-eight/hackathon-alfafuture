package main

import (
	"context"
	"errors"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/testdb"
)

type fixtureTransport func(*http.Request) (*http.Response, error)

func (f fixtureTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func isolatedEnvironment(t *testing.T) {
	t.Helper()
	path := filepath.Join(t.TempDir(), ".env")
	if err := os.WriteFile(path, nil, 0600); err != nil {
		t.Fatal(err)
	}
	for key, value := range map[string]string{
		"ENV_FILE": path, "HTTP_ADDR": "127.0.0.1:8080", "POLL_INTERVAL": "20ms",
		"FETCH_TIMEOUT": "1s", "FETCH_MAX_MB": "1", "LLM_API_KEY": "",
		"RBC_FEED_URL":        "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
		"KOMMERSANT_FEED_URL": "https://www.kommersant.ru/RSS/news.xml",
		"CBR_FEED_URL":        "https://www.cbr.ru/rss/eventrss",
	} {
		t.Setenv(key, value)
	}
}

func TestRunRejectsMissingDatabaseAndHonorsCancellation(t *testing.T) {
	isolatedEnvironment(t)
	t.Setenv("DATABASE_URL", "")
	if err := run(t.Context()); err == nil {
		t.Fatal("missing database configuration accepted")
	}
	t.Setenv("DATABASE_URL", "postgres://localhost/unused")
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	if err := run(ctx); !errors.Is(err, context.Canceled) {
		t.Fatalf("startup ignored cancellation: %v", err)
	}
}

func TestPostgresRunCollectsAndStopsWithoutLLMKey(t *testing.T) {
	db, dsn := testdb.New(t)
	isolatedEnvironment(t)
	t.Setenv("DATABASE_URL", dsn)
	previous := http.DefaultTransport
	http.DefaultTransport = fixtureTransport(func(r *http.Request) (*http.Response, error) {
		status, body := http.StatusOK, ""
		switch r.URL.String() {
		case "https://rssexport.rbc.ru/rbcnews/news/30/full.rss":
			body = `<rss version="2.0"><channel><title>Fixture</title><item><guid>rbc</guid><link>https://www.rbc.ru/fixture</link><description>RSS fixture text.</description></item></channel></rss>`
		case "https://www.kommersant.ru/RSS/news.xml":
			status = http.StatusServiceUnavailable
		case "https://www.cbr.ru/rss/eventrss":
			body = `<rss version="2.0"><channel><title>Fixture</title><item><guid>cbr</guid><link>https://www.cbr.ru/fixture</link></item></channel></rss>`
		case "https://www.cbr.ru/fixture":
			body = `<main id="content"><div class="lead-text">CBR fixture text.</div></main>`
		default:
			return nil, errors.New("unexpected external request")
		}
		return &http.Response{StatusCode: status, Header: make(http.Header), ContentLength: -1, Body: io.NopCloser(strings.NewReader(body))}, nil
	})
	t.Cleanup(func() { http.DefaultTransport = previous })
	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan error, 1)
	go func() { done <- run(ctx) }()
	t.Cleanup(func() {
		cancel()
		select {
		case err := <-done:
			if err != nil {
				t.Errorf("entrypoint returned an error: %v", err)
			}
		case <-time.After(5 * time.Second):
			t.Error("entrypoint did not stop on cancellation")
		}
	})
	deadline := time.NewTimer(5 * time.Second)
	defer deadline.Stop()
	ticks := time.NewTicker(10 * time.Millisecond)
	defer ticks.Stop()
	for {
		var tables int64
		if err := db.Raw("SELECT count(*) FROM information_schema.tables WHERE table_schema = current_schema() AND table_name IN ('sources','articles')").Scan(&tables).Error; err != nil {
			t.Fatal(err)
		}
		if tables == 2 {
			sources, err := store.ListSources(t.Context(), db)
			if err != nil {
				t.Fatal(err)
			}
			if len(sources) == 3 && sources[0].LastSuccessAt != nil && sources[1].LastError == "publisher returned HTTP 503" && sources[2].LastSuccessAt != nil {
				for _, id := range []string{"rbc", "cbr"} {
					article, err := store.FindArticle(t.Context(), db, id, id, "")
					if err != nil || article.Text == "" || article.PublishedAt != nil || article.ProcessingStatus != store.StatusPending {
						t.Fatalf("entrypoint did not collect undated %s text: %+v %v", id, article, err)
					}
				}
				return
			}
		}
		select {
		case <-ticks.C:
		case <-deadline.C:
			t.Fatal("entrypoint did not initialize and collect")
		}
	}
}
