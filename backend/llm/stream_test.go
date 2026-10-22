package llm

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/packages/ssestream"
	"github.com/openai/openai-go/v3/shared"
)

func writeChunk(w io.Writer, choices, extra string) {
	_, _ = fmt.Fprintf(w, "data: {\"id\":\"stream-fixture\",\"object\":\"chat.completion.chunk\",\"created\":1,\"model\":%q,\"choices\":%s%s}\n\n", DefaultModel, choices, extra)
}

const firstChoice = `[{"index":0,"delta":{"content":"partial"},"finish_reason":null}]`

func TestChatStreamFragmentsAndTools(t *testing.T) {
	calls := 0
	client := fixtureClient(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		var body struct {
			Model         string
			Stream        bool
			StreamOptions struct {
				IncludeUsage bool `json:"include_usage"`
			} `json:"stream_options"`
			Messages []json.RawMessage
			Tools    []json.RawMessage
		}
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Model != DefaultModel || !body.Stream || !body.StreamOptions.IncludeUsage || len(body.Messages) != 1 || len(body.Tools) != 1 {
			t.Fatalf("wrong streaming request: %+v (%v)", body, err)
		}
		w.Header().Set("Content-Type", "text/event-stream; charset=utf-8")
		for _, choices := range []string{
			`[{"index":0,"delta":{"role":"assistant","content":"Oil "},"finish_reason":null}]`,
			`[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"lookup_","arguments":"{\"tag"}}]},"finish_reason":null}]`,
			`[{"index":0,"delta":{"tool_calls":[{"index":1,"id":"call_2","type":"function","function":{"name":"lookup_source","arguments":"{\"source\":"}}]},"finish_reason":null}]`,
			`[{"index":0,"delta":{"content":"prices"},"finish_reason":null}]`,
			`[{"index":0,"delta":{"tool_calls":[{"index":0,"function":{"name":"news","arguments":"_id\":\"resource:oil\"}"}}]},"finish_reason":null}]`,
			`[{"index":0,"delta":{"tool_calls":[{"index":1,"function":{"arguments":"\"rbc\"}"}}]},"finish_reason":null}]`,
			`[{"index":0,"delta":{},"finish_reason":"tool_calls"}]`,
		} {
			writeChunk(w, choices, `,"usage":null`)
		}
		writeChunk(w, `[]`, `,"usage":{"prompt_tokens":7,"completion_tokens":8,"total_tokens":15}`)
		_, _ = io.WriteString(w, "data: [DONE]\n\n")
	})
	params := chatParams()
	params.StreamOptions = openai.ChatCompletionStreamOptionsParam{IncludeUsage: openai.Bool(true)}
	params.Tools = []openai.ChatCompletionToolUnionParam{openai.ChatCompletionFunctionTool(shared.FunctionDefinitionParam{Name: "lookup_news"})}
	stream, err := client.ChatStream(t.Context(), params)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = stream.Close() }()
	var accumulator openai.ChatCompletionAccumulator
	var usage *openai.CompletionUsage
	chunks, toolFragments := 0, 0
	for stream.Next() {
		chunk := stream.Current()
		chunks++
		if !strings.Contains(chunk.RawJSON(), `"id":"stream-fixture"`) || !accumulator.AddChunk(chunk) {
			t.Fatal("lost raw chunk or accumulator compatibility")
		}
		if chunk.JSON.Usage.Valid() {
			if len(chunk.Choices) != 0 {
				t.Fatal("usage-only chunk lost its empty choices")
			}
			usage = &chunk.Usage
		}
		for _, choice := range chunk.Choices {
			toolFragments += len(choice.Delta.ToolCalls)
		}
	}
	if err := stream.Err(); err != nil {
		t.Fatal(err)
	}
	if calls != 1 || chunks != 8 || toolFragments != 4 || usage == nil || !usage.JSON.TotalTokens.Valid() || usage.TotalTokens != 15 {
		t.Fatal("chunks, usage or single-request guarantee lost")
	}
	message := accumulator.Choices[0].Message
	if message.Content != "Oil prices" || accumulator.Choices[0].FinishReason != "tool_calls" || len(message.ToolCalls) != 2 {
		t.Fatalf("text/tool accumulation failed: %+v", message)
	}
	first, second := message.ToolCalls[0], message.ToolCalls[1]
	if first.ID != "call_1" || first.Function.Name != "lookup_news" || first.Function.Arguments != `{"tag_id":"resource:oil"}` || second.ID != "call_2" || second.Function.Arguments != `{"source":"rbc"}` {
		t.Fatalf("interleaved tool indexes or argument fragments lost: first=%+v second=%+v accumulated=%+v", first, second, message.ToolCalls)
	}
	if params.Model != "" {
		t.Fatal("streaming mutated caller parameters")
	}
}

