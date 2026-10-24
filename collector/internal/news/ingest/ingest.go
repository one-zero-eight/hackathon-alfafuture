// Package ingest fills the corpus from the curated source list: RSS/Atom feeds every few minutes and,
// less often, Google News (per-outlet site: windows and topic windows) for the depth an RSS feed no longer holds.
// Articles are written through store.InsertArticle, so a repeated run never duplicates a row: (source, dedup key) is unique.
package ingest

import (
	"context"
	"log/slog"
	"net/http"
	"regexp"
	"slices"
	"strings"
	"sync"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/feed"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/gnews"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/store"
	"gorm.io/gorm"
)

const (
	feedWorkers   = 12
	gnewsWorkers  = 4
	gnewsPause    = 400 * time.Millisecond // Google News answers 429 to faster crawlers
	gnewsLimit    = 100
	flushEvery    = 50
	browserAgent  = "Mozilla/5.0 (compatible; NewsResearchBot/0.1)"
	kindSiteDepth = "gnsite"
	kindTopics    = "gn"
)

type Config struct {
	FeedsEvery   time.Duration
	DeepEvery    time.Duration
	FetchTimeout time.Duration
	MaxBytes     int64
}

type Runner struct {
	db        *gorm.DB
	sources   []Source
	topics    []string
	cfg       Config
	http      *http.Client
	gn        *gnews.Client
	afterPass func(context.Context) // e.g. geotag; may be nil
}

func New(db *gorm.DB, sources []Source, topics []string, cfg Config, afterPass func(context.Context)) *Runner {
	return &Runner{db: db, sources: sources, topics: topics, cfg: cfg, afterPass: afterPass,
		http: &http.Client{Timeout: cfg.FetchTimeout, Transport: agentTransport{http.DefaultTransport}}, gn: gnews.New(cfg.FetchTimeout)}
}

// agentTransport sends a browser-like User-Agent: several outlets reject the default one.
type agentTransport struct{ http.RoundTripper }

func (t agentTransport) RoundTrip(r *http.Request) (*http.Response, error) {
	r = r.Clone(r.Context())
	r.Header.Set("User-Agent", browserAgent)
	return t.RoundTripper.RoundTrip(r)
}

// Run polls the feeds every FeedsEvery and adds a rolling 3-day Google News pass every DeepEvery.
func (r *Runner) Run(ctx context.Context) {
	var lastDeep time.Time
	for ctx.Err() == nil {
		r.PollFeeds(ctx)
		if time.Since(lastDeep) >= r.cfg.DeepEvery {
			// Windows move with the date, so a rolling pass ignores the "done" memory.
			for kind, step := range map[string]int{kindSiteDepth: 1, kindTopics: 3} {
				if err := r.Backfill(ctx, kind, 3, step, false, false); err != nil && ctx.Err() == nil {
					slog.Error("rolling Google News pass failed", "kind", kind, "error", err)
				}
			}
			lastDeep = time.Now()
		}
		if r.afterPass != nil && ctx.Err() == nil {
			r.afterPass(ctx)
		}
		select {
		case <-ctx.Done():
		case <-time.After(r.cfg.FeedsEvery):
		}
	}
}

// PollFeeds reads every source that has a feed URL, in parallel, and stores the new articles.
func (r *Runner) PollFeeds(ctx context.Context) {
	var feeds []Source
	for _, s := range r.sources {
		if !s.Native && s.URL != "" {
			feeds = append(feeds, s)
		}
	}
	type result struct {
		s       Source
		entries []feed.Entry
		err     error
	}
	total, fetched := 0, 0
	for res := range parallel(ctx, feedWorkers, feeds, func(ctx context.Context, s Source) result {
		entries, err := feed.FetchGeneric(ctx, r.http, s.URL, r.cfg.MaxBytes)
		return result{s, entries, err}
	}) {
		if res.err != nil {
			slog.Warn("feed fetch failed", "source", res.s.ID, "error", res.err)
			continue
		}
		n, err := r.save(ctx, res.s.ID, res.s.Name, res.s.URL, res.s.region(), res.s.RegionSections, res.entries)
		if err != nil {
			slog.Error("cannot save feed articles", "source", res.s.ID, "error", err)
			continue
		}
		total += n
		fetched++
	}
	slog.Info("feeds pass finished", "feeds", len(feeds), "read", fetched, "new_articles", total)
}

// save stores entries of one source; sections lists feed categories that make an article regional without a model check.
func (r *Runner) save(ctx context.Context, id, name, feedURL, region string, sections []string, entries []feed.Entry) (int, error) {
	if err := store.EnsureSource(ctx, r.db, store.Source{ID: id, Name: name, FeedURL: feedURL}, region); err != nil {
		return 0, err
	}
	now := time.Now()
	inserted := 0
	var geo []store.ArticleGeo
	for _, e := range entries {
		article, isNew, err := store.InsertArticle(ctx, r.db, store.Article{
			SourceID: id, URL: e.URL, Title: e.Title, PublishedAt: e.PublishedAt, CollectedAt: now,
			Text: e.Text, TextProvenance: e.TextProvenance,
		})
		if err != nil {
			continue // a malformed item (bad URL, empty title) must not stop the rest of the feed
		}
		if isNew {
			inserted++
		}
		if region != "" && slices.ContainsFunc(e.Categories, func(c string) bool { return slices.Contains(sections, c) }) {
			tag := region
			geo = append(geo, store.ArticleGeo{ArticleID: article.ID, RegionTag: &tag, Basis: "section"})
		}
	}
	return inserted, store.SaveGeo(ctx, r.db, geo)
}

