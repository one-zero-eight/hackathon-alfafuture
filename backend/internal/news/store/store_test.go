package store

import (
	"context"
	"encoding/json"
	"errors"
	"reflect"
	"slices"
	"strings"
	"testing"

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/vocabulary"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/testdb"
	"gorm.io/gorm"
)

func TestOpenRejectsInvalidDSNWithoutExposingCredentials(t *testing.T) {
	_, err := Open(t.Context(), "postgres://user:do-not-log@localhost:invalid/db")
	if err == nil || strings.Contains(err.Error(), "do-not-log") {
		t.Fatalf("expected a sanitized connection error: %v", err)
	}
}

func TestOpenHonorsCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	if _, err := Open(ctx, "postgres://localhost/db"); !errors.Is(err, context.Canceled) {
		t.Fatalf("expected cancellation: %v", err)
	}
}

func integrationDatabase(t *testing.T) (*gorm.DB, string) {
	t.Helper()
	return testdb.New(t)
}

func closeDatabase(t *testing.T, db *gorm.DB) {
	t.Helper()
	testdb.Close(t, db)
}

func assertCount(t *testing.T, db *gorm.DB, model any, want int64) {
	t.Helper()
	var got int64
	if err := db.Model(model).Count(&got).Error; err != nil {
		t.Fatal(err)
	}
	if got != want {
		t.Fatalf("%T rows: got %d, want %d", model, got, want)
	}
}

func assertSQLState(t *testing.T, err error, want ...string) {
	t.Helper()
	var state interface{ SQLState() string }
	if !errors.As(err, &state) || !slices.Contains(want, state.SQLState()) {
		t.Fatalf("expected PostgreSQL error %v, got %v", want, err)
	}
}

func TestPostgresVocabularyRoundTripAndRepeatedBootstrap(t *testing.T) {
	db, dsn := integrationDatabase(t)
	if err := Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	want, err := vocabulary.Load()
	if err != nil {
		t.Fatal(err)
	}
	var before vocabularyVersion
	if err := db.First(&before, "version = ?", want.Version).Error; err != nil {
		t.Fatal(err)
	}
	pool, err := db.DB()
	if err != nil {
		t.Fatal(err)
	}
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := Open(t.Context(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	closeDatabase(t, reopened)
	if err := Bootstrap(t.Context(), reopened); err != nil {
		t.Fatal(err)
	}
	assertCount(t, reopened, &vocabularyVersion{}, 1)
	assertCount(t, reopened, &tag{}, 525)
	var after vocabularyVersion
	if err := reopened.First(&after, "version = ?", want.Version).Error; err != nil {
		t.Fatal(err)
	}
	if before.Checksum != after.Checksum || !before.CreatedAt.Equal(after.CreatedAt) {
		t.Fatal("repeated bootstrap modified the stored version")
	}
	got, err := LoadVocabulary(t.Context(), reopened, want.Version)
	if err != nil {
		t.Fatal(err)
	}
	slices.SortFunc(want.Tags, func(a, b vocabulary.Tag) int { return strings.Compare(a.ID, b.ID) })
	var gotJSON, wantJSON any
	for _, pair := range []struct {
		value vocabulary.Vocabulary
		out   *any
	}{{got, &gotJSON}, {want, &wantJSON}} {
		data, err := json.Marshal(pair.value)
		if err != nil {
			t.Fatal(err)
		}
		if err := json.Unmarshal(data, pair.out); err != nil {
			t.Fatal(err)
		}
	}
	if !reflect.DeepEqual(gotJSON, wantJSON) {
		t.Fatal("database round-trip lost tag payloads, mappings, rules or schema metadata")
	}
	if _, err := LoadVocabulary(t.Context(), reopened, "missing"); !errors.Is(err, gorm.ErrRecordNotFound) {
		t.Fatalf("expected missing vocabulary error: %v", err)
	}
}

func TestPostgresVocabularyConstraints(t *testing.T) {
	db, _ := integrationDatabase(t)
	if err := Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	duplicate := tag{Version: "v1", ID: "industry:okved:01", Dimension: "industry"}
	assertSQLState(t, db.Create(&duplicate).Error, "23505")
	missingVersion := tag{Version: "missing", ID: "industry:okved:01", Dimension: "industry"}
	assertSQLState(t, db.Create(&missingVersion).Error, "23503")
	parent := "missing"
	missingParent := tag{Version: "v1", ID: "test:missing-parent", Dimension: "geography", ParentID: &parent}
	assertSQLState(t, db.Create(&missingParent).Error, "23503")
	v2 := vocabularyVersion{Version: "v2", Checksum: "test", Metadata: vocabulary.Vocabulary{Version: "v2"}}
	if err := db.Create(&v2).Error; err != nil {
		t.Fatal(err)
	}
	newVersion := tag{Version: "v2", ID: "industry:okved:01", Dimension: "industry"}
	if err := db.Create(&newVersion).Error; err != nil {
		t.Fatal("stable tag IDs must be reusable in a different version:", err)
	}
	parent = "geography:m49:030"
	crossVersion := tag{Version: "v2", ID: "test:cross-version", Dimension: "geography", ParentID: &parent}
	assertSQLState(t, db.Create(&crossVersion).Error, "23503")
	assertSQLState(t, db.Where("version = ? AND id = ?", "v1", parent).Delete(&tag{}).Error, "23001", "23503")
	assertSQLState(t, db.Where("version = ?", "v1").Delete(&vocabularyVersion{}).Error, "23001", "23503")
}

func TestPostgresBootstrapRejectsChangedFrozenVersion(t *testing.T) {
	db, _ := integrationDatabase(t)
	if err := Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	if err := db.Model(&vocabularyVersion{}).Where("version = ?", "v1").Update("checksum", "different").Error; err != nil {
		t.Fatal(err)
	}
	if err := Bootstrap(t.Context(), db); err == nil || !strings.Contains(err.Error(), "checksum") {
		t.Fatalf("expected frozen-version conflict: %v", err)
	}
	var stored vocabularyVersion
	if err := db.First(&stored, "version = ?", "v1").Error; err != nil {
		t.Fatal(err)
	}
	if stored.Checksum != "different" {
		t.Fatal("bootstrap overwrote an existing conflicting version")
	}
	assertCount(t, db, &tag{}, 525)
}

func TestPostgresBootstrapRollsBackFailedSeed(t *testing.T) {
	db, _ := integrationDatabase(t)
	if err := db.AutoMigrate(&vocabularyVersion{}, &tag{}); err != nil {
		t.Fatal(err)
	}
	if err := db.Exec("ALTER TABLE tags ADD CONSTRAINT reject_test_tag CHECK (id <> 'resource:oil')").Error; err != nil {
		t.Fatal(err)
	}
	assertSQLState(t, Bootstrap(t.Context(), db), "23514")
	assertCount(t, db, &vocabularyVersion{}, 0)
	assertCount(t, db, &tag{}, 0)
}
