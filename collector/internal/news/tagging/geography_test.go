package tagging

import (
	"context"
	"encoding/json"
	"slices"
	"strings"
	"testing"

	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/vocabulary"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/llm"
	"github.com/openai/openai-go/v3"
)

func shownGeography(t *testing.T, v vocabulary.Vocabulary, request openai.ChatCompletionNewParams) []string {
	t.Helper()
	raw, err := json.Marshal(request)
	if err != nil {
		t.Fatal(err)
	}
	shown, err := offered(v, string(raw))
	if err != nil {
		t.Fatal(err)
	}
	var geo []string
	for _, tag := range shown.Tags {
		if tag.Dimension == "geography" {
			geo = append(geo, tag.ID)
		}
	}
	return geo
}

func TestGeoIndexMatchesInflectedNamesOnly(t *testing.T) {
	idx := newGeoIndex(fixedVocabulary(t))
	for text, want := range map[string][]string{
		"Власти Китая ввели пошлины, в Москве обсуждают ответ":  {"geography:country:CN", "geography:region:042"},
		"Инвестор из Татарстана купил завод в Республике Алтай": {"geography:region:002", "geography:region:056"},
		"Санкции США против РФ":                                 {"geography:country:RU", "geography:country:US"},
		"Помимо того, на Алтае прошли дожди":                    {},
		"Госдума приняла закон о налоге":                        {},
	} {
		if got := idx.find(text); !slices.Equal(got, want) && !(len(got) == 0 && len(want) == 0) {
			t.Errorf("%q: got %v, want %v", text, got, want)
		}
	}
	if !slices.Equal(idx.scope, []string{"geography:scope:international", "geography:scope:russia"}) && !slices.Equal(idx.scope, []string{"geography:scope:russia", "geography:scope:international"}) {
		t.Fatalf("scope tags: %v", idx.scope)
	}
}

func TestOfferedCatalogRejectsUnshownGeography(t *testing.T) {
	v := fixedVocabulary(t)
	idx := newGeoIndex(v)
	text := "Китай повысил пошлины."
	request, err := BuildRequest(offer(v, idx, []string{"geography:country:CN"}), text, llm.DefaultModel)
	if err != nil {
		t.Fatal(err)
	}
	geo := shownGeography(t, v, request)
	slices.Sort(geo)
	if want := []string{"geography:country:CN", "geography:scope:international", "geography:scope:russia"}; !slices.Equal(geo, want) {
		t.Fatalf("offered geography: %v", geo)
	}
	if full := len(offer(v, idx, nil).Tags); full != len(v.Tags)-363 {
		t.Fatalf("offer kept %d of %d tags", full, len(v.Tags))
	}
	raw, _ := json.Marshal(request)
	shown, err := offered(v, string(raw))
	if err != nil {
		t.Fatal(err)
	}
	if _, err := Decode(shown, text, `{"tags":[{"tag_id":"geography:country:CN","evidence":"Китай"}],"events":[]}`); err != nil {
		t.Fatalf("shown tag rejected: %v", err)
	}
	if _, err := Decode(shown, text, `{"tags":[{"tag_id":"geography:country:RU","evidence":"Китай"}],"events":[]}`); err == nil {
		t.Fatal("tag outside the shown catalog was accepted")
	}
	if _, err := offered(v, `{"messages":[{"content":"no catalog"}]}`); err == nil {
		t.Fatal("request without catalog was accepted")
	}
}

func TestPostgresWorkerAsksPlacesOncePerBatch(t *testing.T) {
	w, client, _, _ := workerFixture(t)
	queueArticle(t, w.db, "a", "Глава МИД провёл переговоры в Пекине.")
	queueArticle(t, w.db, "b", "В Казани открыли новый завод.")
	queueArticle(t, w.db, "c", "Регулятор сохранил ключевую ставку.")
	var prompt string
	client.places = func(_ context.Context, p openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
		prompt = p.Messages[0].OfUser.Content.OfString.Value
		return &openai.ChatCompletion{Choices: []openai.ChatCompletionChoice{{Message: openai.ChatCompletionMessage{
			Content: "```json\n{\"places\": {\"0\": [\"Китай\", \"Атлантида\"], \"1\": [\"Татарстан\"]}}\n```"}}}}, nil
	}
	var shown [][]string
	reply := fixtureReply(t, completionBody())
	client.call = func(_ context.Context, p openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
		shown = append(shown, shownGeography(t, w.v, p))
		return reply, nil
	}
	for range 3 {
		stepOK(t, w)
	}
	if client.placesCalls.Load() != 1 || client.calls.Load() != 3 {
		t.Fatalf("places calls %d, tagging calls %d", client.placesCalls.Load(), client.calls.Load())
	}
	if !strings.Contains(prompt, "0 | Глава МИД") || !strings.Contains(prompt, "2 | Регулятор") {
		t.Fatalf("batch prompt lacks queued articles: %q", prompt)
	}
	for i, want := range []string{"geography:country:CN", "geography:region:056", ""} {
		has := slices.ContainsFunc(shown[i], func(id string) bool { return !strings.HasPrefix(id, "geography:scope:") })
		if want == "" && has || want != "" && (!slices.Contains(shown[i], want) || len(shown[i]) != 3) {
			t.Fatalf("article %d offered %v, want %q plus scope", i, shown[i], want)
		}
	}
	if len(w.places) != 0 {
		t.Fatalf("fallback cache not consumed: %v", w.places)
	}
	var stored []store.TaggingAttempt
	if err := w.db.Order("id").Find(&stored).Error; err != nil || len(stored) != 3 || stored[0].PromptVersion != PromptVersion {
		t.Fatalf("attempts not saved with the new prompt version: %v", err)
	}
}
