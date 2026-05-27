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

  if [[ "$profile" == "qwen3_coder_30b_bnb" ]]; then
    export QWEN_MAX_SEQ_LEN="${PHASE1_CODER_MAX_SEQ_LEN:-4096}"
    export QWEN_CODER_MAX_SEQ_LEN="${PHASE1_CODER_MAX_SEQ_LEN:-4096}"
    export AGENT_MAX_SEQ_LEN="${PHASE1_CODER_AGENT_MAX_SEQ_LEN:-6144}"
    export AGENT_MAX_NEW_TOKENS="${PHASE1_CODER_MAX_NEW_TOKENS:-2048}"
    # Local instruct snapshot + HF BnB + CPU offload.
    # Tokenizer must match instruct weights (unsloth snapshot tokenizer is broken vocab=1).
    # Do NOT use riomus BnB tokenizer with unsloth weights — produces garbage output.
    export QWEN3_CODER_USE_LOCAL_SNAPSHOT=1
    export QWEN3_CODER_SKIP_UNSLOTH=1
    unset QWEN3_CODER_30B_HF_MODEL_ID
    unset QWEN3_CODER_LOCAL_SNAPSHOT
    _coder_tok="${PHASE1_CODER_TOKENIZER_DIR:-}"
    if [[ -z "$_coder_tok" ]]; then
      _qwen_hub="$HOME/.cache/huggingface/hub/models--Qwen--Qwen3-Coder-30B-A3B-Instruct/snapshots"
      if [[ -d "$_qwen_hub" ]]; then
        _coder_tok="$(find "$_qwen_hub" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort | tail -1)"
      fi
    fi
    if [[ -z "$_coder_tok" || ! -f "$_coder_tok/tokenizer.json" ]]; then
      _coder_tok="Qwen/Qwen3-Coder-30B-A3B-Instruct"
    fi
    export HF_TOKENIZER_MODEL_ID="$_coder_tok"
    export HF_DEVICE_MAP="${PHASE1_CODER_HF_DEVICE_MAP:-auto}"
    export HF_MAX_MEMORY="${PHASE1_CODER_HF_MAX_MEMORY:-0:30GiB,cpu:120GiB}"
    export HF_SKIP_ALLOCATOR_WARMUP="${PHASE1_CODER_SKIP_ALLOCATOR_WARMUP:-1}"
    export HF_LOCAL_FILES_ONLY="${PHASE1_CODER_HF_LOCAL_ONLY:-1}"
    export HF_BNB_ALLOW_CPU_OFFLOAD=1
    export HF_LOW_CPU_MEM_USAGE="${PHASE1_CODER_HF_LOW_CPU_MEM_USAGE:-0}"
    unset HF_BNB_META_RETRY_CUDA0
    unset UNSLOTH_DEVICE_MAP
  fi

  if [[ "$profile" == "gpt_oss_20b" ]]; then
    export PHASE1_GPT_OSS_HF_ONLY="${PHASE1_GPT_OSS_HF_ONLY:-1}"
    export GPT_OSS_HF_ONLY=1
    export AGENT_TEMPERATURE="${PHASE1_GPT_OSS_TEMPERATURE:-0}"
    export AGENT_REPETITION_PENALTY="${PHASE1_GPT_OSS_REPETITION_PENALTY:-1}"
    unset HF_DEVICE_MAP
    if [[ "$thinking_flag" == "on" ]]; then
      # thinking_on: tight GPU caps (CPU path is ~30+ min/case and looks hung). Model ignores thinking anyway.
      unset GPT_OSS_CPU_LOAD
      export GPT_OSS_MAX_SEQ_LEN="${PHASE1_GPT_OSS_ON_MAX_SEQ_LEN:-8192}"
      export AGENT_MAX_SEQ_LEN="${PHASE1_GPT_OSS_ON_AGENT_MAX_SEQ:-8192}"
      export AGENT_MAX_NEW_TOKENS="${PHASE1_GPT_OSS_ON_MAX_NEW:-512}"
    else
      unset GPT_OSS_CPU_LOAD
      export GPT_OSS_MAX_SEQ_LEN="${PHASE1_GPT_OSS_MAX_SEQ_LEN:-12288}"
      export AGENT_MAX_NEW_TOKENS="${PHASE1_GPT_OSS_MAX_NEW_TOKENS:-2048}"
    fi
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
