#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

pkill -9 -f run_phase2_supervisor.sh 2>/dev/null || true
pkill -9 -f run_phase2_matrix.sh 2>/dev/null || true
pkill -9 -f 'run_batch.py.*runs/phase2' 2>/dev/null || true
sleep 2

rm -rf runs/phase2/fp runs/phase2/tp runs/phase2/bl runs/phase2/summaries runs/phase2/_verify runs/phase2/smoke
mkdir -p runs/phase2/logs

if [[ -f runs/phase2/logs/master.log ]]; then
  ts=$(date +%Y%m%dT%H%M%S)
  cp runs/phase2/logs/master.log "runs/phase2/logs/master.log.bak-${ts}" 2>/dev/null || true
fi

echo "=== Phase 2 full matrix restart (prompt v2) $(date -Iseconds) ===" > runs/phase2/logs/master.log

uv run python -c "from benchmark.local_model_unload import release_gpu_memory; release_gpu_memory()" 2>/dev/null || true

export PHASE2_SMOKE_MAX=0
nohup bash "$ROOT/benchmark/phases/phase2/run_phase2_supervisor.sh" >> runs/phase2/logs/master.log 2>&1 &
echo "$!" > runs/phase2/logs/supervisor.pid
echo "Started phase2 supervisor PID=$(cat runs/phase2/logs/supervisor.pid)"
