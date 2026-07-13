#!/usr/bin/env bash
# BL v4 full test eval: phase2_bl_test (200) → v7-ship-bl + vLLM + v2_3shot_tp_fp_bl → review.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

# shellcheck source=phase2_infer_env.sh
source "$ROOT/benchmark/phases/phase2/phase2_infer_env.sh"
# shellcheck source=../../phase2_cell_env.sh
source "$ROOT/benchmark/phase2_cell_env.sh"

export HF_HOME="${PHASE2_HF_HOME:-${HOME}/.cache/huggingface}"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"

PROFILE="qwen3_5_9b_bnb"
PROMPT="${SAST_PROMPT_VERSION:-v8-ship-bl}"
FS_CONFIG="${SAST_FEWSHOT_CONFIG:-v2_4shot_tp_fp_bl2}"
FEWSHOT="${BL_V4_FEWSHOT:-4}"
FORCE="${BL_V4_FORCE_RERUN:-0}"
SKIP_REBUILD="${BL_V4_SKIP_REBUILD:-0}"

CORPUS="${BL_V4_CORPUS:-benchmark/corpora/phase2_bl_test}"
RUNS="${BL_V4_RUNS_ROOT:-runs/bl_v4_eval/stage2_ship_bl}"
REVIEW_DIR="${BL_V4_REVIEW_DIR:-runs/bl_v4_eval}"
LOG="$ROOT/$REVIEW_DIR/eval_ship_bl.log"
mkdir -p "$(dirname "$LOG")" "$RUNS"

echo "=== BL v4 full eval (phase2_bl_test + $PROMPT) $(date -Iseconds) ===" | tee "$LOG"
echo "prompt=$PROMPT fewshot=$FEWSHOT config=$FS_CONFIG backend=${QWEN_INFER_BACKEND}" | tee -a "$LOG"

if [[ "$SKIP_REBUILD" != "1" ]]; then
  echo "[1/3] Refresh phase2 corpora from dataset" | tee -a "$LOG"
  uv run python "$ROOT/benchmark/build_phase2_corpora.py" 2>&1 | tee -a "$LOG"
fi

N="$(find "$CORPUS" -maxdepth 1 -name 'OWASP_*.json' | wc -l | tr -d ' ')"
echo "[eval] $N BL test cases in $CORPUS" | tee -a "$LOG"

FORCE_ARGS=()
if [[ "$FORCE" == "1" ]]; then
  FORCE_ARGS=(--force)
fi

echo "[2/3] Inference — vLLM + $PROMPT ($N cases)" | tee -a "$LOG"
phase2_gpu_cleanup "$LOG"
uv run python "$ROOT/benchmark/run_batch.py" \
  --agent llm \
  --profile "$PROFILE" \
  --prompt-version "$PROMPT" \
  --thinking \
  --few-shot "$FEWSHOT" \
  --few-shot-config "$FS_CONFIG" \
  --gold BL \
  --case-dir "$CORPUS" \
  --runs-root "$RUNS" \
  --retry-missing \
  "${FORCE_ARGS[@]}" 2>&1 | tee -a "$LOG"
phase2_gpu_cleanup "$LOG"

echo "[3/3] Automated review report" | tee -a "$LOG"
uv run python "$ROOT/benchmark/analyze_bl_v4_pilot.py" \
  --corpus "$CORPUS" \
  --runs "$RUNS" \
  --profile "$PROFILE" \
  --json-out "$ROOT/$REVIEW_DIR/review_ship_bl.json" \
  --html-out "$ROOT/$REVIEW_DIR/REVIEW_SHIP_BL.html" 2>&1 | tee -a "$LOG"

echo "Done. Open $REVIEW_DIR/REVIEW_SHIP_BL.html" | tee -a "$LOG"
