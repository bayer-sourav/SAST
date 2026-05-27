#!/usr/bin/env bash
# Phase 1: 50 FP + 50 TP (seed-balanced), 6 models ascending size, thinking on/off, zero-shot.
set -euo pipefail
cd "$(dirname "$0")/.."

SEED="${PHASE1_SEED:-42}"
N="${PHASE1_N:-50}"
SLICE_FP="benchmark/phase1_slices/fp_n${N}_seed${SEED}"
SLICE_TP="benchmark/phase1_slices/tp_n${N}_seed${SEED}"
FP_RUNS="FP-runs/phase1_n50"
TP_RUNS="TP-runs/phase1_n50"
LOG_DIR="benchmark/phase1_logs"
MANIFEST="${PHASE1_MANIFEST:-benchmark/phase1_manifest.json}"

# Ascending parameter count: 4B → 8B → 14B → 20B → 30B (Gemma 12B skipped — too slow on L40S)
PROFILES=(
  qwen3_4b_bnb
  qwen3_8b_bnb
  qwen3_14b_bnb
  gpt_oss_20b
  qwen3_coder_30b_bnb
)

mkdir -p "$LOG_DIR"
# shellcheck source=phase1_cell_env.sh
source "$(dirname "$0")/phase1_cell_env.sh"

# Persistent HF cache on root (use /tmp only if PHASE1_HF_HOME is set explicitly).
export HF_HOME="${PHASE1_HF_HOME:-${HOME}/.cache/huggingface}"
export HF_HUB_CACHE="${HF_HOME}/hub"
export TRANSFORMERS_CACHE="${HF_HOME}/transformers"
mkdir -p "$HF_HUB_CACHE" "$TRANSFORMERS_CACHE"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"
# Per-cell limits (see phase1_cell_env.sh): thinking_off 4k new / 16k ctx; thinking_on 16k new / 32k ctx.
echo "HF_HOME=$HF_HOME" | tee "$LOG_DIR/env.txt"
echo "Phase1 tokens: off=${PHASE1_OFF_MAX_NEW_TOKENS:-4096}/${PHASE1_OFF_MAX_SEQ_LEN:-16384} on=${PHASE1_ON_MAX_NEW_TOKENS:-16384}/${PHASE1_ON_MAX_SEQ_LEN:-32768} gpt=${PHASE1_GPT_OSS_MAX_NEW_TOKENS:-4096}/${PHASE1_GPT_OSS_MAX_SEQ_LEN:-12288}" \
  | tee -a "$LOG_DIR/env.txt"

# Resume: skip cells that already have N valid results; omit --force unless PHASE1_FORCE=1.
PHASE1_FORCE="${PHASE1_FORCE:-0}"

echo "=== Phase 1 matrix: N=$N seed=$SEED resume=${PHASE1_RESUME:-0} ===" | tee -a "$LOG_DIR/phase1_master.log"

if [[ "${PHASE1_SKIP_SLICE:-0}" != "1" ]]; then
  echo "=== Building balanced slices ===" | tee -a "$LOG_DIR/phase1_master.log"
  uv run python benchmark/select_balanced_cases.py \
    --src benchmark/rq1_codeql_only --out "$SLICE_FP" -n "$N" --seed "$SEED"
  uv run python benchmark/select_balanced_cases.py \
    --src benchmark/tp_codeql_only --out "$SLICE_TP" -n "$N" --seed "$SEED"
else
  echo "=== Skipping slice rebuild (PHASE1_SKIP_SLICE=1) ===" | tee -a "$LOG_DIR/phase1_master.log"
fi

git rev-parse HEAD > "$LOG_DIR/git_commit.txt" 2>/dev/null || true
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader >> "$LOG_DIR/gpu.txt" 2>/dev/null || true
date -Iseconds > "$LOG_DIR/started_at.txt"

cell_done_count() {
  local runs_root="$1"
  local thinking_flag="$2"
  local profile="$3"
  local d="${runs_root}/thinking_${thinking_flag}/${profile}/llm"
  [[ -d "$d" ]] || { echo 0; return; }
  find "$d" -name 'agent-llm-triage-result.json' 2>/dev/null | wc -l | tr -d ' '
}

