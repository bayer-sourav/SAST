#!/usr/bin/env bash
# Poll Phase 1 every INTERVAL_SEC; resume GPT-OSS monitor or full matrix when idle.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=phase1_lib.sh
source "$(dirname "$0")/phase1_lib.sh"

INTERVAL_SEC="${PHASE1_WATCHDOG_INTERVAL_SEC:-120}"
LOG="benchmark/phase1_logs/watchdog.log"
STATUS="benchmark/phase1_logs/watchdog_status.txt"
mkdir -p benchmark/phase1_logs

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG"; }

log "Watchdog started interval=${INTERVAL_SEC}s status=$STATUS"

while true; do
  uv run python benchmark/phase1_watchdog.py --quiet 2>/dev/null || true
  tail -3 "$STATUS" >> "$LOG" 2>/dev/null || true

  if phase1_matrix_finished; then
    log "matrix finished flag present — idle"
  elif phase1_runner_active; then
    log "runner active — idle"
  elif phase1_gpt_incomplete; then
    log "GPT-OSS incomplete (FP=$(phase1_gpt_fp_ok)/${PHASE1_N} TP=$(phase1_gpt_tp_ok)/${PHASE1_N}) — start monitor"
    phase1_gpu_cleanup
    nohup bash ./benchmark/monitor_gpt_oss_rerun.sh >> benchmark/phase1_logs/gpt_oss_inprocess.out 2>&1 &
    log "Started monitor PID=$!"
  else
    log "GPT-OSS complete; matrix not finished — start run_phase1_matrix"
    nohup env PHASE1_SKIP_SLICE=1 bash ./benchmark/run_phase1_matrix.sh >> benchmark/phase1_logs/matrix_resume.out 2>&1 &
    log "Started matrix PID=$!"
  fi

  sleep "$INTERVAL_SEC"
done
