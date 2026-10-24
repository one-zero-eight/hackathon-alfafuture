package geotag

import (
	"os"
	"testing"

	"github.com/one-zero-eight/hackathon-alfafuture/collector/llm"
)

// One real request to Gemma: set LIVE_LLM_TEST=1 and LLM_API_KEY.
func TestLiveClassify(t *testing.T) {
	if os.Getenv("LIVE_LLM_TEST") != "1" {
		t.Skip("set LIVE_LLM_TEST=1 for one real approved LLM request")
	}
	client, err := llm.NewFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	titles := []string{"В Твери открыли новый мост через Волгу", "ЦБ сохранил ключевую ставку на уровне 17%", "Тверской губернатор встретился с главами районов", "Курс доллара вырос на бирже"}
	got, tokens, err := Classify(t.Context(), client, "Тверская область", titles)
	if err != nil {
		t.Fatal(err)
	}
	t.Logf("regional: %v, tokens: %d", got, tokens)
	if !got[0] || got[1] || got[3] {
		t.Fatalf("expected the bridge (0) regional and the federal items (1, 3) not: %v", got)
	}
}
