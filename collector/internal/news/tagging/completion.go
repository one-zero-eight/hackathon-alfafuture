package tagging

import (
	"context"
	"time"

	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/vocabulary"
	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/packages/respjson"
	"gorm.io/gorm"
)

// FinishCompletion saves one completed SDK reply against the attempt's stored text/version.
// A nil error means the outcome was saved; outcome.Error describes a rejected model reply.
func FinishCompletion(ctx context.Context, db *gorm.DB, attemptID int64, reply *openai.ChatCompletion, finishedAt time.Time) (store.AttemptCompletion, error) {
	attempt, err := store.LoadAttempt(ctx, db, attemptID)
	if err != nil {
		return store.AttemptCompletion{}, err
	}
	v, err := store.LoadVocabulary(ctx, db, attempt.Version)
	if err != nil {
		return store.AttemptCompletion{}, err
	}
	if v, err = offered(v, attempt.Request); err != nil {
		return store.AttemptCompletion{}, err
	}
	outcome := completionOutcome(v, attempt.InputText, reply, finishedAt)
	if err := store.FinishAttempt(ctx, db, attemptID, outcome); err != nil {
		return store.AttemptCompletion{}, err
	}
	return outcome, nil
}

func completionOutcome(v vocabulary.Vocabulary, text string, reply *openai.ChatCompletion, at time.Time) store.AttemptCompletion {
	outcome := store.AttemptCompletion{FinishedAt: at.UTC(), FailureStatus: store.StatusFailed}
	if reply == nil {
		outcome.Error = "LLM returned no completion"
		return outcome
	}
	outcome.Response = reply.RawJSON()
	invalidUsage := false
	count := func(field respjson.Field, value int64) *int64 {
		if !field.Valid() {
			if raw := field.Raw(); raw != "" && raw != "null" {
				invalidUsage = true
			}
			return nil
		}
		if value < 0 {
			invalidUsage = true
			return nil
		}
		return &value
	}
	if reply.JSON.Usage.Valid() {
		outcome.PromptTokens = count(reply.Usage.JSON.PromptTokens, reply.Usage.PromptTokens)
		outcome.CompletionTokens = count(reply.Usage.JSON.CompletionTokens, reply.Usage.CompletionTokens)
		outcome.TotalTokens = count(reply.Usage.JSON.TotalTokens, reply.Usage.TotalTokens)
	} else if raw := reply.JSON.Usage.Raw(); raw != "" && raw != "null" {
		invalidUsage = true
	}
	if invalidUsage {
		outcome.Error = "LLM completion contains invalid token usage"
		return outcome
	}
	if outcome.Response == "" || len(reply.Choices) != 1 {
		outcome.Error = "LLM completion requires a raw response and one choice"
		return outcome
	}
	choice := reply.Choices[0]
	if choice.FinishReason != "stop" || choice.Message.Role != "assistant" || choice.Message.Refusal != "" || len(choice.Message.ToolCalls) != 0 || choice.Message.JSON.FunctionCall.Valid() {
		outcome.Error = "LLM completion is incomplete, refused or contains tools"
		return outcome
	}
	result, err := Decode(v, text, choice.Message.Content)
	if err != nil {
		outcome.Error = err.Error()
		return outcome
	}
	outcome.Result, outcome.Error, outcome.FailureStatus = &result, "", ""
	return outcome
}
