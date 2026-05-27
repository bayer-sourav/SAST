#!/usr/bin/env bash
# Rebuild Phase 1 metrics from run artifacts on disk.
# Syncs gpt_oss thinking_on from thinking_off, then summarize + merge + timing report.
set -euo pipefail
cd "$(dirname "$0")/.."

echo "--- $(date -Iseconds) fill gpt_oss thinking_on (copy from thinking_off) ---"
uv run python benchmark/fill_gpt_oss_thinking_on.py

SEED="${PHASE1_SEED:-42}"
N="${PHASE1_N:-50}"
SLICE_FP="benchmark/phase1_slices/fp_n${N}_seed${SEED}"
SLICE_TP="benchmark/phase1_slices/tp_n${N}_seed${SEED}"
FP_RUNS="FP-runs/phase1_n50"
TP_RUNS="TP-runs/phase1_n50"
LOG_DIR="benchmark/phase1_logs"
mkdir -p "$LOG_DIR"

PROFILES=(
  qwen3_4b_bnb
  qwen3_8b_bnb
  qwen3_14b_bnb
  gpt_oss_20b
  qwen3_coder_30b_bnb
)

summarize_track() {
  local thinking_flag="$1"
  local gold="$2"
  local case_dir="$3"
  local runs_root="$4"
  local json_out="$runs_root/comparison_${gold,,}_n${N}_thinking_${thinking_flag}.json"
  local -a prof_args=()
  for p in "${PROFILES[@]}"; do
    prof_args+=(--profile "$p")
  done
  echo "--- summarize $gold thinking=$thinking_flag ---"
  uv run python benchmark/summarize_triage.py \
    --case-dir "$case_dir" \
    --gold "$gold" \
    --runs "$runs_root/thinking_${thinking_flag}" \
    "${prof_args[@]}" \
    --json-out "$json_out"
}

for THINKING in off on; do
  summarize_track "$THINKING" FP "$SLICE_FP" "$FP_RUNS"
  summarize_track "$THINKING" TP "$SLICE_TP" "$TP_RUNS"
  uv run python benchmark/merge_phase1_summary.py \
    --fp-json "$FP_RUNS/comparison_fp_n${N}_thinking_${THINKING}.json" \
    --tp-json "$TP_RUNS/comparison_tp_n${N}_thinking_${THINKING}.json" \
    --profiles "${PROFILES[@]}" \
    --thinking "$THINKING" \
    --manifest "${SLICE_FP}_manifest.json" \
    --json-out "$FP_RUNS/phase1_matrix_thinking_${THINKING}.json"
done

COMBINED_OUT="benchmark/phase1_combined_summary.json"
uv run python -c "
import json
from pathlib import Path
fp_runs = Path('$FP_RUNS')
out = {'n_cases': $N, 'seed': $SEED, 'thinking': {}, 'profiles': $(printf '%s\n' "${PROFILES[@]}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip().split()))')}
for t in ('off', 'on'):
    p = fp_runs / f'phase1_matrix_thinking_{t}.json'
    if p.is_file():
        out['thinking'][t] = json.loads(p.read_text())
Path('$COMBINED_OUT').write_text(json.dumps(out, indent=2))
print('Wrote $COMBINED_OUT')
"

uv run python benchmark/report_timing.py --json-out benchmark/phase1_timing_report.json \
  >> "$LOG_DIR/timing.log" 2>&1 || true
echo "--- $(date -Iseconds) refresh_phase1_summaries done ---"
