package store

import (
	"context"
	"time"

	"gorm.io/gorm"
)

func NextArticleForTagging(ctx context.Context, db *gorm.DB) (Article, error) {
	var article Article
	err := db.WithContext(ctx).Where("processing_status = ? AND btrim(text) <> ''", StatusPending).Order("id").First(&article).Error
	return article, err
}

// NextArticlesForTagging returns the head of the same queue, for batched work ahead of tagging.
func NextArticlesForTagging(ctx context.Context, db *gorm.DB, limit int) ([]Article, error) {
	var articles []Article
	err := db.WithContext(ctx).Where("processing_status = ? AND btrim(text) <> ''", StatusPending).Order("id").Limit(limit).Find(&articles).Error
	return articles, err
}

func ProcessingAttempts(ctx context.Context, db *gorm.DB) ([]TaggingAttempt, error) {
	var attempts []TaggingAttempt
	err := db.WithContext(ctx).Where("status = ?", StatusProcessing).Order("id").Find(&attempts).Error
	return attempts, err
}

func FailPendingArticle(ctx context.Context, db *gorm.DB, id int64) error {
	result := db.WithContext(ctx).Model(&Article{}).Where("id = ? AND processing_status = ?", id, StatusPending).Update("processing_status", StatusFailed)
	if result.Error != nil {
		return result.Error
	}
	if result.RowsAffected != 1 {
		return ErrArticleNotPending
	}
	return nil
}

// FinishBudgetAttempt saves the attempt and pause together, so restart cannot lose the pause.
func FinishBudgetAttempt(ctx context.Context, db *gorm.DB, id int64, completion AttemptCompletion, until time.Time) error {
	return db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := FinishAttempt(ctx, tx, id, completion); err != nil {
			return err
		}
		return SetBudgetPause(ctx, tx, &until)
	})
}
