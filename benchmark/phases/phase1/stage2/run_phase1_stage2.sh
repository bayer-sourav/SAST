#!/usr/bin/env bash
# Phase 1 Stage 2: full FP + TP corpora, borderline N=200, Qwen 4B/8B/14B, thinking off only.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
cd "$ROOT"

SEED="${PHASE1_SEED:-42}"
BL_N="${PHASE1_STAGE2_BL_N:-200}"
THINKING="off"
LOG_DIR="runs/phase1/stage2/logs"
SUM_DIR="runs/phase1/stage2/summaries"
mkdir -p "$LOG_DIR" "$SUM_DIR"

CORPORA_FP="benchmark/corpora/fp_codeql"
CORPORA_TP="benchmark/corpora/tp_codeql"
CORPORA_BL="benchmark/corpora/borderline_n${BL_N}_seed${SEED}"

RUNS_FP="runs/phase1/stage2/fp"
RUNS_TP="runs/phase1/stage2/tp"
RUNS_BL="runs/phase1/stage2/bl"

PROFILES=(
  qwen3_4b_bnb
  qwen3_8b_bnb
  qwen3_14b_bnb
)

# shellcheck source=phase1_cell_env.sh
source "$ROOT/benchmark/phase1_cell_env.sh"

export HF_HOME="${PHASE1_HF_HOME:-${HOME}/.cache/huggingface}"
export HF_HUB_CACHE="${HF_HOME}/hub"
export TRANSFORMERS_CACHE="${HF_HOME}/transformers"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"

PHASE1_FORCE="${PHASE1_FORCE:-0}"
SMOKE_MAX="${PHASE1_STAGE2_SMOKE_MAX:-0}"
MAX_RETRY_PASSES="${PHASE1_STAGE2_MAX_RETRY_PASSES:-3}"

echo "=== Phase 1 Stage 2: thinking=$THINKING smoke_max=$SMOKE_MAX ===" | tee "$LOG_DIR/master.log"

bash "$ROOT/benchmark/setup_corpora.sh" >> "$LOG_DIR/master.log" 2>&1

if [[ ! -d "$CORPORA_BL" ]] || [[ "${PHASE1_STAGE2_REBUILD_BL:-0}" == "1" ]]; then
  echo "=== Building borderline corpus n=$BL_N seed=$SEED ===" | tee -a "$LOG_DIR/master.log"
  uv run python "$ROOT/benchmark/build_borderline_cases.py" \
    --out "$CORPORA_BL" -n "$BL_N" --seed "$SEED" >> "$LOG_DIR/master.log" 2>&1
fi

count_cases() {
  # -L: corpora/fp_codeql and tp_codeql are symlinks to benchmark/*_codeql_only
  find -L "$1" -maxdepth 1 -name 'OWASP_*.json' 2>/dev/null | wc -l | tr -d ' '
}

N_FP="$(count_cases "$CORPORA_FP")"
N_TP="$(count_cases "$CORPORA_TP")"
N_BL="$(count_cases "$CORPORA_BL")"

cell_done_count() {
  local runs_root="$1"
  local profile="$2"
  uv run python - "$runs_root" "$profile" "$THINKING" <<'PY'
import json, sys
from pathlib import Path
runs_root, profile, thinking = sys.argv[1:4]
llm = Path(runs_root) / f"thinking_{thinking}" / profile / "llm"
valid = {"TP", "FP", "BL", "UNKNOWN"}
n = 0
if llm.is_dir():
    for d in llm.iterdir():
        p = d / "agent-llm-triage-result.json"
        if not p.is_file():
            continue
        try:
            lbl = str(json.loads(p.read_text(encoding="utf-8")).get("label", "")).strip().upper()
        except json.JSONDecodeError:
            continue
        if lbl in valid:
            n += 1
print(n)
PY
}

