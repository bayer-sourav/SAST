#!/usr/bin/env bash
# BL v4 pilot: all-synthetic cases → Stage 2 GOOD + language-agnostic BL calibration → review.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
DATASET="${SAST_DATASET_ROOT:-$ROOT/../SAST-Benchmark-Dataset}"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

# shellcheck source=phase2_infer_env.sh
source "$ROOT/benchmark/phases/phase2/phase2_infer_env.sh"

export HF_HOME="${PHASE2_HF_HOME:-${HOME}/.cache/huggingface}"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"

# Stage 2 GOOD + language-agnostic ship BL calibration (Java few-shot OK)
PROFILE="qwen3_5_9b_bnb"
PROMPT="${SAST_PROMPT_VERSION:-v7-ship-bl}"
FS_CONFIG="${SAST_FEWSHOT_CONFIG:-v2_3shot_tp_fp_bl}"
FEWSHOT=3
FORCE="${PILOT_FORCE_RERUN:-0}"

CORPUS="benchmark/corpora/bl_v4_pilot"
RUNS="runs/bl_v4_pilot/stage2_ship_bl"
LOG="$ROOT/runs/bl_v4_pilot/pilot_ship_bl.log"
mkdir -p "$(dirname "$LOG")" "$RUNS"

echo "=== BL v4 pilot (synthetic + v7-ship-bl) $(date -Iseconds) ===" | tee "$LOG"
echo "prompt=$PROMPT fewshot=$FEWSHOT config=$FS_CONFIG backend=${QWEN_INFER_BACKEND}" | tee -a "$LOG"

echo "[1/4] Build all-synthetic pilot bundles" | tee -a "$LOG"
python3 "$DATASET/scripts/build_borderline_v4_pilot.py" \
  --out "$DATASET/BenchmarkJava/borderline_pilot" \
  --per-category "${PILOT_PER_CATEGORY:-10}" 2>&1 | tee -a "$LOG"

echo "[2/4] Publish pilot corpus" | tee -a "$LOG"
uv run python "$ROOT/benchmark/build_bl_v4_pilot_corpus.py" \
  --pilot-root "$DATASET/BenchmarkJava/borderline_pilot" 2>&1 | tee -a "$LOG"

N="$(find "$CORPUS" -maxdepth 1 -name 'BLv4p*.json' | wc -l | tr -d ' ')"
echo "[pilot] $N synthetic cases in $CORPUS" | tee -a "$LOG"

FORCE_ARGS=()
if [[ "$FORCE" == "1" ]]; then
  FORCE_ARGS=(--force)
fi

echo "[3/4] Inference — vLLM + $PROMPT" | tee -a "$LOG"
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
  "${FORCE_ARGS[@]}" 2>&1 | tee -a "$LOG"

echo "[4/4] Automated review report" | tee -a "$LOG"
uv run python "$ROOT/benchmark/analyze_bl_v4_pilot.py" \
  --corpus "$CORPUS" \
  --runs "$RUNS" \
  --profile "$PROFILE" \
  --json-out "$ROOT/runs/bl_v4_pilot/pilot_review_ship_bl.json" \
  --html-out "$ROOT/runs/bl_v4_pilot/PILOT_REVIEW_SHIP_BL.html" 2>&1 | tee -a "$LOG"

echo "Done. Open runs/bl_v4_pilot/PILOT_REVIEW_SHIP_BL.html" | tee -a "$LOG"
