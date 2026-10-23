package store

import (
	"errors"
	"reflect"
	"sync"
	"testing"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/vocabulary"
)

func pointer[T any](value T) *T { return &value }

func TestValidateTaggingResult(t *testing.T) {
	v := vocabulary.Vocabulary{Tags: []vocabulary.Tag{
		{ID: "resource:oil", Dimension: "resource"},
		{ID: "event:commodity_prices", Dimension: "event"},
	}}
	text := "Oil rose. Oil may fall."
	tags := []ResultTag{{TagID: "resource:oil", Evidence: "Oil"}, {TagID: "event:commodity_prices", Evidence: "Oil rose."}}
	observed := ResultEvent{TagID: "event:commodity_prices", Status: pointer("observed"), Evidence: "Oil rose."}
	tests := []struct {
		name   string
		result TaggingResult
		valid  bool
	}{
		{"empty", TaggingResult{}, true},
		{"mixed", TaggingResult{Tags: tags, Events: []ResultEvent{observed, {TagID: observed.TagID, Status: pointer("forecast"), Evidence: "Oil may fall."}}}, true},
		{"null", TaggingResult{Tags: tags, Events: []ResultEvent{{TagID: observed.TagID, Evidence: observed.Evidence}}}, true},
		{"announced", TaggingResult{Tags: tags, Events: []ResultEvent{{TagID: observed.TagID, Status: pointer("announced_planned"), Evidence: observed.Evidence}}}, true},
		{"unknown tag", TaggingResult{Tags: []ResultTag{{TagID: "invented", Evidence: "Oil"}}}, false},
		{"duplicate tag", TaggingResult{Tags: []ResultTag{tags[0], tags[0]}}, false},
		{"nonliteral tag", TaggingResult{Tags: []ResultTag{{TagID: tags[0].TagID, Evidence: "oil"}}}, false},
		{"blank tag quote", TaggingResult{Tags: []ResultTag{{TagID: tags[0].TagID, Evidence: " "}}}, false},
		{"missing event", TaggingResult{Tags: tags}, false},
		{"unassigned event", TaggingResult{Tags: tags[:1], Events: []ResultEvent{observed}}, false},
		{"wrong dimension", TaggingResult{Tags: tags[:1], Events: []ResultEvent{{TagID: tags[0].TagID, Evidence: "Oil"}}}, false},
		{"unknown status", TaggingResult{Tags: tags, Events: []ResultEvent{{TagID: observed.TagID, Status: pointer("unknown"), Evidence: observed.Evidence}}}, false},
		{"empty status is not null", TaggingResult{Tags: tags, Events: []ResultEvent{{TagID: observed.TagID, Status: pointer(""), Evidence: observed.Evidence}}}, false},
		{"nonliteral event", TaggingResult{Tags: tags, Events: []ResultEvent{{TagID: observed.TagID, Evidence: "oil rose"}}}, false},
		{"blank event quote", TaggingResult{Tags: tags, Events: []ResultEvent{{TagID: observed.TagID, Evidence: " "}}}, false},
		{"duplicate event", TaggingResult{Tags: tags, Events: []ResultEvent{observed, observed}}, false},
		{"duplicate null event", TaggingResult{Tags: tags, Events: []ResultEvent{{TagID: observed.TagID, Evidence: observed.Evidence}, {TagID: observed.TagID, Evidence: observed.Evidence}}}, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := ValidateTaggingResult(v, text, tt.result)
			if (err == nil) != tt.valid {
				t.Fatalf("valid=%v: %v", tt.valid, err)
			}
		})
	}
}

func sampleAttempt(article Article) TaggingAttempt {
	return TaggingAttempt{
		ArticleID: article.ID, Version: "v1", PromptVersion: "test-v1", Model: "deepseek/deepseek-v4.1-flash",
		InputText: article.Text, Request: " {\"messages\":[{\"role\":\"user\",\"content\":\"Synthetic article text.\"}]}\n",
		StartedAt: article.CollectedAt.Add(time.Second),
	}
}

