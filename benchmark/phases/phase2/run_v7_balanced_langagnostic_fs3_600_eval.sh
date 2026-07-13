#!/usr/bin/env bash
# 600-case eval: lang-agnostic v7-balanced + fs3 (v2_3shot_tp_2fp) vs Stage 2 Java baseline.
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
PROMPT="${SAST_PROMPT_VERSION:-v7-balanced-langagnostic}"
FS_CONFIG="${SAST_FEWSHOT_CONFIG:-v2_3shot_tp_2fp}"
FEWSHOT="${LANGAGNOSTIC_FEWSHOT:-3}"
SKIP_INFER="${SKIP_INFER:-0}"

EVAL_ROOT="${LANGAGNOSTIC_EVAL_ROOT:-runs/v7_balanced_langagnostic_fs3_eval}"
SUM_DIR="$EVAL_ROOT/summaries"
LOG="$EVAL_ROOT/eval_600.log"
TRACKS_JSON="$EVAL_ROOT/tp_fp_bl_tracks.json"
STAGE2_SUM_DIR="runs/phase2/stage2/summaries"
mkdir -p "$SUM_DIR" "$(dirname "$LOG")"

RUNS_FP="$EVAL_ROOT/fp/langagnostic_fs3"
RUNS_TP="$EVAL_ROOT/tp/langagnostic_fs3"
RUNS_BL="$EVAL_ROOT/bl/langagnostic_fs3"

echo "=== Lang-agnostic v7-balanced fs3 600-case eval ($PROMPT) $(date -Iseconds) ===" | tee "$LOG"
echo "eval_root=$EVAL_ROOT skip_infer=$SKIP_INFER fs=$FEWSHOT config=$FS_CONFIG" | tee -a "$LOG"

if [[ "$SKIP_INFER" != "1" ]]; then
  cat > "$TRACKS_JSON" <<EOF
[
  {"gold": "FP", "case_dir": "benchmark/corpora/phase2_fp_test", "runs_root": "$RUNS_FP"},
  {"gold": "TP", "case_dir": "benchmark/corpora/phase2_tp_test", "runs_root": "$RUNS_TP"},
  {"gold": "BL", "case_dir": "benchmark/corpora/phase2_bl_test", "runs_root": "$RUNS_BL"}
]
EOF
  echo "[1/2] Inference FP + TP + BL ($PROMPT, $FEWSHOT-shot)" | tee -a "$LOG"
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

echo "[2/2] Summarize + compare vs Stage 2 (Java v7-balanced fs3)" | tee -a "$LOG"
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
  --md-out "$EVAL_ROOT/LANGAGNOSTIC_FS3_600_REPORT.md" 2>&1 | tee -a "$LOG"

uv run python "$ROOT/benchmark/phases/phase2/compare_langagnostic_vs_stage2.py" \
  --candidate-sum-dir "$SUM_DIR" \
  --baseline-sum-dir "$STAGE2_SUM_DIR" \
  --profile "$PROFILE" \
  --candidate-label "Lang-agnostic v7-balanced fs3" \
  --baseline-label "Stage 2 Java v7-balanced fs3 (5.9b_fs3_legacy)" \
  --json-out "$SUM_DIR/compare_vs_stage2.json" \
  --md-out "$EVAL_ROOT/COMPARE_VS_STAGE2.md" 2>&1 | tee -a "$LOG"

echo "Done. $EVAL_ROOT/COMPARE_VS_STAGE2.md" | tee -a "$LOG"