func TestChatStreamUsagePresenceAndCleanEOF(t *testing.T) {
	for _, tt := range []struct {
		name, extra                      string
		usage, prompt, completion, total bool
	}{
		{"absent", "", false, false, false, false},
		{"null", `,"usage":null`, false, false, false, false},
		{"empty", `,"usage":{}`, true, false, false, false},
		{"partial", `,"usage":{"prompt_tokens":2,"total_tokens":null}`, true, true, false, false},
		{"zero", `,"usage":{"prompt_tokens":0,"completion_tokens":0,"total_tokens":0}`, true, true, true, true},
	} {
		t.Run(tt.name, func(t *testing.T) {
			client := fixtureClient(t, func(w http.ResponseWriter, _ *http.Request) {
				w.Header().Set("Content-Type", "text/event-stream")
				writeChunk(w, firstChoice, tt.extra)
				// No [DONE] or finish_reason: a clean EOF is not proof of a complete answer.
			})
			stream, err := client.ChatStream(t.Context(), chatParams())
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = stream.Close() }()
			if !stream.Next() {
				t.Fatal("lost partial chunk", stream.Err())
			}
			chunk := stream.Current()
			if chunk.Choices[0].FinishReason != "" || chunk.JSON.Usage.Valid() != tt.usage || chunk.Usage.JSON.PromptTokens.Valid() != tt.prompt || chunk.Usage.JSON.CompletionTokens.Valid() != tt.completion || chunk.Usage.JSON.TotalTokens.Valid() != tt.total {
				t.Fatal("presence or unfinished state lost")
			}
			if stream.Next() || stream.Err() != nil {
				t.Fatal("SDK clean-EOF behavior changed", stream.Err())
			}
		})
	}
}

func TestChatStreamHTTPAndEventErrors(t *testing.T) {
	for _, status := range []int{400, 429, 503} {
		t.Run(fmt.Sprint(status), func(t *testing.T) {
			calls := 0
			client := fixtureClient(t, func(w http.ResponseWriter, _ *http.Request) {
				calls++
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(status)
				_, _ = io.WriteString(w, `{"error":{"message":"Budget has been exceeded","code":"budget_exceeded"}}`)
			})
			stream, err := client.ChatStream(t.Context(), chatParams())
			var apiErr *openai.Error
			if stream != nil || !errors.As(err, &apiErr) || apiErr.StatusCode != status || apiErr.Code != "budget_exceeded" || apiErr.Message != "Budget has been exceeded" || calls != 1 {
				t.Fatal("startup error lost or retried", err)
			}
		})
	}
	for _, event := range []string{`{"error":{"message":"Budget has been exceeded"}}`, `{malformed`} {
		t.Run(event, func(t *testing.T) {
			calls := 0
			client := fixtureClient(t, func(w http.ResponseWriter, _ *http.Request) {
				calls++
				w.Header().Set("Content-Type", "text/event-stream")
				writeChunk(w, firstChoice, "")
				_, _ = fmt.Fprintf(w, "data: %s\n\n", event)
			})
			stream, err := client.ChatStream(t.Context(), chatParams())
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = stream.Close() }()
			if !stream.Next() || stream.Current().Choices[0].Delta.Content != "partial" {
				t.Fatal("lost partial output")
			}
			if stream.Next() || stream.Err() == nil || calls != 1 {
				t.Fatal("event error lost or request replayed")
			}
			if strings.HasPrefix(event, `{"error"`) {
				var streamErr *ssestream.StreamError
				if !errors.As(stream.Err(), &streamErr) || !strings.Contains(string(streamErr.Event.Data), "Budget has been exceeded") {
					t.Fatal("lost structured SSE error", stream.Err())
				}
			}
		})
	}
}

type failingReader struct{ err error }

func (r failingReader) Read([]byte) (int, error) { return 0, r.err }

type countedBody struct {
	io.ReadCloser
	closes atomic.Int32
}

