package store

import (
	"context"
	"errors"
	"strings"

	"gorm.io/gorm"
)

// RecordArticleText saves an extraction outcome only while text is empty and pending.
// The caller supplies credential-free diagnostics; the first successful snapshot is immutable.
func RecordArticleText(ctx context.Context, db *gorm.DB, id int64, text, provenance string, extractionErr error) (Article, error) {
	if id <= 0 {
		return Article{}, errors.New("article ID must be positive")
	}
	textError := ""
	if extractionErr != nil {
		textError = extractionErr.Error()
		if strings.TrimSpace(textError) == "" {
			return Article{}, errors.New("failed extraction requires a nonempty diagnostic")
		}
	} else if strings.TrimSpace(text) == "" {
		return Article{}, errors.New("successful extraction requires nonempty text")
	}
	if err := validateArticleText(text, provenance, textError); err != nil {
		return Article{}, err
	}
	updated := db.WithContext(ctx).Model(&Article{}).Where("id = ? AND text = '' AND processing_status = ?", id, StatusPending).Updates(map[string]any{
		"text": text, "text_provenance": provenance, "text_error": textError,
	})
	if updated.Error != nil {
		return Article{}, updated.Error
	}
	return LoadArticle(ctx, db, id)
}

// ListArticlesAwaitingText includes persisted failures even if the item has left the feed.
func ListArticlesAwaitingText(ctx context.Context, db *gorm.DB, sourceID string) ([]Article, error) {
	if strings.TrimSpace(sourceID) == "" {
		return nil, errors.New("source ID is required")
	}
	var articles []Article
	err := db.WithContext(ctx).Where("source_id = ? AND text = '' AND processing_status = ?", sourceID, StatusPending).Order("id").Find(&articles).Error
	return articles, err
}
