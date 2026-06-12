#!/usr/bin/env bash
# Wait for the v3 best-profiles smoke job to release the GPU, then run Gemma 4 thinking on+off.
set -euo pipefail

SAST="/home/ec2-user/Projects/SAST"
export PYTHONPATH="${SAST}:${SAST}/benchmark"
LOG_DIR="$SAST/runs/smoke/v7_fewshot_v3_best_profiles/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/gemma4_thinking_supplement.log"

WAIT_PID="${1:-}"

if [[ -z "$WAIT_PID" ]]; then
  echo "usage: $0 <pid-to-wait-for>" | tee -a "$LOG"
  exit 1
fi

echo "--- $(date -Iseconds) waiting for pid=$WAIT_PID (v3 smoke) ---" | tee -a "$LOG"

while kill -0 "$WAIT_PID" 2>/dev/null; do
  sleep 60
done

echo "--- $(date -Iseconds) pid=$WAIT_PID exited; starting gemma4 supplement ---" | tee -a "$LOG"

cd "$SAST"
exec uv run python benchmark/phases/smoke/run_gemma4_thinking_smoke.py 2>&1 | tee -a "$LOG"