run_cell() {
  local thinking_flag="$1"   # off | on
  local profile="$2"
  local gold="$3"            # FP | TP
  local case_dir="$4"
  local runs_root="$5"
  local done
  done="$(cell_done_count "$runs_root" "$thinking_flag" "$profile")"
  if [[ "$PHASE1_FORCE" != "1" && "$done" -ge "$N" ]]; then
    echo "--- $(date -Iseconds) SKIP $gold $profile thinking=$thinking_flag ($done/$N done) ---" \
      | tee -a "$LOG_DIR/phase1_master.log"
    return 0
  fi
  local think_args=()
  if [[ "$thinking_flag" == "on" ]]; then
    think_args=(--thinking)
  fi
  local -a force_args=()
  if [[ "$PHASE1_FORCE" == "1" ]]; then
    force_args=(--force)
  fi
  local log="$LOG_DIR/${gold}_${profile}_thinking_${thinking_flag}.log"
  echo "--- $(date -Iseconds) $gold $profile thinking=$thinking_flag ($done/$N) ---" | tee -a "$log" "$LOG_DIR/phase1_master.log"
  phase1_gpu_cleanup "$LOG_DIR/phase1_master.log"
  phase1_save_env
  phase1_apply_token_limits "$thinking_flag" "$profile"
  echo "[phase1] tokens thinking=$thinking_flag seq=$AGENT_MAX_SEQ_LEN new=$AGENT_MAX_NEW_TOKENS profile=$profile" \
    | tee -a "$log" "$LOG_DIR/phase1_master.log"
  uv run python benchmark/run_batch.py \
    --agent llm \
    --case-dir "$case_dir" \
    --profile "$profile" \
    --runs-root "$runs_root/thinking_${thinking_flag}" \
    --gold "$gold" \
    --retry-missing \
    "${force_args[@]}" \
    "${think_args[@]}" \
    2>&1 | tee -a "$log"
  phase1_gpu_cleanup "$log"
  uv run python benchmark/repair_llm_results.py \
    --runs "$runs_root/thinking_${thinking_flag}" \
    --profile "$profile" || true
  uv run python benchmark/report_timing.py \
    --json-out benchmark/phase1_timing_report.json 2>&1 | tail -3 \
    | tee -a "$LOG_DIR/timing.log"
}

summarize_track() {
  local thinking_flag="$1"
  local gold="$2"
  local case_dir="$3"
  local runs_root="$4"
  local json_out="$runs_root/comparison_${gold,,}_n${N}_thinking_${thinking_flag}.json"
  local -a prof_args=()
  for p in "${PROFILES[@]}"; do
    prof_args+=(--profile "$p")
  done
  uv run python benchmark/summarize_triage.py \
    --case-dir "$case_dir" \
    --gold "$gold" \
    --runs "$runs_root/thinking_${thinking_flag}" \
    "${prof_args[@]}" \
    --json-out "$json_out"
}

for THINKING in off on; do
  for PROFILE in "${PROFILES[@]}"; do
    if [[ "$PROFILE" == "qwen3_coder_30b_bnb" && -f "$LOG_DIR/phase1_skip_coder.txt" ]]; then
      echo "--- SKIP coder ($LOG_DIR/phase1_skip_coder.txt present) ---" | tee -a "$LOG_DIR/phase1_master.log"
      continue
    fi
    run_cell "$THINKING" "$PROFILE" FP "$SLICE_FP" "$FP_RUNS"
    run_cell "$THINKING" "$PROFILE" TP "$SLICE_TP" "$TP_RUNS"
  done
  summarize_track "$THINKING" FP "$SLICE_FP" "$FP_RUNS"
  summarize_track "$THINKING" TP "$SLICE_TP" "$TP_RUNS"
  uv run python benchmark/merge_phase1_summary.py \
    --fp-json "$FP_RUNS/comparison_fp_n${N}_thinking_${THINKING}.json" \
    --tp-json "$TP_RUNS/comparison_tp_n${N}_thinking_${THINKING}.json" \
    --profiles "${PROFILES[@]}" \
    --thinking "$THINKING" \
    --manifest "${SLICE_FP}_manifest.json" \
    --json-out "$FP_RUNS/phase1_matrix_thinking_${THINKING}.json"
done

COMBINED_OUT="benchmark/phase1_combined_summary.json"
uv run python -c "
import json
from pathlib import Path
fp_runs = Path('$FP_RUNS')
out = {'n_cases': $N, 'seed': $SEED, 'thinking': {}, 'profiles': $(printf '%s\n' "${PROFILES[@]}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip().split()))')}
for t in ('off', 'on'):
    p = fp_runs / f'phase1_matrix_thinking_{t}.json'
    if p.is_file():
        out['thinking'][t] = json.loads(p.read_text())
Path('$COMBINED_OUT').write_text(json.dumps(out, indent=2))
print('Wrote $COMBINED_OUT')
"

date -Iseconds > "$LOG_DIR/finished_at.txt"
date -Iseconds > "$LOG_DIR/phase1_matrix_finished.txt"
bash ./benchmark/refresh_phase1_summaries.sh >> "$LOG_DIR/phase1_master.log" 2>&1
echo "=== Phase 1 complete ===" | tee -a "$LOG_DIR/phase1_master.log"
