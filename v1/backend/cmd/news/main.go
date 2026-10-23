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

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/collect"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/config"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/httpapi"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
)

func main() {
	gin.SetMode(gin.ReleaseMode)
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	openapi := flag.Bool("openapi", false, "print OpenAPI JSON without loading config or connecting to services")
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
	if err := run(ctx); err != nil && ctx.Err() == nil {
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

func run(ctx context.Context) error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}
	if err := ctx.Err(); err != nil {
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
	collected := make(chan struct{})
	go func() { collector.Run(runCtx); close(collected) }()
	stopped := make(chan error, 1)
	go func() {
		err := server.Serve(listener)
		if err != nil && !errors.Is(err, http.ErrServerClosed) {
			stopped <- errors.New("HTTP server stopped unexpectedly")
			return
		}
		stopped <- nil
	}()
	slog.Info("news service started", "http_addr", listener.Addr().String(), "poll_interval", cfg.PollInterval)
	remaining := 1
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
	slog.Info("news service stopped")
	return err
}
