#!/usr/bin/env bash
# shellcheck shell=bash
# Phase 1 shared status helpers and runner lock.

_PHASE1_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=phase1_cell_env.sh
source "${_PHASE1_LIB_DIR}/phase1_cell_env.sh"

PHASE1_N="${PHASE1_N:-50}"
PHASE1_GPT_FP_ROOT="FP-runs/phase1_n50/thinking_off/gpt_oss_20b/llm"
PHASE1_GPT_TP_ROOT="TP-runs/phase1_n50/thinking_off/gpt_oss_20b/llm"
PHASE1_RUNNER_LOCK="benchmark/phase1_logs/phase1_runner.lock"
PHASE1_MATRIX_FINISHED="benchmark/phase1_logs/phase1_matrix_finished.txt"
SLICE_FP="benchmark/phase1_slices/fp_n50_seed42"
SLICE_TP="benchmark/phase1_slices/tp_n50_seed42"
GPT_RUNS_FP="FP-runs/phase1_n50/thinking_off"
GPT_RUNS_TP="TP-runs/phase1_n50/thinking_off"

_phase1_gpt_result_count() {
  local root="$1"
  if [[ ! -d "$root" ]]; then
    echo 0
    return
  fi
  find "$root" -name 'agent-llm-triage-result.json' 2>/dev/null | wc -l | tr -d ' '
}

phase1_gpt_fp_ok() {
  _phase1_gpt_result_count "$PHASE1_GPT_FP_ROOT"
}

phase1_gpt_tp_ok() {
  _phase1_gpt_result_count "$PHASE1_GPT_TP_ROOT"
}

phase1_gpt_incomplete() {
  local fp tp
  fp="$(phase1_gpt_fp_ok)"
  tp="$(phase1_gpt_tp_ok)"
  [[ "$fp" -lt "$PHASE1_N" || "$tp" -lt "$PHASE1_N" ]]
}

phase1_gpt_complete() {
  local fp tp
  fp="$(phase1_gpt_fp_ok)"
  tp="$(phase1_gpt_tp_ok)"
  [[ "$fp" -ge "$PHASE1_N" && "$tp" -ge "$PHASE1_N" ]]
}

phase1_runner_active() {
  # Only real work: batch/matrix. A stuck monitor shell must not block the watchdog.
  if pgrep -f 'run_phase1_matrix' >/dev/null 2>&1; then
    return 0
  fi
  if pgrep -f 'run_batch\.py' >/dev/null 2>&1; then
    return 0
  fi
  if pgrep -f 'run_llm_local\.py' >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

# Acquire exclusive runner lock (fd 200). Returns 0 if acquired, 1 if held elsewhere.
phase1_acquire_runner_lock() {
  mkdir -p benchmark/phase1_logs
  exec 200>"$PHASE1_RUNNER_LOCK"
  flock -n 200
}

phase1_matrix_finished() {
  [[ -f "$PHASE1_MATRIX_FINISHED" ]]
}
