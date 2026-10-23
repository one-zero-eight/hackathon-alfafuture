package main

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/collect"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/config"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
)

func main() {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := run(ctx); err != nil && ctx.Err() == nil {
		slog.Error("news service stopped", "error", err)
		os.Exit(1)
	}
}

func run(ctx context.Context) error {
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
	collector, err := collect.New(ctx, db, cfg)
	if err != nil {
		return err
	}
	slog.Info("news collection started", "poll_interval", cfg.PollInterval)
	collector.Run(ctx)
	slog.Info("news collection stopped")
	return nil
}
