package store

import (
	"context"
	"crypto/sha256"
	"errors"
	"fmt"
	"net/url"
	"strings"
	"time"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

const (
	TextFromRSSDescription = "rss_description"
	TextFromRSSFullText    = "rss_full_text"
	TextFromArticlePage    = "article_page"

	StatusPending    = "pending"
	StatusProcessing = "processing"
	StatusCompleted  = "completed"
	StatusFailed     = "failed"
)

type Source struct {
	ID              string    `gorm:"primaryKey"`
	Name            string    `gorm:"not null"`
	FeedURL         string    `gorm:"not null"`
	CollectionSince time.Time `gorm:"not null"`
	CreatedAt       time.Time `gorm:"not null"`
	LastPolledAt    *time.Time
	LastSuccessAt   *time.Time
	LastError       string `gorm:"not null"`
}

type Article struct {
	ID               int64  `gorm:"primaryKey"`
	SourceID         string `gorm:"not null;uniqueIndex:idx_articles_source_identity"`
	DedupKey         string `gorm:"not null;uniqueIndex:idx_articles_source_identity"`
	SourceItemID     string `gorm:"not null"`
	URL              string `gorm:"not null"`
	Title            string `gorm:"not null"`
	PublishedAt      *time.Time
	CollectedAt      time.Time `gorm:"not null"`
	Text             string    `gorm:"not null;check:article_text_provenance,(text = '' AND text_provenance = '') OR (btrim(text) <> '' AND text_provenance IN ('rss_description','rss_full_text','article_page'))"`
	TextProvenance   string    `gorm:"not null"`
	TextError        string    `gorm:"not null;check:article_text_error,text = '' OR text_error = ''"`
	ProcessingStatus string    `gorm:"not null;default:pending;check:article_processing_status,processing_status IN ('pending','processing','completed','failed')"`
	Source           *Source   `gorm:"constraint:OnUpdate:RESTRICT,OnDelete:RESTRICT"`
}

// RegisterSources updates source names/URLs while preserving the first cutoff and poll history.
func RegisterSources(ctx context.Context, db *gorm.DB, sources []Source, now time.Time) error {
	if len(sources) == 0 || now.IsZero() {
		return errors.New("sources and registration time are required")
	}
	rows := make([]Source, len(sources))
	for i, source := range sources {
		u, err := url.Parse(source.FeedURL)
		if strings.TrimSpace(source.ID) == "" || strings.TrimSpace(source.Name) == "" || err != nil || u.Scheme != "https" || u.Hostname() == "" || u.User != nil || u.Fragment != "" {
			return errors.New("source requires an ID, name and HTTPS feed URL without credentials or a fragment")
		}
		rows[i] = Source{ID: source.ID, Name: source.Name, FeedURL: source.FeedURL, CollectionSince: now.UTC().Add(-24 * time.Hour), CreatedAt: now.UTC()}
	}
	return db.WithContext(ctx).Clauses(clause.OnConflict{
		Columns:   []clause.Column{{Name: "id"}},
		DoUpdates: clause.AssignmentColumns([]string{"name", "feed_url"}),
	}).Create(&rows).Error
}

// ListSources returns persisted settings, cutoffs and poll results, ordered by source ID.
func ListSources(ctx context.Context, db *gorm.DB) ([]Source, error) {
	var sources []Source
	err := db.WithContext(ctx).Order("id").Find(&sources).Error
	return sources, err
}

// RecordSourcePoll stores the last outcome without losing the previous successful poll time.
func RecordSourcePoll(ctx context.Context, db *gorm.DB, sourceID string, at time.Time, pollErr error) error {
	if strings.TrimSpace(sourceID) == "" || at.IsZero() {
		return errors.New("source ID and poll time are required")
	}
	values := map[string]any{"last_polled_at": at.UTC(), "last_error": ""}
	if pollErr != nil {
		values["last_error"] = pollErr.Error()
	} else {
		values["last_success_at"] = at.UTC()
	}
	result := db.WithContext(ctx).Model(&Source{}).Where("id = ?", sourceID).Updates(values)
	if result.Error != nil {
		return result.Error
	}
	if result.RowsAffected == 0 {
		return gorm.ErrRecordNotFound
	}
	return nil
}

// InsertArticle preserves the first snapshot and returns the stored row and whether it was new.
func InsertArticle(ctx context.Context, db *gorm.DB, article Article) (Article, bool, error) {
	u, err := url.Parse(article.URL)
	if article.ID != 0 || strings.TrimSpace(article.SourceID) == "" || article.CollectedAt.IsZero() || err != nil || (u.Scheme != "https" && u.Scheme != "http") || u.Hostname() == "" || u.User != nil {
		return Article{}, false, errors.New("new article requires an unset ID, source ID, collection time and HTTP(S) URL without credentials")
	}
	if article.PublishedAt != nil && article.PublishedAt.IsZero() {
		return Article{}, false, errors.New("article publication time must be absent or nonzero")
	}
	if article.ProcessingStatus != "" && article.ProcessingStatus != StatusPending {
		return Article{}, false, errors.New("new article processing status must be pending")
	}
	if article.Text == "" {
		if article.TextProvenance != "" {
			return Article{}, false, errors.New("article without text must not claim text provenance")
		}
	} else if strings.TrimSpace(article.Text) == "" || (article.TextProvenance != TextFromRSSDescription && article.TextProvenance != TextFromRSSFullText && article.TextProvenance != TextFromArticlePage) || article.TextError != "" {
		return Article{}, false, errors.New("article text requires known provenance and no extraction error")
	}
	article.DedupKey = articleKey(article.SourceItemID, article.URL)
	article.ProcessingStatus = StatusPending
	article.CollectedAt = article.CollectedAt.UTC()
	article.Source = nil
	result := db.WithContext(ctx).Clauses(clause.OnConflict{
		Columns: []clause.Column{{Name: "source_id"}, {Name: "dedup_key"}}, DoNothing: true,
	}).Create(&article)
	if result.Error != nil {
		return Article{}, false, result.Error
	}
	if result.RowsAffected == 0 {
		stored, err := FindArticle(ctx, db, article.SourceID, article.SourceItemID, article.URL)
		return stored, false, err
	}
	return article, true, nil
}

// FindArticle checks source identity before callers fetch pages or invoke an LLM.
func FindArticle(ctx context.Context, db *gorm.DB, sourceID, sourceItemID, articleURL string) (Article, error) {
	if strings.TrimSpace(sourceID) == "" || (sourceItemID == "" && articleURL == "") {
		return Article{}, errors.New("source ID and article identity are required")
	}
	var article Article
	err := db.WithContext(ctx).Where("source_id = ? AND dedup_key = ?", sourceID, articleKey(sourceItemID, articleURL)).First(&article).Error
	return article, err
}

// LoadArticle reads a stored snapshot by its generated ID.
func LoadArticle(ctx context.Context, db *gorm.DB, id int64) (Article, error) {
	if id <= 0 {
		return Article{}, errors.New("article ID must be positive")
	}
	var article Article
	err := db.WithContext(ctx).First(&article, id).Error
	return article, err
}

func articleKey(sourceItemID, articleURL string) string {
	identity := "id:" + sourceItemID
	if sourceItemID == "" {
		identity = "url:" + articleURL
	}
	return fmt.Sprintf("%x", sha256.Sum256([]byte(identity)))
}
