package llm

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"reflect"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/packages/param"
	"github.com/openai/openai-go/v3/shared"
)

type fixtureTransport func(*http.Request) (*http.Response, error)

func (f fixtureTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

// In-memory HTTP fixtures cannot accidentally dial a real model endpoint.
func fixtureClient(t *testing.T, handler http.HandlerFunc) *Client {
	t.Helper()
	client, err := newClient("sk-fixture-only", "", fixtureTransport(func(r *http.Request) (*http.Response, error) {
		if r.Method != http.MethodPost || r.URL.String() != BaseURL+"chat/completions" {
			return nil, errors.New("unexpected request route")
		}
		if r.Header.Get("Authorization") != "Bearer sk-fixture-only" {
			return nil, errors.New("unexpected fixture authorization")
		}
		w := httptest.NewRecorder()
		handler(w, r)
		response := w.Result()
		response.Request = r
		return response, nil
	}))
	if err != nil {
		t.Fatal(err)
	}
	return client
}

func writeCompletion(w http.ResponseWriter, extra string) {
	w.Header().Set("Content-Type", "application/json")
	_, _ = fmt.Fprintf(w, `{"id":"fixture","object":"chat.completion","created":1,"model":%q,"choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":"fixture answer"}}]%s}`, DefaultModel, extra)
}

func chatParams() openai.ChatCompletionNewParams {
	return openai.ChatCompletionNewParams{Messages: []openai.ChatCompletionMessageParamUnion{openai.UserMessage("fixture question")}}
}

func TestChatHistoryAndTools(t *testing.T) {
	calls := 0
	client := fixtureClient(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		var body struct {
			Model    string `json:"model"`
			Messages []struct {
				Role, Content string
				ToolCallID    string            `json:"tool_call_id"`
				ToolCalls     []json.RawMessage `json:"tool_calls"`
			} `json:"messages"`
			Tools []struct {
				Type     string
				Function struct {
					Name       string
					Parameters map[string]any
				}
			} `json:"tools"`
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatal(err)
		}
		if body.Model != DefaultModel || len(body.Tools) != 1 || body.Tools[0].Type != "function" || body.Tools[0].Function.Name != "lookup_news" || body.Tools[0].Function.Parameters["type"] != "object" {
			t.Fatalf("wrong model/tools: %+v", body)
		}
		roles := make([]string, len(body.Messages))
		for i, message := range body.Messages {
			roles[i] = message.Role
		}
		if calls == 1 {
			if !reflect.DeepEqual(roles, []string{"system", "user", "assistant", "user"}) || body.Messages[1].Content != "earlier question" || body.Messages[2].Content != "earlier answer" {
				t.Fatalf("lost history: %+v", body.Messages)
			}
			w.Header().Set("Content-Type", "application/json")
			_, _ = io.WriteString(w, `{"id":"fixture-tool","object":"chat.completion","created":1,"model":"deepseek/deepseek-v4.1-flash","choices":[{"index":0,"finish_reason":"tool_calls","message":{"role":"assistant","content":null,"tool_calls":[{"id":"call_1","type":"function","function":{"name":"lookup_news","arguments":"{\"tag_id\":\"resource:oil\"}"}}]}}]}`)
		} else {
			if !reflect.DeepEqual(roles, []string{"system", "user", "assistant", "user", "assistant", "tool"}) || len(body.Messages[4].ToolCalls) != 1 || body.Messages[5].ToolCallID != "call_1" || body.Messages[5].Content != "tool result" {
				t.Fatalf("lost tool history: %+v", body.Messages)
			}
			writeCompletion(w, "")
		}
	})
	params := openai.ChatCompletionNewParams{
		Messages: []openai.ChatCompletionMessageParamUnion{
			openai.SystemMessage("fixture instruction"), openai.UserMessage("earlier question"),
			openai.AssistantMessage("earlier answer"), openai.UserMessage("current question"),
		},
		Tools: []openai.ChatCompletionToolUnionParam{openai.ChatCompletionFunctionTool(shared.FunctionDefinitionParam{
			Name: "lookup_news", Parameters: shared.FunctionParameters{"type": "object", "properties": map[string]any{"tag_id": map[string]string{"type": "string"}}},
		})},
	}
	response, err := client.Chat(t.Context(), params)
	if err != nil {
		t.Fatal(err)
	}
	if calls != 1 || len(response.Choices) != 1 || response.Choices[0].FinishReason != "tool_calls" || len(response.Choices[0].Message.ToolCalls) != 1 {
		t.Fatal("tool execution must stay with caller")
	}
	call := response.Choices[0].Message.ToolCalls[0].AsFunction()
	if call.ID != "call_1" || call.Function.Name != "lookup_news" || call.Function.Arguments != `{"tag_id":"resource:oil"}` {
		t.Fatalf("tool call mismatch: %+v", call)
	}
	params.Messages = append(params.Messages, response.Choices[0].Message.ToParam(), openai.ToolMessage("tool result", call.ID))
	response, err = client.Chat(t.Context(), params)
	if err != nil || calls != 2 || response.Choices[0].Message.Content != "fixture answer" {
		t.Fatal("manual continuation failed", err)
	}
	if params.Model != "" || client.Model() != DefaultModel {
		t.Fatal("request defaults must not mutate caller parameters")
	}
}

