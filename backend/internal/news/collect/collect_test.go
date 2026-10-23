package collect

import (
	"context"
	"errors"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/config"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/feed"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/testdb"
	"gorm.io/gorm"
)

type fixtureFetcher struct {
	discover func(context.Context) (feed.Discovery, error)
	fetch    func(context.Context, feed.Entry) (feed.Entry, error)
}

func (f fixtureFetcher) Discover(ctx context.Context) (feed.Discovery, error) {
	return f.discover(ctx)
}

func (f fixtureFetcher) FetchText(ctx context.Context, entry feed.Entry) (feed.Entry, error) {
	return f.fetch(ctx, entry)
}

func fixtureConfig() config.Config {
	return config.Config{
		PollInterval: time.Minute, FetchTimeout: time.Second, FetchMaxBytes: 1_000_000,
		RBCFeedURL:        "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
		KommersantFeedURL: "https://www.kommersant.ru/RSS/news.xml",
		CBRFeedURL:        "https://www.cbr.ru/rss/eventrss",
	}
}

func fixtureCollector(t *testing.T) (*Collector, string) {
	t.Helper()
	db, dsn := testdb.New(t)
	if err := store.Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	c, err := New(t.Context(), db, fixtureConfig())
	if err != nil {
		t.Fatal(err)
	}
	return c, dsn
}

func TestConstructorRejectsInvalidSettingsBeforeDatabaseWrites(t *testing.T) {
	cfg := fixtureConfig()
	if _, err := New(t.Context(), nil, cfg); err == nil {
		t.Fatal("nil database accepted")
	}
	cfg.PollInterval = 0
	if _, err := New(t.Context(), &gorm.DB{}, cfg); err == nil {
		t.Fatal("zero interval accepted")
	}
	cfg = fixtureConfig()
	cfg.CBRFeedURL = "https://user:secret@www.cbr.ru/rss"
	if _, err := New(t.Context(), &gorm.DB{}, cfg); err == nil || strings.Contains(err.Error(), "secret") {
		t.Fatal("invalid publisher settings must fail before database access")
	}
}

