#!/usr/bin/env bash
# Phase 2 Stage 2: v7-balanced prompt + versioned few-shot configs.
# Runs 4 selected cells (think=on only) × FP/TP/BL × 200 cases.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

STAGE2_MANIFEST="$ROOT/benchmark/phases/phase2/stage2/MANIFEST.json"
LOG_DIR="runs/phase2/stage2/logs"
SUM_DIR="runs/phase2/stage2/summaries"
mkdir -p "$LOG_DIR" "$SUM_DIR"

CORPORA_FP="benchmark/corpora/phase2_fp_test"
CORPORA_TP="benchmark/corpora/phase2_tp_test"
CORPORA_BL="benchmark/corpora/phase2_bl_test"

RUNS_FP="runs/phase2/stage2/fp"
RUNS_TP="runs/phase2/stage2/tp"
RUNS_BL="runs/phase2/stage2/bl"

# shellcheck source=phase2_cell_env.sh
source "$ROOT/benchmark/phase2_cell_env.sh"

export HF_HOME="${PHASE2_HF_HOME:-${HOME}/.cache/huggingface}"
export HF_HUB_CACHE="${HF_HOME}/hub"
export TRANSFORMERS_CACHE="${HF_HOME}/transformers"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"

PHASE2_FORCE="${PHASE2_FORCE:-0}"
SMOKE_MAX="${PHASE2_SMOKE_MAX:-0}"
MAX_RETRY_PASSES="${PHASE2_MAX_RETRY_PASSES:-3}"
PHASE2_LOG_FILE="${PHASE2_LOG_FILE:-$LOG_DIR/master.log}"

echo "=== Phase 2 Stage 2 ($(date -Iseconds)) smoke_max=$SMOKE_MAX ===" | tee "$PHASE2_LOG_FILE"

if [[ "${PHASE2_SKIP_REBUILD:-0}" != "1" ]]; then
  uv run python "$ROOT/benchmark/build_phase2_corpora.py" >> "$PHASE2_LOG_FILE" 2>&1
fi

uv run python - <<'PY' >> "$PHASE2_LOG_FILE" 2>&1
import json
from pathlib import Path
from benchmark.few_shot import assert_no_test_leakage, resolve_few_shot_config_path

manifest = json.loads(Path("benchmark/phases/phase2/MANIFEST.json").read_text())
stage2 = json.loads(Path("benchmark/phases/phase2/stage2/MANIFEST.json").read_text())
test_ids = set()
for t in manifest["tracks"].values():
    test_ids.update(t["case_ids"])
assert_no_test_leakage(test_case_ids=test_ids)
for cell in stage2["cells"]:
    cfg = cell.get("few_shot_config")
    if cfg:
        p = resolve_few_shot_config_path(cfg)
        print(f"[preflight] cell {cell['id']}: few_shot_config={cfg} -> {p}")
print(f"[preflight] stage2 cells={len(stage2['cells'])} few-shot leakage OK")
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
  find "$1" -maxdepth 1 -name 'OWASP_*.json' -o -name 'BLSynthetic_*.json' 2>/dev/null | wc -l | tr -d ' '
}

N_FP="$(count_cases "$CORPORA_FP")"
N_TP="$(count_cases "$CORPORA_TP")"
N_BL="$(count_cases "$CORPORA_BL")"

cell_done_count() {
  local runs_root="$1" profile="$2" fewshot="$3"
  uv run python - "$runs_root" "$profile" "$fewshot" <<'PY'
import json, sys
from pathlib import Path
runs_root, profile, fewshot = sys.argv[1:4]
llm = Path(runs_root) / "thinking_on" / f"fewshot_{fewshot}" / profile / "llm"
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
  local profile="$6" fewshot="$7" fs_config="$8" cell_id="$9"

  local done
  done="$(cell_done_count "$runs_root" "$profile" "$fewshot")"
  if [[ "$PHASE2_FORCE" != "1" && "$done" -ge "$n_expected" ]]; then
    echo "--- SKIP stage2/$cell_id $track $profile fs=$fewshot ($done/$n_expected) ---" | tee -a "$PHASE2_LOG_FILE"
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
  echo "--- $(date -Iseconds) stage2/$cell_id $track $profile fs=$fewshot cfg=${fs_config:-none} ($done/$n_expected) ---" | tee -a "$log" "$PHASE2_LOG_FILE"
  phase2_gpu_cleanup "$PHASE2_LOG_FILE"
  phase2_save_env
  phase2_apply_token_limits on "$profile"

  set +e
  uv run python "$ROOT/benchmark/run_batch.py" \
    --agent llm \
    --case-dir "$case_dir" \
    --profile "$profile" \
    --runs-root "$runs_root/thinking_on/fewshot_${fewshot}" \
    --gold "$gold" \
    --few-shot "$fewshot" \
    --thinking \
    --retry-missing \
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
    --runs "$runs_root/thinking_on/fewshot_${fewshot}" \
    --profile "$profile" || true
}