func TestChatUsageAvailability(t *testing.T) {
	for _, tt := range []struct {
		name, extra                      string
		usage, prompt, completion, total bool
		promptValue                      int64
	}{
		{"absent", "", false, false, false, false, 0},
		{"null", `,"usage":null`, false, false, false, false, 0},
		{"empty", `,"usage":{}`, true, false, false, false, 0},
		{"partial", `,"usage":{"prompt_tokens":7,"completion_tokens":null}`, true, true, false, false, 7},
		{"zero", `,"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}`, true, true, true, true, 0},
	} {
		t.Run(tt.name, func(t *testing.T) {
			client := fixtureClient(t, func(w http.ResponseWriter, _ *http.Request) { writeCompletion(w, tt.extra) })
			response, err := client.Chat(t.Context(), chatParams())
			if err != nil {
				t.Fatal(err)
			}
			usage := response.Usage
			if response.JSON.Usage.Valid() != tt.usage || usage.JSON.PromptTokens.Valid() != tt.prompt || usage.JSON.CompletionTokens.Valid() != tt.completion || usage.JSON.TotalTokens.Valid() != tt.total || usage.PromptTokens != tt.promptValue {
				t.Fatalf("missing usage became a known zero: %s", response.RawJSON())
			}
			if !strings.Contains(response.RawJSON(), `"id":"fixture"`) {
				t.Fatal("raw response was lost")
			}
		})
	}
}

func TestApprovedModels(t *testing.T) {
	for _, model := range []string{"google/gemma-4-26b-a4b-it", "z-ai/glm-5.3-flash", "qwen/qwen3.6-35b-a3b", DefaultModel, "qwen/qwen3-vl-30b-a3b-instruct", "moonshotai/kimi-k2.6"} {
		t.Run(model, func(t *testing.T) {
			client := fixtureClient(t, func(w http.ResponseWriter, r *http.Request) {
				var body struct{ Model string }
				if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Model != model {
					t.Fatal("model was changed", err)
				}
				writeCompletion(w, "")
			})
			params := chatParams()
			params.Model = model
			if _, err := client.Chat(t.Context(), params); err != nil {
				t.Fatal(err)
			}
		})
	}
}

func TestRejectInvalidConfigAndModelBypasses(t *testing.T) {
	for _, key := range []string{"", " ", "sk-secret\n", "sk-secret\t", "sk-secret\x7f", "sk-ключ"} {
		if _, err := New(key, ""); err == nil || strings.Contains(err.Error(), "sk-secret") {
			t.Fatal("expected secret-free key validation error")
		}
	}
	for _, model := range []string{"invented", " deepseek/deepseek-v4.1-flash", "DEEPSEEK/DEEPSEEK-V4.1-FLASH"} {
		if _, err := New("sk-fixture-only", model); err == nil {
			t.Fatal("accepted unapproved default")
		}
	}
	client := fixtureClient(t, func(http.ResponseWriter, *http.Request) { t.Fatal("invalid request reached transport") })
	for _, change := range []func(*openai.ChatCompletionNewParams){
		func(p *openai.ChatCompletionNewParams) { p.Model = "invented" },
		func(p *openai.ChatCompletionNewParams) { p.Messages = nil },
		func(p *openai.ChatCompletionNewParams) { p.SetExtraFields(map[string]any{"model": "invented"}) },
		func(p *openai.ChatCompletionNewParams) { p.SetExtraFields(map[string]any{"stream": true}) },
		func(p *openai.ChatCompletionNewParams) {
			param.SetJSON([]byte(`{"model":"invented","messages":[]}`), p)
		},
	} {
		params := chatParams()
		change(&params)
		if _, err := client.Chat(t.Context(), params); err == nil {
			t.Fatal("accepted invalid request or override")
		}
		if _, err := client.ChatStream(t.Context(), params); err == nil {
			t.Fatal("stream accepted invalid request or override")
		}
	}
}

func TestEnvironmentConfiguration(t *testing.T) {
	t.Setenv("LLM_API_KEY", "sk-fixture-only")
	t.Setenv("LLM_MODEL", "")
	if err := os.Unsetenv("LLM_MODEL"); err != nil {
		t.Fatal(err)
	}
	client, err := NewFromEnv()
	if err != nil || client.Model() != DefaultModel {
		t.Fatal("absent model did not use default", err)
	}
	t.Setenv("LLM_MODEL", "moonshotai/kimi-k2.6")
	client, err = NewFromEnv()
	if err != nil || client.Model() != "moonshotai/kimi-k2.6" {
		t.Fatal("environment model not selected", err)
	}
	for _, model := range []string{"", "invented"} {
		t.Setenv("LLM_MODEL", model)
		if _, err := NewFromEnv(); err == nil {
			t.Fatal("invalid env model accepted")
		}
	}
	t.Setenv("LLM_MODEL", DefaultModel)
	t.Setenv("LLM_API_KEY", "")
	if _, err := NewFromEnv(); err == nil {
		t.Fatal("empty key accepted")
	}
}

