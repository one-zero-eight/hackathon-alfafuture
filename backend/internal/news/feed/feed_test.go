package feed

import (
	"context"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"strings"
	"testing"
	"testing/iotest"
	"time"
)

var sourceURLs = map[string]string{
	"rbc":        "https://rssexport.rbc.ru/rbcnews/news/30/full.rss",
	"kommersant": "https://www.kommersant.ru/RSS/news.xml",
	"cbr":        "https://www.cbr.ru/rss/eventrss",
}

type transportFunc func(*http.Request) (*http.Response, error)

func (f transportFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

func response(status int, body string) *http.Response {
	return &http.Response{StatusCode: status, Header: make(http.Header), ContentLength: -1, Body: io.NopCloser(strings.NewReader(body))}
}

func rss(items string) string {
	return `<?xml version="1.0"?><rss version="2.0" xmlns:publisher="https://www.rbc.ru"><channel><title>Fixture feed</title><link>https://example.test</link><description>Synthetic feed</description>` + items + `</channel></rss>`
}

func fixtureClient(t *testing.T, sourceID, body string) *Client {
	t.Helper()
	client, err := New(sourceID, sourceURLs[sourceID], time.Second, 1_000_000)
	if err != nil {
		t.Fatal(err)
	}
	client.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method != http.MethodGet || r.URL.String() != sourceURLs[sourceID] || r.Header.Get("User-Agent") == "" {
			return nil, errors.New("unexpected RSS request")
		}
		return response(http.StatusOK, body), nil
	})
	return client
}

func TestRBCFullTextNamespaceAndFallback(t *testing.T) {
	client := fixtureClient(t, "rbc", rss(`
<item><title>Oil &amp; gas</title><link>https://www.rbc.ru/news/full?b=2&amp;a=1</link><guid isPermaLink="false">opaque:first</guid><pubDate>Thu, 22 Oct 2026 12:30:00 +0300</pubDate><description>Short excerpt</description><publisher:full-text><![CDATA[<p>Oil <b>rose</b> &amp; gas.</p><p>Forecast: 10 &lt; 20.</p><script>hidden()</script>]]></publisher:full-text></item>
<item><title>Fallback</title><link>https://www.rbc.ru/news/fallback</link><pubDate>not a date</pubDate><description><![CDATA[<p>Only the <i>excerpt</i>.</p>]]></description><publisher:full-text>   </publisher:full-text></item>
<item><title>No text</title><link>https://www.rbc.ru/news/empty</link></item>
<item xmlns:publisher="https://wrong.example"><title>Wrong namespace</title><link>https://www.rbc.ru/news/namespace</link><description>Safe excerpt</description><publisher:full-text>Wrong namespace content</publisher:full-text></item>`))
	result, err := client.Discover(t.Context())
	if err != nil {
		t.Fatal(err)
	}
	if len(result.Entries) != 4 || result.RejectedItems != 0 {
		t.Fatalf("wrong discovery counts: %+v", result)
	}
	full := result.Entries[0]
	if full.SourceID != "rbc" || full.SourceItemID != "opaque:first" || full.URL != "https://www.rbc.ru/news/full?b=2&a=1" || full.Title != "Oil & gas" || full.Text != "Oil rose & gas. Forecast: 10 < 20." || full.TextProvenance != "rss_full_text" || full.TextError != "" {
		t.Fatalf("wrong full-text snapshot: %+v", full)
	}
	if full.PublishedAt == nil || !full.PublishedAt.Equal(time.Date(2026, 10, 22, 9, 30, 0, 0, time.UTC)) || full.PublishedAt.Location() != time.UTC {
		t.Fatal("publication time not preserved in UTC")
	}
	fallback, empty, wrong := result.Entries[1], result.Entries[2], result.Entries[3]
	if fallback.PublishedAt != nil || fallback.SourceItemID != "" || fallback.Text != "Only the excerpt." || fallback.TextProvenance != "rss_description" {
		t.Fatalf("fallback/date/GUID handling: %+v", fallback)
	}
	if empty.Text != "" || empty.TextProvenance != "" || empty.TextError == "" || empty.PublishedAt != nil {
		t.Fatal("headline was fabricated as article text")
	}
	if wrong.Text != "Safe excerpt" || wrong.TextProvenance != "rss_description" {
		t.Fatal("RBC extension matched prefix instead of namespace URI")
	}
}

