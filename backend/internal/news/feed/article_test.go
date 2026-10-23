package feed

import (
	"context"
	"errors"
	"net/http"
	"os"
	"reflect"
	"strings"
	"testing"
	"time"
)

const cbrArticleURL = "https://www.cbr.ru/press/event/?id=32925"

func articleEntry() Entry {
	publication := time.Date(2026, 10, 21, 12, 0, 0, 0, time.UTC)
	return Entry{SourceID: "cbr", SourceItemID: "32925", URL: cbrArticleURL, Title: "RSS title", PublishedAt: &publication}
}

func articleClient(t *testing.T, body string) *Client {
	t.Helper()
	client := fixtureClient(t, "cbr", "")
	client.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) {
		if r.Method != http.MethodGet || r.URL.String() != cbrArticleURL {
			return nil, errors.New("unexpected article request")
		}
		return response(http.StatusOK, body), nil
	})
	return client
}

func TestCBRArticleContainersAndMetadata(t *testing.T) {
	client := articleClient(t, `<html><body>
<nav>Navigation</nav><div class="landing-text">Outside main</div>
<main id="other"><div class="landing-text">Wrong main</div></main>
<main id="content"><h1>Different page headline</h1><div class="news-info-line_date">Different date</div>
<div class="lead-text extra"><p>The rate <b>was raised</b> &amp; applies now.</p></div>
<div class="landing-text"><p>First paragraph.</p><p>Sec<i>ond</i> paragraph.<br>Next line.</p><script>hidden</script></div>
<a href="/document.pdf">Download document</a></main><footer>Footer</footer></body></html>`)
	original := articleEntry()
	original.TextError = "previous extraction failed"
	got, err := client.FetchText(t.Context(), original)
	if err != nil {
		t.Fatal(err)
	}
	expected := original
	expected.Text = "The rate was raised & applies now. First paragraph. Second paragraph. Next line."
	expected.TextProvenance = "article_page"
	expected.TextError = ""
	if !reflect.DeepEqual(got, expected) {
		t.Fatalf("incorrect article snapshot: %+v", got)
	}
	if original.Text != "" || original.TextError != "previous extraction failed" {
		t.Fatal("caller metadata was mutated")
	}
	client.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) { t.Fatal("stored text was fetched again"); return nil, nil })
	if again, err := client.FetchText(t.Context(), got); err != nil || !reflect.DeepEqual(again, got) {
		t.Fatal("first text snapshot changed", err)
	}
}

func TestCBRArticleMissingAndPartialLayouts(t *testing.T) {
	for _, tt := range []struct{ name, body, want string }{
		{"lead only", `<main id="content"><div class="lead-text">Lead only.</div></main>`, "Lead only."},
		{"body only", `<main id="content"><div class="landing-text">Body only.</div></main>`, "Body only."},
		{"document order", `<main id="content"><div class="landing-text">Body.</div><div class="lead-text">Lead.</div></main>`, "Body. Lead."},
		{"nested containers", `<main id="content"><div class="landing-text">Outer.<div class="landing-text">Inner.</div></div></main>`, "Outer. Inner."},
		{"class tokens", "<main id='content'><div class='extra\tlanding-text\nlast'>Matched.</div></main>", "Matched."},
		{"repairable HTML", `<main id="content"><div class="landing-text"><p>Open <b>tags`, "Open tags"},
		{"no main", `<h1>Headline</h1><div class="landing-text">Unscoped.</div>`, ""},
		{"wrong ID", `<main id="content-extra"><div class="landing-text">Wrong.</div></main>`, ""},
		{"wrong class", `<main id="content"><div class="landing-text-extra">Wrong.</div></main>`, ""},
		{"wrong element", `<main id="content"><span class="landing-text">Wrong.</span></main>`, ""},
		{"empty", `<main id="content"><div class="lead-text"> </div><div class="landing-text"><script>hidden</script><style>hidden</style></div></main>`, ""},
		{"headline only", `<main id="content"><h1>Not article text</h1></main>`, ""},
		{"not HTML", `unstructured response`, ""},
	} {
		t.Run(tt.name, func(t *testing.T) {
			got, err := articleClient(t, tt.body).FetchText(t.Context(), articleEntry())
			if tt.want != "" {
				if err != nil || got.Text != tt.want || got.TextProvenance != "article_page" || got.TextError != "" {
					t.Fatal("valid text not extracted", got, err)
				}
			} else if err == nil || got.Text != "" || got.TextProvenance != "" || got.TextError != err.Error() {
				t.Fatal("failed layout became article text", got, err)
			}
		})
	}
}

func TestArticleFetchStagesAndRetry(t *testing.T) {
	client := articleClient(t, `<main id="content"><h1>Not body</h1></main>`)
	failed, err := client.FetchText(t.Context(), articleEntry())
	if err == nil || failed.TextError == "" {
		t.Fatal("missing body was not reported")
	}
	client.http.Transport = articleClient(t, `<main id="content"><div class="lead-text">Recovered.</div></main>`).http.Transport
	recovered, err := client.FetchText(t.Context(), failed)
	if err != nil || recovered.Text != "Recovered." || recovered.TextError != "" || recovered.URL != failed.URL || recovered.SourceItemID != failed.SourceItemID {
		t.Fatal("failure could not be retried explicitly", recovered, err)
	}
	for _, id := range []string{"rbc", "kommersant"} {
		c := fixtureClient(t, id, "")
		c.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) { t.Fatal("RSS text stage fetched a page"); return nil, nil })
		entry := Entry{SourceID: id, Text: "RSS snapshot", TextProvenance: "rss_description"}
		if got, err := c.FetchText(t.Context(), entry); err != nil || !reflect.DeepEqual(got, entry) {
			t.Fatal("RSS snapshot not preserved", err)
		}
		entry.Text, entry.TextProvenance = "", ""
		if got, err := c.FetchText(t.Context(), entry); err == nil || got.Text != "" || got.TextError == "" {
			t.Fatal("empty RSS text became a successful page extraction")
		}
	}
}

