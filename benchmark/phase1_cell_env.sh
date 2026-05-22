# shellcheck shell=bash
# Phase 1 per-cell token limits and GPU cleanup. Source from run_phase1_matrix.sh.

phase1_save_env() {
  _P1_SAVED_AGENT_MAX_SEQ_LEN="${AGENT_MAX_SEQ_LEN-}"
  _P1_SAVED_AGENT_MAX_NEW="${AGENT_MAX_NEW_TOKENS-}"
  _P1_SAVED_AGENT_MAX_NEW_THINKING="${AGENT_MAX_NEW_TOKENS_THINKING-}"
  _P1_SAVED_QWEN_MAX_SEQ="${QWEN_MAX_SEQ_LEN-}"
  _P1_SAVED_GPT_SEQ="${GPT_OSS_MAX_SEQ_LEN-}"
  _P1_SAVED_AGENT_TEMP="${AGENT_TEMPERATURE-}"
  _P1_SAVED_AGENT_REP="${AGENT_REPETITION_PENALTY-}"
  _P1_SAVED_GPT_HF_ONLY="${GPT_OSS_HF_ONLY-}"
}

phase1_restore_env() {
  if [[ -n "${_P1_SAVED_AGENT_MAX_SEQ_LEN+x}" ]]; then
    export AGENT_MAX_SEQ_LEN="$_P1_SAVED_AGENT_MAX_SEQ_LEN"
  else
    unset AGENT_MAX_SEQ_LEN
  fi
  if [[ -n "${_P1_SAVED_AGENT_MAX_NEW+x}" ]]; then
    export AGENT_MAX_NEW_TOKENS="$_P1_SAVED_AGENT_MAX_NEW"
  else
    unset AGENT_MAX_NEW_TOKENS
  fi
  if [[ -n "${_P1_SAVED_AGENT_MAX_NEW_THINKING+x}" ]]; then
    export AGENT_MAX_NEW_TOKENS_THINKING="$_P1_SAVED_AGENT_MAX_NEW_THINKING"
  else
    unset AGENT_MAX_NEW_TOKENS_THINKING
  fi
  if [[ -n "${_P1_SAVED_QWEN_MAX_SEQ+x}" ]]; then
    export QWEN_MAX_SEQ_LEN="$_P1_SAVED_QWEN_MAX_SEQ"
  else
    unset QWEN_MAX_SEQ_LEN
  fi
  if [[ -n "${_P1_SAVED_GPT_SEQ+x}" ]]; then
    export GPT_OSS_MAX_SEQ_LEN="$_P1_SAVED_GPT_SEQ"
  else
    unset GPT_OSS_MAX_SEQ_LEN
  fi
  if [[ -n "${_P1_SAVED_AGENT_TEMP+x}" ]]; then
    export AGENT_TEMPERATURE="$_P1_SAVED_AGENT_TEMP"
  else
    unset AGENT_TEMPERATURE
  fi
  if [[ -n "${_P1_SAVED_AGENT_REP+x}" ]]; then
    export AGENT_REPETITION_PENALTY="$_P1_SAVED_AGENT_REP"
  else
    unset AGENT_REPETITION_PENALTY
  fi
  if [[ -n "${_P1_SAVED_GPT_HF_ONLY+x}" ]]; then
    export GPT_OSS_HF_ONLY="$_P1_SAVED_GPT_HF_ONLY"
  else
    unset GPT_OSS_HF_ONLY
  fi
}

# Triage JSON: thinking_off needs little output; thinking_on needs room for CoT + JSON.
phase1_apply_token_limits() {
  local thinking_flag="$1"   # off | on
  local profile="$2"

  export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"

  if [[ "$thinking_flag" == "on" ]]; then
    export AGENT_MAX_SEQ_LEN="${PHASE1_ON_MAX_SEQ_LEN:-32768}"
    export AGENT_MAX_NEW_TOKENS="${PHASE1_ON_MAX_NEW_TOKENS:-16384}"
    export AGENT_MAX_NEW_TOKENS_THINKING="${PHASE1_ON_MAX_NEW_TOKENS_THINKING:-16384}"
    export QWEN_MAX_SEQ_LEN="${PHASE1_ON_MAX_SEQ_LEN:-32768}"
  else
    export AGENT_MAX_SEQ_LEN="${PHASE1_OFF_MAX_SEQ_LEN:-16384}"
    export AGENT_MAX_NEW_TOKENS="${PHASE1_OFF_MAX_NEW_TOKENS:-4096}"
    unset AGENT_MAX_NEW_TOKENS_THINKING
    export QWEN_MAX_SEQ_LEN="${PHASE1_OFF_MAX_SEQ_LEN:-16384}"
  fi

  if [[ "$profile" == "gpt_oss_20b" ]]; then
    # Try Unsloth once per process; HF after first OOM. Set PHASE1_GPT_OSS_HF_ONLY=1 to skip Unsloth entirely.
    if [[ "${PHASE1_GPT_OSS_HF_ONLY:-0}" == "1" ]]; then
      export GPT_OSS_HF_ONLY=1
    else
      unset GPT_OSS_HF_ONLY
    fi
    export GPT_OSS_MAX_SEQ_LEN="${PHASE1_GPT_OSS_MAX_SEQ_LEN:-12288}"
    export AGENT_MAX_NEW_TOKENS="${PHASE1_GPT_OSS_MAX_NEW_TOKENS:-2048}"
    export PHASE1_GPT_OSS_HF_ONLY="${PHASE1_GPT_OSS_HF_ONLY:-1}"
    export GPT_OSS_HF_ONLY=1
    export AGENT_TEMPERATURE="${PHASE1_GPT_OSS_TEMPERATURE:-0}"
    export AGENT_REPETITION_PENALTY="${PHASE1_GPT_OSS_REPETITION_PENALTY:-1}"
  fi
}

phase1_gpu_cleanup() {
  local log_msg="${1:-}"
  if uv run python -c "
from benchmark.local_model_unload import release_gpu_memory
import os
release_gpu_memory(verbose=os.environ.get('PHASE1_VERBOSE','0')=='1')
" 2>/dev/null; then
    if [[ -n "$log_msg" ]]; then
      echo "[phase1] GPU cleanup after $log_msg" | tee -a "${log_msg}"
    else
      echo "[phase1] GPU cleanup done"
    fi
  fi
}
