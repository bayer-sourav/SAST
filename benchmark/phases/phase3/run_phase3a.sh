#!/usr/bin/env bash
# Phase 3A orchestrator: export SFT data → preflight → train LoRA → eval on Phase 2 test.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

LOG="$ROOT/runs/phase3/stage3a/logs/phase3a.log"
mkdir -p "$(dirname "$LOG")"

echo "=== Phase 3A start $(date -Iseconds) ===" | tee "$LOG"

if [[ "${PHASE3_SKIP_EXPORT:-0}" != "1" ]]; then
  echo "[phase3a] export SFT dataset" | tee -a "$LOG"
  uv run python "$ROOT/benchmark/phases/phase3/export_sft_dataset.py" >> "$LOG" 2>&1
fi

uv run python "$ROOT/benchmark/phases/phase3/preflight_phase3.py" | tee -a "$LOG"

if [[ "${PHASE3_SKIP_TRAIN:-0}" != "1" ]]; then
  echo "[phase3a] train LoRA" | tee -a "$LOG"
  uv run python "$ROOT/benchmark/phases/phase3/run_unsloth_lora.py" >> "$LOG" 2>&1
fi

export SAST_LORA_ADAPTER="${SAST_LORA_ADAPTER:-$ROOT/runs/phase3/stage3a/lora/latest}"
echo "[phase3a] eval with adapter=$SAST_LORA_ADAPTER" | tee -a "$LOG"
bash "$ROOT/benchmark/phases/phase3/run_phase3_eval.sh" >> "$LOG" 2>&1

echo "=== Phase 3A complete $(date -Iseconds) ===" | tee -a "$LOG"
