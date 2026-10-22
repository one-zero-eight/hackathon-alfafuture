// Package llm provides Chat Completions through the organizer-approved gateway.
package llm

import (
	"context"
	"errors"
	"net/http"
	"os"
	"strings"

	"github.com/openai/openai-go/v3"
	"github.com/openai/openai-go/v3/option"
	"github.com/openai/openai-go/v3/packages/ssestream"
)

const (
	BaseURL      = "https://changellenge.up.railway.app/v1/"
	DefaultModel = "deepseek/deepseek-v4.1-flash"
)

type Client struct {
	chat  openai.ChatCompletionService
	model string
}

// New creates a client without making a request. An empty model selects DefaultModel.
func New(apiKey, model string) (*Client, error) {
	return newClient(apiKey, model, http.DefaultTransport)
}

// NewFromEnv reads LLM_API_KEY and LLM_MODEL after the caller has loaded its environment.
// Only an absent LLM_MODEL uses the default; an explicitly empty value is invalid.
func NewFromEnv() (*Client, error) {
	model, exists := os.LookupEnv("LLM_MODEL")
	if exists && model == "" {
		return nil, errors.New("LLM_MODEL must be an organizer-approved model ID")
	}
	return New(os.Getenv("LLM_API_KEY"), model)
}

func newClient(apiKey, model string, transport http.RoundTripper) (*Client, error) {
	if apiKey == "" || strings.IndexFunc(apiKey, func(r rune) bool { return r < 33 || r > 126 }) >= 0 {
		return nil, errors.New("LLM_API_KEY must be a nonempty token without whitespace or control characters")
	}
	if model == "" {
		model = DefaultModel
	}
	if !allowedModel(model) {
		return nil, errors.New("LLM_MODEL must be an organizer-approved model ID")
	}
	httpClient := &http.Client{
		Transport:     transport,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	// The service constructor avoids NewClient's ambient OPENAI_* configuration.
	chat := openai.NewChatCompletionService(
		option.WithAPIKey(apiKey), option.WithBaseURL(BaseURL),
		option.WithHTTPClient(httpClient), option.WithMaxRetries(0),
	)
	return &Client{chat: chat, model: model}, nil
}

// Model returns the configured default for request construction and traceability.
func (c *Client) Model() string { return c.model }

// Chat makes one request; tools, retries and conversation history belong to the caller.
// Usage presence is exposed by the SDK's JSON.Usage and per-counter JSON metadata.
func (c *Client) Chat(ctx context.Context, params openai.ChatCompletionNewParams) (*openai.ChatCompletion, error) {
	params, err := c.prepare(ctx, params)
	if err != nil {
		return nil, err
	}
	return c.chat.New(ctx, params)
}

// ChatStream starts one request; the caller reads Next/Current, checks Err and closes it.
// Request usage through params.StreamOptions; missing usage must remain unknown.
func (c *Client) ChatStream(ctx context.Context, params openai.ChatCompletionNewParams) (*ssestream.Stream[openai.ChatCompletionChunk], error) {
	params, err := c.prepare(ctx, params)
	if err != nil {
		return nil, err
	}
	stream := c.chat.NewStreaming(ctx, params)
	if err := stream.Err(); err != nil {
		_ = stream.Close()
		return nil, err
	}
	// shortcut: SDK accepts EOF without [DONE], add strict termination checks if callers need proof beyond finish_reason.
	return stream, nil
}

func (c *Client) prepare(ctx context.Context, params openai.ChatCompletionNewParams) (openai.ChatCompletionNewParams, error) {
	if err := ctx.Err(); err != nil {
		return params, err
	}
	if _, overridden := params.Overrides(); overridden {
		return params, errors.New("raw request overrides cannot bypass model validation")
	}
	for _, name := range []string{"model", "stream"} {
		if _, exists := params.ExtraFields()[name]; exists {
			return params, errors.New("model and stream must not be overridden through extra fields")
		}
	}
	if params.Model == "" {
		params.Model = c.model
	}
	if !allowedModel(params.Model) {
		return params, errors.New("request model must be an organizer-approved model ID")
	}
	if len(params.Messages) == 0 {
		return params, errors.New("chat requires at least one message")
	}
	return params, nil
}

func allowedModel(model string) bool {
	switch model {
	case "google/gemma-4-26b-a4b-it", "z-ai/glm-5.3-flash", "qwen/qwen3.6-35b-a3b",
		DefaultModel, "qwen/qwen3-vl-30b-a3b-instruct", "moonshotai/kimi-k2.6":
		return true
	default:
		return false
	}
}
