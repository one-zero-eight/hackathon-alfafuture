// Package store owns PostgreSQL persistence for the news service.
package store

import (
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/vocabulary"
	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/clause"
	"gorm.io/gorm/logger"
)

type vocabularyVersion struct {
	Version   string                `gorm:"primaryKey"`
	Checksum  string                `gorm:"not null"`
	Metadata  vocabulary.Vocabulary `gorm:"serializer:json;type:jsonb;not null"`
	CreatedAt time.Time             `gorm:"not null"`
}

type tag struct {
	Version   string `gorm:"primaryKey"`
	ID        string `gorm:"primaryKey"`
	Dimension string `gorm:"not null;index"`
	ParentID  *string
	Payload   vocabulary.Tag `gorm:"serializer:json;type:jsonb;not null"`
	// Both models expose Version, so the relationship direction must be explicit.
	Vocabulary *vocabularyVersion `gorm:"belongsTo:Vocabulary;foreignKey:Version;references:Version;constraint:OnUpdate:RESTRICT,OnDelete:RESTRICT"`
	Parent     *tag               `gorm:"foreignKey:Version,ParentID;references:Version,ID;constraint:OnUpdate:RESTRICT,OnDelete:RESTRICT"`
}

// Open connects without logging SQL or exposing connection credentials in errors.
// The caller owns the connection pool and closes it through db.DB().
func Open(ctx context.Context, databaseURL string) (*gorm.DB, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	db, err := gorm.Open(postgres.Open(databaseURL), &gorm.Config{
		DisableAutomaticPing: true,
		Logger:               logger.Default.LogMode(logger.Silent),
	})
	if err != nil {
		return nil, errors.New("cannot initialize PostgreSQL connection")
	}
	pool, err := db.DB()
	if err != nil {
		return nil, errors.New("cannot access PostgreSQL connection pool")
	}
	if err := pool.PingContext(ctx); err != nil {
		_ = pool.Close()
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		return nil, errors.New("cannot connect to PostgreSQL")
	}
	return db, nil
}

// Bootstrap initializes the news schema and inserts the fixed vocabulary atomically.
func Bootstrap(ctx context.Context, db *gorm.DB) error {
	v, err := vocabulary.Load()
	if err != nil {
		return fmt.Errorf("load vocabulary seed: %w", err)
	}
	encoded, err := json.Marshal(v)
	if err != nil {
		return fmt.Errorf("encode vocabulary seed: %w", err)
	}
	checksum := fmt.Sprintf("%x", sha256.Sum256(encoded))
	tags := make([]tag, len(v.Tags))
	for i, value := range v.Tags {
		tags[i] = tag{Version: v.Version, ID: value.ID, Dimension: value.Dimension, ParentID: value.ParentID, Payload: value}
	}
	v.Tags = nil
	version := vocabularyVersion{Version: v.Version, Checksum: checksum, Metadata: v}
	return db.WithContext(ctx).Transaction(func(tx *gorm.DB) error {
		// shortcut: initial-schema bootstrap; use versioned migrations before evolving persistent schemas.
		if err := tx.AutoMigrate(&vocabularyVersion{}, &tag{}, &Source{}, &Article{}); err != nil {
			return fmt.Errorf("initialize news schema: %w", err)
		}
		if err := tx.Clauses(clause.OnConflict{DoNothing: true}).Create(&version).Error; err != nil {
			return fmt.Errorf("insert vocabulary version: %w", err)
		}
		var stored vocabularyVersion
		if err := tx.First(&stored, "version = ?", v.Version).Error; err != nil {
			return fmt.Errorf("read vocabulary version: %w", err)
		}
		if stored.Checksum != checksum {
			return errors.New("stored vocabulary checksum differs: publish a new vocabulary version")
		}
		if err := tx.Clauses(clause.OnConflict{DoNothing: true}).Create(&tags).Error; err != nil {
			return fmt.Errorf("insert vocabulary tags: %w", err)
		}
		return nil
	})
}

// LoadVocabulary reads metadata and tags from PostgreSQL, ordered by tag ID.
func LoadVocabulary(ctx context.Context, db *gorm.DB, version string) (vocabulary.Vocabulary, error) {
	var stored vocabularyVersion
	if err := db.WithContext(ctx).First(&stored, "version = ?", version).Error; err != nil {
		return vocabulary.Vocabulary{}, fmt.Errorf("read vocabulary version: %w", err)
	}
	var rows []tag
	if err := db.WithContext(ctx).Where("version = ?", version).Order("id").Find(&rows).Error; err != nil {
		return vocabulary.Vocabulary{}, fmt.Errorf("read vocabulary tags: %w", err)
	}
	result := stored.Metadata
	result.Tags = make([]vocabulary.Tag, len(rows))
	for i, row := range rows {
		result.Tags[i] = row.Payload
	}
	return result, nil
}
