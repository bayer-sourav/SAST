#!/usr/bin/env bash
# Regenerate Phase 2 comparison JSONs for core 4 profiles (all 12 matrix cells).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

LOG_DIR="runs/phase2/logs"
SUM_DIR="runs/phase2/summaries"
mkdir -p "$LOG_DIR" "$SUM_DIR"

CORPORA_FP="benchmark/corpora/phase2_fp_test"
CORPORA_TP="benchmark/corpora/phase2_tp_test"
CORPORA_BL="benchmark/corpora/phase2_bl_test"

RUNS_FP="runs/phase2/fp"
RUNS_TP="runs/phase2/tp"
RUNS_BL="runs/phase2/bl"

SUMMARY_PROFILES=(
  qwen3_4b_bnb
  qwen3_8b_bnb
  qwen3_14b_bnb
  qwen3_coder_30b_bnb
)

summarize_cell() {
  local gold="$1"
  local case_dir="$2"
  local runs_root="$3"
  local thinking="$4"
  local fewshot="$5"
  local out="$6"
  local -a prof_args=()
  for p in "${SUMMARY_PROFILES[@]}"; do
    prof_args+=(--profile "$p")
  done

  if [[ "$gold" == "BL" ]]; then
    uv run python "$ROOT/benchmark/summarize_borderline.py" \
      --case-dir "$case_dir" \
      --runs "$runs_root/thinking_${thinking}/fewshot_${fewshot}" \
      "${prof_args[@]}" \
      --json-out "$out" || true
  else
    uv run python "$ROOT/benchmark/summarize_triage.py" \
      --case-dir "$case_dir" --gold "$gold" \
      --runs "$runs_root/thinking_${thinking}/fewshot_${fewshot}" \
      "${prof_args[@]}" \
      --json-out "$out" || true
  fi
}

echo "=== Phase 2 core summaries refresh ($(date -Iseconds)) ==="
for thinking in off on; do
  for fewshot in 0 3; do
    summarize_cell FP "$CORPORA_FP" "$RUNS_FP" "$thinking" "$fewshot" \
      "$SUM_DIR/comparison_fp_test_thinking_${thinking}_fewshot_${fewshot}.json"
    summarize_cell TP "$CORPORA_TP" "$RUNS_TP" "$thinking" "$fewshot" \
      "$SUM_DIR/comparison_tp_test_thinking_${thinking}_fewshot_${fewshot}.json"
    summarize_cell BL "$CORPORA_BL" "$RUNS_BL" "$thinking" "$fewshot" \
      "$SUM_DIR/comparison_bl_test_thinking_${thinking}_fewshot_${fewshot}.json"
  done
done

uv run python "$ROOT/benchmark/phases/phase2/merge_phase2_summary.py" \
  --summaries-dir "$SUM_DIR" \
  --json-out "$SUM_DIR/phase2_matrix.json"

echo "=== Core summaries merged -> $SUM_DIR/phase2_matrix.json ==="
