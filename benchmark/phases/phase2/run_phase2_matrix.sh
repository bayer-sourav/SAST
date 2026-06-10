#!/usr/bin/env bash
# Phase 2: dataset test splits (200×3), Qwen 4B/8B/14B + Coder-30B Bedrock,
# zero-shot + 3-shot few-shot, thinking off then on.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

LOG_DIR="runs/phase2/logs"
SUM_DIR="runs/phase2/summaries"
mkdir -p "$LOG_DIR" "$SUM_DIR"

CORPORA_FP="benchmark/corpora/phase2_fp_test"
CORPORA_TP="benchmark/corpora/phase2_tp_test"
CORPORA_BL="benchmark/corpora/phase2_bl_test"

RUNS_FP="runs/phase2/fp"
RUNS_TP="runs/phase2/tp"
RUNS_BL="runs/phase2/bl"

DEFAULT_PROFILES=(
  qwen3_4b_bnb
  qwen3_8b_bnb
  qwen3_14b_bnb
  qwen3_coder_30b_bnb
)
if [[ -n "${PHASE2_PROFILES:-}" ]]; then
  # shellcheck disable=SC2206
  PROFILES=($PHASE2_PROFILES)
else
  PROFILES=("${DEFAULT_PROFILES[@]}")
fi

# shellcheck source=phase2_cell_env.sh
source "$ROOT/benchmark/phase2_cell_env.sh"

export HF_HOME="${PHASE2_HF_HOME:-${HOME}/.cache/huggingface}"
export HF_HUB_CACHE="${HF_HOME}/hub"
export TRANSFORMERS_CACHE="${HF_HOME}/transformers"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"

PHASE2_FORCE="${PHASE2_FORCE:-0}"
SMOKE_MAX="${PHASE2_SMOKE_MAX:-0}"
MAX_RETRY_PASSES="${PHASE2_MAX_RETRY_PASSES:-3}"
PREFLIGHT_ONLY="${PHASE2_PREFLIGHT_ONLY:-0}"

PHASE2_LOG_FILE="${PHASE2_LOG_FILE:-$LOG_DIR/master.log}"
if [[ -n "${PHASE2_EXTENSION:-}" ]]; then
  echo "=== Phase 2 matrix (extension; smoke_max=$SMOKE_MAX) profiles=${PHASE2_PROFILES:-default} ===" | tee -a "$PHASE2_LOG_FILE"
else
  echo "=== Phase 2 matrix (smoke_max=$SMOKE_MAX) ===" | tee "$PHASE2_LOG_FILE"
fi

_phase2_on_exit() {
  local ec=$?
  echo "[$(date -Iseconds)] run_phase2_matrix.sh exit code=${ec}" >> "$PHASE2_LOG_FILE"
}
trap _phase2_on_exit EXIT

if [[ "${PHASE2_SKIP_REBUILD:-0}" == "1" ]]; then
  echo "[$(date -Iseconds)] PHASE2_SKIP_REBUILD=1: skipping build_phase2_corpora" | tee -a "$PHASE2_LOG_FILE"
else
  uv run python "$ROOT/benchmark/build_phase2_corpora.py" >> "$PHASE2_LOG_FILE" 2>&1
fi >> "$PHASE2_LOG_FILE" 2>&1

uv run python - <<'PY' >> "$PHASE2_LOG_FILE" 2>&1
import json
from pathlib import Path
from benchmark.few_shot import assert_no_test_leakage

manifest = json.loads(Path("benchmark/phases/phase2/MANIFEST.json").read_text())
test_ids = set()
for t in manifest["tracks"].values():
    test_ids.update(t["case_ids"])
assert_no_test_leakage(test_case_ids=test_ids)
print(f"[preflight] few-shot OK: no overlap with {len(test_ids)} test case_ids")
PY

