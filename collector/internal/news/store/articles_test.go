package store

import (
	"errors"
	"strings"
	"testing"
	"time"

	"gorm.io/gorm"
)

func articleDatabase(t *testing.T) (*gorm.DB, string, time.Time) {
	t.Helper()
	db, dsn := integrationDatabase(t)
	if err := Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	now := time.Date(2026, 10, 22, 12, 0, 0, 0, time.FixedZone("MSK", 3*60*60))
	if err := RegisterSources(t.Context(), db, []Source{
		{ID: "rbc", Name: "РБК", FeedURL: "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"},
		{ID: "kommersant", Name: "Коммерсантъ", FeedURL: "https://www.kommersant.ru/RSS/news.xml"},
		{ID: "cbr", Name: "Банк России", FeedURL: "https://www.cbr.ru/rss/eventrss"},
	}, now); err != nil {
		t.Fatal(err)
	}
	return db, dsn, now
}

func sampleArticle(itemID string) Article {
	return Article{
		SourceID:       "rbc",
		SourceItemID:   itemID,
		URL:            "https://www.rbc.ru/news/synthetic-test",
		Title:          "Synthetic news",
		CollectedAt:    time.Date(2026, 10, 22, 9, 0, 0, 0, time.UTC),
		Text:           "Synthetic article text.",
		TextProvenance: TextFromRSSFullText,
	}
}

func TestArticleIdentityKeys(t *testing.T) {
	if articleKey("guid", "https://example.test/one") != articleKey("guid", "https://example.test/two") {
		t.Fatal("GUID must take precedence over URL")
	}
	if articleKey("", "https://example.test/one") == articleKey("", "https://example.test/two") {
		t.Fatal("missing GUID must use URL")
	}
	if articleKey("https://example.test/one", "https://example.test/one") == articleKey("", "https://example.test/one") {
		t.Fatal("GUID and fallback URL identities must have distinct namespaces")
	}
	if len(articleKey(strings.Repeat("opaque-guid", 4096), "https://example.test")) != 64 {
		t.Fatal("long identifiers must have a bounded index key")
	}
}

