package service

import (
	"bytes"
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/Wei-Shaw/sub2api/internal/config"
	"github.com/Wei-Shaw/sub2api/internal/domain"
	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/require"
	"github.com/tidwall/gjson"
)

func TestGatewayService_Forward_OpenAICompatProviderModelAndToolChoice(t *testing.T) {
	gin.SetMode(gin.TestMode)

	rec := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(rec)
	c.Request = httptest.NewRequest(http.MethodPost, "/v1/messages", bytes.NewReader(nil))

	body := []byte(`{
		"model":"openai/gpt-5.3",
		"stream":false,
		"max_tokens":128,
		"tool_choice":{"type":"tool","name":"Read"},
		"tools":[{"name":"Read","description":"read file","input_schema":{"type":"object"}}],
		"messages":[
			{"role":"user","content":[
				{"type":"text","text":"hello"},
				{"type":"image","source":{"type":"url","url":"https://example.com/a.png"}}
			]}
		]
	}`)

	parsed, err := ParseGatewayRequest(body, domain.PlatformAnthropic)
	require.NoError(t, err)

	upstream := &httpUpstreamRecorder{
		resp: &http.Response{
			StatusCode: http.StatusOK,
			Header:     http.Header{"Content-Type": []string{"application/json"}, "x-request-id": []string{"rid-openai-compat"}},
			Body:       io.NopCloser(strings.NewReader(`{"id":"resp_1","output_text":"ok","usage":{"input_tokens":11,"output_tokens":7,"input_tokens_details":{"cached_tokens":2}}}`)),
		},
	}

	svc := &GatewayService{
		httpUpstream: upstream,
		cfg: &config.Config{
			Security: config.SecurityConfig{URLAllowlist: config.URLAllowlistConfig{Enabled: false}},
		},
	}
	account := &Account{
		ID:             11,
		Name:           "openai-apikey",
		Platform:       PlatformOpenAI,
		Type:           AccountTypeAPIKey,
		Concurrency:    1,
		Credentials:    map[string]any{"api_key": "sk-test", "base_url": "https://api.openai.com"},
		Status:         StatusActive,
		Schedulable:    true,
		RateMultiplier: f64p(1),
	}

	result, err := svc.Forward(context.Background(), c, account, parsed)
	require.NoError(t, err)
	require.NotNil(t, result)
	require.Equal(t, "openai/gpt-5.3", result.Model)
	require.False(t, result.Stream)
	require.Equal(t, 11, result.Usage.InputTokens)
	require.Equal(t, 7, result.Usage.OutputTokens)
	require.Equal(t, 2, result.Usage.CacheReadInputTokens)

	require.NotNil(t, upstream.lastReq)
	require.Equal(t, "https://api.openai.com/v1/responses", upstream.lastReq.URL.String())
	require.Equal(t, "Bearer sk-test", upstream.lastReq.Header.Get("authorization"))

	require.Equal(t, "gpt-5.3-codex", gjson.GetBytes(upstream.lastBody, "model").String())
	require.Equal(t, "function", gjson.GetBytes(upstream.lastBody, "tool_choice.type").String())
	require.Equal(t, "Read", gjson.GetBytes(upstream.lastBody, "tool_choice.name").String())
	require.Equal(t, "input_text", gjson.GetBytes(upstream.lastBody, "input.0.content.0.type").String())
	require.Equal(t, "input_image", gjson.GetBytes(upstream.lastBody, "input.0.content.1.type").String())

	respJSON := rec.Body.Bytes()
	require.Equal(t, "openai/gpt-5.3", gjson.GetBytes(respJSON, "model").String())
	require.Equal(t, "text", gjson.GetBytes(respJSON, "content.0.type").String())
	require.Equal(t, "ok", gjson.GetBytes(respJSON, "content.0.text").String())
}