phase2_require_gpu() {
  if [[ "${PHASE2_ALLOW_CPU:-}" == "1" ]]; then
    echo "[preflight] PHASE2_ALLOW_CPU=1: skipping GPU requirement" | tee -a "$PHASE2_LOG_FILE"
    return 0
  fi
  if command -v nvidia-smi >/dev/null 2>&1; then
    nsmi_line="$(nvidia-smi -L 2>&1 | head -1 || true)"
    echo "[preflight] nvidia-smi: ${nsmi_line:-no output}" | tee -a "$PHASE2_LOG_FILE"
  else
    echo "[preflight] nvidia-smi: not installed" | tee -a "$PHASE2_LOG_FILE"
  fi
  if ! uv run python -c "import torch; exit(0 if torch.cuda.is_available() and torch.cuda.device_count()>0 else 1)" >> "$PHASE2_LOG_FILE" 2>&1; then
    echo "ERROR: Phase 2 requires a CUDA GPU (torch.cuda unavailable). Install NVIDIA driver or set PHASE2_ALLOW_CPU=1 for CPU debugging." | tee -a "$PHASE2_LOG_FILE"
    exit 2
  fi
  echo "[preflight] GPU OK (torch.cuda)" | tee -a "$PHASE2_LOG_FILE"
}

phase2_require_gpu

if [[ "$PREFLIGHT_ONLY" == "1" ]]; then
  echo "=== Preflight only; exiting ===" | tee -a "$PHASE2_LOG_FILE"
  exit 0
fi

count_cases() {
  find "$1" -maxdepth 1 -name 'OWASP_*.json' 2>/dev/null | wc -l | tr -d ' '
}

N_FP="$(count_cases "$CORPORA_FP")"
N_TP="$(count_cases "$CORPORA_TP")"
N_BL="$(count_cases "$CORPORA_BL")"

cell_done_count() {
  local runs_root="$1"
  local profile="$2"
  local thinking="$3"
  local fewshot="$4"
  uv run python - "$runs_root" "$profile" "$thinking" "$fewshot" <<'PY'
import json, sys
from pathlib import Path
runs_root, profile, thinking, fewshot = sys.argv[1:5]
llm = Path(runs_root) / f"thinking_{thinking}" / f"fewshot_{fewshot}" / profile / "llm"
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
  local track="$1"
  local gold="$2"
  local case_dir="$3"
  local runs_root="$4"
  local n_expected="$5"
  local profile="$6"
  local thinking="$7"
  local fewshot="$8"

  local done
  done="$(cell_done_count "$runs_root" "$profile" "$thinking" "$fewshot")"
  if [[ "$PHASE2_FORCE" != "1" && "$done" -ge "$n_expected" ]]; then
    echo "--- SKIP $track $profile think=$thinking fs=$fewshot ($done/$n_expected) ---" | tee -a "$PHASE2_LOG_FILE"
    return 0
  fi

  local -a force_args=()
  [[ "$PHASE2_FORCE" == "1" ]] && force_args=(--force)
  local -a max_args=()
  if [[ "$SMOKE_MAX" -gt 0 ]]; then
    max_args=(--max-cases "$SMOKE_MAX")
    n_expected="$SMOKE_MAX"
  fi

  local -a think_args=()
  [[ "$thinking" == "on" ]] && think_args=(--thinking)

  local log="$LOG_DIR/${track}_${profile}_think_${thinking}_fs${fewshot}.log"
  echo "--- $(date -Iseconds) $track $profile think=$thinking fewshot=$fewshot ($done/$n_expected) ---" | tee -a "$log" "$PHASE2_LOG_FILE"
  phase2_gpu_cleanup "$PHASE2_LOG_FILE"
  phase2_save_env
  phase2_apply_token_limits "$thinking" "$profile"

  set +e
  uv run python "$ROOT/benchmark/run_batch.py" \
    --agent llm \
    --case-dir "$case_dir" \
    --profile "$profile" \
    --runs-root "$runs_root/thinking_${thinking}/fewshot_${fewshot}" \
    --gold "$gold" \
    --few-shot "$fewshot" \
    --retry-missing \
    "${think_args[@]}" \
    "${force_args[@]}" \
    "${max_args[@]}" \
    2>&1 | tee -a "$log"
  local batch_ec=${PIPESTATUS[0]}
  set -e
  if [[ "$batch_ec" -ne 0 ]]; then
    echo "[WARN $(date -Iseconds)] run_batch exited ${batch_ec} for ${track} ${profile} think=${thinking} fs=${fewshot}" | tee -a "$log" "$PHASE2_LOG_FILE"
  fi

  phase2_restore_env
  phase2_gpu_cleanup "$log"
  uv run python "$ROOT/benchmark/repair_llm_results.py" \
    --runs "$runs_root/thinking_${thinking}/fewshot_${fewshot}" \
    --profile "$profile" || true
}

