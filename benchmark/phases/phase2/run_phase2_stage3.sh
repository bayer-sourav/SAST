#!/usr/bin/env bash
# Phase 2 Stage 3: prompt variant experiments (v7/v8/v9) on qwen3_5_9b + qwen3_coder_30b.
# Target: VDR > 95% AND FPRR >= 90% on full test corpora.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

STAGE3_MANIFEST="$ROOT/benchmark/phases/phase2/stage3/MANIFEST.json"
LOG_DIR="runs/phase2/stage3/logs"
SUM_DIR="runs/phase2/stage3/summaries"
mkdir -p "$LOG_DIR" "$SUM_DIR"

CORPORA_FP="benchmark/corpora/phase2_fp_test"
CORPORA_TP="benchmark/corpora/phase2_tp_test"
CORPORA_BL="benchmark/corpora/phase2_bl_test"

RUNS_FP="runs/phase2/stage3/fp"
RUNS_TP="runs/phase2/stage3/tp"
RUNS_BL="runs/phase2/stage3/bl"

# shellcheck source=phase2_cell_env.sh
source "$ROOT/benchmark/phase2_cell_env.sh"

export HF_HOME="${PHASE2_HF_HOME:-${HOME}/.cache/huggingface}"
export HF_HUB_CACHE="${HF_HOME}/hub"
export TRANSFORMERS_CACHE="${HF_HOME}/transformers"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"

PHASE2_FORCE="${PHASE2_FORCE:-0}"
SMOKE_MAX="${PHASE3_SMOKE_MAX:-0}"
MAX_RETRY_PASSES="${PHASE2_MAX_RETRY_PASSES:-3}"
PHASE2_LOG_FILE="${PHASE2_LOG_FILE:-$LOG_DIR/master.log}"
PROMPT_FILTER="${PHASE3_PROMPT:-}"  # optional: run single prompt version
CELL_FILTER="${PHASE3_CELL:-}"      # optional: run single cell id

echo "=== Phase 2 Stage 3 ($(date -Iseconds)) smoke_max=$SMOKE_MAX ===" | tee "$PHASE2_LOG_FILE"

if [[ "${PHASE2_SKIP_REBUILD:-0}" != "1" ]]; then
  uv run python "$ROOT/benchmark/build_phase2_corpora.py" >> "$PHASE2_LOG_FILE" 2>&1
fi

uv run python - <<'PY' >> "$PHASE2_LOG_FILE" 2>&1
import json
from pathlib import Path
from benchmark.few_shot import assert_no_test_leakage, resolve_few_shot_config_path
from benchmark.prompt_versions import list_prompt_versions, resolve_prompt_version

manifest = json.loads(Path("benchmark/phases/phase2/MANIFEST.json").read_text())
stage3 = json.loads(Path("benchmark/phases/phase2/stage3/MANIFEST.json").read_text())
test_ids = set()
for t in manifest["tracks"].values():
    test_ids.update(t["case_ids"])
assert_no_test_leakage(test_case_ids=test_ids)
for pv in stage3["prompt_versions"]:
    resolve_prompt_version(pv["id"])
for cell in stage3["cells"]:
    cfg = cell.get("few_shot_config")
    if cfg:
        p = resolve_few_shot_config_path(cfg)
        print(f"[preflight] cell {cell['id']}: prompt={cell['prompt_version']} fs={cfg} -> {p}")
print(f"[preflight] stage3 cells={len(stage3['cells'])} prompts={list_prompt_versions()}")
PY

phase2_require_gpu() {
  if [[ "${PHASE2_ALLOW_CPU:-}" == "1" ]]; then return 0; fi
  if ! uv run python -c "import torch; exit(0 if torch.cuda.is_available() and torch.cuda.device_count()>0 else 1)" >> "$PHASE2_LOG_FILE" 2>&1; then
    echo "ERROR: CUDA GPU required" | tee -a "$PHASE2_LOG_FILE"
    exit 2
  fi
  echo "[preflight] GPU OK" | tee -a "$PHASE2_LOG_FILE"
}
phase2_require_gpu

