package store

import (
	"context"
	"errors"
	"reflect"
	"testing"
	"time"
)

func TestPostgresStatusPreservesUnknownZeroAndPartialUsage(t *testing.T) {
	db, dsn, now := articleDatabase(t)
	empty, err := ReadStatus(t.Context(), db)
	if err != nil || !reflect.DeepEqual(empty, StatusSnapshot{}) {
		t.Fatalf("empty status invented counts or usage: %+v %v", empty, err)
	}
	for _, name := range []string{"pending", "retry-zero", "active", "completed", "failed-partial"} {
		input := sampleArticle(name)
		if name == "pending" {
			input.Text, input.TextProvenance = "", ""
		}
		article, _, err := InsertArticle(t.Context(), db, input)
		if err != nil {
			t.Fatal(err)
		}
		if name == "pending" {
			continue
		}
		attempt, err := StartAttempt(t.Context(), db, sampleAttempt(article))
		if err != nil {
			t.Fatal(err)
		}
		if name == "active" {
			continue
		}
		outcome := AttemptCompletion{FinishedAt: attempt.StartedAt.Add(time.Second)}
		switch name {
		case "retry-zero":
			outcome.Error, outcome.FailureStatus = "transient failure", StatusPending
			outcome.PromptTokens, outcome.CompletionTokens, outcome.TotalTokens = pointer[int64](0), pointer[int64](0), pointer[int64](0)
		case "completed":
			outcome.Result = &TaggingResult{}
			outcome.PromptTokens, outcome.CompletionTokens, outcome.TotalTokens = pointer[int64](100), pointer[int64](20), pointer[int64](120)
		case "failed-partial":
			outcome.Error, outcome.FailureStatus, outcome.PromptTokens = "invalid response", StatusFailed, pointer[int64](7)
		}
		if err := FinishAttempt(t.Context(), db, attempt.ID, outcome); err != nil {
			t.Fatal(err)
		}
		if name == "retry-zero" {
			zero, err := ReadStatus(t.Context(), db)
			if err != nil || zero.PromptTokens == nil || *zero.PromptTokens != 0 || zero.CompletionTokens == nil || *zero.CompletionTokens != 0 || zero.TotalTokens == nil || *zero.TotalTokens != 0 || zero.PromptTokensKnownAttempts != 1 || zero.CompletionTokensKnownAttempts != 1 || zero.TotalTokensKnownAttempts != 1 {
				t.Fatalf("known zero became unknown: %+v %v", zero, err)
			}
		}
	}
	until := now.Add(24 * time.Hour).UTC()
	if err := SetBudgetPause(t.Context(), db, &until); err != nil {
		t.Fatal(err)
	}
	want := StatusSnapshot{
		Pending: 2, Processing: 1, Completed: 1, Failed: 1, Attempts: 4, BudgetPauseUntil: &until,
		PromptTokens: pointer[int64](107), CompletionTokens: pointer[int64](20), TotalTokens: pointer[int64](120),
		PromptTokensKnownAttempts: 3, CompletionTokensKnownAttempts: 2, TotalTokensKnownAttempts: 2,
	}
	reopened, err := Open(t.Context(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	closeDatabase(t, reopened)
	got, err := ReadStatus(t.Context(), reopened)
	if err != nil || got.BudgetPauseUntil == nil || !got.BudgetPauseUntil.Equal(until) {
		t.Fatalf("status lost persisted pause instant: %+v %v", got, err)
	}
	got.BudgetPauseUntil, want.BudgetPauseUntil = nil, nil
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("status lost persisted counts or usage: %+v %v", got, err)
	}
	if err := SetBudgetPause(t.Context(), reopened, nil); err != nil {
		t.Fatal(err)
	}
	got, err = ReadStatus(t.Context(), reopened)
	if err != nil || !reflect.DeepEqual(got, want) {
		t.Fatalf("clearing pause changed counts: %+v %v", got, err)
	}
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	if _, err := ReadStatus(ctx, reopened); !errors.Is(err, context.Canceled) {
		t.Fatalf("status read ignored cancellation: %v", err)
	}
}