type gnJob struct {
	kind, key, query string
	src              Source // site depth only
}

// Backfill runs Google News requests over `days` days in windows of `step` days.
//   - "gnsite": every source host as `site:<host>`; regionalOnly keeps sources that have a region.
//   - "gn": every topic from the topics file.
//
// With resume, finished requests are remembered in the database and skipped on the next run.
func (r *Runner) Backfill(ctx context.Context, kind string, days, step int, regionalOnly, resume bool) error {
	var jobs []gnJob
	today := time.Now()
	window := func(d int) (string, string) {
		return today.AddDate(0, 0, -d-step).Format(time.DateOnly), today.AddDate(0, 0, -d).Format(time.DateOnly)
	}
	switch kind {
	case kindSiteDepth:
		hosts := map[string]bool{}
		for _, s := range r.sources {
			if regionalOnly && s.region() == "" {
				continue
			}
			if err := store.EnsureSource(ctx, r.db, store.Source{ID: s.ID, Name: s.Name, FeedURL: orGoogle(s.URL)}, s.region()); err != nil {
				return err
			}
			if hosts[s.Host] {
				continue
			}
			hosts[s.Host] = true
			for d := 0; d < days; d += step {
				a, b := window(d)
				jobs = append(jobs, gnJob{kind: kind, key: s.Host + "|" + a, query: "site:" + s.Host + " after:" + a + " before:" + b, src: s})
			}
		}
	case kindTopics:
		for _, q := range r.topics {
			for d := 0; d < days; d += step {
				a, b := window(d)
				jobs = append(jobs, gnJob{kind: kind, key: q + "|" + a, query: q + " after:" + a + " before:" + b})
			}
		}
	default:
		return errUnknownKind
	}
	if resume {
		done, err := store.DoneWindows(ctx, r.db, kind)
		if err != nil {
			return err
		}
		jobs = slices.DeleteFunc(jobs, func(j gnJob) bool { return done[j.key] })
	}
	slog.Info("Google News backfill", "kind", kind, "requests", len(jobs))
	type result struct {
		job   gnJob
		items []gnews.Item
		err   error
	}
	added, requests := 0, 0
	var finished []string
	flush := func() {
		if resume {
			if err := store.MarkWindows(ctx, r.db, kind, finished); err != nil {
				slog.Error("cannot remember finished requests", "error", err)
			}
		}
		finished = nil
	}
	for res := range parallel(ctx, gnewsWorkers, jobs, func(ctx context.Context, j gnJob) result {
		sleepCtx(ctx, gnewsPause)
		items, err := r.gn.Search(ctx, j.query, gnewsLimit)
		return result{j, items, err}
	}) {
		requests++
		if res.err == nil && len(res.items) > 0 { // an empty answer (429 included) is retried next time
			n, err := r.saveGoogle(ctx, res.job, res.items)
			if err != nil {
				return err
			}
			added += n
			finished = append(finished, res.job.key)
		}
		if requests%flushEvery == 0 {
			flush()
			slog.Info("Google News progress", "kind", kind, "requests", requests, "of", len(jobs), "new_articles", added)
		}
	}
	flush()
	slog.Info("Google News backfill finished", "kind", kind, "requests", requests, "new_articles", added)
	return ctx.Err()
}

// saveGoogle files the items under their curated source (site depth) or under one source per outlet (topics):
// `articles` has no outlet column, so the source stands for the outlet.
func (r *Runner) saveGoogle(ctx context.Context, j gnJob, items []gnews.Item) (int, error) {
	byOutlet := map[string][]feed.Entry{}
	for _, it := range items {
		byOutlet[it.Outlet] = append(byOutlet[it.Outlet], feed.Entry{URL: it.Link, Title: it.Title, PublishedAt: it.PublishedAt})
	}
	added := 0
	for outlet, entries := range byOutlet {
		id, name := "gn:"+slug(outlet), outlet
		if j.kind == kindSiteDepth {
			id, name = j.src.ID, j.src.Name
		}
		n, err := r.save(ctx, id, name, orGoogle(j.src.URL), "", nil, entries)
		if err != nil {
			return added, err
		}
		added += n
	}
	return added, nil
}

var nonWord = regexp.MustCompile(`[^\p{L}\p{N}_]+`)

func slug(outlet string) string {
	s := []rune(nonWord.ReplaceAllString(strings.ToLower(outlet), "_"))
	return string(s[:min(len(s), 60)])
}

// orGoogle names Google News as the feed of an outlet that has no feed of its own (feed_url is NOT NULL).
func orGoogle(url string) string {
	if url == "" {
		return gnews.SearchURL
	}
	return url
}

func sleepCtx(ctx context.Context, d time.Duration) {
	select {
	case <-ctx.Done():
	case <-time.After(d):
	}
}

// parallel runs fn for every job with at most `workers` in flight and streams the results; the channel closes when all are done.
func parallel[J, R any](ctx context.Context, workers int, jobs []J, fn func(context.Context, J) R) <-chan R {
	out := make(chan R)
	go func() {
		defer close(out)
		var wg sync.WaitGroup
		sem := make(chan struct{}, workers)
		for _, j := range jobs {
			if ctx.Err() != nil {
				break
			}
			sem <- struct{}{}
			wg.Go(func() {
				defer func() { <-sem }()
				out <- fn(ctx, j)
			})
		}
		wg.Wait()
	}()
	return out
}
