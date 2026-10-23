// Package testdb provides an isolated PostgreSQL schema for integration tests.
package testdb

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"net/url"
	"os"
	"testing"
	"time"

	"gorm.io/driver/postgres"
	"gorm.io/gorm"
	"gorm.io/gorm/logger"
)

// New skips without TEST_DATABASE_URL and cleans up only its randomly named schema.
func New(t *testing.T) (*gorm.DB, string) {
	t.Helper()
	dsn := os.Getenv("TEST_DATABASE_URL")
	if dsn == "" {
		t.Skip("set TEST_DATABASE_URL to run real PostgreSQL tests")
	}
	u, err := url.Parse(dsn)
	if err != nil || (u.Scheme != "postgres" && u.Scheme != "postgresql") || u.Hostname() == "" {
		t.Fatal("TEST_DATABASE_URL must be a PostgreSQL URL with a host")
	}
	open := func(dsn string) *gorm.DB {
		t.Helper()
		db, err := gorm.Open(postgres.Open(dsn), &gorm.Config{Logger: logger.Default.LogMode(logger.Silent)})
		if err != nil {
			t.Fatal("cannot open test PostgreSQL connection")
		}
		Close(t, db)
		return db
	}
	admin := open(dsn)
	var random [8]byte
	if _, err := rand.Read(random[:]); err != nil {
		t.Fatal(err)
	}
	schema := "news_test_" + hex.EncodeToString(random[:])
	if err := admin.WithContext(t.Context()).Exec("CREATE SCHEMA " + schema).Error; err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := admin.WithContext(ctx).Exec("DROP SCHEMA " + schema + " CASCADE").Error; err != nil {
			t.Errorf("clean up owned test schema: %v", err)
		}
	})
	query := u.Query()
	query.Set("search_path", schema)
	u.RawQuery = query.Encode()
	db := open(u.String())
	var activeSchema string
	if err := db.WithContext(t.Context()).Raw("SELECT current_schema()").Scan(&activeSchema).Error; err != nil || activeSchema != schema {
		t.Fatal("refusing to migrate outside the owned test schema")
	}
	return db, u.String()
}

func Close(t *testing.T, db *gorm.DB) {
	t.Helper()
	pool, err := db.DB()
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		if err := pool.Close(); err != nil {
			t.Errorf("close PostgreSQL pool: %v", err)
		}
	})
}