count_cases() {
  find "$1" -maxdepth 1 \( -name 'OWASP_*.json' -o -name 'BLSynthetic_*.json' \) 2>/dev/null | wc -l | tr -d ' '
}

N_FP="$(count_cases "$CORPORA_FP")"
N_TP="$(count_cases "$CORPORA_TP")"
N_BL="$(count_cases "$CORPORA_BL")"

cell_done_count() {
  local runs_root="$1" profile="$2"
  uv run python - "$runs_root" "$profile" <<'PY'
import json, sys
from pathlib import Path
runs_root, profile = sys.argv[1:3]
llm = Path(runs_root) / profile / "llm"
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
  local track="$1" gold="$2" case_dir="$3" runs_root="$4" n_expected="$5"
  local profile="$6" fewshot="$7" fs_config="$8" prompt_version="$9" cell_id="${10}"

  local done
  done="$(cell_done_count "$runs_root" "$profile")"
  if [[ "$PHASE2_FORCE" != "1" && "$done" -ge "$n_expected" ]]; then
    echo "--- SKIP stage3/$cell_id $track $profile prompt=$prompt_version ($done/$n_expected) ---" | tee -a "$PHASE2_LOG_FILE"
    return 0
  fi

  local -a force_args=()
  [[ "$PHASE2_FORCE" == "1" ]] && force_args=(--force)
  local -a max_args=()
  if [[ "$SMOKE_MAX" -gt 0 ]]; then
    max_args=(--max-cases "$SMOKE_MAX")
    n_expected="$SMOKE_MAX"
  fi

  local -a fs_cfg_args=()
  if [[ -n "$fs_config" && "$fs_config" != "null" ]]; then
    fs_cfg_args=(--few-shot-config "$fs_config")
  fi

  local log="$LOG_DIR/${cell_id}_${track}.log"
  echo "--- $(date -Iseconds) stage3/$cell_id $track $profile prompt=$prompt_version ($done/$n_expected) ---" | tee -a "$log" "$PHASE2_LOG_FILE"
  phase2_gpu_cleanup "$PHASE2_LOG_FILE"
  phase2_save_env
  phase2_apply_token_limits on "$profile"

  set +e
  uv run python "$ROOT/benchmark/run_batch.py" \
    --agent llm \
    --case-dir "$case_dir" \
    --profile "$profile" \
    --runs-root "$runs_root" \
    --gold "$gold" \
    --few-shot "$fewshot" \
    --thinking \
    --retry-missing \
    --prompt-version "$prompt_version" \
    "${fs_cfg_args[@]}" \
    "${force_args[@]}" \
    "${max_args[@]}" \
    2>&1 | tee -a "$log"
  local batch_ec=${PIPESTATUS[0]}
  set -e
  if [[ "$batch_ec" -ne 0 ]]; then
    echo "[WARN] run_batch exit ${batch_ec} for ${cell_id} ${track}" | tee -a "$log" "$PHASE2_LOG_FILE"
  fi

  phase2_restore_env
  phase2_gpu_cleanup "$log"
  uv run python "$ROOT/benchmark/repair_llm_results.py" \
    --runs "$runs_root" \
    --profile "$profile" || true
}

run_cell_retries() {
  local pass=1
  while [[ "$pass" -le "$MAX_RETRY_PASSES" ]]; do
    run_cell "$@"
    local done_now
    done_now="$(cell_done_count "$4" "$6")"
    local n_exp="$5"
    [[ "$SMOKE_MAX" -gt 0 ]] && n_exp="$SMOKE_MAX"
    if [[ "$done_now" -ge "$n_exp" ]]; then return 0; fi
    echo "--- RETRY pass=$pass done=$done_now/$n_exp ---" | tee -a "$PHASE2_LOG_FILE"
    pass=$((pass + 1))
  done
}

