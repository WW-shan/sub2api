package service

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"
	"github.com/tidwall/gjson"
)

func TestConvertAnthropicMessagesToOpenAIInput_MultimodalAndDocument(t *testing.T) {
	messages := []any{
		map[string]any{
			"role": "user",
			"content": []any{
				map[string]any{"type": "text", "text": "hello"},
				map[string]any{"type": "image", "source": map[string]any{"type": "url", "url": "https://example.com/a.png"}},
				map[string]any{"type": "image", "source": map[string]any{"type": "base64", "media_type": "image/png", "data": "AAAA"}},
				map[string]any{"type": "document", "source": map[string]any{"type": "text", "media_type": "text/plain", "data": "doc line"}},
				map[string]any{"type": "document", "source": map[string]any{"type": "base64", "media_type": "application/pdf", "data": "BBBB"}},
				map[string]any{"type": "search_result", "title": "A", "source": "B", "content": []any{map[string]any{"type": "text", "text": "hit"}}},
			},
		},
	}

	out := convertAnthropicMessagesToOpenAIInput(messages)
	require.Len(t, out, 1)

	msg, ok := out[0].(map[string]any)
	require.True(t, ok)
	require.Equal(t, "message", msg["type"])
	require.Equal(t, "user", msg["role"])

	content, ok := msg["content"].([]map[string]any)
	require.True(t, ok)
	require.Len(t, content, 6)

	require.Equal(t, "input_text", content[0]["type"])
	require.Equal(t, "hello", content[0]["text"])

	require.Equal(t, "input_image", content[1]["type"])
	require.Equal(t, "https://example.com/a.png", content[1]["image_url"])

	require.Equal(t, "input_image", content[2]["type"])
	require.Equal(t, "data:image/png;base64,AAAA", content[2]["image_url"])

	require.Equal(t, "input_text", content[3]["type"])
	require.Equal(t, "doc line", content[3]["text"])

	require.Equal(t, "input_text", content[4]["type"])
	require.Equal(t, "[document:application/pdf]", content[4]["text"])

	require.Equal(t, "input_text", content[5]["type"])
	searchResultJSON, _ := content[5]["text"].(string)
	require.Contains(t, searchResultJSON, `"type":"search_result"`)
}

func TestConvertAnthropicMessagesToOpenAIInput_ThinkingToolUseAndToolResult(t *testing.T) {
	messages := []any{
		map[string]any{
			"role": "assistant",
			"content": []any{
				map[string]any{"type": "thinking", "thinking": "step by step"},
				map[string]any{"type": "tool_use", "id": "toolu_123", "name": "read", "input": map[string]any{"path": "/tmp/a.txt"}},
				map[string]any{"type": "text", "text": "done"},
			},
		},
		map[string]any{
			"role": "user",
			"content": []any{
				map[string]any{"type": "tool_result", "tool_use_id": "toolu_123", "content": "file content"},
			},
		},
	}

	out := convertAnthropicMessagesToOpenAIInput(messages)
	require.Len(t, out, 4)

	assistantMessage1, ok := out[0].(map[string]any)
	require.True(t, ok)
	require.Equal(t, "message", assistantMessage1["type"])
	require.Equal(t, "assistant", assistantMessage1["role"])
	assistantContent1, ok := assistantMessage1["content"].([]map[string]any)
	require.True(t, ok)
	require.Len(t, assistantContent1, 1)
	require.Equal(t, "output_text", assistantContent1[0]["type"])
	require.Equal(t, "step by step", assistantContent1[0]["text"])

	functionCall, ok := out[1].(map[string]any)
	require.True(t, ok)
	require.Equal(t, "function_call", functionCall["type"])
	require.Equal(t, "fc_toolu_123", functionCall["id"])
	require.Equal(t, "toolu_123", functionCall["call_id"])
	require.Equal(t, "read", functionCall["name"])

	assistantMessage2, ok := out[2].(map[string]any)
	require.True(t, ok)
	require.Equal(t, "message", assistantMessage2["type"])
	require.Equal(t, "assistant", assistantMessage2["role"])

	assistantContent2, ok := assistantMessage2["content"].([]map[string]any)
	require.True(t, ok)
	require.Len(t, assistantContent2, 1)
	require.Equal(t, "output_text", assistantContent2[0]["type"])
	require.Equal(t, "done", assistantContent2[0]["text"])

	functionOutput, ok := out[3].(map[string]any)
	require.True(t, ok)
	require.Equal(t, "function_call_output", functionOutput["type"])
	require.Equal(t, "toolu_123", functionOutput["call_id"])
	require.Equal(t, "file content", functionOutput["output"])
}

