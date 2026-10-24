package store

import (
	"context"
	"errors"
	"strings"
	"time"

	"gorm.io/gorm"
	"gorm.io/gorm/clause"
)

// SourceRegion links an outlet to its region tag (geography:region:NNN). The tag is only a candidate for the outlet's articles.
type SourceRegion struct {
	SourceID  string  `gorm:"primaryKey"`
	RegionTag string  `gorm:"not null"`
	Basis     string  `gorm:"not null;default:outlet_region"`
	Source    *Source `gorm:"constraint:OnUpdate:RESTRICT,OnDelete:RESTRICT"`
}

func (SourceRegion) TableName() string { return "source_regions" }

// ArticleGeo is the region verdict for one article of a regional outlet; a nil RegionTag means "checked, not regional".
type ArticleGeo struct {
	ArticleID int64 `gorm:"primaryKey"`
	RegionTag *string
	Basis     string    `gorm:"not null;check:article_geo_basis,basis IN ('section','ai')"`
	DecidedAt time.Time `gorm:"not null;autoCreateTime"`
	Article   *Article  `gorm:"constraint:OnUpdate:RESTRICT,OnDelete:RESTRICT"`
}

func (ArticleGeo) TableName() string { return "article_geo" }

// FetchWindow remembers a finished Google News request (kind + key), so backfills resume after a restart.
type FetchWindow struct {
	Kind   string    `gorm:"primaryKey"`
	Key    string    `gorm:"primaryKey"`
	DoneAt time.Time `gorm:"not null;autoCreateTime"`
}

// GeoCandidate is an article of a regional outlet that has no region verdict yet.
type GeoCandidate struct {
	ID        int64
	Title     string
	RegionTag string
}

// EnsureSource registers a curated source without touching an existing one; region is optional.
// Unlike RegisterSources it accepts any feed URL, because the curated list contains http feeds and Google News placeholders.
func EnsureSource(ctx context.Context, db *gorm.DB, s Source, region string) error {
	if strings.TrimSpace(s.ID) == "" || strings.TrimSpace(s.Name) == "" || strings.TrimSpace(s.FeedURL) == "" {
		return errors.New("source requires an ID, name and feed URL")
	}
	now := time.Now().UTC()
	s.CollectionSince, s.CreatedAt = now.AddDate(-1, 0, 0), now
	return db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		if err := tx.Clauses(clause.OnConflict{DoNothing: true}).Create(&s).Error; err != nil {
			return err
		}
		if region == "" {
			return nil
		}
		return tx.Clauses(clause.OnConflict{Columns: []clause.Column{{Name: "source_id"}}, DoUpdates: clause.AssignmentColumns([]string{"region_tag"})}).
			Create(&SourceRegion{SourceID: s.ID, RegionTag: region}).Error
	})
}

// SaveGeo stores verdicts; a verdict from an outlet section ("section") replaces an earlier AI verdict, never the other way round.
func SaveGeo(ctx context.Context, db *gorm.DB, rows []ArticleGeo) error {
	if len(rows) == 0 {
		return nil
	}
	conflict := clause.OnConflict{DoNothing: true}
	if rows[0].Basis == "section" {
		conflict = clause.OnConflict{Columns: []clause.Column{{Name: "article_id"}}, DoUpdates: clause.AssignmentColumns([]string{"region_tag", "basis", "decided_at"})}
	}
	return db.WithContext(ctx).Clauses(conflict).Create(&rows).Error
}

// PendingGeo lists articles of regional outlets without a verdict, grouped by region for batching.
func PendingGeo(ctx context.Context, db *gorm.DB, limit int) ([]GeoCandidate, error) {
	var rows []GeoCandidate
	err := db.WithContext(ctx).Raw(`SELECT a.id, a.title, r.region_tag FROM articles a
		JOIN source_regions r ON r.source_id = a.source_id
		LEFT JOIN article_geo g ON g.article_id = a.id
		WHERE g.article_id IS NULL ORDER BY r.region_tag, a.id LIMIT ?`, limit).Scan(&rows).Error
	return rows, err
}

// DoneWindows returns the keys of finished requests of one kind.
func DoneWindows(ctx context.Context, db *gorm.DB, kind string) (map[string]bool, error) {
	var keys []string
	if err := db.WithContext(ctx).Model(&FetchWindow{}).Where("kind = ?", kind).Pluck("key", &keys).Error; err != nil {
		return nil, err
	}
	done := make(map[string]bool, len(keys))
	for _, k := range keys {
		done[k] = true
	}
	return done, nil
}

func MarkWindows(ctx context.Context, db *gorm.DB, kind string, keys []string) error {
	if len(keys) == 0 {
		return nil
	}
	rows := make([]FetchWindow, len(keys))
	for i, k := range keys {
		rows[i] = FetchWindow{Kind: kind, Key: k}
	}
	return db.WithContext(ctx).Clauses(clause.OnConflict{DoNothing: true}).Create(&rows).Error
}
