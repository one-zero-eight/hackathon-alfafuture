package store

import (
	"context"
	"time"

	"gorm.io/gorm"
)

type StatusSnapshot struct {
	Pending                       int64
	Processing                    int64
	Completed                     int64
	Failed                        int64
	BudgetPauseUntil              *time.Time
	Attempts                      int64
	PromptTokens                  *int64
	CompletionTokens              *int64
	TotalTokens                   *int64
	PromptTokensKnownAttempts     int64
	CompletionTokensKnownAttempts int64
	TotalTokensKnownAttempts      int64
}

// ReadStatus uses one statement snapshot; missing usage stays NULL rather than becoming free.
func ReadStatus(ctx context.Context, db *gorm.DB) (StatusSnapshot, error) {
	var result StatusSnapshot
	err := db.WithContext(ctx).Raw(`
		SELECT article_counts.*, usage_totals.*,
		       (SELECT until FROM budget_pauses WHERE id = 1) AS budget_pause_until
		FROM (
			SELECT count(*) FILTER (WHERE processing_status = 'pending') AS pending,
			       count(*) FILTER (WHERE processing_status = 'processing') AS processing,
			       count(*) FILTER (WHERE processing_status = 'completed') AS completed,
			       count(*) FILTER (WHERE processing_status = 'failed') AS failed
			FROM articles
		) AS article_counts
		CROSS JOIN (
			SELECT count(*) AS attempts,
			       sum(prompt_tokens) AS prompt_tokens,
			       sum(completion_tokens) AS completion_tokens,
			       sum(total_tokens) AS total_tokens,
			       count(prompt_tokens) AS prompt_tokens_known_attempts,
			       count(completion_tokens) AS completion_tokens_known_attempts,
			       count(total_tokens) AS total_tokens_known_attempts
			FROM tagging_attempts
		) AS usage_totals
	`).Scan(&result).Error
	return result, err
}
