package tagging

import (
	"encoding/json"
	"errors"
	"reflect"
	"strings"
	"testing"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/testdb"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/llm"
	"github.com/openai/openai-go/v3"
	"gorm.io/gorm"
)

const completionText = "Oil rose. Oil may fall."
const completionResult = `{"tags":[{"tag_id":"resource:oil","evidence":"Oil"},{"tag_id":"event:commodity_prices","evidence":"Oil rose."}],"events":[{"tag_id":"event:commodity_prices","status":"observed","evidence":"Oil rose."},{"tag_id":"event:commodity_prices","status":"forecast","evidence":"Oil may fall."}]}`

func completionBody() map[string]any {
	return map[string]any{
		"id": "fixture-completion", "object": "chat.completion", "created": 1, "model": llm.DefaultModel,
		"choices": []any{map[string]any{
			"index": 0, "finish_reason": "stop",
			"message": map[string]any{"role": "assistant", "content": completionResult},
		}},
		"provider_extra": "PRIVATE_MODEL_OUTPUT",
	}
}

func fixtureReply(t *testing.T, body map[string]any) *openai.ChatCompletion {
	t.Helper()
	raw, err := json.Marshal(body)
	if err != nil {
		t.Fatal(err)
	}
	var reply openai.ChatCompletion
	if err := json.Unmarshal(raw, &reply); err != nil {
		t.Fatal(err)
	}
	if reply.RawJSON() != string(raw) {
		t.Fatal("SDK did not preserve the original fixture response")
	}
	return &reply
}

func choice(body map[string]any) map[string]any  { return body["choices"].([]any)[0].(map[string]any) }
func message(body map[string]any) map[string]any { return choice(body)["message"].(map[string]any) }
func tokenCount(n int64) *int64                  { return &n }

