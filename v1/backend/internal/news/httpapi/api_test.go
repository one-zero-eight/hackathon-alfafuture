package httpapi

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/danielgtaylor/huma/v2"
	"github.com/gin-gonic/gin"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/store"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/news/vocabulary"
	"github.com/one-zero-eight/hackathon-alfafuture/backend/internal/testdb"
)

func get(t *testing.T, handler http.Handler, path string, status int) *httptest.ResponseRecorder {
	t.Helper()
	out := httptest.NewRecorder()
	handler.ServeHTTP(out, httptest.NewRequest(http.MethodGet, path, nil))
	if out.Code != status {
		t.Fatalf("GET %s: status=%d want=%d body=%s", path, out.Code, status, out.Body)
	}
	return out
}

func validateResponse(t *testing.T, api huma.API, path string, out *httptest.ResponseRecorder) {
	t.Helper()
	var body any
	if err := json.Unmarshal(out.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	schema := api.OpenAPI().Paths[path].Get.Responses["200"].Content["application/json"].Schema
	result := &huma.ValidateResult{}
	huma.Validate(api.OpenAPI().Components.Schemas, schema, huma.NewPathBuffer(nil, 0), huma.ModeReadFromServer, body, result)
	if len(result.Errors) != 0 {
		t.Fatalf("GET %s does not match its generated schema: %v", path, result.Errors)
	}
}

func TestOfflineContractHealthAndUnavailableDatabase(t *testing.T) {
	router, api, err := New(nil)
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{"/v1/tags", "/v1/sources", "/v1/status", "/v1/news", "/v1/news/1", "/readyz"} {
		out := get(t, router, path, 503)
		if !strings.HasPrefix(out.Header().Get("Content-Type"), "application/problem+json") || !strings.Contains(out.Body.String(), `"status":503`) {
			t.Fatalf("missing documented problem response: %s", out.Body)
		}
	}
	validateResponse(t, api, "/healthz", get(t, router, "/healthz", 200))
	get(t, router, "/v1/tags?unknown=true", 422)
	if out := get(t, router, "/docs", 200); !strings.Contains(out.Body.String(), "/openapi.yaml") {
		t.Fatal("interactive docs do not reference the generated contract")
	}
	get(t, router, "/openapi.yaml", 200)
	get(t, router, "/schemas/Source.json", 200)
	encoded := get(t, router, "/openapi.json", 200).Body.Bytes()
	var exported struct {
		OpenAPI string                                `json:"openapi"`
		Paths   map[string]map[string]json.RawMessage `json:"paths"`
	}
	if err := json.Unmarshal(encoded, &exported); err != nil || exported.OpenAPI != "3.1.0" || len(exported.Paths) != 7 {
		t.Fatalf("wrong offline contract: %v", err)
	}
	for _, path := range []string{"/v1/tags", "/v1/sources", "/v1/status", "/v1/news", "/v1/news/{id}", "/healthz", "/readyz"} {
		if len(exported.Paths[path]) != 1 || exported.Paths[path]["get"] == nil {
			t.Fatalf("missing read-only operation: %s", path)
		}
		get(t, router, strings.ReplaceAll(path, "{id}", "1")+"?unknown=true", 422)
		if api.OpenAPI().Paths[path].Get.Responses["422"] == nil {
			t.Fatalf("unknown-query error missing from contract: %s", path)
		}
	}
	second, err := json.Marshal(api.OpenAPI())
	if err != nil || !bytes.Equal(bytes.TrimSpace(encoded), second) {
		t.Fatal("runtime and offline schemas differ")
	}
	router.GET("/panic", func(*gin.Context) { panic("private panic details") })
	if out := get(t, router, "/panic", 500); strings.Contains(out.Body.String(), "private panic details") {
		t.Fatal("panic response exposed internal details")
	}
}

func TestPostgresVocabularySourcesAndReadiness(t *testing.T) {
	db, _ := testdb.New(t)
	if err := store.Bootstrap(t.Context(), db); err != nil {
		t.Fatal(err)
	}
	router, api, err := New(db)
	if err != nil {
		t.Fatal(err)
	}
	out := get(t, router, "/v1/sources", 200)
	if !strings.Contains(out.Body.String(), `"sources":[]`) {
		t.Fatalf("empty sources must be an array: %s", out.Body)
	}
	validateResponse(t, api, "/v1/sources", out)
	now := time.Date(2026, 10, 23, 10, 0, 0, 0, time.UTC)
	if err := store.RegisterSources(t.Context(), db, []store.Source{
		{ID: "z", Name: "Second", FeedURL: "https://example.com/z.rss"},
		{ID: "a", Name: "First", FeedURL: "https://example.com/a.rss"},
	}, now); err != nil {
		t.Fatal(err)
	}
	if err := store.RecordSourcePoll(t.Context(), db, "a", now, nil); err != nil {
		t.Fatal(err)
	}
	if err := store.RecordSourcePoll(t.Context(), db, "a", now.Add(time.Minute), errors.New("publisher returned HTTP 503")); err != nil {
		t.Fatal(err)
	}
	out = get(t, router, "/v1/sources", 200)
	validateResponse(t, api, "/v1/sources", out)
	var sources SourcesOutput
	if err := json.Unmarshal(out.Body.Bytes(), &sources.Body); err != nil {
		t.Fatal(err)
	}
	if len(sources.Body.Sources) != 2 || sources.Body.Sources[0].ID != "a" || sources.Body.Sources[1].ID != "z" {
		t.Fatalf("wrong source ordering: %+v", sources)
	}
	first := sources.Body.Sources[0]
	if first.LastPolledAt == nil || !first.LastPolledAt.Equal(now.Add(time.Minute)) || first.LastSuccessAt == nil || !first.LastSuccessAt.Equal(now) || first.LastError != "publisher returned HTTP 503" || !first.CollectionSince.Equal(now.Add(-24*time.Hour)) || sources.Body.Sources[1].LastPolledAt != nil {
		t.Fatalf("source state lost: %+v", sources)
	}
	// A fixture-only edit proves the HTTP handler reads PostgreSQL rather than the embedded seed.
	if err := db.Exec(`UPDATE tags SET payload = jsonb_set(payload, '{label}', '"Stored fixture label"') WHERE id = 'event:inflation'`).Error; err != nil {
		t.Fatal(err)
	}
	out = get(t, router, "/v1/tags", 200)
	validateResponse(t, api, "/v1/tags", out)
	var got vocabulary.Vocabulary
	if err := json.Unmarshal(out.Body.Bytes(), &got); err != nil {
		t.Fatal(err)
	}
	want, err := store.LoadVocabulary(t.Context(), db, "v1")
	gotJSON, gotErr := json.Marshal(got)
	wantJSON, wantErr := json.Marshal(want)
	if err != nil || gotErr != nil || wantErr != nil || !bytes.Equal(gotJSON, wantJSON) || len(got.Tags) != 525 {
		t.Fatalf("stored vocabulary was not preserved: %v", err)
	}
	var found bool
	for _, tag := range got.Tags {
		found = found || tag.ID == "event:inflation" && tag.Label == "Stored fixture label"
	}
	if !found {
		t.Fatal("API returned a file snapshot instead of the DB vocabulary")
	}
	validateResponse(t, api, "/readyz", get(t, router, "/readyz", 200))
	pool, err := db.DB()
	if err != nil {
		t.Fatal(err)
	}
	if err := pool.Close(); err != nil {
		t.Fatal(err)
	}
	for _, path := range []string{"/v1/tags", "/v1/sources", "/v1/status", "/v1/news", "/v1/news/1", "/readyz"} {
		out := get(t, router, path, 503)
		for _, forbidden := range []string{"postgres://", "news_test", "sql:", "password", "closed"} {
			if strings.Contains(out.Body.String(), forbidden) {
				t.Fatalf("database failure exposed internal details: %s", out.Body)
			}
		}
	}
	get(t, router, "/healthz", 200)
}
