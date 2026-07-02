#!/usr/bin/env bash
# Phase 3A eval: Phase 2 ship config + LoRA adapter on held-out test corpora.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

# shellcheck source=phase2_cell_env.sh
source "$ROOT/benchmark/phase2_cell_env.sh"

MANIFEST="${PHASE3B_MANIFEST:-$ROOT/benchmark/phases/phase3/stage3b/MANIFEST.json}"
STAGE="${PHASE3_STAGE:-3a}"

if [[ "$STAGE" == "3d" ]]; then
  MANIFEST="${PHASE3_MANIFEST:-$ROOT/benchmark/phases/phase3/stage3d/MANIFEST.json}"
  LOG_DIR="runs/phase3/stage3d/logs"
  SUM_DIR="runs/phase3/stage3d/summaries"
  EVAL_ROOT="${PHASE3_EVAL_ROOT:-runs/phase3/stage3a/eval}"
  LORA="${SAST_LORA_ADAPTER:-runs/phase3/stage3d/lora/best}"
  PROMPT_VERSION="${PHASE3_PROMPT_VERSION:-v7-ship}"
  export QWEN_INFER_BACKEND=vllm
  export SAST_REQUIRE_VLLM=1
elif [[ "$STAGE" == "3c" ]]; then
  MANIFEST="${PHASE3_MANIFEST:-$ROOT/benchmark/phases/phase3/stage3c/MANIFEST.json}"
  LOG_DIR="runs/phase3/stage3c/logs"
  SUM_DIR="runs/phase3/stage3c/summaries"
  EVAL_ROOT="runs/phase3/stage3c/eval"
  LORA="${SAST_LORA_ADAPTER:-runs/phase3/stage3c/lora/best}"
  PROMPT_VERSION="${PHASE3_PROMPT_VERSION:-v7-ship}"
  export QWEN_INFER_BACKEND=vllm
  export SAST_REQUIRE_VLLM=1
elif [[ "$STAGE" == "3b" ]]; then
  LOG_DIR="runs/phase3/stage3b/logs"
  SUM_DIR="runs/phase3/stage3b/summaries"
  EVAL_ROOT="runs/phase3/stage3b/eval"
  LORA="${SAST_LORA_ADAPTER:-runs/phase3/stage3b/lora/best}"
  PROMPT_VERSION="${PHASE3_PROMPT_VERSION:-v7-ship}"
  export QWEN_INFER_BACKEND=vllm
  export SAST_REQUIRE_VLLM=1
else
  MANIFEST="$ROOT/benchmark/phases/phase3/MANIFEST.json"
  LOG_DIR="runs/phase3/stage3a/logs"
  SUM_DIR="runs/phase3/stage3a/summaries"
  EVAL_ROOT="runs/phase3/stage3a/eval"
  LORA="${SAST_LORA_ADAPTER:-runs/phase3/stage3a/lora/latest}"
  PROMPT_VERSION="v7-balanced"
fi