func TestCompletionOutcomePreservesTraceAndUsagePresence(t *testing.T) {
	v := fixedVocabulary(t)
	for _, tc := range []struct {
		name                      string
		usage                     any
		present, valid            bool
		prompt, completion, total *int64
	}{
		{"missing", nil, false, true, nil, nil, nil},
		{"null", nil, true, true, nil, nil, nil},
		{"empty", map[string]any{}, true, true, nil, nil, nil},
		{"partial", map[string]any{"prompt_tokens": 7, "completion_tokens": nil}, true, true, tokenCount(7), nil, nil},
		{"zero", map[string]any{"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, true, true, tokenCount(0), tokenCount(0), tokenCount(0)},
		{"negative", map[string]any{"prompt_tokens": -1, "completion_tokens": 2}, true, false, nil, tokenCount(2), nil},
		{"invalid counter type", map[string]any{"prompt_tokens": "PRIVATE_MODEL_OUTPUT", "completion_tokens": 2}, true, false, nil, tokenCount(2), nil},
		{"invalid usage type", true, true, false, nil, nil, nil},
	} {
		t.Run(tc.name, func(t *testing.T) {
			body := completionBody()
			if tc.present {
				body["usage"] = tc.usage
			}
			reply := fixtureReply(t, body)
			at := time.Date(2026, 10, 23, 12, 0, 0, 0, time.FixedZone("MSK", 3*60*60))
			outcome := completionOutcome(v, completionText, reply, at)
			if (outcome.Result != nil) != tc.valid || outcome.Response != reply.RawJSON() || !outcome.FinishedAt.Equal(at) || outcome.FinishedAt.Location() != time.UTC || !reflect.DeepEqual(outcome.PromptTokens, tc.prompt) || !reflect.DeepEqual(outcome.CompletionTokens, tc.completion) || !reflect.DeepEqual(outcome.TotalTokens, tc.total) {
				t.Fatalf("lost completion trace, null/zero distinction or valid usage: %+v", outcome)
			}
			if tc.valid && (outcome.Error != "" || outcome.FailureStatus != "" || len(outcome.Result.Events) != 2) {
				t.Fatal("valid mixed result was not preserved")
			}
			if !tc.valid && (outcome.Error == "" || outcome.FailureStatus != store.StatusFailed || strings.Contains(outcome.Error, "PRIVATE_MODEL_OUTPUT")) {
				t.Fatal("invalid usage must fail safely without losing the raw response")
			}
		})
	}
}

func TestCompletionOutcomeRejectsIncompleteRefusedAndToolReplies(t *testing.T) {
	v := fixedVocabulary(t)
	for _, tc := range []struct {
		name   string
		change func(map[string]any)
	}{
		{"no choice", func(b map[string]any) { b["choices"] = []any{} }},
		{"multiple choices", func(b map[string]any) { b["choices"] = []any{choice(b), choice(b)} }},
		{"length", func(b map[string]any) { choice(b)["finish_reason"] = "length" }},
		{"missing termination", func(b map[string]any) { delete(choice(b), "finish_reason") }},
		{"refusal", func(b map[string]any) { message(b)["refusal"] = "PRIVATE_MODEL_OUTPUT" }},
		{"wrong role", func(b map[string]any) { message(b)["role"] = "user" }},
		{"tools with stop", func(b map[string]any) {
			message(b)["tool_calls"] = []any{map[string]any{"id": "call_fixture", "type": "function", "function": map[string]any{"name": "unexpected", "arguments": "{}"}}}
		}},
		{"legacy function", func(b map[string]any) { message(b)["function_call"] = map[string]any{} }},
		{"empty content", func(b map[string]any) { message(b)["content"] = "" }},
		{"invalid JSON", func(b map[string]any) { message(b)["content"] = "PRIVATE_MODEL_OUTPUT" }},
		{"invented tag", func(b map[string]any) {
			message(b)["content"] = `{"tags":[{"tag_id":"invented","evidence":"Oil"}],"events":[]}`
		}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			body := completionBody()
			body["usage"] = map[string]any{"prompt_tokens": 12}
			tc.change(body)
			reply := fixtureReply(t, body)
			outcome := completionOutcome(v, completionText, reply, time.Now())
			if outcome.Result != nil || outcome.FailureStatus != store.StatusFailed || outcome.Error == "" || strings.Contains(outcome.Error, "PRIVATE_MODEL_OUTPUT") || outcome.Response != reply.RawJSON() || outcome.PromptTokens == nil || *outcome.PromptTokens != 12 {
				t.Fatalf("invalid completion was accepted or lost trace/usage: %+v", outcome)
			}
		})
	}
	for _, reply := range []*openai.ChatCompletion{nil, {}} {
		outcome := completionOutcome(v, completionText, reply, time.Now())
		if outcome.Result != nil || outcome.Error == "" || outcome.FailureStatus != store.StatusFailed {
			t.Fatal("missing reply was accepted")
		}
	}
}

func startCompletionAttempt(t *testing.T, db *gorm.DB, itemID string) store.TaggingAttempt {
	t.Helper()
	now := time.Date(2026, 10, 23, 9, 0, 0, 0, time.UTC)
	if err := store.RegisterSources(t.Context(), db, []store.Source{{ID: "rbc", Name: "РБК", FeedURL: "https://rssexport.rbc.ru/rbcnews/news/30/full.rss"}}, now); err != nil {
		t.Fatal(err)
	}
	article, _, err := store.InsertArticle(t.Context(), db, store.Article{
		SourceID: "rbc", SourceItemID: itemID, URL: "https://www.rbc.ru/fixture", CollectedAt: now,
		Text: completionText, TextProvenance: store.TextFromRSSFullText,
	})
	if err != nil {
		t.Fatal(err)
	}
	v, err := store.LoadVocabulary(t.Context(), db, "v1")
	if err != nil {
		t.Fatal(err)
	}
	request, err := BuildRequest(v, article.Text, llm.DefaultModel)
	if err != nil {
		t.Fatal(err)
	}
	raw, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	attempt, err := store.StartAttempt(t.Context(), db, store.TaggingAttempt{
		ArticleID: article.ID, Version: v.Version, PromptVersion: PromptVersion, Model: llm.DefaultModel,
		InputText: article.Text, Request: string(raw), StartedAt: now.Add(time.Second),
	})
	if err != nil {
		t.Fatal(err)
	}
	return attempt
}

func TestPostgresCompletionSuccessFailureAndReconnect(t *testing.T) {
	db, dsn := testdb.New(t)
	if err := store.Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	for _, valid := range []bool{true, false} {
		itemID := "valid"
		if !valid {
			itemID = "invalid"
		}
		attempt := startCompletionAttempt(t, db, itemID)
		body := completionBody()
		body["usage"] = map[string]any{"prompt_tokens": 0, "completion_tokens": 8}
		if !valid {
			choice(body)["finish_reason"] = "length"
		}
		reply := fixtureReply(t, body)
		outcome, err := FinishCompletion(t.Context(), db, attempt.ID, reply, attempt.StartedAt.Add(time.Second))
		if err != nil || (outcome.Result != nil) != valid {
			t.Fatalf("could not persist completion outcome: %+v %v", outcome, err)
		}
		if _, err := FinishCompletion(t.Context(), db, attempt.ID, reply, attempt.StartedAt.Add(2*time.Second)); !errors.Is(err, store.ErrAttemptNotProcessing) {
			t.Fatalf("finished attempt could be overwritten: %v", err)
		}
	}
	pool, _ := db.DB()
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}
	reopened, err := store.Open(t.Context(), dsn)
	if err != nil {
		t.Fatal(err)
	}
	testdb.Close(t, reopened)
	for _, valid := range []bool{true, false} {
		id, want := "valid", store.StatusCompleted
		if !valid {
			id, want = "invalid", store.StatusFailed
		}
		article, err := store.FindArticle(t.Context(), reopened, "rbc", id, "")
		if err != nil || article.ProcessingStatus != want {
			t.Fatalf("wrong article outcome: %+v %v", article, err)
		}
		attempts, err := store.LoadAttempts(t.Context(), reopened, article.ID)
		if err != nil || len(attempts) != 1 {
			t.Fatalf("lost attempt: %+v %v", attempts, err)
		}
		a := attempts[0]
		if a.Status != want || a.InputText != completionText || a.Version != "v1" || a.PromptVersion != PromptVersion || a.Model != llm.DefaultModel || a.Request == "" || a.Response == "" || !strings.Contains(a.Response, "PRIVATE_MODEL_OUTPUT") || a.PromptTokens == nil || *a.PromptTokens != 0 || a.CompletionTokens == nil || *a.CompletionTokens != 8 || a.TotalTokens != nil || a.FinishedAt == nil {
			t.Fatal("saved trace or token availability changed after reconnect")
		}
		if valid && (len(a.Assignments) != 2 || len(a.Events) != 2 || a.Error != "") {
			t.Fatal("validated result missing")
		}
		if !valid && (len(a.Assignments) != 0 || len(a.Events) != 0 || a.Error == "" || strings.Contains(a.Error, "PRIVATE_MODEL_OUTPUT")) {
			t.Fatal("invalid response became assignments or leaked into diagnostic")
		}
	}
}

