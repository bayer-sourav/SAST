#!/usr/bin/env bash
# Resume Phase 2 without deleting fp/tp/bl run data; supervisor auto-restarts matrix.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

LOG_DIR="runs/phase2/logs"
SUP="$ROOT/benchmark/phases/phase2/run_phase2_supervisor.sh"
MASTER="$LOG_DIR/master.log"

mkdir -p "$LOG_DIR"

echo "[$(date -Iseconds)] resume_phase2: stopping prior matrix/supervisor (SIGTERM)..." | tee -a "$MASTER"
pkill -TERM -f run_phase2_supervisor.sh 2>/dev/null || true
pkill -TERM -f run_phase2_matrix.sh 2>/dev/null || true
pkill -TERM -f 'run_batch.py.*runs/phase2' 2>/dev/null || true
sleep 3
pkill -KILL -f run_phase2_supervisor.sh 2>/dev/null || true
pkill -KILL -f run_phase2_matrix.sh 2>/dev/null || true
pkill -KILL -f 'run_batch.py.*runs/phase2' 2>/dev/null || true
sleep 1

uv run python -c "from benchmark.local_model_unload import release_gpu_memory; release_gpu_memory()" 2>/dev/null || true

nohup bash "$SUP" >> "$MASTER" 2>&1 &
sup_pid=$!
echo "$sup_pid" > "$LOG_DIR/supervisor.pid"
echo "[$(date -Iseconds)] resume_phase2: started supervisor PID=${sup_pid}" | tee -a "$MASTER"
echo "Supervisor PID: ${sup_pid}"
echo "Monitor: tail -f ${ROOT}/${MASTER}"
echo "Status:  cd ${ROOT} && uv run python benchmark/phases/phase2/status_phase2.py"
