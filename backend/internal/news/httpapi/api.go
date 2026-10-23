// Package httpapi exposes the news service's read-only HTTP contract.
package httpapi

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/danielgtaylor/huma/v2"
	"github.com/danielgtaylor/huma/v2/adapters/humagin"
	"github.com/gin-gonic/gin"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/vocabulary"
	"gorm.io/gorm"
)

type Health struct {
	Status string `json:"status" enum:"ok"`
}

type HealthOutput struct{ Body Health }

type TagsOutput struct{ Body vocabulary.Vocabulary }

type Source struct {
	ID              string     `json:"id"`
	Name            string     `json:"name"`
	FeedURL         string     `json:"feed_url" format:"uri"`
	CollectionSince time.Time  `json:"collection_since"`
	CreatedAt       time.Time  `json:"created_at"`
	LastPolledAt    *time.Time `json:"last_polled_at"`
	LastSuccessAt   *time.Time `json:"last_success_at"`
	LastError       string     `json:"last_error"`
}

type SourcesOutput struct {
	Body struct {
		Sources []Source `json:"sources" nullable:"false"`
	}
}

// New registers the same contract for serving and offline export; registration performs no I/O.
// A nil database is only useful for exporting the contract or checking process health.
func New(db *gorm.DB) (*gin.Engine, huma.API, error) {
	seed, err := vocabulary.Load()
	if err != nil {
		return nil, nil, err
	}
	router := gin.New()
	_ = router.SetTrustedProxies(nil)
	router.Use(gin.CustomRecoveryWithWriter(nil, func(c *gin.Context, _ any) {
		slog.Error("HTTP handler panicked")
		c.Header("Content-Type", "application/problem+json")
		c.AbortWithStatusJSON(http.StatusInternalServerError, huma.NewError(http.StatusInternalServerError, "internal server error"))
	}))
	config := huma.DefaultConfig("News service", "1.0.0")
	config.RejectUnknownQueryParameters = true
	api := humagin.New(router, config)

	huma.Register(api, huma.Operation{
		OperationID: "health", Method: http.MethodGet, Path: "/healthz",
		Summary: "Проверить работоспособность процесса", Tags: []string{"health"}, Errors: []int{422, 500},
	}, func(context.Context, *struct{}) (*HealthOutput, error) {
		return &HealthOutput{Body: Health{Status: "ok"}}, nil
	})
	huma.Register(api, huma.Operation{
		OperationID: "readiness", Method: http.MethodGet, Path: "/readyz",
		Summary: "Проверить подключение к PostgreSQL", Tags: []string{"health"}, Errors: []int{422, 500, 503},
	}, func(ctx context.Context, _ *struct{}) (*HealthOutput, error) {
		if db == nil {
			return nil, huma.Error503ServiceUnavailable("database unavailable")
		}
		pool, err := db.DB()
		if err != nil {
			return nil, huma.Error503ServiceUnavailable("database unavailable")
		}
		ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
		defer cancel()
		if err := pool.PingContext(ctx); err != nil {
			return nil, huma.Error503ServiceUnavailable("database unavailable")
		}
		return &HealthOutput{Body: Health{Status: "ok"}}, nil
	})
	huma.Register(api, huma.Operation{
		OperationID: "list-tags", Method: http.MethodGet, Path: "/v1/tags",
		Summary: "Получить фиксированный словарь из PostgreSQL", Tags: []string{"tags"}, Errors: []int{422, 500, 503},
	}, func(ctx context.Context, _ *struct{}) (*TagsOutput, error) {
		if db == nil {
			return nil, huma.Error503ServiceUnavailable("vocabulary unavailable")
		}
		ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		v, err := store.LoadVocabulary(ctx, db, seed.Version)
		if err != nil {
			return nil, huma.Error503ServiceUnavailable("vocabulary unavailable")
		}
		return &TagsOutput{Body: v}, nil
	})
	huma.Register(api, huma.Operation{
		OperationID: "list-sources", Method: http.MethodGet, Path: "/v1/sources",
		Summary: "Получить источники и состояние сбора", Tags: []string{"sources"}, Errors: []int{422, 500, 503},
	}, func(ctx context.Context, _ *struct{}) (*SourcesOutput, error) {
		if db == nil {
			return nil, huma.Error503ServiceUnavailable("sources unavailable")
		}
		ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		rows, err := store.ListSources(ctx, db)
		if err != nil {
			return nil, huma.Error503ServiceUnavailable("sources unavailable")
		}
		out := &SourcesOutput{}
		out.Body.Sources = make([]Source, len(rows))
		for i, row := range rows {
			out.Body.Sources[i] = Source{
				ID: row.ID, Name: row.Name, FeedURL: row.FeedURL,
				CollectionSince: row.CollectionSince, CreatedAt: row.CreatedAt,
				LastPolledAt: row.LastPolledAt, LastSuccessAt: row.LastSuccessAt, LastError: row.LastError,
			}
		}
		return out, nil
	})
	registerStatus(api, db)
	registerNews(api, db)
	return router, api, nil
}
