#!/usr/bin/env bash
# Rebuild Stage 2 comparison JSON + matrix from current runs (no model load).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT"

THINKING=off
BL_N="${PHASE1_STAGE2_BL_N:-200}"
SEED="${PHASE1_SEED:-42}"
SUM_DIR="runs/phase1/stage2/summaries"

uv run python "$ROOT/benchmark/summarize_triage.py" \
  --case-dir benchmark/corpora/fp_codeql --gold FP \
  --runs "runs/phase1/stage2/fp/thinking_${THINKING}" \
  --profile qwen3_4b_bnb --profile qwen3_8b_bnb --profile qwen3_14b_bnb \
  --json-out "$SUM_DIR/comparison_fp_full_thinking_${THINKING}.json"

uv run python "$ROOT/benchmark/summarize_triage.py" \
  --case-dir benchmark/corpora/tp_codeql --gold TP \
  --runs "runs/phase1/stage2/tp/thinking_${THINKING}" \
  --profile qwen3_4b_bnb --profile qwen3_8b_bnb --profile qwen3_14b_bnb \
  --json-out "$SUM_DIR/comparison_tp_full_thinking_${THINKING}.json"

uv run python "$ROOT/benchmark/summarize_borderline.py" \
  --case-dir "benchmark/corpora/borderline_n${BL_N}_seed${SEED}" \
  --runs "runs/phase1/stage2/bl/thinking_${THINKING}" \
  --profile qwen3_4b_bnb --profile qwen3_8b_bnb --profile qwen3_14b_bnb \
  --json-out "$SUM_DIR/comparison_bl_n${BL_N}_thinking_${THINKING}.json"

uv run python "$ROOT/benchmark/phases/phase1/stage2/merge_stage2_summary.py" \
  --fp-json "$SUM_DIR/comparison_fp_full_thinking_${THINKING}.json" \
  --tp-json "$SUM_DIR/comparison_tp_full_thinking_${THINKING}.json" \
  --bl-json "$SUM_DIR/comparison_bl_n${BL_N}_thinking_${THINKING}.json" \
  --profiles qwen3_4b_bnb qwen3_8b_bnb qwen3_14b_bnb \
  --manifest "benchmark/corpora/borderline_n${BL_N}_seed${SEED}_manifest.json" \
  --json-out "$SUM_DIR/phase1_stage2_matrix_thinking_${THINKING}.json"

uv run python "$ROOT/benchmark/phases/phase1/stage2/report_timing_stage2.py" \
  --json-out "$ROOT/benchmark/phase1_stage2_timing_report.json"

echo "Summaries refreshed."
