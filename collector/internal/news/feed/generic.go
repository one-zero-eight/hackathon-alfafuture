package feed

import (
	"bytes"
	"context"
	"errors"
	"net/http"
	"net/url"

	"github.com/mmcdole/gofeed"
)

const maxGenericText = 2000 // runes of the RSS description kept as article text

// FetchGeneric reads any RSS or Atom feed of the curated source list. Text is the plain-text description.
// Unlike Client it is not tied to one publisher host: the caller owns the list of URLs.
func FetchGeneric(ctx context.Context, client *http.Client, feedURL string, maxBytes int64) ([]Entry, error) {
	if u, err := url.Parse(feedURL); err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Hostname() == "" || u.User != nil {
		return nil, errors.New("feed URL must be HTTP(S) without credentials")
	}
	data, err := readLimited(ctx, client, feedURL, maxBytes)
	if err != nil {
		return nil, err
	}
	parsed, err := gofeed.NewParser().Parse(bytes.NewReader(data))
	if err != nil || parsed == nil {
		return nil, errors.New("cannot parse feed")
	}
	entries := make([]Entry, 0, len(parsed.Items))
	for _, item := range parsed.Items {
		if item == nil || item.Link == "" || plainText(item.Title) == "" {
			continue
		}
		entry := Entry{URL: item.Link, Title: plainText(item.Title), Categories: item.Categories}
		if item.PublishedParsed != nil && !item.PublishedParsed.IsZero() {
			published := item.PublishedParsed.UTC()
			entry.PublishedAt = &published
		}
		if text := []rune(plainText(item.Description)); len(text) > 0 {
			if len(text) > maxGenericText {
				text = text[:maxGenericText]
			}
			entry.Text, entry.TextProvenance = string(text), "rss_description"
		}
		entries = append(entries, entry)
	}
	return entries, nil
}
