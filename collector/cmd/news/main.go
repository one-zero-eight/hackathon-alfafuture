package main

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"log/slog"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-gonic/gin"
	"gorm.io/gorm"

	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/collect"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/config"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/geotag"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/httpapi"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/ingest"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/tagging"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/vocabulary"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/llm"
)

func main() {
	gin.SetMode(gin.ReleaseMode)
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	openapi := flag.Bool("openapi", false, "print OpenAPI JSON without loading config or connecting to services")
	backfill := flag.String("backfill", "", `run one Google News backfill and exit: "gnsite" (per outlet) or "gn" (per topic)`)
	days := flag.Int("days", 60, "backfill depth in days")
	step := flag.Int("step", 2, "backfill window in days")
	regional := flag.Bool("regional", false, "gnsite: only outlets that have a region")
	flag.Parse()
	if *openapi {
		if err := writeOpenAPI(os.Stdout); err != nil {
			slog.Error("cannot export OpenAPI")
			os.Exit(1)
		}
		return
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	var err error
	if *backfill != "" {
		err = runBackfill(ctx, *backfill, *days, *step, *regional)
	} else {
		err = run(ctx)
	}
	if err != nil && ctx.Err() == nil {
		slog.Error("news service stopped", "error", err)
		os.Exit(1)
	}
}

func writeOpenAPI(w io.Writer) error {
	_, api, err := httpapi.New(nil)
	if err != nil {
		return err
	}
	return json.NewEncoder(w).Encode(api.OpenAPI())
}

// runBackfill fills the corpus from Google News once; finished requests are remembered, so it can be restarted.
func runBackfill(ctx context.Context, kind string, days, step int, regional bool) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	db, err := store.Open(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	pool, err := db.DB()
	if err != nil {
		return errors.New("cannot access PostgreSQL pool")
	}
	defer func() { _ = pool.Close() }()
	if err := store.Bootstrap(ctx, db); err != nil {
		return errors.New("cannot initialize news storage")
	}
	runner, err := newIngest(cfg, db, nil)
	if err != nil {
		return err
	}
	return runner.Backfill(ctx, kind, days, step, regional, true)
}

func newIngest(cfg config.Config, db *gorm.DB, afterPass func(context.Context)) (*ingest.Runner, error) {
	sources, err := ingest.LoadSources(cfg.SourcesFile)
	if err != nil {
		return nil, err
	}
	topics, err := ingest.LoadTopics(cfg.TopicsFile)
	if err != nil {
		return nil, err
	}
	return ingest.New(db, sources, topics, ingest.Config{FeedsEvery: cfg.FeedsEvery, DeepEvery: cfg.DeepEvery,
		FetchTimeout: cfg.FetchTimeout, MaxBytes: cfg.FetchMaxBytes}, afterPass), nil
}

func run(ctx context.Context) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	if err := ctx.Err(); err != nil {
		return err
	}
	var client *llm.Client
	if cfg.LLMEnabled {
		if client, err = llm.NewFromEnv(); err != nil {
			return err
		}
	}
	db, err := store.Open(ctx, cfg.DatabaseURL)
	if err != nil {
		return err
	}
	pool, err := db.DB()
	if err != nil {
		return errors.New("cannot access PostgreSQL pool")
	}
	defer func() { _ = pool.Close() }()
	if err := store.Bootstrap(ctx, db); err != nil {
		return errors.New("cannot initialize news storage")
	}
	collector, err := collect.New(ctx, db, cfg)
	if err != nil {
		return err
	}
	var worker *tagging.Worker
	var afterPass func(context.Context)
	if client != nil {
		if worker, err = tagging.NewWorker(ctx, db, client, cfg.LLMTimeout); err != nil {
			return err
		}
		seed, err := vocabulary.Load()
		if err != nil {
			return errors.New("cannot read tagging vocabulary version")
		}
		names := geotag.RegionNames(seed)
		afterPass = func(ctx context.Context) {
			// shortcut: one pass classifies at most 20000 articles; the rest waits for the next pass
			if _, _, err := geotag.Run(ctx, db, client, names, 20000); err != nil && ctx.Err() == nil {
				slog.Error("geotag pass failed", "error", err)
			}
		}
	}
	runner, err := newIngest(cfg, db, afterPass)
	if err != nil {
		return err
	}
	handler, _, err := httpapi.New(db)
	if err != nil {
		return errors.New("cannot initialize HTTP contract")
	}
	listener, err := net.Listen("tcp", cfg.HTTPAddr)
	if err != nil {
		return errors.New("cannot listen on HTTP_ADDR")
	}
	defer func() { _ = listener.Close() }()
	runCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	server := &http.Server{
		Handler: handler, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second,
		WriteTimeout: 15 * time.Second, IdleTimeout: time.Minute,
		BaseContext: func(net.Listener) context.Context { return runCtx },
	}
	collected, ingested := make(chan struct{}), make(chan struct{})
	go func() { collector.Run(runCtx); close(collected) }()
	go func() { runner.Run(runCtx); close(ingested) }()
	stopped := make(chan error, 2)
	remaining := 1 // the HTTP server
	if worker != nil {
		remaining++
		go func() { stopped <- worker.Run(runCtx) }()
	}
	go func() {
		err := server.Serve(listener)
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			stopped <- errors.New("HTTP server stopped unexpectedly")
			return
		}
		stopped <- nil
	}()
	model := ""
	if client != nil {
		model = client.Model()
	}
	slog.Info("news service started", "http_addr", listener.Addr().String(), "poll_interval", cfg.PollInterval, "model", model, "llm_enabled", cfg.LLMEnabled)
	select {
	case <-ctx.Done():
	case err = <-stopped:
		remaining--
	}
	cancel()
	cleanup, stop := context.WithTimeout(context.Background(), 5*time.Second)
	defer stop()
	if shutdownErr := server.Shutdown(cleanup); shutdownErr != nil {
		_ = server.Close()
		if err == nil {
			err = errors.New("HTTP server shutdown timed out")
		}
	}
	for range remaining {
		if stoppedErr := <-stopped; err == nil {
			err = stoppedErr
		}
	}
	<-collected
	<-ingested
	slog.Info("news service stopped")
	return err
}