func TestConvertAnthropicMessagesToOpenAIInput_ToolUseWithoutID_UsesFCPrefixedItemID(t *testing.T) {
	messages := []any{
		map[string]any{
			"role": "assistant",
			"content": []any{
				map[string]any{"type": "tool_use", "name": "read", "input": map[string]any{"path": "/tmp/a.txt"}},
			},
		},
	}

	out := convertAnthropicMessagesToOpenAIInput(messages)
	require.Len(t, out, 1)

	functionCall, ok := out[0].(map[string]any)
	require.True(t, ok)
	require.Equal(t, "function_call", functionCall["type"])
	id, _ := functionCall["id"].(string)
	callID, _ := functionCall["call_id"].(string)
	require.NotEmpty(t, id)
	require.NotEmpty(t, callID)
	require.Contains(t, id, "fc_")
	require.Contains(t, callID, "call_")
}

func TestConvertAnthropicMessagesToOpenAIInput_PreservesInterleavedOrder(t *testing.T) {
	messages := []any{
		map[string]any{
			"role": "user",
			"content": []any{
				map[string]any{"type": "text", "text": "before"},
				map[string]any{"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"},
				map[string]any{"type": "text", "text": "after"},
			},
		},
	}

	out := convertAnthropicMessagesToOpenAIInput(messages)
	require.Len(t, out, 3)

	first, ok := out[0].(map[string]any)
	require.True(t, ok)
	require.Equal(t, "message", first["type"])
	require.Equal(t, "before", first["content"].([]map[string]any)[0]["text"])

	middle, ok := out[1].(map[string]any)
	require.True(t, ok)
	require.Equal(t, "function_call_output", middle["type"])
	require.Equal(t, "toolu_1", middle["call_id"])

	last, ok := out[2].(map[string]any)
	require.True(t, ok)
	require.Equal(t, "message", last["type"])
	require.Equal(t, "after", last["content"].([]map[string]any)[0]["text"])
}

func TestConvertAnthropicMessagesToOpenAIInput_ToolResultNonTextFallback(t *testing.T) {
	messages := []any{
		map[string]any{
			"role": "user",
			"content": []any{
				map[string]any{
					"type":        "tool_result",
					"tool_use_id": "toolu_img_1",
					"content": []any{
						map[string]any{"type": "image", "source": map[string]any{"type": "url", "url": "https://example.com/r.png"}},
					},
				},
			},
		},
	}

	out := convertAnthropicMessagesToOpenAIInput(messages)
	require.Len(t, out, 1)

	functionOutput, ok := out[0].(map[string]any)
	require.True(t, ok)
	require.Equal(t, "function_call_output", functionOutput["type"])
	require.Equal(t, "toolu_img_1", functionOutput["call_id"])

	outputText, _ := functionOutput["output"].(string)
	require.NotEmpty(t, outputText)
	require.Contains(t, outputText, `"type":"image"`)
}

func TestConvertAnthropicMessagesToOpenAIInput_AssistantRoleUsesOutputText(t *testing.T) {
	messages := []any{
		map[string]any{"role": "assistant", "content": "answer"},
	}

	out := convertAnthropicMessagesToOpenAIInput(messages)
	require.Len(t, out, 1)

	msg, ok := out[0].(map[string]any)
	require.True(t, ok)
	content, ok := msg["content"].([]map[string]any)
	require.True(t, ok)
	require.Len(t, content, 1)
	require.Equal(t, "output_text", content[0]["type"])
	require.Equal(t, "answer", content[0]["text"])
}

