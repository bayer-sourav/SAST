#!/usr/bin/env bash
# v8 Phase 1 ablations: hard-slice smoke (8A–8C), optional 600-case for one cell.
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

export HF_HOME="${PHASE2_HF_HOME:-${HOME}/.cache/huggingface}"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"

if [[ "${QWEN_INFER_BACKEND:-vllm}" == "vllm" ]]; then
  if ! uv run python -c "import vllm" 2>/dev/null; then
    echo "ERROR: vLLM required but not importable in .venv." >&2
    echo "Install: bash benchmark/phases/phase3/install_vllm_flash_attn.sh" >&2
    exit 1
  fi
fi

MANIFEST="$ROOT/benchmark/phases/phase2/v8_phase1/MANIFEST.json"
EVAL_ROOT="${V8_PHASE1_ROOT:-runs/phase2/v8_phase1}"
LOG="$EVAL_ROOT/phase1.log"
PROFILE="qwen3_5_9b_bnb"
PHASE1_FULL="${PHASE1_FULL:-0}"
PHASE1_CELL="${PHASE1_CELL:-}"
FORCE="${PHASE1_FORCE:-0}"
SKIP_SMOKE="${PHASE1_SKIP_SMOKE:-0}"

mkdir -p "$EVAL_ROOT" "$(dirname "$LOG")"
cp -f "$ROOT/benchmark/phases/phase2/smoke_slice_cases.json" /tmp/smoke_slice_cases.json

echo "=== v8 Phase 1 $(date -Iseconds) ===" | tee "$LOG"
echo "eval_root=$EVAL_ROOT full=$PHASE1_FULL cell=$PHASE1_CELL" | tee -a "$LOG"

echo "[setup] Hard slice corpora" | tee -a "$LOG"
uv run python "$ROOT/benchmark/phases/phase2/build_hard_slice_corpora.py" 2>&1 | tee -a "$LOG"

_run_smoke_cell() {
  local cell_id="$1"
  local prompt="$2"
  local fewshot="$3"
  local fs_cfg="$4"
  local thinking="$5"
  local runs_root="$EVAL_ROOT/$cell_id/hard_slice"
  local tracks_json="$EVAL_ROOT/$cell_id/tracks_hard_slice.json"
  local think_flag=()
  if [[ "$thinking" == "true" ]]; then
    think_flag=(--thinking)
  fi
  local force_flag=()
  if [[ "$FORCE" == "1" ]]; then
    force_flag=(--force)
  fi

  cat > "$tracks_json" <<EOF
[
  {"gold": "FP", "case_dir": "benchmark/corpora/phase2_hard_slice_fp", "runs_root": "$runs_root"},
  {"gold": "TP", "case_dir": "benchmark/corpora/phase2_hard_slice_tp", "runs_root": "$runs_root"}
]
EOF
  echo "[smoke] $cell_id prompt=$prompt fs=$fewshot cfg=$fs_cfg think=$thinking" | tee -a "$LOG"
  phase2_gpu_cleanup "$LOG"
  uv run python "$ROOT/benchmark/run_batch.py" \
    --agent llm \
    --profile "$PROFILE" \
    --prompt-version "$prompt" \
    "${think_flag[@]}" \
    --few-shot "$fewshot" \
    --few-shot-config "$fs_cfg" \
    --tracks-json "$tracks_json" \
    --retry-missing \
    "${force_flag[@]}" 2>&1 | tee -a "$LOG"
  phase2_gpu_cleanup "$LOG"
}

