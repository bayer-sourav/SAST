# shellcheck shell=bash
# Phase 2 per-cell token limits and GPU cleanup.

phase2_save_env() {
  _P2_SAVED_AGENT_MAX_SEQ_LEN="${AGENT_MAX_SEQ_LEN-}"
  _P2_SAVED_AGENT_MAX_NEW="${AGENT_MAX_NEW_TOKENS-}"
  _P2_SAVED_AGENT_MAX_NEW_THINKING="${AGENT_MAX_NEW_TOKENS_THINKING-}"
  _P2_SAVED_QWEN_MAX_SEQ="${QWEN_MAX_SEQ_LEN-}"
  _P2_SAVED_QWEN_CODER_MAX="${QWEN_CODER_MAX_SEQ_LEN-}"
  _P2_SAVED_CODER_BACKEND="${QWEN3_CODER_BACKEND-}"
}

phase2_restore_env() {
  if [[ -n "${_P2_SAVED_AGENT_MAX_SEQ_LEN+x}" ]]; then
    export AGENT_MAX_SEQ_LEN="$_P2_SAVED_AGENT_MAX_SEQ_LEN"
  else
    unset AGENT_MAX_SEQ_LEN
  fi
  if [[ -n "${_P2_SAVED_AGENT_MAX_NEW+x}" ]]; then
    export AGENT_MAX_NEW_TOKENS="$_P2_SAVED_AGENT_MAX_NEW"
  else
    unset AGENT_MAX_NEW_TOKENS
  fi
  if [[ -n "${_P2_SAVED_AGENT_MAX_NEW_THINKING+x}" ]]; then
    export AGENT_MAX_NEW_TOKENS_THINKING="$_P2_SAVED_AGENT_MAX_NEW_THINKING"
  else
    unset AGENT_MAX_NEW_TOKENS_THINKING
  fi
  if [[ -n "${_P2_SAVED_QWEN_MAX_SEQ+x}" ]]; then
    export QWEN_MAX_SEQ_LEN="$_P2_SAVED_QWEN_MAX_SEQ"
  else
    unset QWEN_MAX_SEQ_LEN
  fi
  if [[ -n "${_P2_SAVED_QWEN_CODER_MAX+x}" ]]; then
    export QWEN_CODER_MAX_SEQ_LEN="$_P2_SAVED_QWEN_CODER_MAX"
  else
    unset QWEN_CODER_MAX_SEQ_LEN
  fi
  if [[ -n "${_P2_SAVED_CODER_BACKEND+x}" ]]; then
    export QWEN3_CODER_BACKEND="$_P2_SAVED_CODER_BACKEND"
  else
    unset QWEN3_CODER_BACKEND
  fi
}

# Thinking-on was not run in Phase 1 Stage 2; cap generation so prompt + CoT + JSON fit context.
phase2_apply_token_limits() {
  local thinking_flag="$1"
  local profile="$2"

  export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"

  if [[ "$thinking_flag" == "on" ]]; then
    export AGENT_MAX_SEQ_LEN="${PHASE2_ON_MAX_SEQ_LEN:-32768}"
    export AGENT_MAX_NEW_TOKENS="${PHASE2_ON_MAX_NEW_TOKENS:-8192}"
    export AGENT_MAX_NEW_TOKENS_THINKING="${PHASE2_ON_MAX_NEW_TOKENS_THINKING:-8192}"
    export QWEN_MAX_SEQ_LEN="${PHASE2_ON_MAX_SEQ_LEN:-32768}"
  else
    export AGENT_MAX_SEQ_LEN="${PHASE2_OFF_MAX_SEQ_LEN:-16384}"
    export AGENT_MAX_NEW_TOKENS="${PHASE2_OFF_MAX_NEW_TOKENS:-4096}"
    unset AGENT_MAX_NEW_TOKENS_THINKING
    export QWEN_MAX_SEQ_LEN="${PHASE2_OFF_MAX_SEQ_LEN:-16384}"
  fi

  if [[ "$profile" == "qwen3_coder_30b_bnb" ]]; then
    export QWEN3_CODER_BACKEND="${PHASE2_CODER_BACKEND:-bedrock}"
    unset QWEN3_CODER_USE_LOCAL_SNAPSHOT
    unset QWEN3_CODER_SKIP_UNSLOTH
    if [[ "$thinking_flag" == "on" ]]; then
      export QWEN_CODER_MAX_SEQ_LEN="${PHASE2_CODER_ON_MAX_SEQ_LEN:-32768}"
      export AGENT_MAX_SEQ_LEN="${PHASE2_CODER_ON_AGENT_MAX_SEQ:-32768}"
      export AGENT_MAX_NEW_TOKENS="${PHASE2_CODER_ON_MAX_NEW:-8192}"
    else
      export QWEN_CODER_MAX_SEQ_LEN="${PHASE2_CODER_OFF_MAX_SEQ_LEN:-16384}"
      export AGENT_MAX_SEQ_LEN="${PHASE2_CODER_OFF_AGENT_MAX_SEQ:-16384}"
      export AGENT_MAX_NEW_TOKENS="${PHASE2_CODER_OFF_MAX_NEW:-4096}"
    fi
  fi
}

phase2_gpu_cleanup() {
  local log_msg="${1:-}"
  if uv run python -c "
from benchmark.local_model_unload import release_gpu_memory
import os
release_gpu_memory(verbose=os.environ.get('PHASE2_VERBOSE','0')=='1')
" 2>/dev/null; then
    if [[ -n "$log_msg" ]]; then
      echo "[phase2] GPU cleanup after $log_msg" | tee -a "${log_msg}"
    else
      echo "[phase2] GPU cleanup done"
    fi
  fi
}

# Fast vLLM inference for Phase 2 batch runs (see phases/phase2/phase2_infer_env.sh).
if [[ -f "$(dirname "${BASH_SOURCE[0]}")/phases/phase2/phase2_infer_env.sh" ]]; then
  # shellcheck source=benchmark/phases/phase2/phase2_infer_env.sh
  source "$(dirname "${BASH_SOURCE[0]}")/phases/phase2/phase2_infer_env.sh"
fi