run_cell_with_retries() {
  local track="$1"
  local gold="$2"
  local case_dir="$3"
  local runs_root="$4"
  local n_expected="$5"
  local profile="$6"
  local thinking="$7"
  local fewshot="$8"

  local pass=1
  while [[ "$pass" -le "$MAX_RETRY_PASSES" ]]; do
    run_cell "$track" "$gold" "$case_dir" "$runs_root" "$n_expected" "$profile" "$thinking" "$fewshot"
    local done_now
    done_now="$(cell_done_count "$runs_root" "$profile" "$thinking" "$fewshot")"
    if [[ "$done_now" -ge "$n_expected" ]]; then
      return 0
    fi
    echo "--- RETRY $track $profile think=$thinking fs=$fewshot pass=$pass done=$done_now/$n_expected ---" | tee -a "$PHASE2_LOG_FILE"
    pass=$((pass + 1))
  done
}

_load_summary_profiles() {
  SUMMARY_PROFILES=("${PROFILES[@]}")
  if [[ -n "${PHASE2_SUMMARY_PROFILES:-}" ]]; then
    # shellcheck disable=SC2206
    SUMMARY_PROFILES=($PHASE2_SUMMARY_PROFILES)
  fi
}

summarize_cell() {
  local gold="$1"
  local case_dir="$2"
  local runs_root="$3"
  local thinking="$4"
  local fewshot="$5"
  local out="$6"
  local -a prof_args=()
  for p in "${SUMMARY_PROFILES[@]}"; do
    prof_args+=(--profile "$p")
  done

  if [[ "$gold" == "BL" ]]; then
    uv run python "$ROOT/benchmark/summarize_borderline.py" \
      --case-dir "$case_dir" \
      --runs "$runs_root/thinking_${thinking}/fewshot_${fewshot}" \
      "${prof_args[@]}" \
      --json-out "$out" || true
  else
    uv run python "$ROOT/benchmark/summarize_triage.py" \
      --case-dir "$case_dir" --gold "$gold" \
      --runs "$runs_root/thinking_${thinking}/fewshot_${fewshot}" \
      "${prof_args[@]}" \
      --json-out "$out" || true
  fi
}

summarize_all() {
  echo "=== Phase 2 summaries ===" | tee -a "$PHASE2_LOG_FILE"
  _load_summary_profiles
  for thinking in off on; do
    for fewshot in 0 3; do
      summarize_cell FP "$CORPORA_FP" "$RUNS_FP" "$thinking" "$fewshot" \
        "$SUM_DIR/comparison_fp_test_thinking_${thinking}_fewshot_${fewshot}.json"
      summarize_cell TP "$CORPORA_TP" "$RUNS_TP" "$thinking" "$fewshot" \
        "$SUM_DIR/comparison_tp_test_thinking_${thinking}_fewshot_${fewshot}.json"
      summarize_cell BL "$CORPORA_BL" "$RUNS_BL" "$thinking" "$fewshot" \
        "$SUM_DIR/comparison_bl_test_thinking_${thinking}_fewshot_${fewshot}.json"
    done
  done
  uv run python "$ROOT/benchmark/phases/phase2/merge_phase2_summary.py" \
    --summaries-dir "$SUM_DIR" \
    --json-out "$SUM_DIR/phase2_matrix.json" || true
}

# Order: 4B→8B→14B→coder; FP→TP→BL; fewshot 0→3; all thinking off before any thinking on.
for thinking in off on; do
  for profile in "${PROFILES[@]}"; do
    for track_info in "fp:FP:$CORPORA_FP:$RUNS_FP:$N_FP" "tp:TP:$CORPORA_TP:$RUNS_TP:$N_TP" "bl:BL:$CORPORA_BL:$RUNS_BL:$N_BL"; do
      IFS=':' read -r track gold case_dir runs_root n_expected <<< "$track_info"
      for fewshot in 0 3; do
        run_cell_with_retries "$track" "$gold" "$case_dir" "$runs_root" "$n_expected" "$profile" "$thinking" "$fewshot"
      done
    done
    phase2_gpu_cleanup "$PHASE2_LOG_FILE"
  done
done

summarize_all
date -Iseconds > "$LOG_DIR/finished_at.txt"
if [[ -n "${PHASE2_EXTENSION:-}" ]]; then
  date -Iseconds > "$LOG_DIR/qwen35_finished_at.txt"
fi
echo "=== Phase 2 complete ===" | tee -a "$PHASE2_LOG_FILE"
