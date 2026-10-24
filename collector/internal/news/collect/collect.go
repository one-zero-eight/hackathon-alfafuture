// Package collect persists RSS discoveries and polls each publisher independently.
package collect

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/config"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/feed"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/store"
	"gorm.io/gorm"
)

// Fetchers return credential-free errors suitable for poll diagnostics.
type fetcher interface {
	Discover(context.Context) (feed.Discovery, error)
	FetchText(context.Context, feed.Entry) (feed.Entry, error)
}

type source struct {
	metadata store.Source
	fetcher  fetcher
}

type Collector struct {
	db       *gorm.DB
	sources  []source
	interval time.Duration
}

type pollStats struct {
	discovered, rejected, inserted, duplicates, tooOld, undated, textFailures, recovered int
}

// New registers configured sources while retaining their persisted history boundary.
// The caller bootstraps the database and owns its pool. Run must be called once.
func New(ctx context.Context, db *gorm.DB, cfg config.Config) (*Collector, error) {
	if db == nil || cfg.PollInterval <= 0 {
		return nil, errors.New("collector requires a database and a positive poll interval")
	}
	c := &Collector{db: db, interval: cfg.PollInterval}
	settings := []store.Source{
		{ID: "rbc", Name: "РБК", FeedURL: cfg.RBCFeedURL},
		{ID: "kommersant", Name: "Коммерсантъ", FeedURL: cfg.KommersantFeedURL},
		{ID: "cbr", Name: "Банк России", FeedURL: cfg.CBRFeedURL},
	}
	for _, setting := range settings {
		client, err := feed.New(setting.ID, setting.FeedURL, cfg.FetchTimeout, cfg.FetchMaxBytes)
		if err != nil {
			return nil, fmt.Errorf("configure %s: %w", setting.ID, err)
		}
		c.sources = append(c.sources, source{metadata: setting, fetcher: client})
	}
	if err := store.RegisterSources(ctx, db, settings, time.Now()); err != nil {
		return nil, errors.New("cannot register collection sources")
	}
	persisted, err := store.ListSources(ctx, db)
	if err != nil {
		return nil, errors.New("cannot load collection sources")
	}
	for i := range c.sources {
		for _, saved := range persisted {
			if saved.ID == c.sources[i].metadata.ID {
				c.sources[i].metadata = saved
			}
		}
	}
	return c, nil
}

// Run polls immediately, then on each interval; one slow source cannot delay another.
func (c *Collector) Run(ctx context.Context) {
	var workers sync.WaitGroup
	for _, s := range c.sources {
		workers.Go(func() {
			ticker := time.NewTicker(c.interval)
			defer ticker.Stop()
			for ctx.Err() == nil {
				stats, err := c.poll(ctx, s)
				if ctx.Err() != nil {
					return
				}
				attrs := []any{"source", s.metadata.ID, "discovered", stats.discovered, "rejected", stats.rejected,
					"inserted", stats.inserted, "duplicates", stats.duplicates, "too_old", stats.tooOld,
					"undated", stats.undated, "text_failures", stats.textFailures, "recovered", stats.recovered}
				if err != nil {
					slog.Error("source poll failed", append(attrs, "error", err)...)
				} else {
					slog.Info("source poll completed", attrs...)
				}
				select {
				case <-ctx.Done():
					return
				case <-ticker.C:
				}
			}
		})
	}
	workers.Wait()
}

func (c *Collector) poll(ctx context.Context, s source) (pollStats, error) {
	stats, err := c.collect(ctx, s)
	if ctx.Err() != nil {
		return stats, ctx.Err()
	}
	if saveErr := store.RecordSourcePoll(ctx, c.db, s.metadata.ID, time.Now(), err); saveErr != nil {
		return stats, errors.New("cannot save source poll outcome")
	}
	return stats, err
}

func (c *Collector) collect(ctx context.Context, s source) (pollStats, error) {
	var stats pollStats
	discovery, discoveryErr := s.fetcher.Discover(ctx)
	if ctx.Err() != nil {
		return stats, ctx.Err()
	}
	if discoveryErr == nil {
		stats.discovered, stats.rejected = len(discovery.Entries), discovery.RejectedItems
		for _, entry := range discovery.Entries {
			if entry.SourceID != s.metadata.ID {
				return stats, errors.New("discovery returned a different source")
			}
			if entry.PublishedAt == nil {
				stats.undated++
			} else if entry.PublishedAt.Before(s.metadata.CollectionSince) {
				stats.tooOld++
				continue
			}
			article, err := store.FindArticle(ctx, c.db, entry.SourceID, entry.SourceItemID, entry.URL)
			if errors.Is(err, gorm.ErrRecordNotFound) {
				var inserted bool
				article, inserted, err = store.InsertArticle(ctx, c.db, store.Article{
					SourceID: entry.SourceID, SourceItemID: entry.SourceItemID, URL: entry.URL, Title: entry.Title,
					PublishedAt: entry.PublishedAt, CollectedAt: time.Now(), Text: entry.Text,
					TextProvenance: entry.TextProvenance, TextError: entry.TextError,
				})
				if inserted {
					stats.inserted++
				} else if err == nil {
					stats.duplicates++
				}
			} else if err == nil {
				stats.duplicates++
			}
			if err != nil {
				return stats, errors.New("cannot save discovered article")
			}
			if article.Text == "" && article.ProcessingStatus == store.StatusPending && s.metadata.ID != "cbr" {
				if entry.Text == "" {
					stats.textFailures++
					continue
				}
				if _, err := store.RecordArticleText(ctx, c.db, article.ID, entry.Text, entry.TextProvenance, nil); err != nil {
					return stats, errors.New("cannot save RSS article text")
				}
				stats.recovered++
			}
		}
	}
	if s.metadata.ID == "cbr" {
		pending, err := store.ListArticlesAwaitingText(ctx, c.db, s.metadata.ID)
		if err != nil {
			return stats, errors.New("cannot load articles awaiting text")
		}
		// The persisted queue has one row per identity, even when RSS repeats an item.
		// shortcut: pages are fetched serially; add bounded batches if retries outgrow a poll interval.
		for _, article := range pending {
			if err := ctx.Err(); err != nil {
				return stats, err
			}
			entry, extractionErr := s.fetcher.FetchText(ctx, feed.Entry{
				SourceID: article.SourceID, SourceItemID: article.SourceItemID, URL: article.URL,
				Title: article.Title, PublishedAt: article.PublishedAt, TextError: article.TextError,
			})
			if ctx.Err() != nil {
				return stats, ctx.Err()
			}
			if _, err := store.RecordArticleText(ctx, c.db, article.ID, entry.Text, entry.TextProvenance, extractionErr); err != nil {
				return stats, errors.New("cannot save article extraction outcome")
			}
			if extractionErr != nil {
				stats.textFailures++
			} else {
				stats.recovered++
			}
		}
	}
	if stats.textFailures > 0 {
		discoveryErr = errors.Join(discoveryErr, fmt.Errorf("%d article extractions failed", stats.textFailures))
	}
	return stats, discoveryErr
}
