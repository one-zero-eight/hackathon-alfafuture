package feed

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

const generic = `<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Новость региона</title><link>https://example.ru/1</link><description>&lt;p&gt;Текст &lt;b&gt;новости&lt;/b&gt;&lt;/p&gt;</description><category>В регионе</category><pubDate>Fri, 23 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title>Без ссылки</title><description>x</description></item>
</channel></rss>`

func TestFetchGenericKeepsTextCategoriesAndSkipsLinkless(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(generic)) }))
	defer srv.Close()
	got, err := FetchGeneric(t.Context(), srv.Client(), srv.URL, 1<<20)
	if err != nil || len(got) != 1 {
		t.Fatalf("entries=%v err=%v", got, err)
	}
	e := got[0]
	if e.Text != "Текст новости" || e.TextProvenance != "rss_description" || len(e.Categories) != 1 || e.Categories[0] != "В регионе" || e.PublishedAt == nil || e.PublishedAt.Before(time.Date(2026, 10, 23, 0, 0, 0, 0, time.UTC)) {
		t.Fatalf("entry parsed wrong: %+v", e)
	}
}

func TestFetchGenericRejectsBadURLAndOversizeBody(t *testing.T) {
	if _, err := FetchGeneric(t.Context(), http.DefaultClient, "ftp://x/y", 10); err == nil {
		t.Fatal("expected a URL error")
	}
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { _, _ = w.Write([]byte(generic)) }))
	defer srv.Close()
	if _, err := FetchGeneric(t.Context(), srv.Client(), srv.URL, 10); err == nil {
		t.Fatal("expected a size error")
	}
}
