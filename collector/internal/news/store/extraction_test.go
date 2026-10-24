package store

import (
	"errors"
	"fmt"
	"reflect"
	"testing"

	"gorm.io/gorm"
)

func TestArticleExtractionValidation(t *testing.T) {
	for _, tc := range []struct {
		name       string
		id         int64
		text       string
		provenance string
		err        error
	}{
		{"zero ID", 0, "text", TextFromArticlePage, nil},
		{"negative ID", -1, "text", TextFromArticlePage, nil},
		{"empty success", 1, "", "", nil},
		{"blank success", 1, " \t\n", TextFromArticlePage, nil},
		{"missing provenance", 1, "text", "", nil},
		{"unknown provenance", 1, "text", "invented", nil},
		{"text with failure", 1, "text", TextFromArticlePage, errors.New("unavailable")},
		{"failure with provenance", 1, "", TextFromArticlePage, errors.New("unavailable")},
		{"empty diagnostic", 1, "", "", errors.New("")},
		{"blank diagnostic", 1, "", "", errors.New(" \t\n")},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if _, err := RecordArticleText(t.Context(), nil, tc.id, tc.text, tc.provenance, tc.err); err == nil {
				t.Fatal("invalid extraction must fail before accessing the database")
			}
		})
	}
	if _, err := ListArticlesAwaitingText(t.Context(), nil, " \t"); err == nil {
		t.Fatal("blank source must fail before accessing the database")
	}
}

func TestPostgresArticleExtractionSurvivesReconnect(t *testing.T) {
	db, dsn, now := articleDatabase(t)
	input := sampleArticle("retry-text")
	input.Text, input.TextProvenance = "", ""
	input.PublishedAt = &now
	article, _, err := InsertArticle(t.Context(), db, input)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := RecordArticleText(t.Context(), db, article.ID, "", "", errors.New("article page unavailable")); err != nil {
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
	failed, err := LoadArticle(t.Context(), reopened, article.ID)
	if err != nil || failed.TextError != "article page unavailable" || failed.Text != "" || failed.TextProvenance != "" || failed.ProcessingStatus != StatusPending {
		t.Fatalf("failed extraction was not retained: %+v %v", failed, err)
	}
	want := failed
	want.Text, want.TextProvenance, want.TextError = "First complete article text.", TextFromArticlePage, ""
	recovered, err := RecordArticleText(t.Context(), reopened, article.ID, want.Text, want.TextProvenance, nil)
	if err != nil || !reflect.DeepEqual(recovered, want) {
		t.Fatalf("retry did not fill text while preserving metadata: %+v %v", recovered, err)
	}
	for _, outcome := range []struct {
		text, provenance string
		err              error
	}{
		{"", "", errors.New("late page failure")},
		{"Revised text.", TextFromRSSDescription, nil},
	} {
		stored, err := RecordArticleText(t.Context(), reopened, article.ID, outcome.text, outcome.provenance, outcome.err)
		if err != nil || !reflect.DeepEqual(stored, want) {
			t.Fatalf("later extraction changed the first text snapshot: %+v %v", stored, err)
		}
	}
	if _, err := RecordArticleText(t.Context(), reopened, 999999, "text", TextFromArticlePage, nil); !errors.Is(err, gorm.ErrRecordNotFound) {
		t.Fatalf("missing article must return ErrRecordNotFound: %v", err)
	}
}

func TestPostgresArticlesAwaitingText(t *testing.T) {
	db, _, _ := articleDatabase(t)
	var wantIDs []int64
	for i, status := range []string{StatusPending, StatusProcessing, StatusCompleted, StatusFailed, StatusPending} {
		input := sampleArticle(fmt.Sprintf("queue-%d", i))
		input.Text, input.TextProvenance, input.TextError = "", "", "previous extraction failed"
		article, _, err := InsertArticle(t.Context(), db, input)
		if err != nil {
			t.Fatal(err)
		}
		if status == StatusPending {
			wantIDs = append(wantIDs, article.ID)
			continue
		}
		if err := db.Model(&Article{}).Where("id = ?", article.ID).Update("processing_status", status).Error; err != nil {
			t.Fatal(err)
		}
		unchanged, err := RecordArticleText(t.Context(), db, article.ID, "Late text.", TextFromArticlePage, nil)
		if err != nil || unchanged.Text != "" || unchanged.TextError != input.TextError || unchanged.ProcessingStatus != status {
			t.Fatalf("extraction modified a non-pending article: %+v %v", unchanged, err)
		}
	}
	complete, _, err := InsertArticle(t.Context(), db, sampleArticle("rss-text-present"))
	if err != nil {
		t.Fatal(err)
	}
	stored, err := RecordArticleText(t.Context(), db, complete.ID, "Replacement.", TextFromArticlePage, nil)
	if err != nil || stored.Text != complete.Text || stored.TextProvenance != complete.TextProvenance {
		t.Fatalf("extraction replaced initial RSS text: %+v %v", stored, err)
	}
	other := sampleArticle("other-source")
	other.SourceID, other.Text, other.TextProvenance = "cbr", "", ""
	if _, _, err := InsertArticle(t.Context(), db, other); err != nil {
		t.Fatal(err)
	}
	queued, err := ListArticlesAwaitingText(t.Context(), db, "rbc")
	if err != nil {
		t.Fatal(err)
	}
	var ids []int64
	for _, article := range queued {
		ids = append(ids, article.ID)
	}
	if !reflect.DeepEqual(ids, wantIDs) {
		t.Fatalf("retry queue has incorrect source, status, text or order: got %v want %v", ids, wantIDs)
	}
	if queued, err := ListArticlesAwaitingText(t.Context(), db, "unknown"); err != nil || len(queued) != 0 {
		t.Fatalf("unknown source must have an empty queue: %+v %v", queued, err)
	}
}

func TestPostgresArticleConcurrentExtraction(t *testing.T) {
	db, _, _ := articleDatabase(t)
	input := sampleArticle("concurrent-extraction")
	input.Text, input.TextProvenance = "", ""
	article, _, err := InsertArticle(t.Context(), db, input)
	if err != nil {
		t.Fatal(err)
	}
	type outcome struct {
		article Article
		err     error
	}
	start := make(chan struct{})
	results := make(chan outcome, 8)
	for i := range 8 {
		go func() {
			<-start
			stored, err := RecordArticleText(t.Context(), db, article.ID, fmt.Sprintf("Snapshot %d.", i), TextFromArticlePage, nil)
			results <- outcome{stored, err}
		}()
	}
	close(start)
	texts := make(map[string]bool)
	for range 8 {
		result := <-results
		if result.err != nil {
			t.Error(result.err)
			continue
		}
		if result.article.TextProvenance != TextFromArticlePage || result.article.TextError != "" || result.article.ProcessingStatus != StatusPending {
			t.Errorf("invalid concurrent outcome: %+v", result.article)
		}
		texts[result.article.Text] = true
	}
	if len(texts) != 1 || texts[""] {
		t.Fatalf("concurrent extraction did not preserve one nonempty snapshot: %v", texts)
	}
	assertCount(t, db, &Article{}, 1)
}
