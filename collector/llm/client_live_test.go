package llm

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/joho/godotenv"
	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/packages/respjson"
	"github.com/openai/openai-go/v3/shared"
)

func TestLiveClient(t *testing.T) {
	if os.Getenv("LIVE_LLM_TEST") != "1" {
		t.Skip("set LIVE_LLM_TEST=1 for up to three real approved LLM requests")
	}
	if path := os.Getenv("ENV_FILE"); path != "" {
		if err := godotenv.Load(path); err != nil {
			t.Fatal("cannot load live-test ENV_FILE")
		}
	}
	client, err := NewFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	check := func(t *testing.T, label string, err error) {
		t.Helper()
		if err != nil {
			var apiErr *openai.Error
			if errors.As(err, &apiErr) {
				t.Fatalf("%s failed: HTTP %d (provider body omitted)", label, apiErr.StatusCode)
			}
			t.Fatalf("%s failed: %T (raw diagnostic omitted)", label, err)
		}
	}
	chat := func(t *testing.T, label string, params openai.ChatCompletionNewParams) *openai.ChatCompletion {
		t.Helper()
		ctx, cancel := context.WithTimeout(t.Context(), 2*time.Minute)
		defer cancel()
		t.Logf("model=%s request=%s starting (no retries)", client.Model(), label)
		reply, err := client.Chat(ctx, params)
		check(t, label, err)
		if reply.JSON.Usage.Valid() {
			logLiveUsage(t, label, reply.Usage)
		} else {
			t.Logf("request=%s usage=unknown", label)
		}
		return reply
	}
	if !t.Run("tools", func(t *testing.T) {
		params := openai.ChatCompletionNewParams{
			Messages: []openai.ChatCompletionMessageParamUnion{openai.UserMessage("Use add to calculate 2 + 3, then reply with only the resulting integer.")},
			Tools: []openai.ChatCompletionToolUnionParam{openai.ChatCompletionFunctionTool(shared.FunctionDefinitionParam{
				Name: "add", Parameters: shared.FunctionParameters{
					"type": "object", "properties": map[string]any{"a": map[string]string{"type": "integer"}, "b": map[string]string{"type": "integer"}},
					"required": []string{"a", "b"}, "additionalProperties": false,
				},
			})},
			ToolChoice: openai.ToolChoiceOptionFunctionToolChoice(openai.ChatCompletionNamedToolChoiceFunctionParam{Name: "add"}),
		}
		reply := chat(t, "tool_call", params)
		if len(reply.Choices) != 1 || reply.Choices[0].FinishReason != "tool_calls" || len(reply.Choices[0].Message.ToolCalls) != 1 {
			t.Fatal("expected one completed function call")
		}
		call := reply.Choices[0].Message.ToolCalls[0].AsFunction()
		var args map[string]int
		if call.ID == "" || call.Function.Name != "add" || json.Unmarshal([]byte(call.Function.Arguments), &args) != nil || len(args) != 2 || args["a"] != 2 || args["b"] != 3 {
			t.Fatal("unexpected function name or arguments; no tool executed")
		}
		params.Messages = append(params.Messages, reply.Choices[0].Message.ToParam(), openai.ToolMessage(strconv.Itoa(args["a"]+args["b"]), call.ID))
		params.ToolChoice = openai.ChatCompletionToolChoiceOptionUnionParam{OfAuto: openai.String("none")}
		reply = chat(t, "tool_result", params)
		if len(reply.Choices) != 1 || reply.Choices[0].FinishReason != "stop" || len(reply.Choices[0].Message.ToolCalls) != 0 || strings.TrimSpace(reply.Choices[0].Message.Content) != "5" {
			t.Fatal("tool-result continuation did not produce the final answer")
		}
	}) {
		return
	}

	t.Run("stream", func(t *testing.T) {
		ctx, cancel := context.WithTimeout(t.Context(), 2*time.Minute)
		defer cancel()
		t.Logf("model=%s request=stream starting (no retries)", client.Model())
		stream, err := client.ChatStream(ctx, openai.ChatCompletionNewParams{
			Messages:      []openai.ChatCompletionMessageParamUnion{openai.UserMessage("Reply with exactly STREAM_OK and no other text.")},
			StreamOptions: openai.ChatCompletionStreamOptionsParam{IncludeUsage: openai.Bool(true)},
		})
		check(t, "stream", err)
		defer func() { _ = stream.Close() }()
		var accumulator openai.ChatCompletionAccumulator
		var usage *openai.CompletionUsage
		finishReason := ""
		chunks := 0
		for stream.Next() {
			chunk := stream.Current()
			chunks++
			if !accumulator.AddChunk(chunk) {
				t.Fatal("incompatible stream chunk")
			}
			if chunk.JSON.Usage.Valid() {
				usage = &chunk.Usage
			}
			for _, choice := range chunk.Choices {
				if choice.Index == 0 && choice.FinishReason != "" {
					finishReason = choice.FinishReason
				}
			}
		}
		if usage == nil {
			t.Log("request=stream usage=unknown")
		} else {
			logLiveUsage(t, "stream", *usage)
		}
		check(t, "stream read", stream.Err())
		t.Logf("stream chunks=%d choices=%d finish=%q", chunks, len(accumulator.Choices), finishReason)
		if len(accumulator.Choices) != 1 || finishReason != "stop" || len(accumulator.Choices[0].Message.ToolCalls) != 0 || strings.TrimSpace(accumulator.Choices[0].Message.Content) != "STREAM_OK" {
			t.Fatal("stream did not produce a complete final answer")
		}
		t.Logf("requests=1 chunks=%d stream=ok", chunks)
	})
}

func logLiveUsage(t *testing.T, label string, usage openai.CompletionUsage) {
	t.Helper()
	count := func(field respjson.Field, n int64) any {
		if !field.Valid() {
			return "unknown"
		}
		return n
	}
	t.Logf("request=%s prompt_tokens=%v completion_tokens=%v total_tokens=%v", label,
		count(usage.JSON.PromptTokens, usage.PromptTokens), count(usage.JSON.CompletionTokens, usage.CompletionTokens), count(usage.JSON.TotalTokens, usage.TotalTokens))
}
