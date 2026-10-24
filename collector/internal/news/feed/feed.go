// Package feed separates RSS discovery from article text retrieval, without database writes.
package feed

import (
	"bytes"
	"context"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/mmcdole/gofeed"
	"golang.org/x/net/html"
)

type Entry struct {
	SourceID       string
	SourceItemID   string
	URL            string
	Title          string
	PublishedAt    *time.Time
	Text           string
	TextProvenance string
	TextError      string
	Categories     []string
}

const userAgent = "AlfaFutureNews/0.1"

type Discovery struct {
	Entries       []Entry
	RejectedItems int
}

type Client struct {
	sourceID    string
	feedURL     string
	articleHost string
	http        *http.Client
	maxBytes    int64
}

// New restricts requests to one approved publisher and uses the existing fetch timeout/byte limit.
func New(sourceID, feedURL string, timeout time.Duration, maxBytes int64) (*Client, error) {
	var feedHost, articleHost string
	switch sourceID {
	case "rbc":
		feedHost, articleHost = "rssexport.rbc.ru", "www.rbc.ru"
	case "kommersant":
		feedHost, articleHost = "www.kommersant.ru", "www.kommersant.ru"
	case "cbr":
		feedHost, articleHost = "www.cbr.ru", "www.cbr.ru"
	default:
		return nil, errors.New("unknown RSS source ID")
	}
	if !publisherURL(feedURL, feedHost, true) {
		return nil, errors.New("RSS URL must use its publisher HTTPS host on port 443 without credentials or a fragment")
	}
	if timeout <= 0 || maxBytes <= 0 || maxBytes == math.MaxInt64 {
		return nil, errors.New("RSS timeout and byte limit must be positive, with room for one overflow-check byte")
	}
	client := &http.Client{Timeout: timeout}
	client.CheckRedirect = func(r *http.Request, via []*http.Request) error {
		if len(via) >= 5 || !publisherURL(r.URL.String(), feedHost, true) {
			return errors.New("RSS redirect limit or publisher host restriction violated")
		}
		return nil
	}
	return &Client{sourceID: sourceID, feedURL: feedURL, articleHost: articleHost, http: client, maxBytes: maxBytes}, nil
}

// Discover returns metadata and available RSS text; CBR entries require later page extraction.
// Missing publication dates remain nil. The caller decides admission and checks stored identities.
func (c *Client) Discover(ctx context.Context) (Discovery, error) {
	data, err := c.read(ctx, c.feedURL)
	if err != nil {
		return Discovery{}, err
	}
	parsed, err := gofeed.NewParser().Parse(bytes.NewReader(data))
	if err != nil || parsed == nil || parsed.FeedType != "rss" {
		return Discovery{}, errors.New("cannot parse publisher RSS feed")
	}
	var original struct {
		Items []struct {
			FullText string `xml:"https://www.rbc.ru full-text"`
		} `xml:"channel>item"`
	}
	if c.sourceID == "rbc" {
		// gofeed preserves extension prefixes rather than namespace URIs.
		// shortcut: this XML pass is strict, add tolerant namespace parsing if the publisher emits malformed XML.
		if err := xml.Unmarshal(data, &original); err != nil || len(original.Items) != len(parsed.Items) {
			return Discovery{}, errors.New("cannot read RBC publisher text extension")
		}
	}
	result := Discovery{Entries: make([]Entry, 0, len(parsed.Items))}
	for i, item := range parsed.Items {
		if item == nil || !publisherURL(item.Link, c.articleHost, false) {
			result.RejectedItems++
			continue
		}
		entry := Entry{SourceID: c.sourceID, SourceItemID: item.GUID, URL: item.Link, Title: plainText(item.Title)}
		if item.PublishedParsed != nil && !item.PublishedParsed.IsZero() {
			published := item.PublishedParsed.UTC()
			entry.PublishedAt = &published
		}
		if c.sourceID != "cbr" {
			if c.sourceID == "rbc" {
				entry.Text = plainText(original.Items[i].FullText)
			}
			if entry.Text != "" {
				entry.TextProvenance = "rss_full_text"
			} else {
				entry.Text = plainText(item.Description)
				if entry.Text != "" {
					entry.TextProvenance = "rss_description"
				}
			}
			if entry.Text == "" {
				entry.TextError = "RSS item contains no usable text"
			}
		}
		result.Entries = append(result.Entries, entry)
	}
	return result, nil
}

func (c *Client) read(ctx context.Context, rawURL string) ([]byte, error) {
	return readLimited(ctx, c.http, rawURL, c.maxBytes)
}

func readLimited(ctx context.Context, client *http.Client, rawURL string, maxBytes int64) ([]byte, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, rawURL, nil)
	if err != nil {
		return nil, errors.New("cannot create publisher request")
	}
	req.Header.Set("User-Agent", userAgent)
	response, err := client.Do(req)
	if err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if errors.Is(err, context.DeadlineExceeded) {
			return nil, context.DeadlineExceeded
		}
		return nil, errors.New("publisher request failed")
	}
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("publisher returned HTTP %d", response.StatusCode)
	}
	if response.ContentLength > maxBytes {
		return nil, errors.New("publisher response exceeds fetch size limit")
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, maxBytes+1))
	if err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if errors.Is(err, context.DeadlineExceeded) {
			return nil, context.DeadlineExceeded
		}
		return nil, errors.New("cannot read publisher response")
	}
	if int64(len(data)) > maxBytes {
		return nil, errors.New("publisher response exceeds fetch size limit")
	}
	return data, nil
}

func publisherURL(raw, host string, httpsOnly bool) bool {
	u, err := url.Parse(raw)
	if err != nil || !strings.EqualFold(u.Hostname(), host) || u.User != nil {
		return false
	}
	if httpsOnly {
		return u.Scheme == "https" && (u.Port() == "" || u.Port() == "443") && u.Fragment == ""
	}
	return (u.Scheme == "https" && (u.Port() == "" || u.Port() == "443")) || (u.Scheme == "http" && (u.Port() == "" || u.Port() == "80"))
}

func plainText(raw string) string {
	root, err := html.Parse(strings.NewReader(raw))
	if err != nil {
		return ""
	}
	return nodeText(root)
}

func nodeText(root *html.Node) string {
	var text strings.Builder
	var visit func(*html.Node)
	visit = func(n *html.Node) {
		if n.Type == html.ElementNode {
			switch n.Data {
			case "script", "style", "template", "noscript":
				return
			}
		}
		block := false
		if n.Type == html.ElementNode {
			switch n.Data {
			case "p", "div", "br", "li", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th", "hr":
				block = true
			}
		}
		if block {
			text.WriteByte(' ')
		}
		if n.Type == html.TextNode {
			text.WriteString(n.Data)
		}
		for child := n.FirstChild; child != nil; child = child.NextSibling {
			visit(child)
		}
		if block {
			text.WriteByte(' ')
		}
	}
	visit(root)
	return strings.Join(strings.Fields(text.String()), " ")
}