func (b *countedBody) Close() error { b.closes.Add(1); return b.ReadCloser.Close() }

func streamResponse(r *http.Request, body io.ReadCloser) *http.Response {
	return &http.Response{StatusCode: http.StatusOK, Header: http.Header{"Content-Type": {"text/event-stream"}}, Body: body, Request: r}
}

func TestChatStreamTransportInterruption(t *testing.T) {
	var first strings.Builder
	writeChunk(&first, firstChoice, "")
	body := &countedBody{ReadCloser: io.NopCloser(io.MultiReader(strings.NewReader(first.String()), failingReader{io.ErrUnexpectedEOF}))}
	calls := 0
	client, err := newClient("sk-fixture-only", "", fixtureTransport(func(r *http.Request) (*http.Response, error) {
		calls++
		return streamResponse(r, body), nil
	}))
	if err != nil {
		t.Fatal(err)
	}
	stream, err := client.ChatStream(t.Context(), chatParams())
	if err != nil {
		t.Fatal(err)
	}
	if !stream.Next() || stream.Current().JSON.Usage.Valid() {
		t.Fatal("lost partial data or invented usage")
	}
	if stream.Next() || !errors.Is(stream.Err(), io.ErrUnexpectedEOF) || calls != 1 || body.closes.Load() != 1 {
		t.Fatal("transport error lost/retried or body leaked", stream.Err())
	}
	if err := stream.Close(); err != nil || body.closes.Load() != 1 {
		t.Fatal("close is not idempotent", err)
	}
}

func TestChatStreamCancellationAndEarlyClose(t *testing.T) {
	for _, earlyClose := range []bool{false, true} {
		t.Run(fmt.Sprint(earlyClose), func(t *testing.T) {
			ctx, cancel := context.WithCancel(t.Context())
			defer cancel()
			reader, writer := io.Pipe()
			t.Cleanup(func() { _ = reader.Close(); _ = writer.Close() })
			body := &countedBody{ReadCloser: reader}
			calls := 0
			client, err := newClient("sk-fixture-only", "", fixtureTransport(func(r *http.Request) (*http.Response, error) { calls++; return streamResponse(r, body), nil }))
			if err != nil {
				t.Fatal(err)
			}
			writerDone := make(chan struct{})
			go func() {
				defer close(writerDone)
				writeChunk(writer, firstChoice, "")
				<-ctx.Done()
				_ = writer.CloseWithError(ctx.Err())
			}()
			stream, err := client.ChatStream(ctx, chatParams())
			if err != nil {
				t.Fatal(err)
			}
			defer func() { _ = stream.Close() }()
			if !stream.Next() {
				t.Fatal("missing initial chunk", stream.Err())
			}
			if earlyClose {
				if err := stream.Close(); err != nil || stream.Next() {
					t.Fatal("early close did not stop iteration", err)
				}
				cancel()
			} else {
				done := make(chan bool, 1)
				go func() { done <- stream.Next() }()
				cancel()
				select {
				case next := <-done:
					if next || !errors.Is(stream.Err(), context.Canceled) {
						t.Fatal("read ignored cancellation", stream.Err())
					}
				case <-time.After(time.Second):
					t.Fatal("cancelled read never returned")
				}
			}
			select {
			case <-writerDone:
			case <-time.After(time.Second):
				t.Fatal("fixture writer leaked")
			}
			if calls != 1 || body.closes.Load() != 1 {
				t.Fatal("request replayed or body leaked")
			}
		})
	}
}

func TestChatStreamDeadlineAndStartupTransportFailure(t *testing.T) {
	var calls atomic.Int32
	transportErr := errors.New("fixture connection unavailable")
	client, err := newClient("sk-fixture-only", "", fixtureTransport(func(*http.Request) (*http.Response, error) {
		calls.Add(1)
		return nil, transportErr
	}))
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithDeadline(t.Context(), time.Unix(1, 0))
	defer cancel()
	if stream, err := client.ChatStream(ctx, chatParams()); stream != nil || !errors.Is(err, context.DeadlineExceeded) || calls.Load() != 0 {
		t.Fatal("expired deadline reached transport", err)
	}
	if stream, err := client.ChatStream(t.Context(), chatParams()); stream != nil || !errors.Is(err, transportErr) || calls.Load() != 1 {
		t.Fatal("startup transport error lost or retried", err)
	}
}
