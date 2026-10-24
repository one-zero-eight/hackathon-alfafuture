// Package geotag decides which articles of a regional outlet really concern its region.
//
// An article of an outlet in source_regions gets the outlet's region tag only if the model decides from the headline that the news
// is about that region (its events, authorities, companies, people, infrastructure) and not federal, foreign or generic.
// Every checked article gets a row; a nil region tag means "checked, not regional", so nothing is classified twice.
package geotag

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"regexp"
	"strings"
	"sync"

	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/vocabulary"
	"github.com/openai/openai-go/v3"
	"gorm.io/gorm"
)

const (
	// Model answers directly; a reasoning model often ran out of tokens on these short batches.
	Model     = "google/gemma-4-26b-a4b-it"
	batchSize = 60
	tries     = 3
	workers   = 4
)

var jsonObject = regexp.MustCompile(`(?s)\{.*\}`)

type Chat interface {
	Chat(context.Context, openai.ChatCompletionNewParams) (*openai.ChatCompletion, error)
}

// Classify returns the indexes of titles judged regional, or an error if no try produced a parsable answer.
func Classify(ctx context.Context, c Chat, regionName string, titles []string) (map[int]bool, int64, error) {
	var b strings.Builder
	for i, t := range titles {
		fmt.Fprintf(&b, "%d | %s\n", i, truncate(t, 200))
	}
	prompt := "Региональное издание региона «" + regionName + "». Ниже заголовки его новостей (номер | заголовок).\n" +
		"Выбери только те, которые относятся именно к этому региону: события, власти, компании, люди, инфраструктура, происшествия в регионе. " +
		"Не выбирай федеральные, зарубежные и общие новости без привязки к региону, даже если издание их перепечатало.\n" +
		"Верни ТОЛЬКО JSON {\"regional\": [номера]}.\n\n" + b.String()
	var tokens int64
	for range tries {
		reply, err := c.Chat(ctx, openai.ChatCompletionNewParams{
			Model:     Model,
			Messages:  []openai.ChatCompletionMessageParamUnion{openai.UserMessage(prompt)},
			MaxTokens: openai.Int(2000),
		})
		if ctx.Err() != nil {
			return nil, tokens, ctx.Err()
		}
		if err != nil || len(reply.Choices) == 0 {
			continue
		}
		tokens += reply.Usage.TotalTokens
		if verdict, ok := parse(reply.Choices[0].Message.Content, len(titles)); ok {
			return verdict, tokens, nil
		}
	}
	return nil, tokens, errors.New("no parsable geotag answer")
}

func parse(content string, n int) (map[int]bool, bool) {
	var out struct {
		Regional []int `json:"regional"`
	}
	if err := json.Unmarshal([]byte(jsonObject.FindString(content)), &out); err != nil {
		return nil, false
	}
	verdict := map[int]bool{}
	for _, i := range out.Regional {
		if i >= 0 && i < n {
			verdict[i] = true
		}
	}
	return verdict, true
}

func truncate(s string, n int) string {
	if r := []rune(s); len(r) > n {
		return string(r[:n])
	}
	return s
}

// Run classifies up to limit pending articles. names maps region tags to their names; articles of unknown regions are skipped.
// A batch whose answer could not be parsed stays pending and is retried on the next pass.
func Run(ctx context.Context, db *gorm.DB, c Chat, names map[string]string, limit int) (done, regional int, err error) {
	rows, err := store.PendingGeo(ctx, db, limit)
	if err != nil {
		return 0, 0, err
	}
	type job struct {
		region string
		batch  []store.GeoCandidate
	}
	var jobs []job
	for i := 0; i < len(rows); {
		j := i
		for j < len(rows) && rows[j].RegionTag == rows[i].RegionTag {
			j++
		}
		for k := i; k < j; k += batchSize {
			jobs = append(jobs, job{rows[i].RegionTag, rows[k:min(k+batchSize, j)]})
		}
		i = j
	}
	slog.Info("geotag pass", "articles", len(rows), "batches", len(jobs))
	var mu sync.Mutex
	var tokens int64
	sem := make(chan struct{}, workers)
	var wg sync.WaitGroup
	for _, j := range jobs {
		name, ok := names[j.region]
		if !ok {
			continue
		}
		wg.Add(1)
		sem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			titles := make([]string, len(j.batch))
			for i, a := range j.batch {
				titles[i] = a.Title
			}
			verdict, used, cerr := Classify(ctx, c, name, titles)
			mu.Lock()
			defer mu.Unlock()
			tokens += used
			if cerr != nil {
				return
			}
			geo := make([]store.ArticleGeo, len(j.batch))
			for i, a := range j.batch {
				geo[i] = store.ArticleGeo{ArticleID: a.ID, Basis: "ai"}
				if verdict[i] {
					region := j.region
					geo[i].RegionTag = &region
					regional++
				}
			}
			if serr := store.SaveGeo(ctx, db, geo); serr != nil {
				err = errors.Join(err, serr)
				return
			}
			done += len(geo)
		}()
	}
	wg.Wait()
	slog.Info("geotag pass finished", "classified", done, "regional", regional, "tokens", tokens)
	return done, regional, err
}

// RegionNames maps each region tag of the vocabulary to its name.
func RegionNames(v vocabulary.Vocabulary) map[string]string {
	names := map[string]string{}
	for _, t := range v.Tags {
		if strings.HasPrefix(t.ID, "geography:region:") {
			names[t.ID] = t.Label
		}
	}
	return names
}
