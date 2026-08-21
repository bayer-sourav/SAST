#!/usr/bin/env bash
# Qwen3.8-27B vs Phase 2 ship: v7-balanced + fs3 v2_3shot_tp_2fp.
# Smoke (20) then optional 600-case (200 FP + 200 TP + 200 BL).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

PROFILE="qwen3_8_27b_nvfp4"
PROMPT="v7-balanced"
FEWSHOT=3
FS_CFG="v2_3shot_tp_2fp"
SMOKE_OUT="runs/smoke/qwen38_27b_nvfp4_v7"
FULL_ROOT="runs/qwen38_27b_nvfp4_v7/full_600"
LOG_DIR="runs/qwen38_27b_nvfp4_v7/logs"
SKIP_600="${SKIP_600:-0}"
FORCE="${FORCE:-0}"
# The smoke harness spawns a fresh engine per case, reloading 27B weights each time.
# run_batch.py preloads once and batches, so SKIP_SMOKE=1 + MAX_CASES=N is the cheap
# way to validate the real path.
SKIP_SMOKE="${SKIP_SMOKE:-0}"
MAX_CASES="${MAX_CASES:-0}"

mkdir -p "$LOG_DIR" "$SMOKE_OUT" "$FULL_ROOT"
LOG="$LOG_DIR/eval.log"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

# shellcheck source=benchmark/phase2_cell_env.sh
source "$ROOT/benchmark/phase2_cell_env.sh"

# NVFP4 needs Blackwell (sm_100+); this L40S is sm_89, so serve the FP8 build instead.
# Unsloth 4-bit decode measured ~7 tok/s here (~100h for 600 cases) — vLLM is the only viable path.
# vLLM 0.27 needs transformers>=5.8, which conflicts with the Unsloth pin, so it lives in .venv-vllm.
PY="${QWEN38_PYTHON:-$ROOT/.venv-vllm/bin/python}"
[[ -x "$PY" ]] || { echo "ERROR: missing $PY (create with: uv venv .venv-vllm)"; exit 2; }
# vLLM's torch.compile shells out to `ninja`; without the venv bin on PATH the
# engine dies with FileNotFoundError even though ninja is installed.
export PATH="$(dirname "$PY"):$PATH"

export QWEN_INFER_BACKEND=vllm
export QWEN_QWEN3_8_27B_NVFP4_VLLM_MODEL_ID="${QWEN38_MODEL_ID:-Qwen/Qwen3.8-27B-FP8}"
# phase2_infer_env.sh points these at Qwen3.5-9B; wrong family for this run.
unset QWEN_VLLM_MODEL_ID || true
unset QWEN_VLLM_TOKENIZER_ID || true
# Prompts reach ~26k tokens on the largest cases; 16k would truncate them.
export QWEN_VLLM_MAX_MODEL_LEN=32768
export QWEN_MAX_SEQ_LEN=32768
# These are assigned unconditionally: phase2_infer_env.sh already exported its own
# defaults above, so a `${VAR:-...}` fallback here would silently keep 0.75/4 and
# starve the KV cache. Override from the outer shell with the QWEN38_* names.
# At 0.75 util the 27.6GiB of weights left only 2.57GiB (36k tokens) of KV cache,
# barely one 32k sequence; vLLM reported 13.02GiB available.
export QWEN_VLLM_GPU_MEMORY_UTILIZATION="${QWEN38_GPU_UTIL:-0.93}"
export QWEN_VLLM_BATCH_SIZE="${QWEN38_BATCH_SIZE:-12}"
# This checkpoint ships no q/prob scales, so fp8 attention runs uncalibrated and
# vLLM warns about accuracy. Weights are 27.6GiB of a ~41GiB budget and only 16 of
# 64 layers keep a KV cache, so bf16 KV fits and keeps the quality comparison clean.
export QWEN_VLLM_KV_CACHE_DTYPE="${QWEN38_KV_DTYPE:-auto}"
# Left at the phase2 value: raising it inflates peak activation, which competes
# with KV cache for the same budget.
export QWEN_VLLM_MAX_NUM_BATCHED_TOKENS="${QWEN_VLLM_MAX_NUM_BATCHED_TOKENS:-16384}"
export QWEN_VLLM_PREFIX_CACHING=1
export QWEN_CODER_MAX_SEQ_LEN="${QWEN_CODER_MAX_SEQ_LEN:-32768}"
export PYTHONPATH="${ROOT}:${ROOT}/benchmark:${PYTHONPATH:-}"
export HF_HUB_DISABLE_XET="${HF_HUB_DISABLE_XET:-1}"

cp -f "$ROOT/benchmark/phases/phase2/smoke_slice_cases.json" /tmp/smoke_slice_cases.json