func TestAmbientOpenAISettingsAreIgnored(t *testing.T) {
	for name, value := range map[string]string{
		"OPENAI_BASE_URL": "https://invalid.example/v1", "OPENAI_API_KEY": "sk-do-not-use", "OPENAI_ADMIN_KEY": "sk-admin-do-not-use",
		"OPENAI_ORG_ID": "org-do-not-use", "OPENAI_PROJECT_ID": "project-do-not-use", "OPENAI_CUSTOM_HEADERS": "Authorization: Bearer do-not-use\nX-Unwanted: true",
	} {
		t.Setenv(name, value)
	}
	client := fixtureClient(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("OpenAI-Organization") != "" || r.Header.Get("OpenAI-Project") != "" || r.Header.Get("X-Unwanted") != "" {
			t.Fatal("inherited ambient SDK headers")
		}
		writeCompletion(w, "")
	})
	if _, err := client.Chat(t.Context(), chatParams()); err != nil {
		t.Fatal(err)
	}
}

func TestProviderErrorsArePreservedWithoutRetries(t *testing.T) {
	for _, status := range []int{400, 401, 403, 408, 409, 429, 500, 503} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			calls := 0
			client := fixtureClient(t, func(w http.ResponseWriter, _ *http.Request) {
				calls++
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(status)
				_, _ = io.WriteString(w, `{"error":{"message":"Budget has been exceeded sk-do-not-log","type":"budget_error","code":"budget_exceeded"}}`)
			})
			_, err := client.Chat(t.Context(), chatParams())
			var apiErr *openai.Error
			if !errors.As(err, &apiErr) || apiErr.StatusCode != status || apiErr.Code != "budget_exceeded" || !strings.Contains(apiErr.Message, "Budget has been exceeded") || !strings.Contains(apiErr.RawJSON(), "budget_error") || calls != 1 {
				t.Fatalf("error lost or retried (calls=%d): %v", calls, err)
			}
			if strings.Contains(err.Error(), "sk-do-not-log") {
				t.Fatal("routine API error formatting exposed provider text")
			}
		})
	}
}

func TestMalformedJSONAndRedirectsAreNotReplayed(t *testing.T) {
	for _, kind := range []string{"json", "redirect", "plain error"} {
		t.Run(kind, func(t *testing.T) {
			calls := 0
			client := fixtureClient(t, func(w http.ResponseWriter, _ *http.Request) {
				calls++
				switch kind {
				case "json":
					w.Header().Set("Content-Type", "application/json")
					_, _ = io.WriteString(w, "{")
				case "redirect":
					w.Header().Set("Location", "https://invalid.example/v1/chat/completions")
					w.WriteHeader(http.StatusTemporaryRedirect)
				case "plain error":
					w.WriteHeader(http.StatusForbidden)
					_, _ = io.WriteString(w, "Budget has been exceeded")
				}
			})
			_, err := client.Chat(t.Context(), chatParams())
			if err == nil || calls != 1 {
				t.Fatalf("unexpected success/replay (calls=%d): %v", calls, err)
			}
			if kind == "plain error" {
				var apiErr *openai.Error
				if !errors.As(err, &apiErr) || apiErr.StatusCode != http.StatusForbidden {
					t.Fatal("lost plain-error status", err)
				}
				body, readErr := io.ReadAll(apiErr.Response.Body)
				_ = apiErr.Response.Body.Close()
				if readErr != nil || string(body) != "Budget has been exceeded" {
					t.Fatal("lost raw error body", readErr)
				}
			}
		})
	}
}

func TestCancellationAndTransportFailure(t *testing.T) {
	var calls atomic.Int32
	started := make(chan struct{})
	client, err := newClient("sk-fixture-only", "", fixtureTransport(func(r *http.Request) (*http.Response, error) {
		calls.Add(1)
		close(started)
		<-r.Context().Done()
		return nil, r.Context().Err()
	}))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	done := make(chan error, 1)
	go func() { _, err := client.Chat(ctx, chatParams()); done <- err }()
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("request never started")
	}
	cancel()
	select {
	case err := <-done:
		if !errors.Is(err, context.Canceled) || calls.Load() != 1 {
			t.Fatal("cancellation lost/retried", err)
		}
	case <-time.After(time.Second):
		t.Fatal("request ignored cancellation")
	}
	if _, err := client.Chat(ctx, chatParams()); !errors.Is(err, context.Canceled) || calls.Load() != 1 {
		t.Fatal("cancelled request reached transport", err)
	}
	transportErr := errors.New("fixture transport unavailable")
	client, err = newClient("sk-fixture-only", "", fixtureTransport(func(*http.Request) (*http.Response, error) { calls.Add(1); return nil, transportErr }))
	if err != nil {
		t.Fatal(err)
	}
	_, err = client.Chat(t.Context(), chatParams())
	if !errors.Is(err, transportErr) || calls.Load() != 2 {
		t.Fatal("transport error lost/retried", err)
	}
}