run_cell() {
  local track="$1"       # fp | tp | bl
  local gold="$2"        # FP | TP | BL
  local case_dir="$3"
  local runs_root="$4"
  local n_expected="$5"
  local profile="$6"

  local done
  done="$(cell_done_count "$runs_root" "$profile")"
  if [[ "$PHASE1_FORCE" != "1" && "$done" -ge "$n_expected" ]]; then
    echo "--- SKIP $track $profile ($done/$n_expected) ---" | tee -a "$LOG_DIR/master.log"
    return 0
  fi

  local -a force_args=()
  [[ "$PHASE1_FORCE" == "1" ]] && force_args=(--force)
  local -a max_args=()
  if [[ "$SMOKE_MAX" -gt 0 ]]; then
    max_args=(--max-cases "$SMOKE_MAX")
    n_expected="$SMOKE_MAX"
  fi

  local log="$LOG_DIR/${track}_${profile}_thinking_${THINKING}.log"
  echo "--- $(date -Iseconds) $track $profile ($done/$n_expected) ---" | tee -a "$log" "$LOG_DIR/master.log"
  phase1_gpu_cleanup "$LOG_DIR/master.log"
  phase1_save_env
  phase1_apply_token_limits "$THINKING" "$profile"

  uv run python "$ROOT/benchmark/run_batch.py" \
    --agent llm \
    --case-dir "$case_dir" \
    --profile "$profile" \
    --runs-root "$runs_root/thinking_${THINKING}" \
    --gold "$gold" \
    --retry-missing \
    "${force_args[@]}" \
    "${max_args[@]}" \
    2>&1 | tee -a "$log"

  phase1_gpu_cleanup "$log"
  uv run python "$ROOT/benchmark/repair_llm_results.py" \
    --runs "$runs_root/thinking_${THINKING}" \
    --profile "$profile" || true
}

run_cell_with_retries() {
  local track="$1"
  local gold="$2"
  local case_dir="$3"
  local runs_root="$4"
  local n_expected="$5"
  local profile="$6"

  local pass=1
  while [[ "$pass" -le "$MAX_RETRY_PASSES" ]]; do
    run_cell "$track" "$gold" "$case_dir" "$runs_root" "$n_expected" "$profile"
    local done_now
    done_now="$(cell_done_count "$runs_root" "$profile")"
    if [[ "$done_now" -ge "$n_expected" ]]; then
      return 0
    fi
    echo "--- RETRY $track $profile pass=$pass done=$done_now/$n_expected ---" | tee -a "$LOG_DIR/master.log"
    pass=$((pass + 1))
  done
}

summarize_all() {
  echo "=== Summaries ===" | tee -a "$LOG_DIR/master.log"
  local -a prof_args=()
  for p in "${PROFILES[@]}"; do prof_args+=(--profile "$p"); done

  uv run python "$ROOT/benchmark/summarize_triage.py" \
    --case-dir "$CORPORA_FP" --gold FP \
    --runs "$RUNS_FP/thinking_${THINKING}" \
    "${prof_args[@]}" \
    --json-out "$SUM_DIR/comparison_fp_full_thinking_${THINKING}.json"

  uv run python "$ROOT/benchmark/summarize_triage.py" \
    --case-dir "$CORPORA_TP" --gold TP \
    --runs "$RUNS_TP/thinking_${THINKING}" \
    "${prof_args[@]}" \
    --json-out "$SUM_DIR/comparison_tp_full_thinking_${THINKING}.json"

  uv run python "$ROOT/benchmark/summarize_borderline.py" \
    --case-dir "$CORPORA_BL" \
    --runs "$RUNS_BL/thinking_${THINKING}" \
    "${prof_args[@]}" \
    --json-out "$SUM_DIR/comparison_bl_n${BL_N}_thinking_${THINKING}.json"

  uv run python "$ROOT/benchmark/phases/phase1/stage2/merge_stage2_summary.py" \
    --fp-json "$SUM_DIR/comparison_fp_full_thinking_${THINKING}.json" \
    --tp-json "$SUM_DIR/comparison_tp_full_thinking_${THINKING}.json" \
    --bl-json "$SUM_DIR/comparison_bl_n${BL_N}_thinking_${THINKING}.json" \
    --profiles "${PROFILES[@]}" \
    --manifest "benchmark/corpora/borderline_n${BL_N}_seed${SEED}_manifest.json" \
    --json-out "$SUM_DIR/phase1_stage2_matrix_thinking_${THINKING}.json"

  uv run python "$ROOT/benchmark/phases/phase1/stage2/report_timing_stage2.py" \
    --json-out "$ROOT/benchmark/phase1_stage2_timing_report.json" \
    --n-fp "$N_FP" --n-tp "$N_TP" --n-bl "$N_BL"
}

# Run order: 4B -> 8B -> 14B; per model FP -> TP -> BL
for profile in "${PROFILES[@]}"; do
  run_cell_with_retries fp FP "$CORPORA_FP" "$RUNS_FP" "$N_FP" "$profile"
  run_cell_with_retries tp TP "$CORPORA_TP" "$RUNS_TP" "$N_TP" "$profile"
  run_cell_with_retries bl BL "$CORPORA_BL" "$RUNS_BL" "$N_BL" "$profile"
done

summarize_all
date -Iseconds > "$LOG_DIR/finished_at.txt"
echo "=== Stage 2 complete ===" | tee -a "$LOG_DIR/master.log"
