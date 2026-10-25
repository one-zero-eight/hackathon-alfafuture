package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/testdb"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/llm"
)

func TestOpenAPIExportNeedsNoConfigurationOrServices(t *testing.T) {
	t.Setenv("ENV_FILE", "/does-not-exist")
	t.Setenv("DATABASE_URL", "")
	t.Setenv("LLM_API_KEY", "")
	var first, second bytes.Buffer
	if err := writeOpenAPI(&first); err != nil {
		t.Fatal(err)
	}
	if err := writeOpenAPI(&second); err != nil || !bytes.Equal(first.Bytes(), second.Bytes()) {
		t.Fatal("offline contract export is not deterministic")
	}
	var spec struct{ OpenAPI string }
	if err := json.Unmarshal(first.Bytes(), &spec); err != nil || spec.OpenAPI != "3.1.0" {
		t.Fatal("export is not OpenAPI JSON")
	}
}

func availableAddress(t *testing.T) string {
	t.Helper()
	l, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	address := l.Addr().String()
	if err := l.Close(); err != nil {
		t.Fatal(err)
	}
	return address
}

type fixtureTransport func(*http.Request) (*http.Response, error)

func (f fixtureTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func isolatedEnvironment(t *testing.T) {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, ".env")
	if err := os.WriteFile(path, nil, 0600); err != nil {
		t.Fatal(err)
	}
	// An empty curated list keeps the Google News and feed passes idle: these tests cover the three native publishers.
	sources, topics := filepath.Join(dir, "sources.json"), filepath.Join(dir, "topics.txt")
	if err := os.WriteFile(sources, []byte("[]"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(topics, nil, 0600); err != nil {
		t.Fatal(err)
	}
	for key, value := range map[string]string{
		"SOURCES_FILE": sources, "TOPICS_FILE": topics,
		"ENV_FILE": path, "HTTP_ADDR": "127.0.0.1:8080", "POLL_INTERVAL": "20ms",
		"FETCH_TIMEOUT": "1s", "LLM_TIMEOUT": "1s", "FETCH_MAX_MB": "1", "LLM_API_KEY": "sk-fixture", "LLM_MODEL": llm.DefaultModel,
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

func TestRunRequiresLLMKey(t *testing.T) {
	isolatedEnvironment(t)
	t.Setenv("DATABASE_URL", "postgres://localhost/unused")
	t.Setenv("LLM_API_KEY", "")
	if err := run(t.Context()); err == nil || !strings.Contains(err.Error(), "LLM_API_KEY") {
		t.Fatalf("missing key must fail before DB connection: %v", err)
	}
}

func TestRunWithoutLLMNeedsNoKey(t *testing.T) {
	isolatedEnvironment(t)
	t.Setenv("DATABASE_URL", "postgres://localhost:1/unused")
	t.Setenv("LLM_API_KEY", "")
	t.Setenv("LLM_ENABLED", "false")
	if err := run(t.Context()); err == nil || strings.Contains(err.Error(), "LLM_API_KEY") {
		t.Fatalf("collection-only mode must not ask for the key: %v", err)
	}
}

func TestPostgresRunRejectsOccupiedPortBeforeBackgroundRequests(t *testing.T) {
	_, dsn := testdb.New(t)
	isolatedEnvironment(t)
	t.Setenv("DATABASE_URL", dsn)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	t.Setenv("HTTP_ADDR", listener.Addr().String())
	previous := http.DefaultTransport
	var calls atomic.Int32
	http.DefaultTransport = fixtureTransport(func(*http.Request) (*http.Response, error) {
		calls.Add(1)
		return nil, errors.New("unexpected background request")
	})
	t.Cleanup(func() { http.DefaultTransport = previous })
	if err := run(t.Context()); err == nil || err.Error() != "cannot listen on HTTP_ADDR" {
		t.Fatalf("occupied HTTP port did not stop startup safely: %v", err)
	}
	if calls.Load() != 0 {
		t.Fatal("background requests started before HTTP listener was available")
	}
}

func TestPostgresRunCollectsTagsAndKeepsCollectingDuringBudgetPause(t *testing.T) {
	for _, paused := range []bool{false, true} {
		name := "normal"
		if paused {
			name = "budget_pause"
		}
		t.Run(name, func(t *testing.T) {
			db, dsn := testdb.New(t)
			isolatedEnvironment(t)
			t.Setenv("DATABASE_URL", dsn)
			address := availableAddress(t)
			t.Setenv("HTTP_ADDR", address)
			var calls atomic.Int32
			var quota atomic.Bool
			previous := http.DefaultTransport
			http.DefaultTransport = fixtureTransport(func(r *http.Request) (*http.Response, error) {
				status, body := http.StatusOK, ""
				switch r.URL.String() {
				case "https://rssexport.rbc.ru/rbcnews/news/30/full.rss":
					id := "rbc"
					if paused && quota.Load() {
						id = "after-pause"
					}
					body = `<rss version="2.0"><channel><title>Fixture</title><item><guid>` + id + `</guid><link>https://www.rbc.ru/fixture</link><description>RSS fixture text.</description></item></channel></rss>`
				case "https://www.kommersant.ru/RSS/news.xml":
					status = http.StatusServiceUnavailable
				case "https://www.cbr.ru/rss/eventrss":
					body = `<rss version="2.0"><channel><title>Fixture</title><item><guid>cbr</guid><link>https://www.cbr.ru/fixture</link></item></channel></rss>`
				case "https://www.cbr.ru/fixture":
					body = `<main id="content"><div class="lead-text">CBR fixture text.</div></main>`
				case llm.BaseURL + "chat/completions":
					if r.Method != http.MethodPost || r.Header.Get("Authorization") != "Bearer sk-fixture" {
						return nil, errors.New("unexpected LLM request")
					}
					raw, err := io.ReadAll(r.Body)
					var sent struct{ Messages []struct{ Content string } }
					if err == nil && json.Unmarshal(raw, &sent) == nil && len(sent.Messages) == 1 {
						// Geography fallback of the tagging worker: no place found, not counted as a tagging request.
						body = `{"id":"fixture","object":"chat.completion","created":1,"model":"google/gemma-4-26b-a4b-it","choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":"{\"places\":{}}"}}]}`
						break
					}
					calls.Add(1)
					if err != nil || len(sent.Messages) != 2 {
						return nil, errors.New("invalid tagging request body")
					}
					var claimed store.Article
					if err := db.Where("text = ? AND processing_status = ?", sent.Messages[1].Content, store.StatusProcessing).First(&claimed).Error; err != nil {
						return nil, errors.New("HTTP request sent before article claim")
					}
					trace, err := store.LoadAttempts(r.Context(), db, claimed.ID)
					if err != nil || len(trace) != 1 || trace[0].Request != string(raw) {
						t.Error("saved request differs from actual SDK HTTP body")
						return nil, errors.New("tagging request trace mismatch")
					}
					if paused {
						quota.Store(true)
						status, body = http.StatusForbidden, `{"error":{"message":"Budget has been exceeded"}}`
					} else {
						body = `{"id":"fixture","object":"chat.completion","created":1,"model":"deepseek/deepseek-v4.1-flash","choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":"{\"tags\":[],\"events\":[]}"}}],"usage":{"prompt_tokens":11,"completion_tokens":5,"total_tokens":16}}`
					}
				default:
					return nil, errors.New("unexpected external request")
				}
				return &http.Response{StatusCode: status, Header: http.Header{"Content-Type": []string{"application/json"}}, ContentLength: -1, Body: io.NopCloser(strings.NewReader(body))}, nil
			})
			t.Cleanup(func() { http.DefaultTransport = previous })
			ctx, cancel := context.WithCancel(t.Context())
			transport := &http.Transport{Proxy: nil}
			defer transport.CloseIdleConnections()
			client := &http.Client{Transport: transport, Timeout: time.Second}
			done := make(chan error, 1)
			go func() { done <- run(ctx) }()
			t.Cleanup(func() {
				cancel()
				select {
				case err := <-done:
					if err != nil {
						t.Errorf("entrypoint returned error: %v", err)
					}
					if conn, err := net.DialTimeout("tcp", address, 100*time.Millisecond); err == nil {
						_ = conn.Close()
						t.Error("HTTP listener remained open after shutdown")
					}
				case <-time.After(5 * time.Second):
					t.Error("entrypoint did not stop")
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
						ready := true
						want := store.StatusCompleted
						if paused {
							want = store.StatusPending
						}
						for _, id := range []string{"rbc", "cbr"} {
							article, err := store.FindArticle(t.Context(), db, id, id, "")
							if err != nil || article.Text == "" || article.PublishedAt != nil {
								t.Fatalf("failed collection: %+v %v", article, err)
							}
							if article.ProcessingStatus != want {
								ready = false
							}
						}
						if paused {
							_, err := store.FindArticle(t.Context(), db, "rbc", "after-pause", "")
							ready = ready && err == nil
							pause, err := store.LoadBudgetPause(t.Context(), db)
							ready = ready && err == nil && pause != nil
						}
						if ready {
							for _, path := range []string{"/healthz", "/readyz", "/v1/tags", "/v1/sources", "/v1/status", "/v1/news", "/v1/news?processing_status=pending", "/openapi.json", "/docs"} {
								response, err := client.Get("http://" + address + path)
								if err != nil {
									t.Fatal(err)
								}
								_, readErr := io.Copy(io.Discard, response.Body)
								_ = response.Body.Close()
								if response.StatusCode != http.StatusOK || readErr != nil {
									t.Fatalf("HTTP endpoint %s failed: status=%d err=%v", path, response.StatusCode, readErr)
								}
							}
							wantCalls := int32(2)
							if paused {
								wantCalls = 1
							}
							if calls.Load() != wantCalls {
								t.Fatalf("unexpected LLM requests: %d want %d", calls.Load(), wantCalls)
							}
							return
						}
					}
				}
				select {
				case <-ticks.C:
				case <-deadline.C:
					t.Fatal("full pipeline did not finish expected work")
				}
			}
		})
	}
}
