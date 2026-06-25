#!/usr/bin/env bash
# Phase 3B orchestrator: infra → teacher → distill → train (rank sweep) → rerank → test eval.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

# shellcheck source=phase3b_env.sh
source "$ROOT/benchmark/phases/phase3/phase3b_env.sh"

LOG="$PHASE3B_ROOT/logs/phase3b.log"
mkdir -p "$PHASE3B_ROOT"/{logs,summaries,data,lora,val_eval,eval,teacher/train}

echo "=== Phase 3B start $(date -Iseconds) ===" | tee "$LOG"

if [[ "${PHASE3B_SKIP_INFRA:-0}" != "1" ]]; then
  bash "$ROOT/benchmark/phases/phase3/optimize_infra.sh" | tee -a "$LOG"
fi

# shellcheck source=phase2_cell_env.sh
source "$ROOT/benchmark/phase2_cell_env.sh"
phase2_apply_token_limits on qwen3_5_9b_bnb

if [[ "${PHASE3B_SKIP_TEACHER:-0}" != "1" ]]; then
  echo "[phase3b] teacher on train (1500)" | tee -a "$LOG"
  uv run python "$ROOT/benchmark/phases/phase3/run_stage2_teacher_on_split.py" \
    ${PHASE3B_SMOKE_MAX:+--smoke-max "$PHASE3B_SMOKE_MAX"} \
    >> "$LOG" 2>&1
fi

if [[ "${PHASE3B_SKIP_EXPORT:-0}" != "1" ]]; then
  echo "[phase3b] export distill JSONL" | tee -a "$LOG"
  uv run python "$ROOT/benchmark/phases/phase3/export_distill_dataset.py" >> "$LOG" 2>&1
fi

  .venv/bin/python "$ROOT/benchmark/phases/phase3/preflight_phase3.py" --stage 3b | tee -a "$LOG"

if [[ "${PHASE3B_SKIP_TRAIN:-0}" != "1" ]]; then
  for r in $PHASE3_LORA_RANKS; do
    echo "[phase3b] train rank=$r (css every ${PHASE3_CSS_EVAL_EVERY:-2} epochs)" | tee -a "$LOG"
    PHASE3_LORA_R="$r" PHASE3_LORA_ALPHA="$r" \
      .venv/bin/python "$ROOT/benchmark/phases/phase3/run_unsloth_lora_css.py" >> "$LOG" 2>&1
  done
fi

if [[ "${PHASE3B_SKIP_RERANK:-0}" != "1" ]]; then
  echo "[phase3b] rerank CSS-eligible on full val" | tee -a "$LOG"
  .venv/bin/python "$ROOT/benchmark/phases/phase3/rerank_val_checkpoints.py" >> "$LOG" 2>&1
fi

export SAST_LORA_ADAPTER="${PHASE3_BEST_ADAPTER:-$PHASE3B_ROOT/lora/best}"
export PHASE3_STAGE=3b
echo "[phase3b] test eval adapter=$SAST_LORA_ADAPTER" | tee -a "$LOG"
bash "$ROOT/benchmark/phases/phase3/run_phase3_eval.sh" >> "$LOG" 2>&1

echo "=== Phase 3B complete $(date -Iseconds) ===" | tee -a "$LOG"
