package geotag

import (
	"context"
	"errors"
	"testing"

	"github.com/openai/openai-go/v3"
)

type fake struct {
	answers []string
	calls   int
}

func (f *fake) Chat(context.Context, openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
	a := f.answers[min(f.calls, len(f.answers)-1)]
	f.calls++
	if a == "ERR" {
		return nil, errors.New("boom")
	}
	return &openai.ChatCompletion{Choices: []openai.ChatCompletionChoice{{Message: openai.ChatCompletionMessage{Content: a}}}}, nil
}

func TestClassifyKeepsValidIndexesAndRetriesBadAnswers(t *testing.T) {
	f := &fake{answers: []string{"ERR", "not json", "```json\n{\"regional\": [0, 2, 7, -1]}\n```"}}
	got, _, err := Classify(t.Context(), f, "Тверская область", []string{"a", "b", "c"})
	if err != nil || f.calls != 3 || len(got) != 2 || !got[0] || !got[2] {
		t.Fatalf("got=%v err=%v calls=%d", got, err, f.calls)
	}
}

func TestClassifyGivesUpAfterThreeBadAnswers(t *testing.T) {
	f := &fake{answers: []string{"nope"}}
	if _, _, err := Classify(t.Context(), f, "x", []string{"a"}); err == nil || f.calls != 3 {
		t.Fatalf("err=%v calls=%d", err, f.calls)
	}
}
