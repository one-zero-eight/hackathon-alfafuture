// Package gnews searches Google News RSS: the source of per-outlet depth and topic backfills.
package gnews

import (
	"context"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/mail"
	"net/url"
	"strings"
	"time"
)

const (
	// SearchURL is also stored as feed_url of sources that exist only through Google News.
	SearchURL = "https://news.google.com/rss/search"
	userAgent = "Mozilla/5.0 (compatible; NewsResearchBot/0.1)"
)

// ErrBlocked means Google kept answering 429/503 after every retry: it treats us as a bot, so further requests only prolong it.
var ErrBlocked = errors.New("google news is blocking requests")

type Item struct {
	Title       string
	Link        string
	Outlet      string
	PublishedAt *time.Time
}

type Client struct {
	http  *http.Client
	base  string
	sleep func(context.Context, time.Duration) // replaced in tests
}

func New(timeout time.Duration) *Client { return NewAt(SearchURL, timeout) }

// NewAt points the client at another endpoint (tests).
func NewAt(base string, timeout time.Duration) *Client {
	return &Client{http: &http.Client{Timeout: timeout}, base: base, sleep: sleep}
}

// NoPause drops the retry pauses (tests of other packages).
func (c *Client) NoPause() *Client {
	c.sleep = func(context.Context, time.Duration) {}
	return c
}

func sleep(ctx context.Context, d time.Duration) {
	t := time.NewTimer(d)
	defer t.Stop()
	select {
	case <-ctx.Done():
	case <-t.C:
	}
}

type rss struct {
	Items []struct {
		Title   string `xml:"title"`
		Link    string `xml:"link"`
		PubDate string `xml:"pubDate"`
		Source  string `xml:"source"`
	} `xml:"channel>item"`
}

// Search returns up to limit items. HTTP 429/503 are retried with a growing pause, then reported as ErrBlocked; any other failure is returned.
func (c *Client) Search(ctx context.Context, query string, limit int) ([]Item, error) {
	q := url.Values{"q": {query}, "hl": {"ru"}, "gl": {"RU"}, "ceid": {"RU:ru"}}
	var lastErr error
	for attempt := range 5 {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		body, status, err := c.get(ctx, c.base+"?"+q.Encode())
		switch {
		case err == nil && status == http.StatusOK:
			return parse(body, limit)
		case err == nil && (status == http.StatusTooManyRequests || status == http.StatusServiceUnavailable):
			lastErr = fmt.Errorf("%w: HTTP %d", ErrBlocked, status)
			c.sleep(ctx, time.Duration(5*(attempt+1))*time.Second)
		case err == nil:
			return nil, fmt.Errorf("google news returned HTTP %d", status)
		default:
			lastErr = err
			c.sleep(ctx, 2*time.Second)
		}
	}
	return nil, lastErr
}

func (c *Client) get(ctx context.Context, rawURL string) ([]byte, int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, 0, errors.New("cannot create Google News request")
	}
	req.Header.Set("User-Agent", userAgent)
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, 0, errors.New("Google News request failed")
	}
	defer func() { _ = resp.Body.Close() }()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 16<<20))
	return body, resp.StatusCode, err
}

func parse(body []byte, limit int) ([]Item, error) {
	var doc rss
	if err := xml.Unmarshal(body, &doc); err != nil {
		return nil, errors.New("cannot parse Google News feed")
	}
	var items []Item
	for _, it := range doc.Items {
		outlet, title := strings.TrimSpace(it.Source), strings.TrimSpace(it.Title)
		// Google appends " - Outlet" to every title.
		if outlet != "" {
			title = strings.TrimSuffix(title, " - "+outlet)
		}
		if outlet == "" {
			outlet = "?"
		}
		item := Item{Title: title, Link: strings.TrimSpace(it.Link), Outlet: outlet}
		if t, err := mail.ParseDate(it.PubDate); err == nil {
			t = t.UTC()
			item.PublishedAt = &t
		}
		items = append(items, item)
		if len(items) >= limit {
			break
		}
	}
	return items, nil
}