echo "=== Qwen3.8-27B NVFP4 eval $(date -Iseconds) backend=$QWEN_INFER_BACKEND ===" | tee "$LOG"
"$PY" "$ROOT/benchmark/phases/smoke/test_qwen38_nvfp4_profile.py" 2>&1 | tee -a "$LOG"

phase2_require_gpu() {
  if ! "$PY" -c "import torch; exit(0 if torch.cuda.is_available() else 1)"; then
    echo "ERROR: CUDA GPU required" | tee -a "$LOG"
    exit 2
  fi
}
phase2_require_gpu
phase2_apply_token_limits on "$PROFILE"

if [[ "$SKIP_SMOKE" == "1" ]]; then
  echo "=== SKIP_SMOKE=1 — straight to run_batch ===" | tee -a "$LOG"
else
  echo "=== smoke 20 ===" | tee -a "$LOG"
  LARGE_QWEN_SMOKE_PROFILES="$PROFILE" \
  LARGE_QWEN_SMOKE_OUT="$ROOT/$SMOKE_OUT" \
  LARGE_QWEN_SMOKE_SLICE="/tmp/smoke_slice_cases.json" \
  LARGE_QWEN_FORCE="$FORCE" \
    "$PY" "$ROOT/benchmark/phases/smoke/run_large_qwen_smoke.py" 2>&1 | tee -a "$LOG"
fi

if [[ "$SKIP_600" == "1" ]]; then
  echo "SKIP_600=1 — stopping after smoke" | tee -a "$LOG"
  exit 0
fi

SUM_DIR="$FULL_ROOT/summaries"
mkdir -p "$SUM_DIR"
cat > "$FULL_ROOT/tracks.json" <<EOF
[
  {"gold": "FP", "case_dir": "benchmark/corpora/phase2_fp_test", "runs_root": "$FULL_ROOT/fp/thinking_on/fewshot_${FEWSHOT}"},
  {"gold": "TP", "case_dir": "benchmark/corpora/phase2_tp_test", "runs_root": "$FULL_ROOT/tp/thinking_on/fewshot_${FEWSHOT}"},
  {"gold": "BL", "case_dir": "benchmark/corpora/phase2_bl_test", "runs_root": "$FULL_ROOT/bl/thinking_on/fewshot_${FEWSHOT}"}
]
EOF

force_flag=()
[[ "$FORCE" == "1" ]] && force_flag=(--force)
max_flag=()
[[ "$MAX_CASES" != "0" ]] && max_flag=(--max-cases "$MAX_CASES")

echo "=== 600-case FP+TP+BL ===" | tee -a "$LOG"
phase2_gpu_cleanup "$LOG"
"$PY" "$ROOT/benchmark/run_batch.py" \
  --agent llm \
  --profile "$PROFILE" \
  --prompt-version "$PROMPT" \
  --thinking \
  --few-shot "$FEWSHOT" \
  --few-shot-config "$FS_CFG" \
  --tracks-json "$FULL_ROOT/tracks.json" \
  --retry-missing \
  "${max_flag[@]}" \
  "${force_flag[@]}" 2>&1 | tee -a "$LOG"

"$PY" "$ROOT/benchmark/summarize_triage.py" \
  --case-dir benchmark/corpora/phase2_fp_test --gold FP \
  --runs "$FULL_ROOT/fp/thinking_on/fewshot_${FEWSHOT}" --profile "$PROFILE" \
  --json-out "$SUM_DIR/comparison_fp.json" 2>&1 | tee -a "$LOG"
"$PY" "$ROOT/benchmark/summarize_triage.py" \
  --case-dir benchmark/corpora/phase2_tp_test --gold TP \
  --runs "$FULL_ROOT/tp/thinking_on/fewshot_${FEWSHOT}" --profile "$PROFILE" \
  --json-out "$SUM_DIR/comparison_tp.json" 2>&1 | tee -a "$LOG"
"$PY" "$ROOT/benchmark/summarize_borderline.py" \
  --case-dir benchmark/corpora/phase2_bl_test \
  --runs "$FULL_ROOT/bl/thinking_on/fewshot_${FEWSHOT}" --profile "$PROFILE" \
  --json-out "$SUM_DIR/comparison_bl.json" 2>&1 | tee -a "$LOG"
"$PY" "$ROOT/benchmark/phases/phase2/merge_prod_ship_600_summary.py" \
  --sum-dir "$SUM_DIR" --profile "$PROFILE" \
  --json-out "$SUM_DIR/merged_600.json" \
  --md-out "$FULL_ROOT/PROD_SHIP_600_REPORT.md" 2>&1 | tee -a "$LOG"

echo "=== done $(date -Iseconds) ===" | tee -a "$LOG"
echo "Smoke: $SMOKE_OUT/smoke_summary.json"
echo "600:   $FULL_ROOT/PROD_SHIP_600_REPORT.md"
