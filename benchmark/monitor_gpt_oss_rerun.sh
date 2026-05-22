#!/usr/bin/env bash
# Re-run failed gpt_oss_20b cells via rerun_bad_cases + run_batch --retry-missing.
set -euo pipefail
cd "$(dirname "$0")/.."
# shellcheck source=phase1_lib.sh
source "$(dirname "$0")/phase1_lib.sh"

if ! phase1_acquire_runner_lock; then
  echo "[monitor] phase1_runner.lock held by another runner; exit 0"
  exit 0
fi

MAX_ROUNDS="${1:-50}"
LOG_DIR="benchmark/phase1_logs"
mkdir -p "$LOG_DIR"

if phase1_gpt_complete; then
  echo "[monitor] GPT-OSS thinking_off already ${PHASE1_N}/${PHASE1_N} FP+TP"
  exit 0
fi

round=0
while phase1_gpt_incomplete && [[ "$round" -lt "$MAX_ROUNDS" ]]; do
  round=$((round + 1))
  ok_fp="$(phase1_gpt_fp_ok)"
  ok_tp="$(phase1_gpt_tp_ok)"
  echo "=== GPT-OSS rerun round ${round}/${MAX_ROUNDS} $(date -Iseconds) FP=${ok_fp}/${PHASE1_N} TP=${ok_tp}/${PHASE1_N} ==="
  phase1_gpu_cleanup

  for gold in FP TP; do
    phase1_apply_token_limits off gpt_oss_20b
    if [[ "$gold" == FP ]]; then
      if [[ "$(phase1_gpt_fp_ok)" -ge "$PHASE1_N" ]]; then
        echo "[monitor] skip FP (${PHASE1_N}/${PHASE1_N})"
        continue
      fi
      slice="$SLICE_FP"
      root="$GPT_RUNS_FP"
    else
      if [[ "$(phase1_gpt_tp_ok)" -ge "$PHASE1_N" ]]; then
        echo "[monitor] skip TP (${PHASE1_N}/${PHASE1_N})"
        continue
      fi
      slice="$SLICE_TP"
      root="$GPT_RUNS_TP"
    fi

    echo "[monitor] $gold rerun_bad_cases + run_batch --retry-missing"
    uv run python benchmark/rerun_bad_cases.py \
      --case-dir "$slice" \
      --runs-root "$root" \
      --profile gpt_oss_20b \
      --gold "$gold" \
      2>&1 | tee -a "${LOG_DIR}/gpt_oss_rerun_round${round}_${gold}.log" || true

    uv run python benchmark/run_batch.py \
      --agent llm \
      --case-dir "$slice" \
      --profile gpt_oss_20b \
      --runs-root "$root" \
      --gold "$gold" \
      --retry-missing \
      2>&1 | tee -a "${LOG_DIR}/gpt_oss_rerun_round${round}_${gold}.log"
    phase1_gpu_cleanup
  done

  ok_fp="$(phase1_gpt_fp_ok)"
  ok_tp="$(phase1_gpt_tp_ok)"
  echo "round ${round}: FP=${ok_fp}/${PHASE1_N} TP=${ok_tp}/${PHASE1_N}"
  if phase1_gpt_complete; then
    echo "GPT-OSS thinking_off complete."
    exit 0
  fi
done

if phase1_gpt_complete; then
  echo "GPT-OSS thinking_off complete."
  exit 0
fi

echo "Stopped after ${round} rounds (FP=$(phase1_gpt_fp_ok)/${PHASE1_N} TP=$(phase1_gpt_tp_ok)/${PHASE1_N})."
exit 1
