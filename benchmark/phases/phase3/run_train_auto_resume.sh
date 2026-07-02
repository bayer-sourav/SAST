#!/usr/bin/env bash
# Run LoRA+CSS training with auto-resume from latest checkpoint on unexpected exit.
# Expects ROOT, PHASE3_MANIFEST, and phase env already sourced.
set -euo pipefail

_rank="${1:?usage: run_train_auto_resume.sh <lora_rank>}"
ROOT="${ROOT:-$(cd "$(dirname "$0")/../../.." && pwd)}"
cd "$ROOT"

GUARD="$ROOT/benchmark/phases/phase3/lora_disk_guard.py"
TRAIN="$ROOT/benchmark/phases/phase3/run_unsloth_lora_css.py"
MIN_DISK_GB="${PHASE3_MIN_DISK_GB:-25}"
MAX_ATTEMPTS="${PHASE3_TRAIN_MAX_RESUME:-100}"
SLEEP_SEC="${PHASE3_TRAIN_RESUME_SLEEP:-15}"

RUN_DIR="$(.venv/bin/python -c "
import json, os
from pathlib import Path
root = Path(${ROOT@Q})
manifest = json.loads(Path(os.environ['PHASE3_MANIFEST']).read_text())
rank = int(${_rank@Q})
print((root / manifest['outputs']['lora'] / f'r{rank}').resolve())
")"

LOG="${PHASE3_TRAIN_LOG:-}"
if [[ -z "$LOG" ]]; then
  case "${PHASE3_STAGE:-}" in
    3d) LOG="${PHASE3D_ROOT}/logs/phase3d.log" ;;
    3c) LOG="${PHASE3C_ROOT}/logs/phase3c.log" ;;
    *) LOG="${PHASE3D_ROOT:-${PHASE3C_ROOT:-runs/phase3/stage3b}}/logs/phase3.log" ;;
  esac
fi

if .venv/bin/python "$GUARD" training-finished --lora-dir "$RUN_DIR" 2>/dev/null; then
  echo "[phase3] train rank=$_rank already complete ($RUN_DIR)" | tee -a "$LOG"
  exit 0
fi

.venv/bin/python "$GUARD" ensure-disk --path / --min-gb "$MIN_DISK_GB" --lora-dir "$RUN_DIR" \
  | tee -a "$LOG"

attempt=0
explicit_resume="${PHASE3_RESUME_CHECKPOINT:-}"
PENDING_CSS="$ROOT/benchmark/phases/phase3/run_pending_css.py"

while (( attempt < MAX_ATTEMPTS )); do
  attempt=$((attempt + 1))
  .venv/bin/python "$GUARD" prune --lora-dir "$RUN_DIR" 2>&1 | tee -a "$LOG" || true

  .venv/bin/python "$PENDING_CSS" --lora-dir "$RUN_DIR" --rank "$_rank" 2>&1 | tee -a "$LOG" || true

  resume_ckpt=""
  if [[ -n "$explicit_resume" && $attempt -eq 1 ]]; then
    resume_ckpt="$explicit_resume"
  else
    resume_ckpt="$(.venv/bin/python "$GUARD" latest-checkpoint --lora-dir "$RUN_DIR" 2>/dev/null || true)"
  fi

  echo "[phase3] train rank=$_rank attempt=$attempt/${MAX_ATTEMPTS} resume=${resume_ckpt:-<fresh>}" | tee -a "$LOG"

  set +e
  if [[ -n "$resume_ckpt" ]]; then
    PHASE3_LORA_R="$_rank" PHASE3_LORA_ALPHA="$_rank" \
      PHASE3_RESUME_CHECKPOINT="$resume_ckpt" \
      .venv/bin/python "$TRAIN" >> "$LOG" 2>&1
  else
    PHASE3_LORA_R="$_rank" PHASE3_LORA_ALPHA="$_rank" \
      .venv/bin/python "$TRAIN" >> "$LOG" 2>&1
  fi
  train_rc=$?
  set -e

  if .venv/bin/python "$GUARD" training-finished --lora-dir "$RUN_DIR" 2>/dev/null; then
    echo "[phase3] train rank=$_rank finished OK (attempt $attempt)" | tee -a "$LOG"
    exit 0
  fi

  if (( train_rc != 0 )); then
    echo "[phase3] train rank=$_rank exited rc=$train_rc — auto-resume in ${SLEEP_SEC}s" | tee -a "$LOG"
  else
    echo "[phase3] train rank=$_rank stopped before train_meta.json — auto-resume in ${SLEEP_SEC}s" | tee -a "$LOG"
  fi
  explicit_resume=""
  sleep "$SLEEP_SEC"
done

echo "[phase3] train rank=$_rank failed after $MAX_ATTEMPTS attempts" | tee -a "$LOG"
exit 1
