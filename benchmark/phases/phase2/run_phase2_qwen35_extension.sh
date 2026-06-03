#!/usr/bin/env bash
# Phase 2 extension: Qwen3.5-4B + Qwen3.5-9B (Unsloth 4-bit), same matrix as main Phase 2.
# Run after the primary matrix finishes (or in parallel on another GPU).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

export PHASE2_PROFILES="qwen3_5_4b_bnb qwen3_5_9b_bnb"
export PHASE2_SUMMARY_PROFILES="qwen3_4b_bnb qwen3_8b_bnb qwen3_14b_bnb qwen3_coder_30b_bnb qwen3_5_4b_bnb qwen3_5_9b_bnb"

LOG_DIR="runs/phase2/logs"
mkdir -p "$LOG_DIR"

export PHASE2_EXTENSION=1
export PHASE2_LOG_FILE="$LOG_DIR/qwen35_extension.log"

echo "=== Phase 2 Qwen3.5 extension ($(date -Iseconds)) ===" | tee -a "$PHASE2_LOG_FILE"
echo "Profiles: $PHASE2_PROFILES" | tee -a "$PHASE2_LOG_FILE"

bash "$ROOT/benchmark/phases/phase2/run_phase2_matrix.sh" 2>&1 | tee -a "$PHASE2_LOG_FILE"
