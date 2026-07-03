#!/usr/bin/env bash
# Resume BL v4 pilot after partial runs: sequential GPU jobs, no overlap.
# Typical flow: ship-bl 1-17 → balanced-bl 18-40 → ship-bl 18-40 → reports.
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

export HF_HOME="${PHASE2_HF_HOME:-${HOME}/.cache/huggingface}"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"

PROFILE="qwen3_5_9b_bnb"
FS_CONFIG="${SAST_FEWSHOT_CONFIG:-v2_3shot_tp_fp_bl}"
FEWSHOT=3
FORCE="${PILOT_FORCE_RERUN:-0}"
CORPUS="benchmark/corpora/bl_v4_pilot"
CORPUS_FIRST17="benchmark/corpora/bl_v4_pilot_ship_first17"
CORPUS_18_40="benchmark/corpora/bl_v4_pilot_bal_18_40"
RUNS_BAL="runs/bl_v4_pilot/stage2_good_bl"
RUNS_SHIP="runs/bl_v4_pilot/stage2_ship_bl"
LOG="$ROOT/runs/bl_v4_pilot/pilot_chain.log"

count_results() {
  local dir="$1"
  find "$ROOT/$dir" -name 'agent-llm-triage-result.json' 2>/dev/null | wc -l | tr -d ' '
}

run_batch() {
  local prompt="$1"
  local case_dir="$2"
  local runs_root="$3"
  local tag="$4"
  echo "=== [$tag] prompt=$prompt backend=${QWEN_INFER_BACKEND} cases=$case_dir $(date -Iseconds) ===" | tee -a "$LOG"
  # shellcheck source=../../phase2_cell_env.sh
  source "$ROOT/benchmark/phase2_cell_env.sh"
  phase2_gpu_cleanup "$LOG"
  local force_args=()
  if [[ "$FORCE" == "1" ]]; then
    force_args=(--force)
  fi
  uv run python "$ROOT/benchmark/run_batch.py" \
    --agent llm \
    --profile "$PROFILE" \
    --prompt-version "$prompt" \
    --thinking \
    --few-shot "$FEWSHOT" \
    --few-shot-config "$FS_CONFIG" \
    --gold BL \
    --case-dir "$case_dir" \
    --runs-root "$runs_root" \
    "${force_args[@]}" 2>&1 | tee -a "$LOG"
}

mkdir -p "$(dirname "$LOG")" "$ROOT/$RUNS_BAL" "$ROOT/$RUNS_SHIP"

echo "=== BL v4 pilot chain backend=${QWEN_INFER_BACKEND} $(date -Iseconds) ===" | tee "$LOG"

# Step 1: ship-bl 1-17
ship_n="$(count_results "$RUNS_SHIP")"
if [[ "$ship_n" -lt 17 ]]; then
  echo "[step 1] ship-bl 1-17 (have $ship_n/17)" | tee -a "$LOG"
  run_batch "v7-ship-bl" "$CORPUS_FIRST17" "$RUNS_SHIP" "ship-bl-1-17"
else
  echo "[step 1] ship-bl 1-17 already complete ($ship_n)" | tee -a "$LOG"
fi

# Step 2: balanced-bl 18-40
bal_n="$(count_results "$RUNS_BAL")"
if [[ "$bal_n" -lt 40 ]]; then
  echo "[step 2] v7-balanced-bl 18-40 (have $bal_n/40)" | tee -a "$LOG"
  run_batch "v7-balanced-bl" "$CORPUS_18_40" "$RUNS_BAL" "balanced-bl-18-40"
else
  echo "[step 2] balanced-bl already complete ($bal_n)" | tee -a "$LOG"
fi

# Step 3: ship-bl 18-40
ship_n="$(count_results "$RUNS_SHIP")"
if [[ "$ship_n" -lt 40 ]]; then
  echo "[step 3] v7-ship-bl 18-40 (have $ship_n/40)" | tee -a "$LOG"
  run_batch "v7-ship-bl" "$CORPUS_18_40" "$RUNS_SHIP" "ship-bl-18-40"
else
  echo "[step 3] ship-bl already complete ($ship_n)" | tee -a "$LOG"
fi

# Step 4: reports
echo "[step 4] reports" | tee -a "$LOG"
uv run python "$ROOT/benchmark/analyze_bl_v4_pilot.py" \
  --corpus "$CORPUS" \
  --runs "$RUNS_BAL" \
  --profile "$PROFILE" \
  --json-out "$ROOT/runs/bl_v4_pilot/pilot_review_bl.json" \
  --html-out "$ROOT/runs/bl_v4_pilot/PILOT_REVIEW_BL.html" 2>&1 | tee -a "$LOG"

uv run python "$ROOT/benchmark/analyze_bl_v4_pilot.py" \
  --corpus "$CORPUS" \
  --runs "$RUNS_SHIP" \
  --profile "$PROFILE" \
  --json-out "$ROOT/runs/bl_v4_pilot/pilot_review_ship_bl.json" \
  --html-out "$ROOT/runs/bl_v4_pilot/PILOT_REVIEW_SHIP_BL.html" 2>&1 | tee -a "$LOG"

echo "Done. balanced-bl: PILOT_REVIEW_BL.html | ship-bl: PILOT_REVIEW_SHIP_BL.html" | tee -a "$LOG"