func TestCBRArticleURLAndSourceGuards(t *testing.T) {
	client := articleClient(t, "")
	client.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
		t.Fatal("invalid article reached transport")
		return nil, nil
	})
	for _, rawURL := range []string{"", "http://www.cbr.ru/press/event/?id=1", "https://evil.example/press/event/?id=1", "https://www.cbr.ru.evil.example/", "https://user:do-not-log@www.cbr.ru/press/event/?id=1", "https://www.cbr.ru:444/press/event/?id=1", "https://www.cbr.ru/press/event/?id=1#fragment"} {
		entry := articleEntry()
		entry.URL = rawURL
		got, err := client.FetchText(t.Context(), entry)
		if err == nil || strings.Contains(err.Error(), "do-not-log") || got.TextError != err.Error() {
			t.Fatal("article URL accepted or diagnostic exposed", err)
		}
	}
	entry := articleEntry()
	entry.SourceID = "rbc"
	if _, err := client.FetchText(t.Context(), entry); err == nil {
		t.Fatal("wrong source accepted")
	}
}

func TestCBRArticleNetworkLimitsAndErrors(t *testing.T) {
	client := articleClient(t, "")
	client.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
		return response(http.StatusServiceUnavailable, "do-not-log body"), nil
	})
	if got, err := client.FetchText(t.Context(), articleEntry()); err == nil || got.TextError != err.Error() || !strings.Contains(err.Error(), "503") || strings.Contains(err.Error(), "do-not-log") {
		t.Fatal("HTTP failure lost or exposed", err)
	}
	client.maxBytes = 8
	var closed bool
	client.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
		r := response(http.StatusOK, "too large")
		r.Body = &observedBody{ReadCloser: r.Body, closed: &closed}
		return r, nil
	})
	if got, err := client.FetchText(t.Context(), articleEntry()); err == nil || got.TextError != err.Error() || got.Text != "" || !closed {
		t.Fatal("page size limit or cleanup lost", err)
	}
	client.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
		t.Fatal("cancelled article reached transport")
		return nil, nil
	})
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	if got, err := client.FetchText(ctx, articleEntry()); !errors.Is(err, context.Canceled) || got.TextError != err.Error() {
		t.Fatal("page cancellation lost", err)
	}
	client.http.Timeout = 10 * time.Millisecond
	client.http.Transport = transportFunc(func(r *http.Request) (*http.Response, error) { <-r.Context().Done(); return nil, r.Context().Err() })
	if got, err := client.FetchText(t.Context(), articleEntry()); !errors.Is(err, context.DeadlineExceeded) || got.TextError != err.Error() {
		t.Fatal("page timeout lost", err)
	}
}

func TestCBRArticleRedirects(t *testing.T) {
	for _, target := range []string{"/press/event/?id=2", "https://evil.example/?token=do-not-log", "http://www.cbr.ru/press/event/?id=2", cbrArticleURL} {
		t.Run(target, func(t *testing.T) {
			client := articleClient(t, "")
			calls := 0
			client.http.Transport = transportFunc(func(*http.Request) (*http.Response, error) {
				calls++
				if target == "/press/event/?id=2" && calls == 2 {
					return response(http.StatusOK, `<main id="content"><div class="landing-text">Redirected body.</div></main>`), nil
				}
				r := response(http.StatusTemporaryRedirect, "")
				r.Header.Set("Location", target)
				return r, nil
			})
			got, err := client.FetchText(t.Context(), articleEntry())
			if target == "/press/event/?id=2" {
				if err != nil || calls != 2 || got.Text != "Redirected body." || got.URL != cbrArticleURL {
					t.Fatal("same-host redirect changed identity or failed", err)
				}
			} else {
				want := 1
				if target == cbrArticleURL {
					want = 5
				}
				if err == nil || calls != want || strings.Contains(err.Error(), "do-not-log") {
					t.Fatal("unsafe/looping page redirect accepted", calls, err)
				}
			}
		})
	}
}

func TestLiveCBRPage(t *testing.T) {
	if os.Getenv("LIVE_RSS_TEST") != "1" {
		t.Skip("set LIVE_RSS_TEST=1 for one bounded CBR page request")
	}
	client, err := New("cbr", sourceURLs["cbr"], 30*time.Second, 8_000_000)
	if err != nil {
		t.Fatal(err)
	}
	entry := articleEntry()
	got, err := client.FetchText(t.Context(), entry)
	if err != nil || got.Text == "" || got.TextProvenance != "article_page" || got.TextError != "" || got.Title != entry.Title || got.URL != entry.URL {
		t.Fatal("live CBR extraction failed", err)
	}
	t.Logf("article text: %d runes, provenance=%s", len([]rune(got.Text)), got.TextProvenance)
}
