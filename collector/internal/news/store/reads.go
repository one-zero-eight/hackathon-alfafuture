package store

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"gorm.io/gorm"
)

type ArticleQuery struct {
	SourceID, TagID, ProcessingStatus string
	PublishedFrom, PublishedTo        *time.Time
	Limit, Offset                     int
}

type ArticlePage struct {
	Articles []Article
	Attempts []TaggingAttempt
	HasMore  bool
}

// ListArticles returns a coherent page and its completed results without loading private traces.
func ListArticles(ctx context.Context, db *gorm.DB, q ArticleQuery) (ArticlePage, error) {
	if q.Limit < 1 || q.Limit > 100 || q.Offset < 0 ||
		(q.ProcessingStatus != StatusPending && q.ProcessingStatus != StatusProcessing && q.ProcessingStatus != StatusCompleted && q.ProcessingStatus != StatusFailed) ||
		(q.PublishedFrom != nil && q.PublishedTo != nil && q.PublishedFrom.After(*q.PublishedTo)) {
		return ArticlePage{}, errors.New("invalid article query")
	}
	var page ArticlePage
	err := db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		query := tx.Where("processing_status = ?", q.ProcessingStatus)
		if q.SourceID != "" {
			query = query.Where("source_id = ?", q.SourceID)
		}
		if q.TagID != "" {
			query = query.Where(`EXISTS (
				SELECT 1 FROM tagging_attempts AS a JOIN tag_assignments AS t ON t.attempt_id = a.id
				WHERE a.article_id = articles.id AND a.status = ? AND t.tag_id = ?
			)`, StatusCompleted, q.TagID)
		}
		if q.PublishedFrom != nil {
			query = query.Where("published_at >= ?", *q.PublishedFrom)
		}
		if q.PublishedTo != nil {
			query = query.Where("published_at <= ?", *q.PublishedTo)
		}
		// shortcut: offset pages can shift during writes; use cursors if a consumer needs stable traversal.
		if err := query.Order("COALESCE(published_at, collected_at) DESC, id DESC").Limit(q.Limit + 1).Offset(q.Offset).Find(&page.Articles).Error; err != nil {
			return err
		}
		page.HasMore = len(page.Articles) > q.Limit
		if page.HasMore {
			page.Articles = page.Articles[:q.Limit]
		}
		if len(page.Articles) == 0 {
			return nil
		}
		ids := make([]int64, len(page.Articles))
		for i, article := range page.Articles {
			ids[i] = article.ID
		}
		return publicAttempts(tx).Where("article_id IN ? AND status = ?", ids, StatusCompleted).Find(&page.Attempts).Error
	}, &sql.TxOptions{Isolation: sql.LevelRepeatableRead, ReadOnly: true})
	if err != nil {
		return ArticlePage{}, err
	}
	return page, nil
}

func ReadArticleDetail(ctx context.Context, db *gorm.DB, id int64) (Article, []TaggingAttempt, error) {
	var article Article
	var attempts []TaggingAttempt
	err := db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		var err error
		article, err = LoadArticle(ctx, tx, id)
		if err != nil {
			return err
		}
		return publicAttempts(tx).Where("article_id = ?", id).Find(&attempts).Error
	}, &sql.TxOptions{Isolation: sql.LevelRepeatableRead, ReadOnly: true})
	if err != nil {
		return Article{}, nil, err
	}
	return article, attempts, nil
}

func publicAttempts(db *gorm.DB) *gorm.DB {
	return db.Select("id", "article_id", "number", "version", "prompt_version", "model", "started_at", "finished_at", "status", "error", "prompt_tokens", "completion_tokens", "total_tokens").
		Order("article_id, number").
		Preload("Assignments", func(tx *gorm.DB) *gorm.DB { return tx.Order("tag_id") }).
		Preload("Events", func(tx *gorm.DB) *gorm.DB { return tx.Order("id") })
}
