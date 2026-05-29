#!/usr/bin/env bash
# Create benchmark/corpora symlinks to full CodeQL corpora.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p benchmark/corpora
ln -sfn ../rq1_codeql_only benchmark/corpora/fp_codeql
ln -sfn ../tp_codeql_only benchmark/corpora/tp_codeql
echo "benchmark/corpora/fp_codeql -> benchmark/rq1_codeql_only"
echo "benchmark/corpora/tp_codeql -> benchmark/tp_codeql_only"
echo "Run: uv run python benchmark/build_borderline_cases.py"
