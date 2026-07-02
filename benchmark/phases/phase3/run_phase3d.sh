#!/usr/bin/env bash
# Phase 3D: TP→FP error analysis → hard-neg export → CSS train → constrained rerank → test.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

# shellcheck source=phase3d_env.sh
source "$ROOT/benchmark/phases/phase3/phase3d_env.sh"

LOG="$PHASE3D_ROOT/logs/phase3d.log"
mkdir -p "$PHASE3D_ROOT"/{logs,summaries,data,lora,val_eval,eval}

_log_tee() {
  if [[ -n "${PHASE3_RESUME_CHECKPOINT:-}" ]]; then
    tee -a "$LOG"
  else
    tee "$LOG"
  fi
}

echo "=== Phase 3D start $(date -Iseconds) ===" | _log_tee
echo "[phase3d] manifest=$PHASE3_MANIFEST experiment=${PHASE3D_EXPERIMENT:-3d-001}" | tee -a "$LOG"
if [[ -n "${PHASE3_RESUME_CHECKPOINT:-}" ]]; then
  echo "[phase3d] resume checkpoint=$PHASE3_RESUME_CHECKPOINT" | tee -a "$LOG"
fi

if [[ "${PHASE3D_SKIP_ANALYSIS:-0}" != "1" ]]; then
  echo "[phase3d] TP→FP error analysis (3C eval → hard_negatives.json)" | tee -a "$LOG"
  .venv/bin/python "$ROOT/benchmark/phases/phase3/analyze_tp_fp_errors.py" \
    --eval-root "$ROOT/runs/phase3/stage3c/eval" \
    --out "$PHASE3D_HARD_NEG_JSON" \
    --report "$PHASE3D_ROOT/summaries/PHASE3D_TP_FP_ANALYSIS.md" \
    >> "$LOG" 2>&1
else
  echo "[phase3d] skip error analysis" | tee -a "$LOG"
fi

if [[ "${PHASE3D_SKIP_EXPORT:-0}" != "1" ]]; then
  echo "[phase3d] export distill JSONL (tracks=$PHASE3D_TRAIN_TRACKS oversample=$PHASE3D_OVERSAMPLE_FACTOR)" | tee -a "$LOG"
  .venv/bin/python "$ROOT/benchmark/phases/phase3/export_distill_dataset.py" \
    --max-total-tokens "${PHASE3_MAX_SEQ_LEN}" \
    --tracks "$PHASE3D_TRAIN_TRACKS" \
    --hard-neg-json "$PHASE3D_HARD_NEG_JSON" \
    --oversample-factor "$PHASE3D_OVERSAMPLE_FACTOR" \
    >> "$LOG" 2>&1
fi

.venv/bin/python "$ROOT/benchmark/phases/phase3/preflight_phase3.py" --stage 3d | tee -a "$LOG"

if [[ "${PHASE3D_SKIP_TRAIN:-0}" != "1" ]]; then
  for r in $PHASE3_LORA_RANKS; do
    echo "[phase3d] train rank=$r (CSS val fs0_off every ${PHASE3_CSS_EVAL_EVERY} epochs, auto-resume on)" | tee -a "$LOG"
    bash "$ROOT/benchmark/phases/phase3/run_train_auto_resume.sh" "$r"
  done
fi

if [[ "${PHASE3D_SKIP_RERANK:-0}" != "1" ]]; then
  echo "[phase3d] full val rerank (constrained SRS pick)" | tee -a "$LOG"
  .venv/bin/python "$ROOT/benchmark/phases/phase3/rerank_val_checkpoints.py" >> "$LOG" 2>&1
fi

if [[ "${PHASE3D_SKIP_TEST:-0}" != "1" ]]; then
  export SAST_LORA_ADAPTER="${PHASE3_BEST_ADAPTER:-$PHASE3D_ROOT/lora/best}"
  echo "[phase3d] test eval adapter=$SAST_LORA_ADAPTER (fs0_off)" | tee -a "$LOG"
  bash "$ROOT/benchmark/phases/phase3/run_phase3_eval.sh" >> "$LOG" 2>&1
fi

echo "=== Phase 3D complete $(date -Iseconds) ===" | tee -a "$LOG"
