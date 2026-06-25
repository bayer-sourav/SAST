#!/usr/bin/env bash
# Phase 3B test ablations: zero-shot and thinking-off cells for fine-tuned LoRA.
set -euo pipefail
ROOT="/home/ec2-user/Projects/SAST"
cd "$ROOT"

export PHASE3_STAGE=3b
export SAST_LORA_ADAPTER="${SAST_LORA_ADAPTER:-runs/phase3/stage3b/lora/best}"
export PHASE3_PROMPT_VERSION="${PHASE3_PROMPT_VERSION:-v7-ship}"

LOG="runs/phase3/stage3b/logs/ablations.log"
echo "=== Phase 3B ablations $(date -Iseconds) ===" | tee "$LOG"

# id:fewshot:thinking  (run in order: fastest/most promising first)
CELLS="${PHASE3B_ABLATION_CELLS:-fs0_off:0:off fs3_off:3:off fs0_on:0:on}"

for spec in $CELLS; do
  IFS=: read -r cell_id fewshot thinking <<< "$spec"
  echo "--- cell $cell_id (fs=$fewshot think=$thinking) $(date -Iseconds) ---" | tee -a "$LOG"
  export PHASE3_FEWSHOT="$fewshot"
  export PHASE3_THINKING="$thinking"
  export PHASE3_EVAL_ROOT="runs/phase3/stage3b/eval_ablation/${cell_id}"
  export PHASE3_SUM_SUFFIX="_${cell_id}"
  export PHASE3_LOG_NAME="eval_${cell_id}.log"
  bash benchmark/phases/phase3/run_phase3_eval.sh 2>&1 | tee -a "$LOG"
done

"$ROOT/.venv/bin/python" benchmark/phases/phase3/report_phase3b_ablations.py 2>&1 | tee -a "$LOG"
echo "=== Phase 3B ablations done $(date -Iseconds) ===" | tee -a "$LOG"
