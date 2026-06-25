#!/usr/bin/env bash
# Rebuild Phase 3B + Phase 2 benchmark tables from on-disk summaries.
set -euo pipefail
ROOT="/home/ec2-user/Projects/SAST"
cd "$ROOT"
export PYTHONPATH="${ROOT}:${ROOT}/benchmark${PYTHONPATH:+:$PYTHONPATH}"
PY="${ROOT}/.venv/bin/python"

echo "=== Phase 3B reports $(date -Iseconds) ==="
"$PY" benchmark/phases/phase3/report_phase3b_test.py
"$PY" benchmark/phases/phase3/report_phase3b_ablations.py
"$PY" benchmark/phases/phase3/report_phase3b_fs0_best.py
echo "=== Phase 3B benchmark $(date -Iseconds) ==="
"$PY" benchmark/phases/phase3/build_phase3b_benchmark_tables.py
echo "=== Phase 2 benchmark (+ Phase 3B rows) $(date -Iseconds) ==="
"$PY" benchmark/phases/phase2/build_results_tables.py
echo "=== Publish reports/phase3b $(date -Iseconds) ==="
"$PY" benchmark/phases/phase3/publish_phase3b_reports.py
echo "=== done ==="
