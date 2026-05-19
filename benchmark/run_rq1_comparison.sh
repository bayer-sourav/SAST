#!/usr/bin/env bash
# Shortcut: RQ1 FP corpus, 45 cases, default runs root.
# Usage: ./benchmark/run_rq1_comparison.sh [N]
set -euo pipefail
N="${1:-45}"
exec "$(dirname "$0")/run_comparison.sh" "$N" benchmark/rq1_codeql_only FP runs