func TestConvertAnthropicMessagesToOpenAIInput_AssistantImageFallsBackToOutputText(t *testing.T) {
	messages := []any{
		map[string]any{
			"role": "assistant",
			"content": []any{
				map[string]any{"type": "image", "source": map[string]any{"type": "url", "url": "https://example.com/ctx.png"}},
			},
		},
	}

	out := convertAnthropicMessagesToOpenAIInput(messages)
	require.Len(t, out, 1)

	msg, ok := out[0].(map[string]any)
	require.True(t, ok)
	content, ok := msg["content"].([]map[string]any)
	require.True(t, ok)
	require.Len(t, content, 1)
	require.Equal(t, "output_text", content[0]["type"])
	require.Equal(t, "https://example.com/ctx.png", content[0]["text"])
}

func TestBuildOpenAIResponsesBodyFromAnthropicRequest_ToolChoiceMapping(t *testing.T) {
	tests := []struct {
		name           string
		toolChoiceJSON string
		wantType       string
		wantName       string
	}{
		{name: "string any", toolChoiceJSON: `"any"`, wantType: "required"},
		{name: "auto", toolChoiceJSON: `{"type":"auto"}`, wantType: "auto"},
		{name: "any -> required", toolChoiceJSON: `{"type":"any"}`, wantType: "required"},
		{name: "none", toolChoiceJSON: `{"type":"none"}`, wantType: "none"},
		{name: "specific tool", toolChoiceJSON: `{"type":"tool","name":"Read"}`, wantType: "function", wantName: "Read"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			body := []byte(`{
				"model":"openai/gpt-5.3",
				"stream":false,
				"max_tokens":128,
				"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}],
				"tool_choice":` + tt.toolChoiceJSON + `
			}`)

			outBody, err := buildOpenAIResponsesBodyFromAnthropicRequest(body, "openai/gpt-5.3", false, false)
			require.NoError(t, err)

			var out map[string]any
			require.NoError(t, json.Unmarshal(outBody, &out))

			switch got := out["tool_choice"].(type) {
			case string:
				require.Equal(t, tt.wantType, got)
			case map[string]any:
				require.Equal(t, tt.wantType, got["type"])
				require.Equal(t, tt.wantName, got["name"])
			default:
				t.Fatalf("unexpected tool_choice type: %T", out["tool_choice"])
			}
		})
	}
}

func TestBuildOpenAIResponsesBodyFromAnthropicRequest_InvalidToolChoiceDropped(t *testing.T) {
	body := []byte(`{
		"model":"openai/gpt-5.3",
		"stream":false,
		"max_tokens":64,
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}],
		"tool_choice":{"type":"tool"}
	}`)

	outBody, err := buildOpenAIResponsesBodyFromAnthropicRequest(body, "openai/gpt-5.3", false, false)
	require.NoError(t, err)

	var out map[string]any
	require.NoError(t, json.Unmarshal(outBody, &out))
	_, exists := out["tool_choice"]
	require.False(t, exists)
}

func TestBuildOpenAIResponsesBodyFromAnthropicRequest_AssistantContextUsesOutputText(t *testing.T) {
	body := []byte(`{
		"model":"openai/gpt-5.3",
		"stream":false,
		"max_tokens":128,
		"messages":[
			{"role":"user","content":[{"type":"text","text":"q1"}]},
			{"role":"assistant","content":[{"type":"text","text":"a1"}]},
			{"role":"user","content":[{"type":"text","text":"q2"}]}
		]
	}`)

	outBody, err := buildOpenAIResponsesBodyFromAnthropicRequest(body, "openai/gpt-5.3", false, false)
	require.NoError(t, err)
	require.Equal(t, "input_text", gjson.GetBytes(outBody, "input.0.content.0.type").String())
	require.Equal(t, "output_text", gjson.GetBytes(outBody, "input.1.content.0.type").String())
	require.Equal(t, "input_text", gjson.GetBytes(outBody, "input.2.content.0.type").String())
}

