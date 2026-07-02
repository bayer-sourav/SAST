#!/usr/bin/env bash
# Phase 3C: ship-aligned distill export → CSS train → full val rerank → fs0 test eval.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

# shellcheck source=phase3c_env.sh
source "$ROOT/benchmark/phases/phase3/phase3c_env.sh"

LOG="$PHASE3C_ROOT/logs/phase3c.log"
mkdir -p "$PHASE3C_ROOT"/{logs,summaries,data,lora,val_eval,eval}

echo "=== Phase 3C start $(date -Iseconds) ===" | tee "$LOG"
echo "[phase3c] manifest=$PHASE3_MANIFEST" | tee -a "$LOG"

if [[ "${PHASE3C_SKIP_TEACHER:-1}" != "1" ]]; then
  echo "[phase3c] teacher on train (1500) — usually skipped; reuses 3B cache" | tee -a "$LOG"
  .venv/bin/python "$ROOT/benchmark/phases/phase3/run_stage2_teacher_on_split.py" \
    ${PHASE3C_SMOKE_MAX:+--smoke-max "$PHASE3C_SMOKE_MAX"} \
    >> "$LOG" 2>&1
else
  echo "[phase3c] skip teacher — using runs/phase3/stage3b/teacher/train" | tee -a "$LOG"
fi

if [[ "${PHASE3C_SKIP_EXPORT:-0}" != "1" ]]; then
  echo "[phase3c] export ship-aligned distill JSONL (json_only, fs0)" | tee -a "$LOG"
  .venv/bin/python "$ROOT/benchmark/phases/phase3/export_distill_dataset.py" \
    --max-total-tokens "${PHASE3_MAX_SEQ_LEN}" \
    >> "$LOG" 2>&1
fi

.venv/bin/python "$ROOT/benchmark/phases/phase3/preflight_phase3.py" --stage 3c | tee -a "$LOG"

if [[ "${PHASE3C_SKIP_TRAIN:-0}" != "1" ]]; then
  for r in $PHASE3_LORA_RANKS; do
    echo "[phase3c] train rank=$r (CSS val fs0_off every ${PHASE3_CSS_EVAL_EVERY} epochs, auto-resume on)" | tee -a "$LOG"
    bash "$ROOT/benchmark/phases/phase3/run_train_auto_resume.sh" "$r"
  done
fi

if [[ "${PHASE3C_SKIP_RERANK:-0}" != "1" ]]; then
  echo "[phase3c] full val rerank on CSS-eligible checkpoints" | tee -a "$LOG"
  .venv/bin/python "$ROOT/benchmark/phases/phase3/rerank_val_checkpoints.py" >> "$LOG" 2>&1
fi

export SAST_LORA_ADAPTER="${PHASE3_BEST_ADAPTER:-$PHASE3C_ROOT/lora/best}"
echo "[phase3c] test eval adapter=$SAST_LORA_ADAPTER (fs0_off)" | tee -a "$LOG"
bash "$ROOT/benchmark/phases/phase3/run_phase3_eval.sh" >> "$LOG" 2>&1

echo "=== Phase 3C complete $(date -Iseconds) ===" | tee -a "$LOG"