func TestKommersantDescriptionsAndCBRDiscovery(t *testing.T) {
	for _, sourceID := range []string{"kommersant", "cbr"} {
		t.Run(sourceID, func(t *testing.T) {
			host := "www.kommersant.ru"
			if sourceID == "cbr" {
				host = "www.cbr.ru"
			}
			body := rss(fmt.Sprintf(`<item><guid>one</guid><link>https://%s/news/one</link><title>Headline only</title><description><![CDATA[<p>Excerpt &amp; context.</p>]]></description><publisher:full-text>Never use foreign full text</publisher:full-text></item>`, host))
			client := fixtureClient(t, sourceID, body)
			result, err := client.Discover(t.Context())
			if err != nil || len(result.Entries) != 1 {
				t.Fatal("discovery failed", err)
			}
			entry := result.Entries[0]
			if sourceID == "kommersant" && (entry.Text != "Excerpt & context." || entry.TextProvenance != "rss_description") {
				t.Fatal("Kommersant excerpt mislabeled", entry)
			}
			if sourceID == "cbr" && (entry.Text != "" || entry.TextProvenance != "" || entry.TextError != "") {
				t.Fatal("CBR discovery must wait for page extraction")
			}
		})
	}
}

func TestInvalidLinksAreRejectedIndividually(t *testing.T) {
	var items strings.Builder
	for _, link := range []string{"https://www.rbc.ru/valid", "https://www.rbc.ru/valid", "", "/relative", "https://evil.example/news", "https://www.rbc.ru.evil.example/news", "https://user:do-not-log@www.rbc.ru/news", "https://www.rbc.ru:8443/news", "javascript:alert(1)"} {
		_, _ = fmt.Fprintf(&items, `<item><link>%s</link><description>text</description></item>`, link)
	}
	result, err := fixtureClient(t, "rbc", rss(items.String())).Discover(t.Context())
	if err != nil || len(result.Entries) != 2 || result.RejectedItems != 7 {
		t.Fatal("bad item prevented valid discovery", result, err)
	}
	if result.Entries[0].URL != result.Entries[1].URL {
		t.Fatal("discovery must leave dedup to persistent collector")
	}
}

func TestPlainText(t *testing.T) {
	for raw, want := range map[string]string{
		"A\n\tB\u00a0C": "A B C",
		`<p>One<b>word</b>.</p><div>Two<br>three.</div>`:                                                                   "Oneword. Two three.",
		`<style>hidden</style><script>hidden</script><template>hidden</template><noscript>hidden</noscript><p>visible</p>`: "visible",
		`<p>Broken <b>markup`:      "Broken markup",
		`5 &lt; 7 &amp; 10 &gt; 9`: "5 < 7 & 10 > 9",
	} {
		if got := plainText(raw); got != want {
			t.Fatalf("plain text: got %q, want %q", got, want)
		}
	}
}

func TestInvalidFeedAndBounds(t *testing.T) {
	for _, body := range []string{"not RSS", "<rss><channel><item>", `<feed xmlns="http://www.w3.org/2005/Atom"><title>Not selected RSS</title></feed>`} {
		if _, err := fixtureClient(t, "rbc", body).Discover(t.Context()); err == nil {
			t.Fatal("accepted malformed or unsupported feed")
		}
	}
	if result, err := fixtureClient(t, "rbc", rss("")).Discover(t.Context()); err != nil || len(result.Entries) != 0 {
		t.Fatal("empty valid feed rejected", err)
	}
	for _, declared := range []bool{false, true} {
		client := fixtureClient(t, "rbc", rss(""))
		client.maxBytes = 16
		var closed bool
		client.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
			r := response(http.StatusOK, strings.Repeat("x", 17))
			r.Body = &observedBody{ReadCloser: r.Body, closed: &closed}
			if declared {
				r.ContentLength = 17
			}
			return r, nil
		})
		if _, err := client.Discover(t.Context()); err == nil || !closed {
			t.Fatal("oversized body accepted or left open")
		}
	}
	client := fixtureClient(t, "rbc", rss(""))
	client.maxBytes = int64(len(rss("")))
	if _, err := client.Discover(t.Context()); err != nil {
		t.Fatal("exact-limit feed rejected", err)
	}
}

type observedBody struct {
	io.ReadCloser
	closed *bool
}

func (b *observedBody) Close() error { *b.closed = true; return b.ReadCloser.Close() }

