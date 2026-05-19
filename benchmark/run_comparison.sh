#!/usr/bin/env bash
# Usage: ./benchmark/run_comparison.sh <N> <case-dir> <gold> [runs-root]
set -euo pipefail
cd "$(dirname "$0")/.."
N="${1:-45}"
CASE_DIR="${2:-benchmark/rq1_codeql_only}"
GOLD="${3:-FP}"
RUNS_ROOT="${4:-runs}"
JSON_OUT="${RUNS_ROOT}/comparison_${GOLD,,}_${N}.json"

echo "=== Cases: $CASE_DIR (gold=$GOLD, n=$N) ==="
for PROFILE in qwen3_4b_bnb qwen3_8b_bnb; do
  echo "--- $PROFILE ---"
  uv run python benchmark/run_batch.py \
    --agent llm --case-dir "$CASE_DIR" --max-cases "$N" --profile "$PROFILE" \
    --runs-root "$RUNS_ROOT" --gold "$GOLD"
done

echo "=== Repair + summarize ==="
for PROFILE in qwen3_4b_bnb qwen3_8b_bnb; do
  uv run python benchmark/repair_llm_results.py --runs "$RUNS_ROOT" --profile "$PROFILE" || true
done
uv run python benchmark/summarize_triage.py \
  --case-dir "$CASE_DIR" --max-cases "$N" --gold "$GOLD" --runs "$RUNS_ROOT" \
  --json-out "$JSON_OUT"
