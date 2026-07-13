#!/usr/bin/env bash
# Fast BL v4 feedback loop: 40-case pilot (10/category), ~20–30 min vs ~2h full test.
#
# Usage:
#   bash benchmark/phases/phase2/run_bl_v4_pilot_fast.sh              # rebuild + infer + review
#   PILOT_SKIP_REBUILD=1 bash benchmark/phases/phase2/run_bl_v4_pilot_fast.sh   # infer only
#   PILOT_PER_CATEGORY=5 bash ...                                   # 20 cases (~10 min)
#
# Outputs: runs/bl_v4_pilot_fast_v3/pilot_review_ship_bl.json, PILOT_REVIEW_SHIP_BL.html
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

PROFILE="qwen3_5_9b_bnb"
PROMPT="${SAST_PROMPT_VERSION:-v8-ship-bl}"
FS_CONFIG="${SAST_FEWSHOT_CONFIG:-v2_4shot_tp_fp_bl2}"
FEWSHOT="${PILOT_FEWSHOT:-4}"
FORCE="${PILOT_FORCE_RERUN:-1}"
SKIP_REBUILD="${PILOT_SKIP_REBUILD:-0}"
PER_CAT="${PILOT_PER_CATEGORY:-10}"

CORPUS="${BL_V4_PILOT_CORPUS:-benchmark/corpora/bl_v4_pilot}"
RUNS="${BL_V4_PILOT_RUNS:-runs/bl_v4_pilot_fast_v3/stage2_ship_bl}"
REVIEW_DIR="${BL_V4_PILOT_REVIEW:-runs/bl_v4_pilot_fast_v3}"
LOG="$ROOT/$REVIEW_DIR/pilot_fast.log"
mkdir -p "$(dirname "$LOG")" "$RUNS" "$REVIEW_DIR"

echo "=== BL v4 pilot FAST (40-case feedback) $(date -Iseconds) ===" | tee "$LOG"
echo "prompt=$PROMPT fewshot=$FEWSHOT config=$FS_CONFIG per_category=$PER_CAT skip_rebuild=$SKIP_REBUILD" | tee -a "$LOG"

if [[ "$SKIP_REBUILD" != "1" ]]; then
  echo "[1/3] Build pilot bundles ($PER_CAT per category)" | tee -a "$LOG"
  python3 "$DATASET/scripts/build_borderline_v4_pilot.py" \
    --out "$DATASET/BenchmarkJava/borderline_pilot" \
    --per-category "$PER_CAT" 2>&1 | tee -a "$LOG"

  echo "[2/3] Publish pilot corpus" | tee -a "$LOG"
  uv run python "$ROOT/benchmark/build_bl_v4_pilot_corpus.py" \
    --pilot-root "$DATASET/BenchmarkJava/borderline_pilot" \
    --out-dir "$ROOT/$CORPUS" 2>&1 | tee -a "$LOG"
else
  echo "[1-2/3] Skipped rebuild (PILOT_SKIP_REBUILD=1)" | tee -a "$LOG"
fi

N="$(find "$ROOT/$CORPUS" -maxdepth 1 -name 'BenchmarkTest*.json' | wc -l | tr -d ' ')"
echo "[pilot] $N cases in $CORPUS" | tee -a "$LOG"

FORCE_ARGS=()
if [[ "$FORCE" == "1" ]]; then
  FORCE_ARGS=(--force)
fi

echo "[3/3] Inference + review" | tee -a "$LOG"
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

uv run python "$ROOT/benchmark/analyze_bl_v4_pilot.py" \
  --corpus "$CORPUS" \
  --runs "$RUNS" \
  --profile "$PROFILE" \
  --json-out "$ROOT/$REVIEW_DIR/pilot_review_ship_bl.json" \
  --html-out "$ROOT/$REVIEW_DIR/PILOT_REVIEW_SHIP_BL.html" 2>&1 | tee -a "$LOG"

echo "Done. Open $REVIEW_DIR/PILOT_REVIEW_SHIP_BL.html" | tee -a "$LOG"
