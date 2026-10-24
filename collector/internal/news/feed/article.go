package feed

import (
	"bytes"
	"context"
	"errors"
	"slices"
	"strings"

	"golang.org/x/net/html"
)

// FetchText is called after admission and duplicate checks; it preserves an existing snapshot.
// Extraction failures retain the entry metadata and carry a safe TextError for persistence.
func (c *Client) FetchText(ctx context.Context, entry Entry) (Entry, error) {
	if entry.SourceID != c.sourceID {
		return entry, errors.New("entry source does not match fetcher")
	}
	if entry.Text != "" {
		return entry, nil
	}
	entry.TextProvenance = ""
	var err error
	if c.sourceID == "cbr" {
		entry.Text, err = c.cbrText(ctx, entry.URL)
		if err == nil {
			entry.TextProvenance = "article_page"
			entry.TextError = ""
			return entry, nil
		}
	} else {
		err = errors.New("RSS item contains no usable text")
	}
	entry.TextError = err.Error()
	return entry, err
}

func (c *Client) cbrText(ctx context.Context, rawURL string) (string, error) {
	if !publisherURL(rawURL, c.articleHost, true) {
		return "", errors.New("CBR article URL must use its HTTPS publisher host on port 443 without credentials or a fragment")
	}
	data, err := c.read(ctx, rawURL)
	if err != nil {
		return "", err
	}
	root, err := html.Parse(bytes.NewReader(data))
	if err != nil {
		return "", errors.New("cannot parse CBR article HTML")
	}
	var main *html.Node
	for n := range root.Descendants() {
		if n.Type == html.ElementNode && n.Data == "main" && attribute(n, "id") == "content" {
			main = n
			break
		}
	}
	if main == nil {
		return "", errors.New("CBR article content container is missing")
	}
	var parts []string
	var visit func(*html.Node)
	visit = func(n *html.Node) {
		if n.Type == html.ElementNode && n.Data == "div" {
			classes := strings.Fields(attribute(n, "class"))
			if slices.Contains(classes, "lead-text") || slices.Contains(classes, "landing-text") {
				if text := nodeText(n); text != "" {
					parts = append(parts, text)
				}
				return
			}
		}
		for child := n.FirstChild; child != nil; child = child.NextSibling {
			visit(child)
		}
	}
	visit(main)
	if len(parts) == 0 {
		return "", errors.New("CBR article has no usable lead or body text")
	}
	return strings.Join(parts, " "), nil
}

func attribute(n *html.Node, name string) string {
	for _, attr := range n.Attr {
		if attr.Key == name {
			return attr.Val
		}
	}
	return ""
}