func TestConvertOpenAIResponsesJSONToClaude_UsesRefusalText(t *testing.T) {
	respBody := []byte(`{
		"id":"resp_refusal_1",
		"output":[
			{"type":"message","role":"assistant","content":[{"type":"refusal","refusal":"I cannot help with that."}]}
		],
		"usage":{"input_tokens":3,"output_tokens":5}
	}`)

	out, usage := convertOpenAIResponsesJSONToClaude(respBody, "openai/gpt-5.3")
	require.NotNil(t, usage)
	require.Equal(t, 3, usage.InputTokens)
	require.Equal(t, 5, usage.OutputTokens)

	var claude map[string]any
	require.NoError(t, json.Unmarshal(out, &claude))
	require.Equal(t, "message", claude["type"])
	require.Equal(t, "assistant", claude["role"])
	require.Equal(t, "text", claude["content"].([]any)[0].(map[string]any)["type"])
	require.Equal(t, "I cannot help with that.", claude["content"].([]any)[0].(map[string]any)["text"])
}

func TestBuildOpenAIResponsesBodyFromAnthropicRequest_UsesSkillsAndPluginsAsTools(t *testing.T) {
	body := []byte(`{
		"model":"openai/gpt-5.3",
		"stream":false,
		"max_tokens":128,
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}],
		"skills":[
			{"name":"TodoWrite","description":"write todo list","input_schema":{"type":"object","properties":{"todos":{"type":"array"}}}},
			{"function":{"name":"Read","description":"read file","parameters":{"type":"object","properties":{"path":{"type":"string"}}}}}
		],
		"plugins":[
			{"name":"TodoWrite","description":"duplicate todo plugin"},
			{"name":"Search","description":"search code"}
		]
	}`)

	outBody, err := buildOpenAIResponsesBodyFromAnthropicRequest(body, "openai/gpt-5.3", false, false)
	require.NoError(t, err)

	require.Equal(t, 3, len(gjson.GetBytes(outBody, "tools").Array()))
	require.Equal(t, "TodoWrite", gjson.GetBytes(outBody, "tools.0.name").String())
	require.Equal(t, "Read", gjson.GetBytes(outBody, "tools.1.name").String())
	require.Equal(t, "Search", gjson.GetBytes(outBody, "tools.2.name").String())
	require.Equal(t, "object", gjson.GetBytes(outBody, "tools.2.parameters.type").String())
}

func TestBuildOpenAIResponsesBodyFromAnthropicRequest_PreservesMetadata(t *testing.T) {
	body := []byte(`{
		"model":"openai/gpt-5.3",
		"stream":false,
		"max_tokens":128,
		"metadata":{"user_id":"user_abc","trace_id":"trace_1"},
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]
	}`)

	outBody, err := buildOpenAIResponsesBodyFromAnthropicRequest(body, "openai/gpt-5.3", false, false)
	require.NoError(t, err)
	require.Equal(t, "user_abc", gjson.GetBytes(outBody, "metadata.user_id").String())
	require.Equal(t, "trace_1", gjson.GetBytes(outBody, "metadata.trace_id").String())
}

func TestBuildOpenAIResponsesBodyFromAnthropicRequest_MapsOutputConfigEffortToReasoning(t *testing.T) {
	body := []byte(`{
		"model":"openai/gpt-5.3",
		"stream":false,
		"max_tokens":128,
		"output_config":{"effort":"HIGH"},
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]
	}`)

	outBody, err := buildOpenAIResponsesBodyFromAnthropicRequest(body, "openai/gpt-5.3", false, false)
	require.NoError(t, err)
	require.Equal(t, "high", gjson.GetBytes(outBody, "reasoning.effort").String())
}

func TestBuildOpenAIResponsesBodyFromAnthropicRequest_ReasoningTakesPriorityOverOutputConfig(t *testing.T) {
	body := []byte(`{
		"model":"openai/gpt-5.3",
		"stream":false,
		"max_tokens":128,
		"reasoning":{"effort":"medium"},
		"output_config":{"effort":"high"},
		"messages":[{"role":"user","content":[{"type":"text","text":"hi"}]}]
	}`)

	outBody, err := buildOpenAIResponsesBodyFromAnthropicRequest(body, "openai/gpt-5.3", false, false)
	require.NoError(t, err)
	require.Equal(t, "medium", gjson.GetBytes(outBody, "reasoning.effort").String())
}