run_cell_retries() {
  local pass=1
  while [[ "$pass" -le "$MAX_RETRY_PASSES" ]]; do
    run_cell "$@"
    local done_now
    done_now="$(cell_done_count "$4" "$6" "$7")"
    local n_exp="$5"
    [[ "$SMOKE_MAX" -gt 0 ]] && n_exp="$SMOKE_MAX"
    if [[ "$done_now" -ge "$n_exp" ]]; then return 0; fi
    echo "--- RETRY pass=$pass done=$done_now/$n_exp ---" | tee -a "$PHASE2_LOG_FILE"
    pass=$((pass + 1))
  done
}

summarize_all() {
  echo "=== Stage 2 summaries ===" | tee -a "$PHASE2_LOG_FILE"
  local -a profs=()
  while IFS= read -r p; do profs+=("$p"); done < <(
    uv run python - "$STAGE2_MANIFEST" <<'PY'
import json, sys
for c in json.loads(open(sys.argv[1]).read())["cells"]:
    print(c["profile"])
PY
  )
  for cell in $(uv run python - "$STAGE2_MANIFEST" <<'PY'
import json, sys
for c in json.loads(open(sys.argv[1]).read())["cells"]:
    print(f"{c['fewshot']}")
PY
); do
    :
  done
  # Per-cell fewshot levels differ; summarize each fs bucket present
  for fewshot in 0 3; do
    local -a prof_args=()
    while IFS= read -r line; do
      IFS=: read -r prof fs <<< "$line"
      [[ "$fs" == "$fewshot" ]] && prof_args+=(--profile "$prof")
    done < <(
      uv run python - "$STAGE2_MANIFEST" <<'PY'
import json, sys
for c in json.loads(open(sys.argv[1]).read())["cells"]:
    print(f"{c['profile']}:{c['fewshot']}")
PY
    )
    [[ ${#prof_args[@]} -eq 0 ]] && continue
    uv run python "$ROOT/benchmark/summarize_triage.py" \
      --case-dir "$CORPORA_FP" --gold FP \
      --runs "$RUNS_FP/thinking_on/fewshot_${fewshot}" \
      "${prof_args[@]}" \
      --json-out "$SUM_DIR/comparison_fp_think_on_fs${fewshot}.json" || true
    uv run python "$ROOT/benchmark/summarize_triage.py" \
      --case-dir "$CORPORA_TP" --gold TP \
      --runs "$RUNS_TP/thinking_on/fewshot_${fewshot}" \
      "${prof_args[@]}" \
      --json-out "$SUM_DIR/comparison_tp_think_on_fs${fewshot}.json" || true
    uv run python "$ROOT/benchmark/summarize_borderline.py" \
      --case-dir "$CORPORA_BL" \
      --runs "$RUNS_BL/thinking_on/fewshot_${fewshot}" \
      "${prof_args[@]}" \
      --json-out "$SUM_DIR/comparison_bl_think_on_fs${fewshot}.json" || true
  done
  uv run python "$ROOT/benchmark/phases/phase2/stage2/report_stage2_status.py" || true
}

# Order: smaller/faster profiles first; FP→TP→BL per cell
while IFS= read -r line; do
  IFS='|' read -r cell_id profile fewshot fs_config <<< "$line"
  for track_info in "fp:FP:$CORPORA_FP:$RUNS_FP:$N_FP" "tp:TP:$CORPORA_TP:$RUNS_TP:$N_TP" "bl:BL:$CORPORA_BL:$RUNS_BL:$N_BL"; do
    IFS=':' read -r track gold case_dir runs_root n_expected <<< "$track_info"
    run_cell_retries "$track" "$gold" "$case_dir" "$runs_root" "$n_expected" \
      "$profile" "$fewshot" "$fs_config" "$cell_id"
  done
  phase2_gpu_cleanup "$PHASE2_LOG_FILE"
done < <(
  uv run python - "$STAGE2_MANIFEST" <<'PY'
import json, sys
order = {"qwen3_8b_bnb": 0, "qwen3_14b_bnb": 1, "qwen3_5_9b_bnb": 2, "qwen3_coder_30b_bnb": 3}
cells = json.loads(open(sys.argv[1]).read())["cells"]
cells.sort(key=lambda c: order.get(c["profile"], 99))
for c in cells:
    cfg = c.get("few_shot_config") or ""
    print(f"{c['id']}|{c['profile']}|{c['fewshot']}|{cfg}")
PY
)

summarize_all
date -Iseconds > "$LOG_DIR/finished_at.txt"
echo "=== Phase 2 Stage 2 complete ===" | tee -a "$PHASE2_LOG_FILE"
