package ingest

import (
	"errors"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/feed"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/gnews"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/testdb"
)

func TestLoadSourcesValidates(t *testing.T) {
	dir := t.TempDir()
	write := func(body string) string {
		p := filepath.Join(dir, "s.json")
		if err := os.WriteFile(p, []byte(body), 0o600); err != nil {
			t.Fatal(err)
		}
		return p
	}
	if got, err := LoadSources(write(`[{"id":"a","name":"A","url":"https://a.ru/rss","host":"a.ru","region":null},{"id":"r","name":"R","host":"r.ru","region":"geography:region:001"},{"id":"rbc","name":"РБК","host":"rbc.ru","native":true}]`)); err != nil || len(got) != 3 || got[1].region() == "" {
		t.Fatalf("valid list rejected: %v %v", got, err)
	}
	for name, body := range map[string]string{
		"duplicate": `[{"id":"a","name":"A","url":"https://a.ru","host":"a.ru"},{"id":"a","name":"B","url":"https://b.ru","host":"b.ru"}]`,
		"unread":    `[{"id":"a","name":"A","host":"a.ru"}]`,
		"no host":   `[{"id":"a","name":"A","url":"https://a.ru"}]`,
		"not json":  `{`,
	} {
		if _, err := LoadSources(write(body)); err == nil {
			t.Errorf("%s: expected an error", name)
		}
	}
}

func TestShippedSourcesFileIsValid(t *testing.T) {
	sources, err := LoadSources("../../../sources.json")
	if err != nil || len(sources) < 300 {
		t.Fatalf("sources.json: %d sources, err=%v", len(sources), err)
	}
	if topics, err := LoadTopics("../../../topics.txt"); err != nil || len(topics) < 100 {
		t.Fatalf("topics.txt: %d topics, err=%v", len(topics), err)
	}
}

func TestSaveStoresOnceAndTagsSectionArticles(t *testing.T) {
	db, _ := testdb.New(t)
	if err := store.Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	r := &Runner{db: db}
	now := time.Now()
	entries := []feed.Entry{
		{URL: "https://tverlife.ru/1", Title: "В Твери открыли мост", PublishedAt: &now, Text: "Текст", TextProvenance: "rss_description", Categories: []string{"В регионе"}},
		{URL: "https://tverlife.ru/2", Title: "Курс доллара", Categories: []string{"Экономика"}},
		{URL: "not a url", Title: "Битая ссылка"},
	}
	n, err := r.save(t.Context(), "tver", "Tverlife", "https://tverlife.ru/rss", "geography:region:069", []string{"В регионе"}, entries)
	if err != nil || n != 2 {
		t.Fatalf("first save: n=%d err=%v", n, err)
	}
	if n, err := r.save(t.Context(), "tver", "Tverlife", "https://tverlife.ru/rss", "geography:region:069", []string{"В регионе"}, entries); err != nil || n != 0 {
		t.Fatalf("second save must add nothing: n=%d err=%v", n, err)
	}
	var geo []store.ArticleGeo
	if err := db.Find(&geo).Error; err != nil || len(geo) != 1 || geo[0].Basis != "section" || *geo[0].RegionTag != "geography:region:069" {
		t.Fatalf("geo rows: %+v err=%v", geo, err)
	}
	pending, err := store.PendingGeo(t.Context(), db, 10)
	if err != nil || len(pending) != 1 || pending[0].Title != "Курс доллара" {
		t.Fatalf("only the unchecked regional-outlet article is pending: %+v err=%v", pending, err)
	}
}

func TestBackfillResumesFinishedWindows(t *testing.T) {
	db, _ := testdb.New(t)
	if err := store.Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	var hits atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		_, _ = w.Write([]byte(`<rss><channel><item><title>Новость ` + r.URL.Query().Get("q") + ` - Гость</title><link>https://example.ru/` + r.URL.Query().Get("q") + `</link><source>Гость</source></item></channel></rss>`))
	}))
	defer srv.Close()
	r := &Runner{db: db, sources: []Source{{ID: "site", Name: "Сайт", Host: "site.ru"}}, gn: gnews.NewAt(srv.URL, time.Second)}
	for run, want := range []int32{2, 0} {
		hits.Store(0)
		if err := r.Backfill(t.Context(), "gnsite", 2, 1, false, true); err != nil {
			t.Fatal(err)
		}
		if hits.Load() != want {
			t.Fatalf("run %d: %d requests, want %d", run, hits.Load(), want)
		}
	}
	var count int64
	if err := db.Model(&store.Article{}).Where("source_id = ?", "site").Count(&count).Error; err != nil || count != 2 {
		t.Fatalf("articles under the curated source: %d err=%v", count, err)
	}
}

func TestBackfillStopsWhenGoogleBlocks(t *testing.T) {
	db, _ := testdb.New(t)
	if err := store.Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	var hits atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		hits.Add(1)
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer srv.Close()
	r := &Runner{db: db, sources: []Source{{ID: "site", Name: "Сайт", Host: "site.ru"}}, gn: gnews.NewAt(srv.URL, time.Second).NoPause()}
	err := r.Backfill(t.Context(), "gnsite", 20, 1, false, false)
	if !errors.Is(err, gnews.ErrBlocked) {
		t.Fatalf("err=%v, want ErrBlocked", err)
	}
	if hits.Load() >= 20*5 { // 20 windows x 5 attempts if the pass went on
		t.Fatalf("%d requests: the pass did not stop", hits.Load())
	}
}
