package httpapi

import (
	"context"
	"errors"
	"net/http"
	"time"

	"github.com/danielgtaylor/huma/v2"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
	"gorm.io/gorm"
)

type ListNewsInput struct {
	SourceID         string    `query:"source_id" doc:"Точный ID источника"`
	TagID            string    `query:"tag_id" doc:"Точный ID непосредственно назначенного тега"`
	ProcessingStatus string    `query:"processing_status" default:"completed" enum:"pending,processing,completed,failed"`
	PublishedFrom    time.Time `query:"published_from" doc:"Включительная нижняя граница даты публикации, RFC3339"`
	PublishedTo      time.Time `query:"published_to" doc:"Включительная верхняя граница даты публикации, RFC3339"`
	Limit            int       `query:"limit" default:"20" minimum:"1" maximum:"100"`
	Offset           int       `query:"offset" default:"0" minimum:"0"`
	from, to         *time.Time
}

func (in *ListNewsInput) Resolve(ctx huma.Context) []error {
	// Huma does not support pointer query parameters; presence preserves a supplied zero timestamp.
	if ctx.Query("published_from") != "" {
		in.from = &in.PublishedFrom
	}
	if ctx.Query("published_to") != "" {
		in.to = &in.PublishedTo
	}
	if in.from != nil && in.to != nil && in.from.After(*in.to) {
		return []error{&huma.ErrorDetail{Location: "query.published_to", Message: "published_to must not precede published_from"}}
	}
	return nil
}

type NewsIDInput struct {
	ID int64 `path:"id" minimum:"1"`
}

type TokenUsage struct {
	PromptTokens     *int64 `json:"prompt_tokens" minimum:"0"`
	CompletionTokens *int64 `json:"completion_tokens" minimum:"0"`
	TotalTokens      *int64 `json:"total_tokens" minimum:"0"`
}

type AttemptMetadata struct {
	ID                int64      `json:"id"`
	Number            int        `json:"number"`
	VocabularyVersion string     `json:"vocabulary_version"`
	PromptVersion     string     `json:"prompt_version"`
	Model             string     `json:"model"`
	StartedAt         time.Time  `json:"started_at"`
	FinishedAt        *time.Time `json:"finished_at"`
	Status            string     `json:"status" enum:"processing,completed,failed"`
	Error             string     `json:"error"`
	Usage             TokenUsage `json:"usage"`
}

type AssignedTag struct {
	TagID    string `json:"tag_id"`
	Evidence string `json:"evidence"`
}

type Event struct {
	ID       int64   `json:"id"`
	TagID    string  `json:"tag_id"`
	Status   *string `json:"status" enum:"observed,announced_planned,forecast"`
	Evidence string  `json:"evidence"`
}

type Tagging struct {
	Attempt AttemptMetadata `json:"attempt"`
	Tags    []AssignedTag   `json:"tags" nullable:"false"`
	Events  []Event         `json:"events" nullable:"false"`
}

type NewsArticle struct {
	ID               int64      `json:"id"`
	SourceID         string     `json:"source_id"`
	SourceItemID     string     `json:"source_item_id"`
	URL              string     `json:"url" format:"uri"`
	Title            string     `json:"title"`
	PublishedAt      *time.Time `json:"published_at"`
	CollectedAt      time.Time  `json:"collected_at"`
	Text             string     `json:"text"`
	TextProvenance   string     `json:"text_provenance"`
	TextError        string     `json:"text_error"`
	ProcessingStatus string     `json:"processing_status" enum:"pending,processing,completed,failed"`
	Tagging          *Tagging   `json:"tagging,omitempty"`
}

type ListNewsOutput struct {
	Body struct {
		Items   []NewsArticle `json:"items" nullable:"false"`
		Limit   int           `json:"limit"`
		Offset  int           `json:"offset"`
		HasMore bool          `json:"has_more"`
	}
}

type NewsDetailOutput struct {
	Body struct {
		Article  NewsArticle       `json:"article"`
		Attempts []AttemptMetadata `json:"attempts" nullable:"false"`
	}
}