summarize_all() {
  echo "=== Stage 3 summaries ===" | tee -a "$PHASE2_LOG_FILE"
  while IFS= read -r line; do
    IFS='|' read -r cell_id profile prompt_version fewshot <<< "$line"
    local runs_fp="$RUNS_FP/thinking_on/fewshot_${fewshot}/${prompt_version}"
    local runs_tp="$RUNS_TP/thinking_on/fewshot_${fewshot}/${prompt_version}"
    local runs_bl="$RUNS_BL/thinking_on/fewshot_${fewshot}/${prompt_version}"
    uv run python "$ROOT/benchmark/summarize_triage.py" \
      --case-dir "$CORPORA_FP" --gold FP \
      --runs "$runs_fp" \
      --profile "$profile" \
      --json-out "$SUM_DIR/${cell_id}_fp.json" || true
    uv run python "$ROOT/benchmark/summarize_triage.py" \
      --case-dir "$CORPORA_TP" --gold TP \
      --runs "$runs_tp" \
      --profile "$profile" \
      --json-out "$SUM_DIR/${cell_id}_tp.json" || true
    uv run python "$ROOT/benchmark/summarize_borderline.py" \
      --case-dir "$CORPORA_BL" \
      --runs "$runs_bl" \
      --profile "$profile" \
      --json-out "$SUM_DIR/${cell_id}_bl.json" || true
  done < <(
    uv run python - "$STAGE3_MANIFEST" <<'PY'
import json, sys
for c in json.loads(open(sys.argv[1]).read())["cells"]:
    print(f"{c['id']}|{c['profile']}|{c['prompt_version']}|{c['fewshot']}")
PY
  )
  uv run python "$ROOT/benchmark/phases/phase2/stage3/report_stage3_status.py" || true
}

while IFS= read -r line; do
  IFS='|' read -r cell_id profile fewshot fs_config prompt_version <<< "$line"
  for track_info in "fp:FP:$CORPORA_FP:$RUNS_FP:$N_FP" "tp:TP:$CORPORA_TP:$RUNS_TP:$N_TP" "bl:BL:$CORPORA_BL:$RUNS_BL:$N_BL"; do
    IFS=':' read -r track gold case_dir runs_base n_expected <<< "$track_info"
    runs_root="$runs_base/thinking_on/fewshot_${fewshot}/${prompt_version}"
    run_cell_retries "$track" "$gold" "$case_dir" "$runs_root" "$n_expected" \
      "$profile" "$fewshot" "$fs_config" "$prompt_version" "$cell_id"
  done
  phase2_gpu_cleanup "$PHASE2_LOG_FILE"
done < <(
  uv run python - "$STAGE3_MANIFEST" "$PROMPT_FILTER" "$CELL_FILTER" <<'PY'
import json, sys
prompt_filter = sys.argv[2] or None
cell_filter = sys.argv[3] or None
order = {"qwen3_5_9b_bnb": 0, "qwen3_coder_30b_bnb": 1}
pv_order = {"v7-balanced": 0, "v8-dual-gate": 1, "v9-fprr-first": 2}
cells = json.loads(open(sys.argv[1]).read())["cells"]
if prompt_filter:
    cells = [c for c in cells if c["prompt_version"] == prompt_filter]
if cell_filter:
    cells = [c for c in cells if c["id"] == cell_filter]
cells.sort(key=lambda c: (order.get(c["profile"], 99), pv_order.get(c["prompt_version"], 99)))
for c in cells:
    cfg = c.get("few_shot_config") or ""
    print(f"{c['id']}|{c['profile']}|{c['fewshot']}|{cfg}|{c['prompt_version']}")
PY
)

summarize_all
date -Iseconds > "$LOG_DIR/finished_at.txt"
echo "=== Phase 2 Stage 3 complete ===" | tee -a "$PHASE2_LOG_FILE"