mkdir -p "$LOG_DIR" "$SUM_DIR"
if [[ "$LORA" != /* ]]; then
  LORA="$ROOT/$LORA"
fi
if [[ ! -d "$LORA" ]]; then
  echo "ERROR: LoRA adapter not found at $LORA (set SAST_LORA_ADAPTER or train first)" >&2
  exit 2
fi
export SAST_LORA_ADAPTER="$LORA"

PROFILE="qwen3_5_9b_bnb"
FEWSHOT="${PHASE3_FEWSHOT:-3}"
FS_CONFIG="${PHASE3_FEW_SHOT_CONFIG:-v2_3shot_tp_2fp}"
THINKING="${PHASE3_THINKING:-on}"
SMOKE_MAX="${PHASE3_SMOKE_MAX:-0}"
FORCE="${PHASE3_FORCE:-0}"
EVAL_ROOT="${PHASE3_EVAL_ROOT:-$EVAL_ROOT}"
SUM_SUFFIX="${PHASE3_SUM_SUFFIX:-}"
LOG_NAME="${PHASE3_LOG_NAME:-eval.log}"

CORPORA_FP="benchmark/corpora/phase2_fp_test"
CORPORA_TP="benchmark/corpora/phase2_tp_test"
CORPORA_BL="benchmark/corpora/phase2_bl_test"

RUNS_FP="$EVAL_ROOT/fp"
RUNS_TP="$EVAL_ROOT/tp"
RUNS_BL="$EVAL_ROOT/bl"

export HF_HOME="${PHASE3_HF_HOME:-${HOME}/.cache/huggingface}"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"

if [[ "$STAGE" == "3c" ]]; then
  # shellcheck source=phase3c_env.sh
  source "$ROOT/benchmark/phases/phase3/phase3c_env.sh"
else
  # shellcheck source=phase3b_env.sh
  source "$ROOT/benchmark/phases/phase3/phase3b_env.sh"
fi

phase2_apply_token_limits "$THINKING" "$PROFILE"
export SAST_PROMPT_VERSION="$PROMPT_VERSION"
export PYTHONPATH="${ROOT}:${ROOT}/benchmark${PYTHONPATH:+:$PYTHONPATH}"

if [[ "${QWEN_INFER_BACKEND:-vllm}" == "vllm" ]]; then
  echo "[eval] merging LoRA for vLLM: $LORA" | tee -a "$LOG_DIR/$LOG_NAME"
  MERGED="$("$ROOT/.venv/bin/python" "$ROOT/benchmark/phases/phase3/export_lora_for_vllm.py" --adapter "$LORA")"
  export QWEN_VLLM_MODEL_ID="$MERGED"
  export QWEN_VLLM_USE_LORA=0
  unset SAST_LORA_ADAPTER
fi

echo "=== Phase 3 stage=$STAGE eval ($(date -Iseconds)) lora=$LORA think=$THINKING fs=$FEWSHOT vllm_model=${QWEN_VLLM_MODEL_ID:-base} smoke_max=$SMOKE_MAX eval_root=$EVAL_ROOT ===" | tee -a "$LOG_DIR/$LOG_NAME"

uv run python "$ROOT/benchmark/phases/phase3/preflight_phase3.py" --stage "$STAGE" >> "$LOG_DIR/$LOG_NAME" 2>&1

THINKING_PY=False
if [[ "$THINKING" == "on" ]]; then
  THINKING_PY=True
fi

"$ROOT/.venv/bin/python" - >> "$LOG_DIR/$LOG_NAME" 2>&1 <<PY
import json
import os
from pathlib import Path

from benchmark.phases.phase3.phase3_inference import run_batch_tracks

root = Path("$ROOT")
eval_root = Path("$EVAL_ROOT")
fewshot = int("$FEWSHOT")
thinking = ${THINKING_PY}
tracks = [
    {
        "gold": "FP",
        "case_dir": str(root / "$CORPORA_FP"),
        "runs_root": str(eval_root / "fp/thinking_${THINKING}/fewshot_${FEWSHOT}"),
    },
    {
        "gold": "TP",
        "case_dir": str(root / "$CORPORA_TP"),
        "runs_root": str(eval_root / "tp/thinking_${THINKING}/fewshot_${FEWSHOT}"),
    },
    {
        "gold": "BL",
        "case_dir": str(root / "$CORPORA_BL"),
        "runs_root": str(eval_root / "bl/thinking_${THINKING}/fewshot_${FEWSHOT}"),
    },
]
kwargs = {
    "profile": "$PROFILE",
    "thinking": thinking,
    "few_shot": fewshot,
    "few_shot_config": "$FS_CONFIG",
    "prompt_version": "$PROMPT_VERSION",
    "retry_missing": True,
    "sast_root": root,
}
if int("${SMOKE_MAX:-0}") > 0:
    kwargs["max_cases"] = int("$SMOKE_MAX")
if "${FORCE:-0}" == "1":
    kwargs["force"] = True
print(f"[eval] multi-track test infer think={thinking} fs={fewshot} (single vLLM session)", flush=True)
run_batch_tracks(tracks, **kwargs)
PY

uv run python "$ROOT/benchmark/summarize_triage.py" \
  --case-dir "$CORPORA_FP" --gold FP \
  --runs "$RUNS_FP/thinking_${THINKING}/fewshot_${FEWSHOT}" \
  --profile "$PROFILE" \
  --json-out "$SUM_DIR/comparison_fp_phase3a${SUM_SUFFIX}.json" >> "$LOG_DIR/$LOG_NAME" 2>&1 || true

uv run python "$ROOT/benchmark/summarize_triage.py" \
  --case-dir "$CORPORA_TP" --gold TP \
  --runs "$RUNS_TP/thinking_${THINKING}/fewshot_${FEWSHOT}" \
  --profile "$PROFILE" \
  --json-out "$SUM_DIR/comparison_tp_phase3a${SUM_SUFFIX}.json" >> "$LOG_DIR/$LOG_NAME" 2>&1 || true

uv run python "$ROOT/benchmark/summarize_borderline.py" \
  --case-dir "$CORPORA_BL" \
  --runs "$RUNS_BL/thinking_${THINKING}/fewshot_${FEWSHOT}" \
  --profile "$PROFILE" \
  --json-out "$SUM_DIR/comparison_bl_phase3a${SUM_SUFFIX}.json" >> "$LOG_DIR/$LOG_NAME" 2>&1 || true

if [[ -z "$SUM_SUFFIX" ]]; then
  uv run python "$ROOT/benchmark/phases/phase3/report_phase3_status.py" >> "$LOG_DIR/$LOG_NAME" 2>&1
fi
echo "=== Phase 3 eval done think=$THINKING fs=$FEWSHOT ===" | tee -a "$LOG_DIR/$LOG_NAME"