func registerNews(api huma.API, db *gorm.DB) {
	huma.Register(api, huma.Operation{
		OperationID: "list-news", Method: http.MethodGet, Path: "/v1/news",
		Summary: "Получить статьи с фильтрами и пагинацией", Tags: []string{"news"}, Errors: []int{422, 500, 503},
	}, func(ctx context.Context, in *ListNewsInput) (*ListNewsOutput, error) {
		if db == nil {
			return nil, huma.Error503ServiceUnavailable("news unavailable")
		}
		ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		page, err := store.ListArticles(ctx, db, store.ArticleQuery{
			SourceID: in.SourceID, TagID: in.TagID, ProcessingStatus: in.ProcessingStatus,
			PublishedFrom: in.from, PublishedTo: in.to, Limit: in.Limit, Offset: in.Offset,
		})
		if err != nil {
			return nil, huma.Error503ServiceUnavailable("news unavailable")
		}
		results := make(map[int64]*Tagging, len(page.Attempts))
		for _, attempt := range page.Attempts {
			results[attempt.ArticleID] = taggingResult(attempt)
		}
		out := &ListNewsOutput{}
		out.Body.Items = make([]NewsArticle, len(page.Articles))
		for i, article := range page.Articles {
			out.Body.Items[i] = newsArticle(article, results[article.ID])
		}
		out.Body.Limit, out.Body.Offset, out.Body.HasMore = in.Limit, in.Offset, page.HasMore
		return out, nil
	})
	huma.Register(api, huma.Operation{
		OperationID: "read-news", Method: http.MethodGet, Path: "/v1/news/{id}",
		Summary: "Получить статью, результат и историю попыток", Tags: []string{"news"}, Errors: []int{404, 422, 500, 503},
	}, func(ctx context.Context, in *NewsIDInput) (*NewsDetailOutput, error) {
		if db == nil {
			return nil, huma.Error503ServiceUnavailable("news unavailable")
		}
		ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
		defer cancel()
		article, attempts, err := store.ReadArticleDetail(ctx, db, in.ID)
		if errors.Is(err, gorm.ErrRecordNotFound) {
			return nil, huma.Error404NotFound("article not found")
		}
		if err != nil {
			return nil, huma.Error503ServiceUnavailable("news unavailable")
		}
		out := &NewsDetailOutput{}
		out.Body.Attempts = make([]AttemptMetadata, len(attempts))
		var result *Tagging
		for i, attempt := range attempts {
			out.Body.Attempts[i] = attemptMetadata(attempt)
			if attempt.Status == store.StatusCompleted {
				result = taggingResult(attempt)
			}
		}
		out.Body.Article = newsArticle(article, result)
		return out, nil
	})
}

func newsArticle(article store.Article, result *Tagging) NewsArticle {
	return NewsArticle{
		ID: article.ID, SourceID: article.SourceID, SourceItemID: article.SourceItemID, URL: article.URL,
		Title: article.Title, PublishedAt: article.PublishedAt, CollectedAt: article.CollectedAt,
		Text: article.Text, TextProvenance: article.TextProvenance, TextError: article.TextError,
		ProcessingStatus: article.ProcessingStatus, Tagging: result,
	}
}

func attemptMetadata(attempt store.TaggingAttempt) AttemptMetadata {
	return AttemptMetadata{
		ID: attempt.ID, Number: attempt.Number, VocabularyVersion: attempt.Version, PromptVersion: attempt.PromptVersion,
		Model: attempt.Model, StartedAt: attempt.StartedAt, FinishedAt: attempt.FinishedAt, Status: attempt.Status, Error: attempt.Error,
		Usage: TokenUsage{PromptTokens: attempt.PromptTokens, CompletionTokens: attempt.CompletionTokens, TotalTokens: attempt.TotalTokens},
	}
}

func taggingResult(attempt store.TaggingAttempt) *Tagging {
	result := &Tagging{Attempt: attemptMetadata(attempt), Tags: make([]AssignedTag, len(attempt.Assignments)), Events: make([]Event, len(attempt.Events))}
	for i, assignment := range attempt.Assignments {
		result.Tags[i] = AssignedTag{TagID: assignment.TagID, Evidence: assignment.Evidence}
	}
	for i, event := range attempt.Events {
		result.Events[i] = Event{ID: event.ID, TagID: event.TagID, Status: event.Status, Evidence: event.Evidence}
	}
	return result
}