func TestPostgresCompletionValidationLeavesAttemptUntouched(t *testing.T) {
	db, _ := testdb.New(t)
	if err := store.Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	attempt := startCompletionAttempt(t, db, "bad-finish-time")
	reply := fixtureReply(t, completionBody())
	if outcome, err := FinishCompletion(t.Context(), db, attempt.ID, reply, attempt.StartedAt.Add(-time.Second)); err == nil || !reflect.DeepEqual(outcome, store.AttemptCompletion{}) {
		t.Fatal("invalid finish time must fail without a partial outcome")
	}
	unchanged, err := store.LoadAttempt(t.Context(), db, attempt.ID)
	if err != nil || unchanged.Status != store.StatusProcessing || unchanged.Response != "" || unchanged.FinishedAt != nil || unchanged.Request != attempt.Request {
		t.Fatalf("failed save changed the saved request: %+v %v", unchanged, err)
	}
	if _, err := FinishCompletion(t.Context(), db, 999999, reply, time.Now()); !errors.Is(err, gorm.ErrRecordNotFound) {
		t.Fatalf("missing attempt: %v", err)
	}
	if _, err := FinishCompletion(t.Context(), nil, 0, reply, time.Now()); err == nil {
		t.Fatal("zero attempt ID accepted")
	}
	if _, err := FinishCompletion(t.Context(), db, attempt.ID, reply, attempt.StartedAt.Add(time.Second)); err != nil {
		t.Fatal(err)
	}
}
