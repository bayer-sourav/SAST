#!/usr/bin/env bash
# Source before running GitHub advisory triage (language-agnostic Stage-2-quality ship config).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export SAST_ROOT="${SAST_ROOT:-$ROOT}"
export GITHUB_ADVISORY_MANIFEST="${GITHUB_ADVISORY_MANIFEST:-$ROOT/integrations/github/MANIFEST.json}"

# Inference — base Qwen3.5-9B, v7-ship, thinking on, no few-shot (language agnostic)
export SAST_PROMPT_VERSION="${SAST_PROMPT_VERSION:-v7-ship}"
export PHASE3_THINKING="${PHASE3_THINKING:-on}"
export PHASE3_FEWSHOT="${PHASE3_FEWSHOT:-0}"
unset SAST_LORA_ADAPTER 2>/dev/null || true

# vLLM defaults (override in CloudFormation user-data / ECS task env)
export QWEN_VLLM_BATCH_SIZE="${QWEN_VLLM_BATCH_SIZE:-4}"
export TORCHINDUCTOR_FX_GRAPH_REMOTE_CACHE="${TORCHINDUCTOR_FX_GRAPH_REMOTE_CACHE:-0}"

# Service (set in deployment)
: "${TRIAGE_API_HMAC_SECRET:=dev-change-me}"
: "${GITHUB_WEBHOOK_SECRET:=dev-change-me}"
: "${GITHUB_APP_ID:=}"
: "${GITHUB_APP_PRIVATE_KEY_PATH:=}"

echo "github_env: SAST_PROMPT_VERSION=$SAST_PROMPT_VERSION PHASE3_THINKING=$PHASE3_THINKING"