_run_600_cell() {
  local cell_id="$1"
  local prompt="$2"
  local fewshot="$3"
  local fs_cfg="$4"
  local thinking="$5"
  local cell_root="$EVAL_ROOT/$cell_id/full_600"
  local sum_dir="$cell_root/summaries"
  local think_flag=()
  if [[ "$thinking" == "true" ]]; then
    think_flag=(--thinking)
  fi
  local force_flag=()
  if [[ "$FORCE" == "1" ]]; then
    force_flag=(--force)
  fi

  mkdir -p "$sum_dir"
  cat > "$cell_root/tp_fp_tracks.json" <<EOF
[
  {"gold": "FP", "case_dir": "benchmark/corpora/phase2_fp_test", "runs_root": "$cell_root/fp"},
  {"gold": "TP", "case_dir": "benchmark/corpora/phase2_tp_test", "runs_root": "$cell_root/tp"}
]
EOF
  echo "[600] $cell_id" | tee -a "$LOG"
  phase2_gpu_cleanup "$LOG"
  uv run python "$ROOT/benchmark/run_batch.py" \
    --agent llm \
    --profile "$PROFILE" \
    --prompt-version "$prompt" \
    "${think_flag[@]}" \
    --few-shot "$fewshot" \
    --few-shot-config "$fs_cfg" \
    --tracks-json "$cell_root/tp_fp_tracks.json" \
    --retry-missing \
    "${force_flag[@]}" 2>&1 | tee -a "$LOG"
  phase2_gpu_cleanup "$LOG"

  # BL results land under $BL_V4_RUNS_ROOT/<profile>/llm/; keep that root as the
  # summarize --runs path (do not append stage2_ship_bl — that only matches the
  # dedicated prod-ship layout under runs/bl_v4_prod_ship_eval/).
  BL_V4_SKIP_REBUILD=1 BL_V4_FORCE_RERUN="$FORCE" \
    BL_V4_RUNS_ROOT="$cell_root/bl" BL_V4_REVIEW_DIR="$cell_root" \
    SAST_PROMPT_VERSION="$prompt" SAST_FEWSHOT_CONFIG="$fs_cfg" BL_V4_FEWSHOT="$fewshot" \
    bash "$ROOT/benchmark/phases/phase2/run_bl_v4_eval.sh" 2>&1 | tee -a "$LOG"

  uv run python "$ROOT/benchmark/summarize_triage.py" \
    --case-dir benchmark/corpora/phase2_fp_test --gold FP \
    --runs "$cell_root/fp" --profile "$PROFILE" \
    --json-out "$sum_dir/comparison_fp.json" 2>&1 | tee -a "$LOG"
  uv run python "$ROOT/benchmark/summarize_triage.py" \
    --case-dir benchmark/corpora/phase2_tp_test --gold TP \
    --runs "$cell_root/tp" --profile "$PROFILE" \
    --json-out "$sum_dir/comparison_tp.json" 2>&1 | tee -a "$LOG"
  uv run python "$ROOT/benchmark/summarize_borderline.py" \
    --case-dir benchmark/corpora/phase2_bl_test \
    --runs "$cell_root/bl" --profile "$PROFILE" \
    --json-out "$sum_dir/comparison_bl.json" 2>&1 | tee -a "$LOG"
  uv run python "$ROOT/benchmark/phases/phase2/merge_prod_ship_600_summary.py" \
    --sum-dir "$sum_dir" --profile "$PROFILE" \
    --json-out "$sum_dir/merged_600.json" \
    --md-out "$cell_root/PROD_SHIP_600_REPORT.md" 2>&1 | tee -a "$LOG"
}

if [[ "$SKIP_SMOKE" != "1" && "$PHASE1_FULL" != "1" ]]; then
  cells="$(uv run python - <<'PY'
import json, os
from pathlib import Path
m = json.loads(Path("benchmark/phases/phase2/v8_phase1/MANIFEST.json").read_text())
filt = os.environ.get("PHASE1_CELL", "").strip()
for c in m["cells"]:
    if filt and c["id"] != filt:
        continue
    print("\t".join([
        c["id"],
        c["prompt_version"],
        str(c["few_shot"]),
        c["few_shot_config"],
        "true" if c["thinking"] else "false",
    ]))
PY
)"
  while IFS=$'\t' read -r cid prompt fewshot fs_cfg thinking; do
    [[ -z "$cid" ]] && continue
    _run_smoke_cell "$cid" "$prompt" "$fewshot" "$fs_cfg" "$thinking"
  done <<< "$cells"

  uv run python "$ROOT/benchmark/phases/phase2/summarize_v8_phase1.py" \
    --eval-root "$EVAL_ROOT" 2>&1 | tee -a "$LOG"
fi

if [[ "$PHASE1_FULL" == "1" ]]; then
  target="${PHASE1_CELL:-}"
  if [[ -z "$target" ]]; then
    target="$(uv run python - <<'PY'
import json
from pathlib import Path
p = Path("runs/phase2/v8_phase1/PHASE1_SMOKE_SUMMARY.json")
if p.is_file():
    d = json.loads(p.read_text())
    ids = d.get("passed_ids") or []
    print(ids[0] if ids else d.get("best_id") or "")
else:
    print("")
PY
)"
  fi
  if [[ -z "$target" ]]; then
    echo "No PHASE1_CELL and no smoke summary; set PHASE1_CELL explicitly." | tee -a "$LOG"
    exit 1
  fi
  read -r prompt fewshot fs_cfg thinking <<< "$(uv run python - <<PY
import json
from pathlib import Path
m = json.loads(Path("benchmark/phases/phase2/v8_phase1/MANIFEST.json").read_text())
cid = "$target"
for c in m["cells"]:
    if c["id"] == cid:
        print(c["prompt_version"], c["few_shot"], c["few_shot_config"], "true" if c["thinking"] else "false")
        break
PY
)"
  _run_600_cell "$target" "$prompt" "$fewshot" "$fs_cfg" "$thinking"
  echo "Done 600-case: $EVAL_ROOT/$target/PROD_SHIP_600_REPORT.md" | tee -a "$LOG"
fi

echo "Done. $EVAL_ROOT/PHASE1_SMOKE_REPORT.md" | tee -a "$LOG"
