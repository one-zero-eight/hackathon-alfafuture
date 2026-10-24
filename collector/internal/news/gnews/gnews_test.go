package gnews

import (
	"context"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
)

const sample = `<rss><channel>
<item><title>Ставка выросла - Ведомости</title><link>https://news.google.com/a</link><pubDate>Fri, 23 Oct 2026 10:00:00 GMT</pubDate><source url="https://vedomosti.ru">Ведомости</source></item>
<item><title>Без источника</title><link>https://news.google.com/b</link><pubDate>broken</pubDate></item>
</channel></rss>`

func TestSearchParsesTitlesOutletsAndDates(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("q") != "site:vedomosti.ru" {
			t.Errorf("unexpected query %q", r.URL.RawQuery)
		}
		_, _ = w.Write([]byte(sample))
	}))
	defer srv.Close()
	c := New(time.Second)
	c.base = srv.URL
	items, err := c.Search(t.Context(), "site:vedomosti.ru", 100)
	if err != nil || len(items) != 2 {
		t.Fatalf("items=%v err=%v", items, err)
	}
	if items[0].Title != "Ставка выросла" || items[0].Outlet != "Ведомости" || items[0].PublishedAt == nil {
		t.Fatalf("first item parsed wrong: %+v", items[0])
	}
	if items[1].Outlet != "?" || items[1].PublishedAt != nil {
		t.Fatalf("second item parsed wrong: %+v", items[1])
	}
}

func TestSearchRetriesRateLimit(t *testing.T) {
	var calls atomic.Int32
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) < 3 {
			w.WriteHeader(http.StatusTooManyRequests)
			return
		}
		_, _ = w.Write([]byte(sample))
	}))
	defer srv.Close()
	c := New(time.Second)
	c.base, c.sleep = srv.URL, func(context.Context, time.Duration) {}
	items, err := c.Search(t.Context(), "x", 1)
	if err != nil || len(items) != 1 || calls.Load() != 3 {
		t.Fatalf("items=%v err=%v calls=%d", items, err, calls.Load())
	}
}
