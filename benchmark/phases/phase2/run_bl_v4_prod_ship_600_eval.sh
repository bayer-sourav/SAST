#!/usr/bin/env bash
# 600-case test eval: FP + TP + BL with prod ship config (v8-ship-bl + 4-shot).
# BL track: reuse runs/bl_v4_prod_ship_eval/stage2_ship_bl unless BL_FORCE_RERUN=1.
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
FEWSHOT="${PROD_SHIP_FEWSHOT:-4}"
SKIP_INFER="${SKIP_INFER:-0}"
BL_FORCE="${BL_FORCE_RERUN:-0}"

EVAL_ROOT="${PROD_SHIP_EVAL_ROOT:-runs/bl_v4_prod_ship_eval}"
SUM_DIR="$EVAL_ROOT/summaries"
LOG="$EVAL_ROOT/eval_600.log"
TRACKS_JSON="$EVAL_ROOT/tp_fp_tracks.json"
mkdir -p "$SUM_DIR" "$(dirname "$LOG")"

RUNS_FP="$EVAL_ROOT/fp/stage2_ship_bl"
RUNS_TP="$EVAL_ROOT/tp/stage2_ship_bl"
RUNS_BL="$EVAL_ROOT/stage2_ship_bl"

echo "=== Prod ship 600-case eval ($PROMPT fs=$FEWSHOT) $(date -Iseconds) ===" | tee "$LOG"
echo "eval_root=$EVAL_ROOT skip_infer=$SKIP_INFER" | tee -a "$LOG"

if [[ "$SKIP_INFER" != "1" ]]; then
  cat > "$TRACKS_JSON" <<EOF
[
  {"gold": "FP", "case_dir": "benchmark/corpora/phase2_fp_test", "runs_root": "$EVAL_ROOT/fp/stage2_ship_bl"},
  {"gold": "TP", "case_dir": "benchmark/corpora/phase2_tp_test", "runs_root": "$EVAL_ROOT/tp/stage2_ship_bl"}
]
EOF
  echo "[1/2] Inference FP + TP ($PROMPT, $FEWSHOT-shot)" | tee -a "$LOG"
  phase2_gpu_cleanup "$LOG"
  uv run python "$ROOT/benchmark/run_batch.py" \
    --agent llm \
    --profile "$PROFILE" \
    --prompt-version "$PROMPT" \
    --thinking \
    --few-shot "$FEWSHOT" \
    --few-shot-config "$FS_CONFIG" \
    --tracks-json "$TRACKS_JSON" \
    --retry-missing \
    --force 2>&1 | tee -a "$LOG"
  phase2_gpu_cleanup "$LOG"
else
  echo "[1/2] Skipped inference (SKIP_INFER=1)" | tee -a "$LOG"
fi

if [[ "$BL_FORCE" == "1" ]]; then
  echo "[BL] Re-running BL track (BL_FORCE_RERUN=1)" | tee -a "$LOG"
  BL_V4_SKIP_REBUILD=1 BL_V4_FORCE_RERUN=1 \
    BL_V4_RUNS_ROOT="$RUNS_BL" BL_V4_REVIEW_DIR="$EVAL_ROOT" \
    bash "$ROOT/benchmark/phases/phase2/run_bl_v4_eval.sh" 2>&1 | tee -a "$LOG"
fi

echo "[2/2] Summarize FP + TP + BL + merged SRS" | tee -a "$LOG"
uv run python "$ROOT/benchmark/summarize_triage.py" \
  --case-dir benchmark/corpora/phase2_fp_test \
  --gold FP \
  --runs "$RUNS_FP" \
  --profile "$PROFILE" \
  --json-out "$SUM_DIR/comparison_fp.json" 2>&1 | tee -a "$LOG"

uv run python "$ROOT/benchmark/summarize_triage.py" \
  --case-dir benchmark/corpora/phase2_tp_test \
  --gold TP \
  --runs "$RUNS_TP" \
  --profile "$PROFILE" \
  --json-out "$SUM_DIR/comparison_tp.json" 2>&1 | tee -a "$LOG"

uv run python "$ROOT/benchmark/summarize_borderline.py" \
  --case-dir benchmark/corpora/phase2_bl_test \
  --runs "$RUNS_BL" \
  --profile "$PROFILE" \
  --json-out "$SUM_DIR/comparison_bl.json" 2>&1 | tee -a "$LOG"

uv run python "$ROOT/benchmark/phases/phase2/merge_prod_ship_600_summary.py" \
  --sum-dir "$SUM_DIR" \
  --profile "$PROFILE" \
  --json-out "$SUM_DIR/merged_600.json" \
  --md-out "$EVAL_ROOT/PROD_SHIP_600_REPORT.md" 2>&1 | tee -a "$LOG"

echo "Done. $EVAL_ROOT/PROD_SHIP_600_REPORT.md" | tee -a "$LOG"