func TestGatewayService_Forward_OpenAICompatStreamNoDuplicateToolUse(t *testing.T) {
	gin.SetMode(gin.TestMode)

	rec := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(rec)
	c.Request = httptest.NewRequest(http.MethodPost, "/v1/messages", bytes.NewReader(nil))

	body := []byte(`{
		"model":"openai/gpt-5.3",
		"stream":true,
		"max_tokens":64,
		"messages":[{"role":"user","content":[{"type":"text","text":"call tool"}]}]
	}`)

	parsed, err := ParseGatewayRequest(body, domain.PlatformAnthropic)
	require.NoError(t, err)

	upstreamSSE := strings.Join([]string{
		`data: {"type":"response.output_item.added","item":{"type":"function_call","id":"fc_1","call_id":"call_1","name":"Read","arguments":"{\"path\":\"README.md\"}"}}`,
		"",
		`data: {"type":"response.output_item.done","item":{"type":"function_call","id":"fc_1","call_id":"call_1","name":"Read","arguments":"{\"path\":\"README.md\"}"}}`,
		"",
		`data: {"type":"response.completed","response":{"usage":{"input_tokens":5,"output_tokens":3}}}`,
		"",
	}, "\n")

	upstream := &httpUpstreamRecorder{
		resp: &http.Response{
			StatusCode: http.StatusOK,
			Header:     http.Header{"Content-Type": []string{"text/event-stream"}, "x-request-id": []string{"rid-openai-stream"}},
			Body:       io.NopCloser(strings.NewReader(upstreamSSE)),
		},
	}

	svc := &GatewayService{
		httpUpstream: upstream,
		cfg: &config.Config{
			Security: config.SecurityConfig{URLAllowlist: config.URLAllowlistConfig{Enabled: false}},
		},
	}
	account := &Account{
		ID:             12,
		Name:           "openai-apikey",
		Platform:       PlatformOpenAI,
		Type:           AccountTypeAPIKey,
		Concurrency:    1,
		Credentials:    map[string]any{"api_key": "sk-test", "base_url": "https://api.openai.com"},
		Status:         StatusActive,
		Schedulable:    true,
		RateMultiplier: f64p(1),
	}

	result, err := svc.Forward(context.Background(), c, account, parsed)
	require.NoError(t, err)
	require.NotNil(t, result)
	require.True(t, result.Stream)
	require.Equal(t, 5, result.Usage.InputTokens)
	require.Equal(t, 3, result.Usage.OutputTokens)

	streamBody := rec.Body.String()
	require.Equal(t, 1, strings.Count(streamBody, `"type":"tool_use"`), "tool_use block should be emitted once")
	require.Contains(t, streamBody, `"name":"Read"`)
	require.Contains(t, streamBody, `"stop_reason":"tool_use"`)
}

func TestGatewayService_Forward_OpenAICompatStream_FunctionCallArgumentsDeltaToInputJsonDelta(t *testing.T) {
	gin.SetMode(gin.TestMode)

	rec := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(rec)
	c.Request = httptest.NewRequest(http.MethodPost, "/v1/messages", bytes.NewReader(nil))

	body := []byte(`{
		"model":"openai/gpt-5.3",
		"stream":true,
		"max_tokens":64,
		"messages":[{"role":"user","content":[{"type":"text","text":"call tool with delta"}]}]
	}`)

	parsed, err := ParseGatewayRequest(body, domain.PlatformAnthropic)
	require.NoError(t, err)

	upstreamSSE := strings.Join([]string{
		`data: {"type":"response.output_item.added","item":{"type":"function_call","id":"fc_delta","call_id":"call_delta","name":"Read"}}`,
		"",
		`data: {"type":"response.function_call_arguments.delta","item_id":"fc_delta","call_id":"call_delta","delta":"{\"path\":\"REA"}`,
		"",
		`data: {"type":"response.function_call_arguments.delta","item_id":"fc_delta","call_id":"call_delta","delta":"DME.md\"}"}`,
		"",
		`data: {"type":"response.output_item.done","item":{"type":"function_call","id":"fc_delta","call_id":"call_delta","name":"Read","arguments":"{\"path\":\"README.md\"}"}}`,
		"",
		`data: {"type":"response.completed","response":{"usage":{"input_tokens":6,"output_tokens":4}}}`,
		"",
	}, "\n")

	upstream := &httpUpstreamRecorder{
		resp: &http.Response{
			StatusCode: http.StatusOK,
			Header:     http.Header{"Content-Type": []string{"text/event-stream"}, "x-request-id": []string{"rid-openai-delta"}},
			Body:       io.NopCloser(strings.NewReader(upstreamSSE)),
		},
	}

	svc := &GatewayService{
		httpUpstream: upstream,
		cfg: &config.Config{
			Security: config.SecurityConfig{URLAllowlist: config.URLAllowlistConfig{Enabled: false}},
		},
	}
	account := &Account{
		ID:             13,
		Name:           "openai-apikey",
		Platform:       PlatformOpenAI,
		Type:           AccountTypeAPIKey,
		Concurrency:    1,
		Credentials:    map[string]any{"api_key": "sk-test", "base_url": "https://api.openai.com"},
		Status:         StatusActive,
		Schedulable:    true,
		RateMultiplier: f64p(1),
	}

	result, err := svc.Forward(context.Background(), c, account, parsed)
	require.NoError(t, err)
	require.NotNil(t, result)
	require.True(t, result.Stream)
	require.Equal(t, 6, result.Usage.InputTokens)
	require.Equal(t, 4, result.Usage.OutputTokens)

	streamBody := rec.Body.String()
	require.Equal(t, 1, strings.Count(streamBody, `"type":"tool_use"`))
	require.Equal(t, 2, strings.Count(streamBody, `"type":"input_json_delta"`))
}

