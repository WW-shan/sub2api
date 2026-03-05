package service

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"
)

func TestIsGPTModelPrefix_WithProviderQualifiedModel(t *testing.T) {
	tests := []struct {
		name  string
		model string
		want  bool
	}{
		{name: "plain gpt model", model: "gpt-5.3-codex", want: true},
		{name: "provider qualified gpt model", model: "openai/gpt-5.3-codex", want: true},
		{name: "provider qualified mixed case", model: "OpenAI/GPT-5.3", want: true},
		{name: "non gpt model", model: "claude-sonnet-4-20250514", want: false},
		{name: "empty model", model: "", want: false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			require.Equal(t, tt.want, isGPTModelPrefix(tt.model))
		})
	}
}

func TestNormalizeOpenAICompatModelID(t *testing.T) {
	tests := []struct {
		name  string
		model string
		want  string
	}{
		{name: "provider qualified gpt 5.3", model: "openai/gpt-5.3", want: "gpt-5.3-codex"},
		{name: "provider qualified codex model", model: "openai/gpt-5.3-codex", want: "gpt-5.3-codex"},
		{name: "gpt 5.3 alias with effort", model: "GPT-5.3-HIGH", want: "gpt-5.3-codex"},
		{name: "non codex gpt model passthrough", model: "openai/gpt-4.1", want: "gpt-4.1"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			require.Equal(t, tt.want, normalizeOpenAICompatModelID(tt.model))
		})
	}
}

func TestBuildOpenAIResponsesBodyFromAnthropicRequest_NormalizesClaudeCodeGPT53Model(t *testing.T) {
	body := []byte(`{
		"model":"openai/gpt-5.3",
		"stream":true,
		"max_tokens":2048,
		"system":[{"type":"text","text":"You are Claude Code"}],
		"messages":[
			{"role":"user","content":[{"type":"text","text":"hello"}]}
		]
	}`)

	outBody, err := buildOpenAIResponsesBodyFromAnthropicRequest(body, "openai/gpt-5.3", true, false)
	require.NoError(t, err)

	var out map[string]any
	require.NoError(t, json.Unmarshal(outBody, &out))
	require.Equal(t, "gpt-5.3-codex", out["model"])
	require.Equal(t, true, out["stream"])
	require.Equal(t, float64(2048), out["max_output_tokens"])
	require.Equal(t, "You are Claude Code", out["instructions"])
}