func TestPostgresAdmissionDeduplicationAndLateRSSText(t *testing.T) {
	c, dsn := fixtureCollector(t)
	s := c.sources[0]
	cutoff := s.metadata.CollectionSince
	old := cutoff.Add(-time.Second)
	base := feed.Entry{SourceID: "rbc", SourceItemID: "exact", URL: "https://www.rbc.ru/exact", Title: "First title", PublishedAt: &cutoff, Text: "First text.", TextProvenance: store.TextFromRSSFullText}
	tooOld := base
	tooOld.SourceItemID, tooOld.PublishedAt = "old", &old
	undated := base
	undated.SourceItemID, undated.URL, undated.PublishedAt = "", "https://www.rbc.ru/undated", nil
	duplicate := undated
	duplicate.Title, duplicate.Text = "Revised title", "Revised text."
	empty := base
	empty.SourceItemID, empty.URL, empty.Text, empty.TextProvenance, empty.TextError = "missing-text", "https://www.rbc.ru/missing", "", "", "RSS item contains no usable text"
	s.fetcher = fixtureFetcher{discover: func(context.Context) (feed.Discovery, error) {
		return feed.Discovery{Entries: []feed.Entry{tooOld, base, undated, duplicate, empty}, RejectedItems: 2}, nil
	}}
	stats, err := c.poll(t.Context(), s)
	if err == nil || stats.inserted != 3 || stats.duplicates != 1 || stats.tooOld != 1 || stats.undated != 2 || stats.rejected != 2 || stats.textFailures != 1 {
		t.Fatalf("unexpected admission result: %+v %v", stats, err)
	}
	stored, err := store.FindArticle(t.Context(), c.db, "rbc", "", undated.URL)
	if err != nil || stored.PublishedAt != nil || stored.Text != undated.Text || stored.Title != undated.Title {
		t.Fatalf("undated duplicate changed original metadata/text: %+v %v", stored, err)
	}
	if _, err := store.FindArticle(t.Context(), c.db, "rbc", "old", tooOld.URL); !errors.Is(err, gorm.ErrRecordNotFound) {
		t.Fatalf("old article was admitted: %v", err)
	}
	empty.Text, empty.TextProvenance, empty.TextError, empty.Title = "Available later.", store.TextFromRSSDescription, "", "Changed title"
	s.fetcher = fixtureFetcher{discover: func(context.Context) (feed.Discovery, error) {
		return feed.Discovery{Entries: []feed.Entry{empty}}, nil
	}}
	stats, err = c.poll(t.Context(), s)
	if err != nil || stats.recovered != 1 || stats.duplicates != 1 {
		t.Fatalf("missing RSS text did not recover: %+v %v", stats, err)
	}
	recovered, err := store.FindArticle(t.Context(), c.db, "rbc", empty.SourceItemID, empty.URL)
	if err != nil || recovered.Text != empty.Text || recovered.TextError != "" || recovered.Title != base.Title {
		t.Fatalf("late RSS text changed the first metadata: %+v %v", recovered, err)
	}
	pool, _ := c.db.DB()
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := store.Open(t.Context(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	testdb.Close(t, reopened)
	restarted, err := New(t.Context(), reopened, fixtureConfig())
	if err != nil || !restarted.sources[0].metadata.CollectionSince.Equal(cutoff) || restarted.sources[0].metadata.LastSuccessAt == nil || restarted.sources[0].metadata.LastError != "" {
		t.Fatalf("restart lost cutoff/poll history: %v", err)
	}
	stats, err = restarted.poll(t.Context(), s)
	if err != nil || stats.inserted != 0 || stats.duplicates != 1 || stats.recovered != 0 {
		t.Fatalf("restart repeated completed work: %+v %v", stats, err)
	}
}

func TestPostgresCBRRetryAfterRestartAndFeedFailure(t *testing.T) {
	c, dsn := fixtureCollector(t)
	s := c.sources[2]
	entry := feed.Entry{SourceID: "cbr", SourceItemID: "cbr-guid", URL: "https://www.cbr.ru/press/event/?id=synthetic", Title: "First title"}
	tooOld := entry
	old := s.metadata.CollectionSince.Add(-time.Second)
	tooOld.SourceItemID, tooOld.PublishedAt = "old-cbr", &old
	pageCalls := 0
	s.fetcher = fixtureFetcher{
		discover: func(context.Context) (feed.Discovery, error) {
			return feed.Discovery{Entries: []feed.Entry{tooOld, entry, entry}}, nil
		},
		fetch: func(ctx context.Context, e feed.Entry) (feed.Entry, error) {
			pageCalls++
			if _, err := store.FindArticle(ctx, c.db, "cbr", e.SourceItemID, e.URL); err != nil {
				return e, errors.New("metadata must be stored before page retrieval")
			}
			return e, errors.New("page unavailable")
		},
	}
	stats, err := c.poll(t.Context(), s)
	if err == nil || stats.inserted != 1 || stats.duplicates != 1 || stats.tooOld != 1 || stats.textFailures != 1 || pageCalls != 1 {
		t.Fatalf("duplicate RSS caused repeated page work: %+v calls=%d %v", stats, pageCalls, err)
	}
	failed, err := store.FindArticle(t.Context(), c.db, "cbr", entry.SourceItemID, entry.URL)
	if err != nil || failed.TextError != "page unavailable" || failed.PublishedAt != nil || failed.ProcessingStatus != store.StatusPending {
		t.Fatalf("extraction failure not saved: %+v %v", failed, err)
	}
	pool, _ := c.db.DB()
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := store.Open(t.Context(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	testdb.Close(t, reopened)
	c, err = New(t.Context(), reopened, fixtureConfig())
	if err != nil {
		t.Fatal(err)
	}
	s = c.sources[2]
	s.fetcher = fixtureFetcher{
		discover: func(context.Context) (feed.Discovery, error) { return feed.Discovery{}, errors.New("feed unavailable") },
		fetch: func(_ context.Context, e feed.Entry) (feed.Entry, error) {
			pageCalls++
			if e.URL != entry.URL || e.Title != entry.Title || e.TextError != "page unavailable" {
				return e, errors.New("retry lost persisted metadata")
			}
			e.Text, e.TextProvenance, e.TextError = "Recovered CBR text.", store.TextFromArticlePage, ""
			return e, nil
		},
	}
	stats, err = c.poll(t.Context(), s)
	if err == nil || err.Error() != "feed unavailable" || stats.recovered != 1 || pageCalls != 2 {
		t.Fatalf("persisted work was not retried without RSS: %+v %v", stats, err)
	}
	recovered, err := store.LoadArticle(t.Context(), c.db, failed.ID)
	if err != nil || recovered.Text != "Recovered CBR text." || recovered.TextError != "" || recovered.Title != failed.Title || !recovered.CollectedAt.Equal(failed.CollectedAt) {
		t.Fatalf("retry did not preserve the first snapshot: %+v %v", recovered, err)
	}
	entry.URL, entry.Title = "https://www.cbr.ru/revised", "Revised title"
	s.fetcher = fixtureFetcher{discover: func(context.Context) (feed.Discovery, error) {
		return feed.Discovery{Entries: []feed.Entry{entry}}, nil
	}}
	if stats, err := c.poll(t.Context(), s); err != nil || stats.duplicates != 1 || stats.recovered != 0 {
		t.Fatalf("completed CBR article was fetched again: %+v %v", stats, err)
	}
	entry.SourceItemID = "interrupted"
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	s.fetcher = fixtureFetcher{
		discover: func(context.Context) (feed.Discovery, error) {
			return feed.Discovery{Entries: []feed.Entry{entry}}, nil
		},
		fetch: func(_ context.Context, e feed.Entry) (feed.Entry, error) { cancel(); return e, context.Canceled },
	}
	if _, err := c.poll(ctx, s); !errors.Is(err, context.Canceled) {
		t.Fatalf("poll did not propagate shutdown: %v", err)
	}
	interrupted, err := store.FindArticle(t.Context(), c.db, "cbr", entry.SourceItemID, entry.URL)
	if err != nil || interrupted.Text != "" || interrupted.TextError != "" || interrupted.ProcessingStatus != store.StatusPending {
		t.Fatalf("shutdown lost queued metadata: %+v %v", interrupted, err)
	}
}

func TestPostgresIndependentImmediateAndIntervalPolling(t *testing.T) {
	c, _ := fixtureCollector(t)
	c.interval = 20 * time.Millisecond
	var slowCalls, failedCalls atomic.Int32
	c.sources[0].fetcher = fixtureFetcher{discover: func(ctx context.Context) (feed.Discovery, error) {
		slowCalls.Add(1)
		<-ctx.Done()
		return feed.Discovery{}, ctx.Err()
	}}
	c.sources[1].fetcher = fixtureFetcher{discover: func(context.Context) (feed.Discovery, error) {
		failedCalls.Add(1)
		return feed.Discovery{}, errors.New("publisher unavailable")
	}}
	c.sources[2].fetcher = fixtureFetcher{
		discover: func(context.Context) (feed.Discovery, error) {
			return feed.Discovery{Entries: []feed.Entry{{SourceID: "cbr", SourceItemID: "healthy", URL: "https://www.cbr.ru/healthy"}}}, nil
		},
		fetch: func(_ context.Context, e feed.Entry) (feed.Entry, error) {
			e.Text, e.TextProvenance = "Healthy source text.", store.TextFromArticlePage
			return e, nil
		},
	}
	ctx, cancel := context.WithCancel(t.Context())
	done := make(chan struct{})
	go func() { c.Run(ctx); close(done) }()
	t.Cleanup(func() {
		cancel()
		select {
		case <-done:
		case <-time.After(5 * time.Second):
			t.Error("scheduler did not stop on cancellation")
		}
	})
	deadline := time.NewTimer(5 * time.Second)
	defer deadline.Stop()
	ticks := time.NewTicker(10 * time.Millisecond)
	defer ticks.Stop()
	for {
		sources, err := store.ListSources(t.Context(), c.db)
		if err != nil {
			t.Fatal(err)
		}
		if failedCalls.Load() >= 2 && sources[0].LastSuccessAt != nil && sources[1].LastError == "publisher unavailable" {
			break
		}
		select {
		case <-ticks.C:
		case <-deadline.C:
			t.Fatal("slow/failed publishers blocked healthy polling")
		}
	}
	if slowCalls.Load() != 1 {
		t.Fatal("polls of the same slow source overlapped")
	}
	article, err := store.FindArticle(t.Context(), c.db, "cbr", "healthy", "https://www.cbr.ru/healthy")
	if err != nil || article.Text != "Healthy source text." {
		t.Fatalf("healthy source was not persisted independently: %+v %v", article, err)
	}
}