func TestPostgresTaggingTraceRoundTrip(t *testing.T) {
	db, dsn, _ := articleDatabase(t)
	input := sampleArticle("tagged")
	input.Text = "Oil rose. Oil may fall."
	article, _, err := InsertArticle(t.Context(), db, input)
	if err != nil {
		t.Fatal(err)
	}
	attemptInput := sampleAttempt(article)
	attempt, err := StartAttempt(t.Context(), db, attemptInput)
	if err != nil {
		t.Fatal(err)
	}
	if attempt.Number != 1 || attempt.Status != StatusProcessing {
		t.Fatal("attempt not started", attempt)
	}
	inflight, err := LoadAttempts(t.Context(), db, article.ID)
	if err != nil || len(inflight) != 1 || inflight[0].Request != attemptInput.Request || inflight[0].FinishedAt != nil {
		t.Fatal("request was not saved before completion", err)
	}
	result := TaggingResult{
		Tags: []ResultTag{{TagID: "resource:oil", Evidence: "Oil"}, {TagID: "event:commodity_prices", Evidence: "Oil rose."}},
		Events: []ResultEvent{
			{TagID: "event:commodity_prices", Status: pointer("observed"), Evidence: "Oil rose."},
			{TagID: "event:commodity_prices", Status: pointer("forecast"), Evidence: "Oil may fall."},
			{TagID: "event:commodity_prices", Evidence: "Oil"},
		},
	}
	completion := AttemptCompletion{FinishedAt: attempt.StartedAt.Add(time.Second), Response: "raw provider response", PromptTokens: pointer[int64](0), CompletionTokens: pointer[int64](12), TotalTokens: pointer[int64](12), Result: &result}
	if err := FinishAttempt(t.Context(), db, attempt.ID, completion); err != nil {
		t.Fatal(err)
	}
	if err := Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	reopened, err := Open(t.Context(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	closeDatabase(t, reopened)
	attempts, err := LoadAttempts(t.Context(), reopened, article.ID)
	if err != nil || len(attempts) != 1 {
		t.Fatal("load attempt", err)
	}
	got := attempts[0]
	if got.Status != StatusCompleted || got.Version != attemptInput.Version || got.PromptVersion != attemptInput.PromptVersion || got.Model != attemptInput.Model || got.InputText != input.Text || got.Request != attemptInput.Request || got.Response != completion.Response || got.FinishedAt == nil || !got.FinishedAt.Equal(completion.FinishedAt) || got.PromptTokens == nil || *got.PromptTokens != 0 || got.CompletionTokens == nil || *got.CompletionTokens != 12 || got.TotalTokens == nil || *got.TotalTokens != 12 {
		t.Fatalf("trace mismatch: %+v", got)
	}
	if len(got.Assignments) != 2 || got.Assignments[0].TagID != "event:commodity_prices" || got.Assignments[1].TagID != "resource:oil" || got.Assignments[1].Evidence != "Oil" || got.Assignments[1].Version != "v1" {
		t.Fatalf("assignment mismatch: %+v", got.Assignments)
	}
	if len(got.Events) != 3 || !reflect.DeepEqual(got.Events[0].Status, pointer("observed")) || !reflect.DeepEqual(got.Events[1].Status, pointer("forecast")) || got.Events[2].Status != nil || got.Events[1].Evidence != "Oil may fall." {
		t.Fatalf("event mismatch: %+v", got.Events)
	}
	stored, err := LoadArticle(t.Context(), reopened, article.ID)
	if err != nil || stored.ProcessingStatus != StatusCompleted {
		t.Fatal("article was not completed", err)
	}
	if err := FinishAttempt(t.Context(), reopened, attempt.ID, completion); !errors.Is(err, ErrAttemptNotProcessing) {
		t.Fatal("completed trace can be overwritten", err)
	}
	if _, err := StartAttempt(t.Context(), reopened, attemptInput); !errors.Is(err, ErrArticleNotPending) {
		t.Fatal("completed article can be tagged again", err)
	}
	assertCount(t, reopened, &TagAssignment{}, 2)
	assertCount(t, reopened, &EventInstance{}, 3)
}

func TestPostgresFailedAndEmptyTaggingResults(t *testing.T) {
	db, _, _ := articleDatabase(t)
	article, _, err := InsertArticle(t.Context(), db, sampleArticle("retry"))
	if err != nil {
		t.Fatal(err)
	}
	attempt, err := StartAttempt(t.Context(), db, sampleAttempt(article))
	if err != nil {
		t.Fatal(err)
	}
	failure := AttemptCompletion{FinishedAt: attempt.StartedAt.Add(time.Second), Response: "invalid model JSON", Error: "invalid result", FailureStatus: StatusPending}
	if err := FinishAttempt(t.Context(), db, attempt.ID, failure); err != nil {
		t.Fatal(err)
	}
	attempt, err = StartAttempt(t.Context(), db, sampleAttempt(article))
	if err != nil || attempt.Number != 2 {
		t.Fatal("next attempt", err)
	}
	if err := FinishAttempt(t.Context(), db, attempt.ID, AttemptCompletion{FinishedAt: failure.FinishedAt, Result: &TaggingResult{}}); err != nil {
		t.Fatal(err)
	}
	attempts, err := LoadAttempts(t.Context(), db, article.ID)
	if err != nil || len(attempts) != 2 {
		t.Fatal("attempt history", err)
	}
	if attempts[0].Status != StatusFailed || attempts[0].Error != "invalid result" || attempts[0].Response != failure.Response || attempts[0].PromptTokens != nil || attempts[0].CompletionTokens != nil || attempts[0].TotalTokens != nil || attempts[1].Status != StatusCompleted {
		t.Fatalf("failed/unknown usage trace: %+v", attempts)
	}
	assertCount(t, db, &TagAssignment{}, 0)
	assertCount(t, db, &EventInstance{}, 0)
	other, _, err := InsertArticle(t.Context(), db, sampleArticle("terminal"))
	if err != nil {
		t.Fatal(err)
	}
	terminal, err := StartAttempt(t.Context(), db, sampleAttempt(other))
	if err != nil {
		t.Fatal(err)
	}
	failure.FailureStatus = StatusFailed
	if err := FinishAttempt(t.Context(), db, terminal.ID, failure); err != nil {
		t.Fatal(err)
	}
	stored, err := LoadArticle(t.Context(), db, other.ID)
	if err != nil || stored.ProcessingStatus != StatusFailed {
		t.Fatal("terminal failure not persisted", err)
	}
}

func TestPostgresTaggingRollbackAndConstraints(t *testing.T) {
	db, _, _ := articleDatabase(t)
	article, _, err := InsertArticle(t.Context(), db, sampleArticle("rollback"))
	if err != nil {
		t.Fatal(err)
	}
	badVersion := sampleAttempt(article)
	badVersion.Version = "missing"
	_, err = StartAttempt(t.Context(), db, badVersion)
	assertSQLState(t, err, "23503")
	assertCount(t, db, &TaggingAttempt{}, 0)
	stored, err := LoadArticle(t.Context(), db, article.ID)
	if err != nil || stored.ProcessingStatus != StatusPending {
		t.Fatal("failed start changed article", err)
	}
	attempt, err := StartAttempt(t.Context(), db, sampleAttempt(article))
	if err != nil {
		t.Fatal(err)
	}
	completion := AttemptCompletion{FinishedAt: attempt.StartedAt.Add(time.Second), Response: "raw response", Result: &TaggingResult{Tags: []ResultTag{{TagID: "resource:oil", Evidence: "Synthetic"}}}}
	// Force failure after result/trace writes to prove the transaction rolls them back.
	if err := db.Model(&Article{}).Where("id = ?", article.ID).Update("processing_status", StatusFailed).Error; err != nil {
		t.Fatal(err)
	}
	if err := FinishAttempt(t.Context(), db, attempt.ID, completion); err == nil {
		t.Fatal("expected article state conflict")
	}
	assertCount(t, db, &TagAssignment{}, 0)
	attempts, err := LoadAttempts(t.Context(), db, article.ID)
	if err != nil || len(attempts) != 1 || attempts[0].Status != StatusProcessing || attempts[0].Response != "" || attempts[0].FinishedAt != nil {
		t.Fatal("partial result escaped rollback", err)
	}
	if err := db.Model(&Article{}).Where("id = ?", article.ID).Update("processing_status", StatusProcessing).Error; err != nil {
		t.Fatal(err)
	}
	completion.Result.Tags[0].Evidence = "invented quotation"
	if err := FinishAttempt(t.Context(), db, attempt.ID, completion); err == nil {
		t.Fatal("accepted invented evidence")
	}
	completion.Result.Tags[0].Evidence = "Synthetic"
	if err := FinishAttempt(t.Context(), db, attempt.ID, completion); err != nil {
		t.Fatal(err)
	}
	assertSQLState(t, db.Create(&TagAssignment{AttemptID: attempt.ID, Version: "v1", TagID: "unknown", Evidence: "Synthetic"}).Error, "23503")
	assertSQLState(t, db.Create(&TagAssignment{AttemptID: attempt.ID, Version: "v1", TagID: "resource:oil", Evidence: "Synthetic"}).Error, "23505")
	assertSQLState(t, db.Create(&TagAssignment{AttemptID: attempt.ID + 1000, Version: "v1", TagID: "resource:oil", Evidence: "Synthetic"}).Error, "23503")
	assertSQLState(t, db.Create(&EventInstance{AttemptID: attempt.ID, TagID: "event:commodity_prices", Evidence: "Synthetic"}).Error, "23503")
	assertSQLState(t, db.Create(&EventInstance{AttemptID: attempt.ID, TagID: "resource:oil", Status: pointer("invalid"), Evidence: "Synthetic"}).Error, "23514")
	assertSQLState(t, db.Model(&TaggingAttempt{}).Where("id = ?", attempt.ID).Update("prompt_tokens", -1).Error, "23514")
	assertSQLState(t, db.Model(&TaggingAttempt{}).Where("id = ?", attempt.ID).Update("status", "invalid").Error, "23514")
	assertSQLState(t, db.Model(&TaggingAttempt{}).Where("id = ?", attempt.ID).Update("finished_at", nil).Error, "23514")
}

func TestPostgresConcurrentAttemptClaims(t *testing.T) {
	db, _, _ := articleDatabase(t)
	article, _, err := InsertArticle(t.Context(), db, sampleArticle("concurrent-claim"))
	if err != nil {
		t.Fatal(err)
	}
	var wg sync.WaitGroup
	errorsByCall := make([]error, 8)
	for i := range errorsByCall {
		wg.Go(func() { _, errorsByCall[i] = StartAttempt(t.Context(), db, sampleAttempt(article)) })
	}
	wg.Wait()
	winners := 0
	for _, err := range errorsByCall {
		if err == nil {
			winners++
		} else if !errors.Is(err, ErrArticleNotPending) {
			t.Fatal(err)
		}
	}
	if winners != 1 {
		t.Fatalf("got %d successful claims", winners)
	}
	assertCount(t, db, &TaggingAttempt{}, 1)
}

func TestPostgresBudgetPauseSurvivesReconnect(t *testing.T) {
	db, dsn, now := articleDatabase(t)
	if until, err := LoadBudgetPause(t.Context(), db); err != nil || until != nil {
		t.Fatal("unexpected initial pause", until, err)
	}
	until := now.Add(12 * time.Hour)
	if err := SetBudgetPause(t.Context(), db, &until); err != nil {
		t.Fatal(err)
	}
	reopened, err := Open(t.Context(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	closeDatabase(t, reopened)
	got, err := LoadBudgetPause(t.Context(), reopened)
	if err != nil || got == nil || !got.Equal(until) {
		t.Fatal("pause lost on reconnect", got, err)
	}
	if err := SetBudgetPause(t.Context(), reopened, pointer(time.Time{})); err == nil {
		t.Fatal("accepted zero pause")
	}
	if err := SetBudgetPause(t.Context(), reopened, nil); err != nil {
		t.Fatal(err)
	}
	if got, err := LoadBudgetPause(t.Context(), reopened); err != nil || got != nil {
		t.Fatal("pause not cleared", got, err)
	}
	assertCount(t, reopened, &BudgetPause{}, 1)
	assertSQLState(t, reopened.Create(&BudgetPause{ID: 2, Until: &until}).Error, "23514")
}

func TestAttemptInputValidation(t *testing.T) {
	base := sampleAttempt(Article{ID: 1, Text: "text", CollectedAt: time.Now()})
	for _, change := range []func(*TaggingAttempt){
		func(a *TaggingAttempt) { a.ID = 1 }, func(a *TaggingAttempt) { a.ArticleID = 0 },
		func(a *TaggingAttempt) { a.Version = "" }, func(a *TaggingAttempt) { a.PromptVersion = "" },
		func(a *TaggingAttempt) { a.Model = "" }, func(a *TaggingAttempt) { a.InputText = " " },
		func(a *TaggingAttempt) { a.Request = "[]" }, func(a *TaggingAttempt) { a.Request = "{" },
		func(a *TaggingAttempt) { a.StartedAt = time.Time{} },
	} {
		bad := base
		change(&bad)
		if _, err := StartAttempt(t.Context(), nil, bad); err == nil {
			t.Fatal("accepted invalid attempt")
		}
	}
	for _, completion := range []AttemptCompletion{
		{}, {FinishedAt: time.Now()},
		{FinishedAt: time.Now(), Error: "failure", FailureStatus: StatusCompleted},
		{FinishedAt: time.Now(), Result: &TaggingResult{}, Error: "failure"},
		{FinishedAt: time.Now(), Result: &TaggingResult{}, FailureStatus: StatusFailed},
		{FinishedAt: time.Now(), Result: &TaggingResult{}, PromptTokens: pointer[int64](-1)},
	} {
		if err := FinishAttempt(t.Context(), nil, 1, completion); err == nil {
			t.Fatal("accepted invalid completion")
		}
	}
}
