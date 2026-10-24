package httpapi

import (
	"context"
	"net/http"
	"time"

	"github.com/danielgtaylor/huma/v2"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/store"
	"gorm.io/gorm"
)

type ArticleCounts struct {
	Pending    int64 `json:"pending" minimum:"0"`
	Processing int64 `json:"processing" minimum:"0"`
	Completed  int64 `json:"completed" minimum:"0"`
	Failed     int64 `json:"failed" minimum:"0"`
}

type UsageTotals struct {
	Attempts                      int64  `json:"attempts" minimum:"0"`
	PromptTokens                  *int64 `json:"prompt_tokens" minimum:"0"`
	CompletionTokens              *int64 `json:"completion_tokens" minimum:"0"`
	TotalTokens                   *int64 `json:"total_tokens" minimum:"0"`
	PromptTokensKnownAttempts     int64  `json:"prompt_tokens_known_attempts" minimum:"0"`
	CompletionTokensKnownAttempts int64  `json:"completion_tokens_known_attempts" minimum:"0"`
	TotalTokensKnownAttempts      int64  `json:"total_tokens_known_attempts" minimum:"0"`
}

type StatusOutput struct {
	Body struct {
		Articles         ArticleCounts `json:"articles"`
		BudgetPauseUntil *time.Time    `json:"budget_pause_until"`
		TaggingPaused    bool          `json:"tagging_paused"`
		Usage            UsageTotals   `json:"usage"`
	}
}

func registerStatus(api huma.API, db *gorm.DB) {
	huma.Register(api, huma.Operation{
		OperationID: "read-status", Method: http.MethodGet, Path: "/v1/status",
		Summary: "Получить очереди, бюджетную паузу и доступный usage", Tags: []string{"status"}, Errors: []int{422, 500, 503},
	}, func(ctx context.Context, _ *struct{}) (*StatusOutput, error) {
		if db == nil {
			return nil, huma.Error503ServiceUnavailable("status unavailable")
		}
		ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		snapshot, err := store.ReadStatus(ctx, db)
		if err != nil {
			return nil, huma.Error503ServiceUnavailable("status unavailable")
		}
		out := &StatusOutput{}
		out.Body.Articles = ArticleCounts{Pending: snapshot.Pending, Processing: snapshot.Processing, Completed: snapshot.Completed, Failed: snapshot.Failed}
		out.Body.BudgetPauseUntil = snapshot.BudgetPauseUntil
		out.Body.TaggingPaused = snapshot.BudgetPauseUntil != nil && snapshot.BudgetPauseUntil.After(time.Now())
		out.Body.Usage = UsageTotals{
			Attempts: snapshot.Attempts, PromptTokens: snapshot.PromptTokens, CompletionTokens: snapshot.CompletionTokens, TotalTokens: snapshot.TotalTokens,
			PromptTokensKnownAttempts: snapshot.PromptTokensKnownAttempts, CompletionTokensKnownAttempts: snapshot.CompletionTokensKnownAttempts, TotalTokensKnownAttempts: snapshot.TotalTokensKnownAttempts,
		}
		return out, nil
	})
}
