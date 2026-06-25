#!/usr/bin/env bash
# Phase 3B runtime environment — source before train/val/test jobs.
# shellcheck disable=SC2034
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

# Hugging Face / cache (model already on disk ~18G)
export HF_HOME="${HF_HOME:-${HOME}/.cache/huggingface}"
export HF_HUB_CACHE="${HF_HUB_CACHE:-${HF_HOME}/hub}"
export TRANSFORMERS_CACHE="${TRANSFORMERS_CACHE:-${HF_HOME}/hub}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"

# PyTorch CUDA allocator — reduces fragmentation on long LoRA runs
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"
export PYTORCH_CUDA_ALLOC_CONF="${PYTORCH_CUDA_ALLOC_CONF:-expandable_segments:True}"

# CPU thread budget (16 vCPU host — leave headroom for tokenization / dataloader)
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-8}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-8}"

# Phase 3B training defaults (override via env)
export PHASE3_BASE_MODEL="${PHASE3_BASE_MODEL:-unsloth/Qwen3.5-9B}"
export PHASE3_MAX_SEQ_LEN="${PHASE3_MAX_SEQ_LEN:-16384}"
export PHASE3_MAX_THINKING_TOKENS="${PHASE3_MAX_THINKING_TOKENS:-4096}"
export PHASE3_PACKING="${PHASE3_PACKING:-1}"
export PHASE3_EPOCHS="${PHASE3_EPOCHS:-10}"
export PHASE3_LR="${PHASE3_LR:-5e-5}"
export PHASE3_LORA_R="${PHASE3_LORA_R:-32}"
export PHASE3_LORA_ALPHA="${PHASE3_LORA_ALPHA:-${PHASE3_LORA_R}}"

# CSS val during training
export PHASE3_CSS_VAL_MODE="${PHASE3_CSS_VAL_MODE:-fast}"
export PHASE3_CSS_VAL_N="${PHASE3_CSS_VAL_N:-150}"
export PHASE3_CSS_EARLY_STOP_PATIENCE="${PHASE3_CSS_EARLY_STOP_PATIENCE:-3}"
export PHASE3_CSS_EVAL_EVERY="${PHASE3_CSS_EVAL_EVERY:-2}"

# LoRA rank sweep — default r=32 only (fast path); set PHASE3_LORA_RANKS="32 64" to compare
export PHASE3_LORA_RANKS="${PHASE3_LORA_RANKS:-32}"

# Paths
export PHASE3B_ROOT="${PHASE3B_ROOT:-${ROOT}/runs/phase3/stage3b}"
export PHASE3B_MANIFEST="${PHASE3B_MANIFEST:-${ROOT}/benchmark/phases/phase3/stage3b/MANIFEST.json}"

# Inference token caps — teacher distillation (match export thinking cap 4096)
export PHASE2_ON_MAX_SEQ_LEN="${PHASE2_ON_MAX_SEQ_LEN:-32768}"
export PHASE2_ON_MAX_NEW_TOKENS="${PHASE2_ON_MAX_NEW_TOKENS:-4800}"
export PHASE2_ON_MAX_NEW_TOKENS_THINKING="${PHASE2_ON_MAX_NEW_TOKENS_THINKING:-4096}"

# Inference backend: vllm (fast batch/CSS) | unsloth (legacy)
export QWEN_INFER_BACKEND="${QWEN_INFER_BACKEND:-vllm}"
export QWEN_VLLM_MODEL_ID="${QWEN_VLLM_MODEL_ID:-Qwen/Qwen3.5-9B}"
export QWEN_VLLM_MAX_MODEL_LEN="${QWEN_VLLM_MAX_MODEL_LEN:-16384}"
export QWEN_VLLM_PROMPT_RESERVE="${QWEN_VLLM_PROMPT_RESERVE:-128}"
export QWEN_VLLM_TOKENIZER_SLACK="${QWEN_VLLM_TOKENIZER_SLACK:-64}"
export QWEN_MAX_SEQ_LEN="${QWEN_MAX_SEQ_LEN:-${QWEN_VLLM_MAX_MODEL_LEN}}"
export QWEN_VLLM_GPU_MEMORY_UTILIZATION="${QWEN_VLLM_GPU_MEMORY_UTILIZATION:-0.90}"
# vLLM throughput tuning (CSS/batch infer)
export QWEN_VLLM_PREFIX_CACHING="${QWEN_VLLM_PREFIX_CACHING:-1}"
export QWEN_VLLM_BATCH_SIZE="${QWEN_VLLM_BATCH_SIZE:-4}"
export QWEN_VLLM_MAX_NUM_BATCHED_TOKENS="${QWEN_VLLM_MAX_NUM_BATCHED_TOKENS:-16384}"
export QWEN_VLLM_MERGE_BASE="${QWEN_VLLM_MERGE_BASE:-Qwen/Qwen3.5-9B}"
export QWEN_VLLM_TOKENIZER_ID="${QWEN_VLLM_TOKENIZER_ID:-Qwen/Qwen3.5-9B}"
export QWEN_VLLM_LANGUAGE_MODEL_ONLY="${QWEN_VLLM_LANGUAGE_MODEL_ONLY:-1}"
