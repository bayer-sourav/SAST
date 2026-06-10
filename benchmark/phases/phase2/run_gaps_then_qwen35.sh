#!/usr/bin/env bash
# Finish core gap cells, then run Qwen3.5 extension supervisor (single pipeline lock).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

LOG_DIR="runs/phase2/logs"
mkdir -p "$LOG_DIR"
LOCK="$LOG_DIR/pipeline.lock"
PIPELINE_LOG="$LOG_DIR/pipeline.log"
QWEN35_LOG="$LOG_DIR/qwen35_extension.log"
SCRIPT_DIR="$ROOT/benchmark/phases/phase2"

exec 200>"$LOCK"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] pipeline: another instance holds $LOCK; exiting 1" >> "$PIPELINE_LOG"
  exit 1
fi

date -Iseconds > "$LOG_DIR/pipeline_started_at.txt"
echo "[$(date -Iseconds)] pipeline: started pid=$$" | tee -a "$PIPELINE_LOG"

echo "[$(date -Iseconds)] pipeline: running finish_core_gaps" >> "$PIPELINE_LOG"
uv run python "$SCRIPT_DIR/finish_core_gaps.py" >> "$PIPELINE_LOG" 2>&1
gaps_ec=$?
echo "[$(date -Iseconds)] pipeline: finish_core_gaps exited ec=${gaps_ec}" >> "$PIPELINE_LOG"

echo "[$(date -Iseconds)] pipeline: starting qwen35 supervisor" >> "$PIPELINE_LOG"
bash "$SCRIPT_DIR/run_phase2_qwen35_supervisor.sh" >> "$QWEN35_LOG" 2>&1
sup_ec=$?
echo "[$(date -Iseconds)] pipeline: qwen35 supervisor exited ec=${sup_ec}" >> "$PIPELINE_LOG"
exit "$sup_ec"
