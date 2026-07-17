#!/usr/bin/env bash
# Latency ablation (thinking ON): token budget ± short-CoT on hard slice (20).
# Cells: 5.9b_fs3_legacy (v7-balanced) and lang-agnostic (v7-balanced-langagnostic).
#
# Usage:
#   WAIT_FOR_GPU=1 bash benchmark/phases/phase2/run_latency_budget_ablation.sh
#   ARMS="baseline,t2048_short" bash ...   # subset
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

# shellcheck source=phase2_infer_env.sh
source "$ROOT/benchmark/phases/phase2/phase2_infer_env.sh"
# shellcheck source=../../phase2_cell_env.sh
source "$ROOT/benchmark/phase2_cell_env.sh"

export QWEN_INFER_BACKEND=vllm
export SAST_REQUIRE_VLLM=1
export QWEN_VLLM_GPU_MEMORY_UTILIZATION="${QWEN_VLLM_GPU_MEMORY_UTILIZATION:-0.90}"
export HF_HOME="${PHASE2_HF_HOME:-${HOME}/.cache/huggingface}"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"

EVAL_ROOT="${LATENCY_EVAL_ROOT:-runs/phase2/latency_budget_ablation}"
LOG="$EVAL_ROOT/ablation.log"
mkdir -p "$EVAL_ROOT"

PROFILE="qwen3_5_9b_bnb"
FS_CONFIG="v2_3shot_tp_2fp"
FEWSHOT=3
WAIT_FOR_GPU="${WAIT_FOR_GPU:-1}"
ARMS_CSV="${ARMS:-baseline,t2048,t2048_short,t1536_short}"

wait_gpu() {
  if [[ "$WAIT_FOR_GPU" != "1" ]]; then
    return 0
  fi
  echo "[wait] waiting for free GPU (no other VLLM::EngineCore / large CUDA apps)..." | tee -a "$LOG"
  while true; do
    local n
    n=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | grep -c '[0-9]' || true)
    if [[ "${n:-0}" -eq 0 ]]; then
      echo "[wait] GPU free at $(date -Iseconds)" | tee -a "$LOG"
      return 0
    fi
    # Allow only our eventual process; if another user's job holds >8GB, keep waiting.
    local mem
    mem=$(nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits 2>/dev/null \
      | awk '{s+=$1} END{print s+0}')
    if [[ "${mem:-0}" -lt 512 ]]; then
      echo "[wait] GPU free (mem=${mem}MiB) at $(date -Iseconds)" | tee -a "$LOG"
      return 0
    fi
    sleep 60
  done
}

echo "=== Latency budget ablation $(date -Iseconds) backend=$QWEN_INFER_BACKEND arms=$ARMS_CSV ===" | tee "$LOG"

uv run python "$ROOT/benchmark/phases/phase2/build_hard_slice_corpora.py" 2>&1 | tee -a "$LOG"

wait_gpu

IFS=',' read -r -a ARMS <<<"$ARMS_CSV"

run_arm() {
  local cell_id="$1" prompt="$2" arm="$3"
  local think_cap short short_env
  short=0
  short_env=0
  case "$arm" in
    baseline)
      think_cap=4096
      ;;
    t2048)
      think_cap=2048
      ;;
    t2048_short)
      think_cap=2048
      short=1
      short_env=1
      ;;
    t1536_short)
      think_cap=1536
      short=1
      short_env=1
      ;;
    t1024_short)
      think_cap=1024
      short=1
      short_env=1
      ;;
    *)
      echo "ERROR: unknown arm $arm" | tee -a "$LOG"
      return 1
      ;;
  esac

  local cell_root="$EVAL_ROOT/$cell_id/$arm"
  local tracks_json="$cell_root/tracks_hard_slice.json"
  mkdir -p "$cell_root"

  export PHASE2_ON_MAX_NEW_TOKENS_THINKING="$think_cap"
  export PHASE2_ON_MAX_NEW_TOKENS=$((think_cap + 400))
  export AGENT_MAX_NEW_TOKENS_THINKING="$think_cap"
  export AGENT_MAX_NEW_TOKENS=$((think_cap + 400))
  if [[ "$short_env" == "1" ]]; then
    export SAST_SHORT_THINKING=1
  else
    unset SAST_SHORT_THINKING || true
  fi

  cat >"$tracks_json" <<EOF
[
  {"gold": "FP", "case_dir": "benchmark/corpora/phase2_hard_slice_fp", "runs_root": "$cell_root"},
  {"gold": "TP", "case_dir": "benchmark/corpora/phase2_hard_slice_tp", "runs_root": "$cell_root"}
]
EOF

  echo "" | tee -a "$LOG"
  echo "=== [$cell_id / $arm] think_cap=$think_cap short=$short prompt=$prompt $(date -Iseconds) ===" | tee -a "$LOG"
  phase2_gpu_cleanup "$LOG" || true
  uv run python "$ROOT/benchmark/run_batch.py" \
    --agent llm \
    --profile "$PROFILE" \
    --prompt-version "$prompt" \
    --thinking \
    --few-shot "$FEWSHOT" \
    --few-shot-config "$FS_CONFIG" \
    --tracks-json "$tracks_json" \
    --retry-missing \
    --force 2>&1 | tee -a "$LOG"
  phase2_gpu_cleanup "$LOG" || true

  uv run python "$ROOT/benchmark/phases/phase2/summarize_latency_arm.py" \
    --cell-root "$cell_root" \
    --cell-id "$cell_id" \
    --arm "$arm" \
    --think-cap "$think_cap" \
    --short "$short" \
    --prompt "$prompt" \
    --json-out "$cell_root/arm_summary.json" 2>&1 | tee -a "$LOG"
}

# Cell A: Stage 2 GOOD · 5.9b_fs3_legacy
for arm in "${ARMS[@]}"; do
  run_arm "5.9b_fs3_legacy" "v7-balanced" "$arm"
done

# Cell B: lang-agnostic v7
for arm in "${ARMS[@]}"; do
  run_arm "langagnostic_fs3" "v7-balanced-langagnostic" "$arm"
done

uv run python "$ROOT/benchmark/phases/phase2/summarize_latency_arm.py" \
  --merge-root "$EVAL_ROOT" \
  --json-out "$EVAL_ROOT/ABLATION_SUMMARY.json" \
  --md-out "$EVAL_ROOT/ABLATION_SUMMARY.md" 2>&1 | tee -a "$LOG"

echo "Done. See $EVAL_ROOT/ABLATION_SUMMARY.md" | tee -a "$LOG"
