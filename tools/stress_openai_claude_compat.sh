#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"

ITERATIONS=10
RUN_FULL=1

if [[ $# -ge 1 ]]; then
  ITERATIONS="$1"
fi
if [[ $# -ge 2 ]]; then
  RUN_FULL="$2"
fi

if ! [[ "$ITERATIONS" =~ ^[0-9]+$ ]] || [[ "$ITERATIONS" -le 0 ]]; then
  echo "Usage: $0 [iterations>0] [run_full(0|1)]"
  exit 1
fi

if ! command -v go >/dev/null 2>&1; then
  if [[ -x "/c/Program Files/Go/bin/go.exe" ]]; then
    export PATH="$PATH:/c/Program Files/Go/bin"
  fi
fi

if ! command -v go >/dev/null 2>&1; then
  echo "go command not found"
  exit 1
fi

COMPAT_REGEX='TestGatewayService_Forward_OpenAICompatProviderModelAndToolChoice|TestGatewayService_Forward_OpenAICompatStreamNoDuplicateToolUse|TestGatewayService_Forward_OpenAICompatStream_FunctionCallArgumentsDeltaToInputJsonDelta|TestGatewayService_Forward_OpenAICompatStream_RefusalDeltaAsText|TestGatewayService_Forward_OpenAICompatStream_PreservesWhitespaceInTextDelta|TestIsGPTModelPrefix_WithProviderQualifiedModel|TestNormalizeOpenAICompatModelID|TestBuildOpenAIResponsesBodyFromAnthropicRequest_NormalizesClaudeCodeGPT53Model|TestBuildOpenAIResponsesBodyFromAnthropicRequest_AssistantContextUsesOutputText|TestBuildOpenAIResponsesBodyFromAnthropicRequest_UsesSkillsAndPluginsAsTools|TestConvertAnthropicMessagesToOpenAIInput_AssistantRoleUsesOutputText|TestConvertAnthropicMessagesToOpenAIInput_AssistantImageFallsBackToOutputText|TestConvertOpenAIResponsesJSONToClaude_UsesRefusalText|TestBuildOpenAIResponsesBodyFromAnthropicRequest_ToolChoiceMapping|TestBuildOpenAIResponsesBodyFromAnthropicRequest_InvalidToolChoiceDropped'

cd "$BACKEND_DIR"

echo "== OpenAI/Claude compatibility stress test =="
echo "Go: $(go version)"
echo "Iterations: $ITERATIONS"
echo "Run full internal/service once after loop: $RUN_FULL"

for ((i = 1; i <= ITERATIONS; i++)); do
  echo
  echo "[${i}/${ITERATIONS}] running compatibility suite..."
  go test ./internal/service -run "$COMPAT_REGEX" -count=1 -shuffle=on
done

if [[ "$RUN_FULL" == "1" ]]; then
  echo
  echo "Running full internal/service suite once..."
  go test ./internal/service -count=1
fi

echo
echo "All compatibility stress checks passed."