func TestGatewayService_Forward_OpenAICompatStream_RefusalDeltaAsText(t *testing.T) {
	gin.SetMode(gin.TestMode)

	rec := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(rec)
	c.Request = httptest.NewRequest(http.MethodPost, "/v1/messages", bytes.NewReader(nil))

	body := []byte(`{
		"model":"openai/gpt-5.3",
		"stream":true,
		"max_tokens":64,
		"messages":[{"role":"user","content":[{"type":"text","text":"unsafe ask"}]}]
	}`)

	parsed, err := ParseGatewayRequest(body, domain.PlatformAnthropic)
	require.NoError(t, err)

	upstreamSSE := strings.Join([]string{
		`data: {"type":"response.refusal.delta","delta":"I cannot"}`,
		"",
		`data: {"type":"response.refusal.delta","delta":" comply."}`,
		"",
		`data: {"type":"response.completed","response":{"usage":{"input_tokens":4,"output_tokens":2}}}`,
		"",
	}, "\n")

	upstream := &httpUpstreamRecorder{
		resp: &http.Response{
			StatusCode: http.StatusOK,
			Header:     http.Header{"Content-Type": []string{"text/event-stream"}, "x-request-id": []string{"rid-openai-refusal"}},
			Body:       io.NopCloser(strings.NewReader(upstreamSSE)),
		},
	}

	svc := &GatewayService{
		httpUpstream: upstream,
		cfg: &config.Config{
			Security: config.SecurityConfig{URLAllowlist: config.URLAllowlistConfig{Enabled: false}},
		},
	}
	account := &Account{
		ID:             14,
		Name:           "openai-apikey",
		Platform:       PlatformOpenAI,
		Type:           AccountTypeAPIKey,
		Concurrency:    1,
		Credentials:    map[string]any{"api_key": "sk-test", "base_url": "https://api.openai.com"},
		Status:         StatusActive,
		Schedulable:    true,
		RateMultiplier: f64p(1),
	}

	result, err := svc.Forward(context.Background(), c, account, parsed)
	require.NoError(t, err)
	require.NotNil(t, result)
	require.True(t, result.Stream)
	require.Equal(t, 4, result.Usage.InputTokens)
	require.Equal(t, 2, result.Usage.OutputTokens)

	streamBody := rec.Body.String()
	require.Contains(t, streamBody, `"type":"text_delta"`)
	require.Contains(t, streamBody, `I cannot`)
	require.Contains(t, streamBody, `comply.`)
	require.Contains(t, streamBody, `"stop_reason":"end_turn"`)
}