func TestRedirectRestrictions(t *testing.T) {
	for _, target := range []string{"/lowercase.rss", "https://evil.example/feed?token=do-not-log", "http://rssexport.rbc.ru/feed", "https://user:do-not-log@rssexport.rbc.ru/feed", "https://rssexport.rbc.ru:444/feed", "https://rssexport.rbc.ru/feed#fragment", sourceURLs["rbc"]} {
		t.Run(target, func(t *testing.T) {
			client := fixtureClient(t, "rbc", rss(""))
			calls := 0
			client.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
				calls++
				if target == "/lowercase.rss" && calls == 2 {
					return response(http.StatusOK, rss("")), nil
				}
				res := response(http.StatusTemporaryRedirect, "")
				res.Header.Set("Location", target)
				return res, nil
			})
			_, err := client.Discover(t.Context())
			if target == "/lowercase.rss" {
				if err != nil || calls != 2 {
					t.Fatal("same-host redirect failed", err)
				}
			} else {
				expected := 1
				if target == sourceURLs["rbc"] {
					expected = 5
				}
				if err == nil || calls != expected || strings.Contains(err.Error(), "do-not-log") {
					t.Fatal("redirect escaped host/loop/error restrictions", calls, err)
				}
			}
		})
	}
}

func TestConfigurationAndSafeErrors(t *testing.T) {
	for _, invalid := range []struct {
		id, url string
		timeout time.Duration
		size    int64
	}{
		{"unknown", sourceURLs["rbc"], time.Second, 100}, {"rbc", "https://user:do-not-log@rssexport.rbc.ru/feed", time.Second, 100},
		{"rbc", "http://rssexport.rbc.ru/feed", time.Second, 100}, {"rbc", "https://evil.example/feed", time.Second, 100},
		{"rbc", sourceURLs["rbc"], 0, 100}, {"rbc", sourceURLs["rbc"], time.Second, 0}, {"rbc", sourceURLs["rbc"], time.Second, math.MaxInt64},
	} {
		if _, err := New(invalid.id, invalid.url, invalid.timeout, invalid.size); err == nil || strings.Contains(err.Error(), "do-not-log") {
			t.Fatal("invalid config accepted or exposed", err)
		}
	}
	client := fixtureClient(t, "rbc", rss(""))
	client.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
		return response(http.StatusServiceUnavailable, "do-not-log body"), nil
	})
	if _, err := client.Discover(t.Context()); err == nil || !strings.Contains(err.Error(), "503") || strings.Contains(err.Error(), "do-not-log") {
		t.Fatal("HTTP error lost or exposed", err)
	}
	client.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) { return nil, errors.New("do-not-log transport") })
	if _, err := client.Discover(t.Context()); err == nil || strings.Contains(err.Error(), "do-not-log") {
		t.Fatal("transport error exposed", err)
	}
	var closed bool
	client.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
		r := response(http.StatusOK, "")
		r.Body = &observedBody{ReadCloser: io.NopCloser(iotest.ErrReader(errors.New("do-not-log reader"))), closed: &closed}
		return r, nil
	})
	if _, err := client.Discover(t.Context()); err == nil || strings.Contains(err.Error(), "do-not-log") || !closed {
		t.Fatal("body-read error exposed or body left open", err)
	}
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	client.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
		t.Fatal("cancelled request reached transport")
		return nil, nil
	})
	if _, err := client.Discover(ctx); !errors.Is(err, context.Canceled) {
		t.Fatal("cancellation lost", err)
	}
	client.http.Timeout = 10 * time.Millisecond
	client.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) { <-r.Context().Done(); return nil, r.Context().Err() })
	if _, err := client.Discover(t.Context()); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatal("fetch timeout lost", err)
	}
}

func TestLiveRSS(t *testing.T) {
	if os.Getenv("LIVE_RSS_TEST") != "1" {
		t.Skip("set LIVE_RSS_TEST=1 for three bounded public-feed requests")
	}
	for _, id := range []string{"rbc", "kommersant", "cbr"} {
		t.Run(id, func(t *testing.T) {
			client, err := New(id, sourceURLs[id], 30*time.Second, 8_000_000)
			if err != nil {
				t.Fatal(err)
			}
			result, err := client.Discover(t.Context())
			if err != nil || len(result.Entries) == 0 {
				t.Fatal("live discovery failed", err)
			}
			text, full, undated := 0, 0, 0
			for _, entry := range result.Entries {
				if entry.Text != "" {
					text++
				}
				if entry.TextProvenance == "rss_full_text" {
					full++
				}
				if entry.PublishedAt == nil {
					undated++
				}
			}
			if id == "rbc" && full == 0 || id == "kommersant" && text == 0 || id == "cbr" && text != 0 {
				t.Fatal("publisher text behavior changed")
			}
			t.Logf("entries=%d rejected=%d with_text=%d full_text=%d undated=%d", len(result.Entries), result.RejectedItems, text, full, undated)
		})
	}
}
