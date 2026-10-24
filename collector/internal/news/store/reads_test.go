package store

import (
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"gorm.io/gorm"
)

func TestArticleQueryRejectsUnsafeBoundsBeforeDatabaseAccess(t *testing.T) {
	valid := ArticleQuery{ProcessingStatus: StatusCompleted, Limit: 20}
	now := time.Now()
	later := now.Add(time.Hour)
	for _, bad := range []ArticleQuery{
		{ProcessingStatus: StatusCompleted},
		{ProcessingStatus: StatusCompleted, Limit: 101},
		{ProcessingStatus: StatusCompleted, Limit: 1, Offset: -1},
		{ProcessingStatus: "invalid", Limit: 1},
		{ProcessingStatus: valid.ProcessingStatus, Limit: valid.Limit, PublishedFrom: &later, PublishedTo: &now},
	} {
		if _, err := ListArticles(t.Context(), nil, bad); err == nil {
			t.Fatalf("invalid query accepted: %+v", bad)
		}
	}
}

func TestPostgresArticleDetailSnapshotDuringCompletion(t *testing.T) {
	db, _, _ := articleDatabase(t)
	article, _, err := InsertArticle(t.Context(), db, sampleArticle("snapshot"))
	if err != nil {
		t.Fatal(err)
	}
	attempt, err := StartAttempt(t.Context(), db, sampleAttempt(article))
	if err != nil {
		t.Fatal(err)
	}
	readArticle, resume := make(chan struct{}), make(chan struct{})
	unblock := sync.OnceFunc(func() { close(resume) })
	defer unblock()
	var armed atomic.Bool
	armed.Store(true)
	const callback = "test:pause_article_snapshot"
	if err := db.Callback().Query().After("gorm:query").Register(callback, func(tx *gorm.DB) {
		if tx.Statement.Table == "articles" && armed.CompareAndSwap(true, false) {
			close(readArticle)
			select {
			case <-resume:
			case <-t.Context().Done():
			}
		}
	}); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = db.Callback().Query().Remove(callback) })
	type detail struct {
		article  Article
		attempts []TaggingAttempt
		err      error
	}
	done := make(chan detail, 1)
	go func() {
		a, attempts, err := ReadArticleDetail(t.Context(), db, article.ID)
		done <- detail{a, attempts, err}
	}()
	select {
	case <-readArticle:
	case <-time.After(5 * time.Second):
		t.Fatal("article read did not reach the snapshot barrier")
	}
	if err := FinishAttempt(t.Context(), db, attempt.ID, AttemptCompletion{
		FinishedAt: attempt.StartedAt.Add(time.Second), Result: &TaggingResult{},
	}); err != nil {
		t.Fatal(err)
	}
	unblock()
	select {
	case got := <-done:
		if got.err != nil || got.article.ProcessingStatus != StatusProcessing || len(got.attempts) != 1 || got.attempts[0].Status != StatusProcessing || got.attempts[0].FinishedAt != nil || got.attempts[0].Request != "" {
			t.Fatalf("read mixed old article with new outcome: %+v", got)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("article read did not finish")
	}
	got, traces, err := ReadArticleDetail(t.Context(), db, article.ID)
	if err != nil || got.ProcessingStatus != StatusCompleted || len(traces) != 1 || traces[0].Status != StatusCompleted {
		t.Fatal("next request did not observe the committed outcome", err)
	}
}
