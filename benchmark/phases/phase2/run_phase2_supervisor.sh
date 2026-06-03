#!/usr/bin/env bash
# Auto-restart Phase 2 matrix until finished_at.txt exists (OOM / batch failures).
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
PHASE2_LOG_FILE="${PHASE2_LOG_FILE:-$LOG_DIR/master.log}"
MATRIX="$ROOT/benchmark/phases/phase2/run_phase2_matrix.sh"
LOCK="$LOG_DIR/supervisor.lock"

# shellcheck source=phase2_cell_env.sh
source "$ROOT/benchmark/phase2_cell_env.sh"

exec 200>"$LOCK"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] supervisor: another instance holds $LOCK; exiting 1" >&2
  exit 1
fi

echo $$ > "$LOG_DIR/supervisor.pid"
echo "[$(date -Iseconds)] supervisor: started pid=$$" | tee -a "$PHASE2_LOG_FILE"

while true; do
  date -Iseconds > "$LOG_DIR/heartbeat_at.txt"
  if [[ -f "$LOG_DIR/finished_at.txt" ]]; then
    echo "[$(date -Iseconds)] supervisor: finished_at.txt present; exiting 0" | tee -a "$PHASE2_LOG_FILE"
    exit 0
  fi

  echo "[$(date -Iseconds)] supervisor: launching matrix (PHASE2_SKIP_REBUILD=1)" | tee -a "$PHASE2_LOG_FILE"
  _phase2_heartbeat_loop() {
    while true; do
      date -Iseconds > "$LOG_DIR/heartbeat_at.txt"
      sleep 60
    done
  }
  _phase2_heartbeat_loop &
  HB_PID=$!
  set +e
  PHASE2_SKIP_REBUILD=1 bash "$MATRIX"
  matrix_ec=$?
  set -e
  kill "$HB_PID" 2>/dev/null || true
  wait "$HB_PID" 2>/dev/null || true
  echo "[$(date -Iseconds)] supervisor: matrix exited ec=${matrix_ec}" | tee -a "$PHASE2_LOG_FILE"

  if [[ -f "$LOG_DIR/finished_at.txt" ]]; then
    echo "[$(date -Iseconds)] supervisor: matrix finished; exiting 0" | tee -a "$PHASE2_LOG_FILE"
    exit 0
  fi

  phase2_gpu_cleanup "$PHASE2_LOG_FILE" || true
  if [[ "$matrix_ec" -eq 2 && "${PHASE2_ALLOW_CPU:-}" != "1" ]]; then
    echo "[$(date -Iseconds)] supervisor: waiting for GPU (matrix ec=2); sleeping 300s before restart" | tee -a "$PHASE2_LOG_FILE"
    sleep 300
  else
    echo "[$(date -Iseconds)] supervisor: sleeping 45s before restart" | tee -a "$PHASE2_LOG_FILE"
    sleep 45
  fi
done
