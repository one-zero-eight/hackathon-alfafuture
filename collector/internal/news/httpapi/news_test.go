package httpapi

import (
	"encoding/json"
	"fmt"
	"net/url"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/danielgtaylor/huma/v2"
	"github.com/gin-gonic/gin"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/collector/internal/testdb"
	"gorm.io/gorm"
)

const newsText = "Oil rose. Oil may fall. Russia."

func newsDatabase(t *testing.T) (*gorm.DB, *gin.Engine, huma.API) {
	t.Helper()
	db, _ := testdb.New(t)
	if err := store.Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	if err := store.RegisterSources(t.Context(), db, []store.Source{
		{ID: "rbc", Name: "RBC", FeedURL: "https://rssexport.rbc.ru/feed"},
		{ID: "cbr", Name: "CBR", FeedURL: "https://www.cbr.ru/feed"},
	}, time.Now()); err != nil {
		t.Fatal(err)
	}
	router, api, err := New(db)
	if err != nil {
		t.Fatal(err)
	}
	return db, router, api
}

func newsItem(t *testing.T, db *gorm.DB, source, id string, published *time.Time, collected time.Time) store.Article {
	t.Helper()
	article, _, err := store.InsertArticle(t.Context(), db, store.Article{
		SourceID: source, SourceItemID: id, URL: "https://example.com/" + id, Title: id,
		PublishedAt: published, CollectedAt: collected, Text: newsText, TextProvenance: store.TextFromRSSDescription,
	})
	if err != nil {
		t.Fatal(err)
	}
	return article
}

func newsAttempt(t *testing.T, db *gorm.DB, article store.Article) store.TaggingAttempt {
	t.Helper()
	attempt, err := store.StartAttempt(t.Context(), db, store.TaggingAttempt{
		ArticleID: article.ID, Version: "v1", PromptVersion: "fixture-v1", Model: "deepseek/deepseek-v4.1-flash",
		InputText: article.Text, Request: `{"private":"PRIVATE_REQUEST"}`, StartedAt: article.CollectedAt,
	})
	if err != nil {
		t.Fatal(err)
	}
	return attempt
}

func finishNews(t *testing.T, db *gorm.DB, attempt store.TaggingAttempt, result *store.TaggingResult, failureStatus string) {
	t.Helper()
	zero := int64(0)
	outcome := store.AttemptCompletion{
		FinishedAt: attempt.StartedAt.Add(time.Second), Response: "PRIVATE_RESPONSE", Result: result,
		PromptTokens: &zero, FailureStatus: failureStatus,
	}
	if result == nil {
		outcome.Error = "LLM returned HTTP 503"
	}
	if err := store.FinishAttempt(t.Context(), db, attempt.ID, outcome); err != nil {
		t.Fatal(err)
	}
}

func decodeNewsPage(t *testing.T, router *gin.Engine, api huma.API, path string) ListNewsOutput {
	t.Helper()
	out := get(t, router, path, 200)
	validateResponse(t, api, "/v1/news", out)
	assertNoPrivateTrace(t, out.Body.Bytes())
	var page ListNewsOutput
	if err := json.Unmarshal(out.Body.Bytes(), &page.Body); err != nil {
		t.Fatal(err)
	}
	return page
}

func assertNoPrivateTrace(t *testing.T, raw []byte) {
	t.Helper()
	for _, secret := range []string{"PRIVATE_REQUEST", "PRIVATE_RESPONSE", `"request":`, `"response":`, `"input_text":`, `"dedup_key":`} {
		if strings.Contains(string(raw), secret) {
			t.Fatalf("public news response leaked private trace: %s", secret)
		}
	}
}