func TestPostgresSourcesPreserveCutoffAndPollHistory(t *testing.T) {
	db, dsn, now := articleDatabase(t)
	success := now.Add(time.Minute)
	failure := now.Add(2 * time.Minute)
	if err := RecordSourcePoll(t.Context(), db, "rbc", success, nil); err != nil {
		t.Fatal(err)
	}
	if err := RecordSourcePoll(t.Context(), db, "rbc", failure, errors.New("feed unavailable")); err != nil {
		t.Fatal(err)
	}
	if err := RegisterSources(t.Context(), db, []Source{
		{ID: "rbc", Name: "Updated RBC", FeedURL: "https://rssexport.rbc.ru/custom.rss"},
	}, now.Add(48*time.Hour)); err != nil {
		t.Fatal(err)
	}
	pool, err := db.DB()
	if err != nil {
		t.Fatal(err)
	}
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := Open(t.Context(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	closeDatabase(t, reopened)
	sources, err := ListSources(t.Context(), reopened)
	if err != nil {
		t.Fatal(err)
	}
	if len(sources) != 3 || sources[0].ID != "cbr" || sources[1].ID != "kommersant" || sources[2].ID != "rbc" {
		t.Fatalf("unexpected source list: %+v", sources)
	}
	for _, source := range sources {
		if !source.CollectionSince.Equal(now.Add(-24*time.Hour)) || !source.CreatedAt.Equal(now) {
			t.Fatalf("source registration moved the initial cutoff: %+v", source)
		}
	}
	rbc := sources[2]
	if rbc.Name != "Updated RBC" || rbc.FeedURL != "https://rssexport.rbc.ru/custom.rss" || rbc.LastPolledAt == nil || !rbc.LastPolledAt.Equal(failure) || rbc.LastSuccessAt == nil || !rbc.LastSuccessAt.Equal(success) || rbc.LastError != "feed unavailable" {
		t.Fatalf("source settings/history were not preserved: %+v", rbc)
	}
	if sources[0].LastError != "" || sources[0].LastPolledAt != nil {
		t.Fatal("one source failure modified another source")
	}
	if err := RecordSourcePoll(t.Context(), reopened, "rbc", now.Add(3*time.Minute), nil); err != nil {
		t.Fatal(err)
	}
	sources, err = ListSources(t.Context(), reopened)
	if err != nil || sources[2].LastError != "" || !sources[2].LastSuccessAt.Equal(now.Add(3*time.Minute)) {
		t.Fatal("successful poll did not clear the last error:", err)
	}
	if err := RecordSourcePoll(t.Context(), reopened, "missing", now, nil); !errors.Is(err, gorm.ErrRecordNotFound) {
		t.Fatalf("expected missing source error: %v", err)
	}
	if err := Bootstrap(t.Context(), reopened); err != nil {
		t.Fatal(err)
	}
	assertCount(t, reopened, &Source{}, 3)
}

func TestPostgresArticleSnapshotsAndMissingDates(t *testing.T) {
	db, dsn, now := articleDatabase(t)
	input := sampleArticle("first-guid")
	published := now.Add(-time.Hour)
	input.PublishedAt = &published
	first, inserted, err := InsertArticle(t.Context(), db, input)
	if err != nil || !inserted || first.ID <= 0 || first.ProcessingStatus != StatusPending {
		t.Fatalf("insert failed: %+v %v %v", first, inserted, err)
	}
	changed := input
	changed.URL = "https://www.rbc.ru/news/changed"
	changed.Title = "Revised title"
	changed.Text = "Revised text"
	changed.CollectedAt = now.Add(24 * time.Hour)
	changed.PublishedAt = &now
	again, inserted, err := InsertArticle(t.Context(), db, changed)
	if err != nil || inserted || again.ID != first.ID || again.URL != input.URL || again.Title != input.Title || again.Text != input.Text || again.PublishedAt == nil || !again.PublishedAt.Equal(published) || !again.CollectedAt.Equal(input.CollectedAt) {
		t.Fatalf("duplicate changed the first snapshot: %+v %v %v", again, inserted, err)
	}
	missingText := Article{SourceID: "cbr", SourceItemID: "pending-page", URL: "https://www.cbr.ru/press/event/?id=synthetic", Title: "A title is not article text", CollectedAt: now, TextError: "page unavailable"}
	pending, inserted, err := InsertArticle(t.Context(), db, missingText)
	if err != nil || !inserted {
		t.Fatal("could not persist pending extraction:", err)
	}
	longGUID := sampleArticle(strings.Repeat("opaque-guid-", 4096))
	if _, inserted, err := InsertArticle(t.Context(), db, longGUID); err != nil || !inserted {
		t.Fatal("long GUID should not exceed PostgreSQL index limits:", err)
	}
	pool, err := db.DB()
	if err != nil {
		t.Fatal(err)
	}
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := Open(t.Context(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	closeDatabase(t, reopened)
	stored, err := FindArticle(t.Context(), reopened, "rbc", "first-guid", changed.URL)
	if err != nil || stored.ID != first.ID || stored.Text != input.Text || stored.TextProvenance != input.TextProvenance {
		t.Fatalf("snapshot was not retained after reconnect: %+v %v", stored, err)
	}
	stored, err = LoadArticle(t.Context(), reopened, pending.ID)
	if err != nil || stored.PublishedAt != nil || stored.Text != "" || stored.TextProvenance != "" || stored.TextError != "page unavailable" || stored.ProcessingStatus != StatusPending {
		t.Fatalf("pending extraction or absent date was fabricated: %+v %v", stored, err)
	}
	if _, err := LoadArticle(t.Context(), reopened, 999999); !errors.Is(err, gorm.ErrRecordNotFound) {
		t.Fatalf("expected missing article error: %v", err)
	}
	if _, err := FindArticle(t.Context(), reopened, "rbc", "missing-guid", input.URL); !errors.Is(err, gorm.ErrRecordNotFound) {
		t.Fatalf("an unrelated GUID was merged by URL: %v", err)
	}
	assertCount(t, reopened, &Article{}, 3)
}

func TestPostgresArticleFallbackNamespaceAndConstraints(t *testing.T) {
	db, _, _ := articleDatabase(t)
	fallback := sampleArticle("")
	first, inserted, err := InsertArticle(t.Context(), db, fallback)
	if err != nil || !inserted {
		t.Fatal(err)
	}
	if again, inserted, err := InsertArticle(t.Context(), db, fallback); err != nil || inserted || again.ID != first.ID {
		t.Fatalf("URL fallback did not deduplicate: %+v %v %v", again, inserted, err)
	}
	withGUID := fallback
	withGUID.SourceItemID = fallback.URL
	if _, inserted, err := InsertArticle(t.Context(), db, withGUID); err != nil || !inserted {
		t.Fatal("GUID namespace collided with URL fallback:", err)
	}
	otherSource := fallback
	otherSource.SourceID = "kommersant"
	if _, inserted, err := InsertArticle(t.Context(), db, otherSource); err != nil || !inserted {
		t.Fatal("articles from different publishers were merged:", err)
	}
	rawDuplicate := first
	rawDuplicate.ID = 0
	assertSQLState(t, db.Create(&rawDuplicate).Error, "23505")
	unknown := sampleArticle("unknown-source")
	unknown.SourceID = "missing"
	_, _, err = InsertArticle(t.Context(), db, unknown)
	assertSQLState(t, err, "23503")
	badStatus := sampleArticle("bad-status")
	badStatus.DedupKey = articleKey(badStatus.SourceItemID, badStatus.URL)
	badStatus.ProcessingStatus = "invented"
	assertSQLState(t, db.Create(&badStatus).Error, "23514")
	badProvenance := sampleArticle("bad-provenance")
	badProvenance.DedupKey = articleKey(badProvenance.SourceItemID, badProvenance.URL)
	badProvenance.Text = ""
	assertSQLState(t, db.Create(&badProvenance).Error, "23514")
	assertSQLState(t, db.Where("id = ?", "rbc").Delete(&Source{}).Error, "23001", "23503")
	assertCount(t, db, &Article{}, 3)
}

func TestPostgresArticleConcurrentDuplicates(t *testing.T) {
	db, _, _ := articleDatabase(t)
	type outcome struct {
		article  Article
		inserted bool
		err      error
	}
	results := make(chan outcome, 8)
	for range 8 {
		go func() {
			a, inserted, err := InsertArticle(t.Context(), db, sampleArticle("concurrent-guid"))
			results <- outcome{a, inserted, err}
		}()
	}
	insertedCount := 0
	ids := make(map[int64]bool)
	for range 8 {
		result := <-results
		if result.err != nil {
			t.Error(result.err)
			continue
		}
		ids[result.article.ID] = true
		if result.inserted {
			insertedCount++
		}
	}
	if insertedCount != 1 || len(ids) != 1 || ids[0] {
		t.Fatalf("simultaneous duplicates produced %d inserts and IDs %v", insertedCount, ids)
	}
	assertCount(t, db, &Article{}, 1)
}

func TestPostgresArticleAndSourceValidation(t *testing.T) {
	db, _, now := articleDatabase(t)
	for _, tc := range []struct {
		name   string
		mutate func(*Article)
	}{
		{"assigned ID", func(a *Article) { a.ID = 1 }},
		{"source", func(a *Article) { a.SourceID = "" }},
		{"collection time", func(a *Article) { a.CollectedAt = time.Time{} }},
		{"publication time", func(a *Article) { a.PublishedAt = &time.Time{} }},
		{"URL", func(a *Article) { a.URL = "file:///tmp/news" }},
		{"URL credentials", func(a *Article) { a.URL = "https://user:do-not-log@www.rbc.ru/news" }},
		{"processing status", func(a *Article) { a.ProcessingStatus = StatusCompleted }},
		{"blank text", func(a *Article) { a.Text = " \t\n" }},
		{"unknown provenance", func(a *Article) { a.TextProvenance = "invented" }},
		{"missing text", func(a *Article) { a.Text = "" }},
		{"text with extraction error", func(a *Article) { a.TextError = "failed extraction" }},
	} {
		t.Run(tc.name, func(t *testing.T) {
			a := sampleArticle(tc.name)
			tc.mutate(&a)
			if _, _, err := InsertArticle(t.Context(), db, a); err == nil || strings.Contains(err.Error(), "do-not-log") {
				t.Fatalf("expected safe validation error: %v", err)
			}
		})
	}
	if _, err := FindArticle(t.Context(), db, "rbc", "", ""); err == nil {
		t.Fatal("empty identity should fail validation")
	}
	if _, err := LoadArticle(t.Context(), db, 0); err == nil {
		t.Fatal("zero article ID should fail validation")
	}
	if err := RegisterSources(t.Context(), db, []Source{
		{ID: "new", Name: "Valid", FeedURL: "https://www.cbr.ru/rss/eventrss"},
		{ID: "invalid", Name: "Invalid", FeedURL: "https://user:do-not-log@www.cbr.ru/rss"},
	}, now); err == nil || strings.Contains(err.Error(), "do-not-log") {
		t.Fatalf("source settings should be validated before any write: %v", err)
	}
	if err := RegisterSources(t.Context(), db, nil, now); err == nil {
		t.Fatal("empty source set should fail validation")
	}
	if err := RecordSourcePoll(t.Context(), db, "rbc", time.Time{}, nil); err == nil {
		t.Fatal("zero poll time should fail validation")
	}
	assertCount(t, db, &Source{}, 3)
	assertCount(t, db, &Article{}, 0)
}