func TestNewsInputValidationBeforeDatabaseAccess(t *testing.T) {
	router, _, err := New(nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, query := range []string{
		"limit=0", "limit=-1", "limit=101", "limit=1.5", "limit=overflow",
		"offset=-1", "offset=1.5", "offset=9223372036854775808",
		"processing_status=invalid", "unknown=true", "published_from=2026-10-23", "published_to=invalid",
		"published_from=2026-10-24T00:00:00Z&published_to=2026-10-23T00:00:00Z",
	} {
		t.Run(query, func(t *testing.T) { get(t, router, "/v1/news?"+query, 422) })
	}
	for _, id := range []string{"0", "-1", "abc", "1.5", "9223372036854775808"} {
		get(t, router, "/v1/news/"+id, 422)
	}
}

func TestPostgresNewsFiltersOrderingAndPagination(t *testing.T) {
	db, router, api := newsDatabase(t)
	base := time.Date(2026, 10, 23, 9, 0, 0, 0, time.UTC)
	tie := base.Add(time.Hour)
	older := newsItem(t, db, "rbc", "older", &base, base.Add(4*time.Hour))
	dated := newsItem(t, db, "rbc", "dated", &tie, base.Add(3*time.Hour))
	undated := newsItem(t, db, "cbr", "undated", nil, tie)
	tied := newsItem(t, db, "cbr", "tied", &tie, base)
	for _, article := range []store.Article{older, dated, undated, tied} {
		result := &store.TaggingResult{}
		if article.ID != tied.ID {
			result.Tags = []store.ResultTag{{TagID: "resource:oil", Evidence: "Oil"}}
		}
		finishNews(t, db, newsAttempt(t, db, article), result, "")
	}
	pending := newsItem(t, db, "rbc", "pending", nil, base.Add(5*time.Hour))
	processing := newsItem(t, db, "rbc", "processing", nil, base.Add(5*time.Hour))
	newsAttempt(t, db, processing)
	failed := newsItem(t, db, "rbc", "failed", nil, base.Add(5*time.Hour))
	finishNews(t, db, newsAttempt(t, db, failed), nil, store.StatusFailed)
	checks := []struct {
		query string
		ids   []int64
		more  bool
	}{
		{"", []int64{tied.ID, undated.ID, dated.ID, older.ID}, false},
		{"limit=2", []int64{tied.ID, undated.ID}, true},
		{"limit=2&offset=2", []int64{dated.ID, older.ID}, false},
		{"limit=2&offset=4", nil, false},
		{"limit=100", []int64{tied.ID, undated.ID, dated.ID, older.ID}, false},
		{"source_id=rbc", []int64{dated.ID, older.ID}, false},
		{"tag_id=resource:oil", []int64{undated.ID, dated.ID, older.ID}, false},
		{"source_id=cbr&tag_id=resource:oil", []int64{undated.ID}, false},
		{"source_id=missing", nil, false},
		{"tag_id=missing", nil, false},
		{"source_id=" + url.QueryEscape("rbc' OR 1=1 --"), nil, false},
		{"tag_id=" + url.QueryEscape("resource:oil' OR 1=1 --"), nil, false},
		{"processing_status=pending", []int64{pending.ID}, false},
		{"processing_status=processing", []int64{processing.ID}, false},
		{"processing_status=failed", []int64{failed.ID}, false},
		{"processing_status=pending&tag_id=resource:oil", nil, false},
		{"published_from=2026-10-23T10:00:00Z", []int64{tied.ID, dated.ID}, false},
		{"published_to=2026-10-23T10:00:00Z", []int64{tied.ID, dated.ID, older.ID}, false},
		{"published_from=" + url.QueryEscape("2026-10-23T13:00:00+03:00") + "&published_to=2026-10-23T10:00:00Z", []int64{tied.ID, dated.ID}, false},
		{"source_id=rbc&tag_id=resource:oil&published_from=2026-10-23T10:00:00Z&published_to=2026-10-23T10:00:00Z&limit=1", []int64{dated.ID}, false},
		{"published_to=0001-01-01T00:00:00Z", nil, false},
	}
	for _, tc := range checks {
		t.Run(tc.query, func(t *testing.T) {
			page := decodeNewsPage(t, router, api, "/v1/news?"+tc.query)
			ids := make([]int64, len(page.Body.Items))
			for i, item := range page.Body.Items {
				ids[i] = item.ID
				if item.Text != newsText || item.Tagging == nil && item.ProcessingStatus == store.StatusCompleted {
					t.Fatal("missing stored text or completed tagging result")
				}
			}
			if !slices.Equal(ids, tc.ids) || page.Body.HasMore != tc.more || page.Body.Items == nil {
				t.Fatalf("wrong page: ids=%v more=%v want=%v more=%v", ids, page.Body.HasMore, tc.ids, tc.more)
			}
			if tc.query == "" && (page.Body.Limit != 20 || page.Body.Offset != 0) {
				t.Fatal("incorrect default page size or offset")
			}
		})
	}
}

func TestPostgresNewsDetailHistoryAndEventInstances(t *testing.T) {
	db, router, api := newsDatabase(t)
	now := time.Date(2026, 10, 23, 9, 0, 0, 0, time.UTC)
	article := newsItem(t, db, "rbc", "history", nil, now)
	first := newsAttempt(t, db, article)
	finishNews(t, db, first, nil, store.StatusPending)
	second := newsAttempt(t, db, article)
	observed, forecast := "observed", "forecast"
	finishNews(t, db, second, &store.TaggingResult{
		Tags: []store.ResultTag{{TagID: "resource:oil", Evidence: "Oil"}, {TagID: "event:commodity_prices", Evidence: "Oil rose."}, {TagID: "geography:country:RU", Evidence: "Russia"}},
		Events: []store.ResultEvent{
			{TagID: "event:commodity_prices", Status: &observed, Evidence: "Oil rose."},
			{TagID: "event:commodity_prices", Status: &forecast, Evidence: "Oil may fall."},
			{TagID: "event:commodity_prices", Evidence: "Oil"},
		},
	}, "")
	out := get(t, router, fmt.Sprintf("/v1/news/%d", article.ID), 200)
	validateResponse(t, api, "/v1/news/{id}", out)
	assertNoPrivateTrace(t, out.Body.Bytes())
	var detail NewsDetailOutput
	if err := json.Unmarshal(out.Body.Bytes(), &detail.Body); err != nil {
		t.Fatal(err)
	}
	got := detail.Body
	if got.Article.ID != article.ID || got.Article.Text != newsText || got.Article.PublishedAt != nil || got.Article.TextProvenance != store.TextFromRSSDescription || len(got.Attempts) != 2 || got.Attempts[0].ID != first.ID || got.Attempts[1].ID != second.ID || got.Attempts[0].Status != store.StatusFailed || got.Attempts[0].Error != "LLM returned HTTP 503" {
		t.Fatalf("history lost: %+v", got)
	}
	result := got.Article.Tagging
	if result == nil || result.Attempt.ID != second.ID || result.Attempt.VocabularyVersion != "v1" || result.Attempt.PromptVersion != "fixture-v1" || result.Attempt.FinishedAt == nil || result.Attempt.Usage.PromptTokens == nil || *result.Attempt.Usage.PromptTokens != 0 || result.Attempt.Usage.TotalTokens != nil || len(result.Tags) != 3 || result.Tags[0].TagID != "event:commodity_prices" || len(result.Events) != 3 {
		t.Fatalf("result lost: %+v", result)
	}
	if result.Events[0].Status == nil || *result.Events[0].Status != observed || result.Events[1].Status == nil || *result.Events[1].Status != forecast || result.Events[2].Status != nil || result.Events[0].ID >= result.Events[1].ID || result.Events[1].ID >= result.Events[2].ID {
		t.Fatalf("event instances were merged or reordered: %+v", result.Events)
	}
	for _, query := range []string{"tag_id=geography:m49:150", "tag_id=economic_group:brics"} {
		if page := decodeNewsPage(t, router, api, "/v1/news?"+query); len(page.Body.Items) != 0 {
			t.Fatal("direct tag search inferred an ancestor or economic membership")
		}
	}
	get(t, router, "/v1/news/9223372036854775807", 404)
	stored, attempts, err := store.ReadArticleDetail(t.Context(), db, article.ID)
	if err != nil || stored.ID != article.ID || len(attempts) != 2 {
		t.Fatal("public read path failed", err)
	}
	for _, attempt := range attempts {
		if attempt.Request != "" || attempt.Response != "" || attempt.InputText != "" {
			t.Fatal("public read path fetched private trace columns")
		}
	}
}

func TestPostgresNewsDefaultPageSize(t *testing.T) {
	db, router, api := newsDatabase(t)
	now := time.Date(2026, 10, 23, 9, 0, 0, 0, time.UTC)
	var lastID int64
	for i := range 21 {
		article := newsItem(t, db, "rbc", fmt.Sprintf("page-%d", i), &now, now)
		finishNews(t, db, newsAttempt(t, db, article), &store.TaggingResult{}, "")
		lastID = article.ID
	}
	page := decodeNewsPage(t, router, api, "/v1/news")
	if len(page.Body.Items) != 20 || page.Body.Limit != 20 || !page.Body.HasMore || page.Body.Items[0].ID != lastID {
		t.Fatal("default page is not the newest20items with a following page")
	}
	page = decodeNewsPage(t, router, api, "/v1/news?offset=20")
	if len(page.Body.Items) != 1 || page.Body.HasMore || page.Body.Offset != 20 {
		t.Fatal("last default page is incorrect")
	}
}

func TestPostgresUnfinishedAndEmptyNewsDetails(t *testing.T) {
	db, router, api := newsDatabase(t)
	now := time.Date(2026, 10, 23, 9, 0, 0, 0, time.UTC)
	for _, status := range []string{store.StatusPending, store.StatusProcessing, store.StatusFailed, store.StatusCompleted} {
		article := newsItem(t, db, "cbr", status, nil, now)
		if status == store.StatusPending {
			if err := db.Model(&store.Article{}).Where("id = ?", article.ID).Updates(map[string]any{"text": "", "text_provenance": "", "text_error": "publisher request failed"}).Error; err != nil {
				t.Fatal(err)
			}
		} else {
			attempt := newsAttempt(t, db, article)
			if status == store.StatusCompleted {
				finishNews(t, db, attempt, &store.TaggingResult{}, "")
			} else if status == store.StatusFailed {
				finishNews(t, db, attempt, nil, store.StatusFailed)
			}
		}
		out := get(t, router, fmt.Sprintf("/v1/news/%d", article.ID), 200)
		validateResponse(t, api, "/v1/news/{id}", out)
		assertNoPrivateTrace(t, out.Body.Bytes())
		var detail NewsDetailOutput
		if err := json.Unmarshal(out.Body.Bytes(), &detail.Body); err != nil {
			t.Fatal(err)
		}
		got := detail.Body
		if got.Article.ProcessingStatus != status || got.Attempts == nil || (got.Article.Tagging != nil) != (status == store.StatusCompleted) {
			t.Fatalf("unfinished and empty-result states confused: %+v", got)
		}
		if status == store.StatusPending && (got.Article.Text != "" || got.Article.TextError != "publisher request failed" || len(got.Attempts) != 0) {
			t.Fatal("unfinished extraction detail lost")
		}
		if status == store.StatusProcessing && (got.Attempts[0].FinishedAt != nil || got.Attempts[0].Usage.PromptTokens != nil) {
			t.Fatal("processing attempt invented finish time or usage")
		}
		if status == store.StatusCompleted && (got.Article.Tagging.Tags == nil || got.Article.Tagging.Events == nil || len(got.Article.Tagging.Tags) != 0 || len(got.Article.Tagging.Events) != 0) {
			t.Fatal("empty completed result must contain empty arrays")
		}
	}
}
