#!/usr/bin/env bash
# Phase 3B infra audit + safe optimizations. Run once before long 3B jobs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

echo "=== Phase 3B infra audit $(date -Iseconds) ==="

echo
echo "--- CPU ---"
echo "cores: $(nproc)"
lscpu | grep -E "Model name|CPU\(s\)|Thread|Core" || true

echo
echo "--- RAM ---"
free -h

echo
echo "--- SWAP ---"
swapon --show 2>/dev/null || echo "(no swap configured)"
echo "vm.swappiness=$(cat /proc/sys/vm/swappiness)"

echo
echo "--- DISK ---"
df -hT / /tmp "${HOME}" 2>/dev/null || df -h /
echo "SAST project: $(du -sh "$ROOT" 2>/dev/null | cut -f1)"
echo "HF cache: $(du -sh "${HF_HOME:-$HOME/.cache/huggingface}" 2>/dev/null | cut -f1 || echo n/a)"
echo "runs/phase3: $(du -sh "$ROOT/runs/phase3" 2>/dev/null | cut -f1 || echo n/a)"

echo
echo "--- GPU ---"
if command -v nvidia-smi >/dev/null; then
  nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version,persistence_mode --format=csv
else
  echo "nvidia-smi not found"
fi

echo
echo "--- ML stack ---"
uv run python3 - <<'PY'
import torch
print(f"torch {torch.__version__} cuda={torch.cuda.is_available()}")
if torch.cuda.is_available():
    print(f"gpu {torch.cuda.get_device_name(0)}")
for mod, label in [("flash_attn", "flash_attn"), ("xformers", "xformers"), ("unsloth", "unsloth")]:
    try:
        m = __import__(mod)
        v = getattr(m, "__version__", "ok")
        print(f"{label}: {v}")
    except Exception as e:
        print(f"{label}: MISSING ({e})")
PY

echo
echo "--- Recommendations ---"
AVAIL_GB=$(free -g | awk '/^Mem:/ {print $7}')
DISK_AVAIL=$(df -BG / | awk 'NR==2 {print $4}' | tr -d G)
HF_SIZE=$(du -sm "${HF_HOME:-$HOME/.cache/huggingface}" 2>/dev/null | cut -f1 || echo 0)

ok=true
if [[ "${AVAIL_GB:-0}" -lt 32 ]]; then
  echo "WARN: available RAM ${AVAIL_GB}G — prefer unload trainer before val infer"
  ok=false
else
  echo "OK: RAM ${AVAIL_GB}G available"
fi
if [[ "${DISK_AVAIL:-0}" -lt 50 ]]; then
  echo "WARN: disk free ${DISK_AVAIL}G — monitor LoRA checkpoints + teacher cache"
  ok=false
else
  echo "OK: disk ${DISK_AVAIL}G free on /"
fi
if [[ "${HF_SIZE:-0}" -lt 500 ]]; then
  echo "NOTE: Qwen3.5-9B HF cache ~18G — will download on first train/infer if missing"
else
  echo "OK: HF cache ${HF_SIZE}MB present"
fi

ATTN=$(uv run python3 -c "import importlib.util; print('yes' if importlib.util.find_spec('flash_attn') else 'no')" 2>/dev/null || echo no)
if [[ "$ATTN" == "no" ]]; then
  echo "NOTE: flash-attn not installed — Unsloth uses xformers (slower). Optional: uv pip install flash-attn --no-build-isolation (15–30 min compile)"
else
  echo "OK: flash-attn installed"
fi

echo
echo "--- Applying safe runtime settings (session) ---"
# shellcheck source=phase3b_env.sh
source "$ROOT/benchmark/phases/phase3/phase3b_env.sh"
echo "PYTORCH_CUDA_ALLOC_CONF=$PYTORCH_CUDA_ALLOC_CONF"
echo "OMP_NUM_THREADS=$OMP_NUM_THREADS"
echo "PHASE3_MAX_SEQ_LEN=$PHASE3_MAX_SEQ_LEN"

mkdir -p "$ROOT/runs/phase3/stage3b"/{teacher/train,data,lora,val_eval,eval,summaries,logs,corpora}

if [[ "${PHASE3B_CLEAN_UV_CACHE:-0}" == "1" ]]; then
  echo "Cleaning uv cache (PHASE3B_CLEAN_UV_CACHE=1)..."
  uv cache clean || true
fi

if [[ "${PHASE3B_PRUNE_PIP:-0}" == "1" ]]; then
  echo "Pruning pip cache..."
  uv run pip cache purge 2>/dev/null || true
fi

echo
if $ok; then
  echo "=== Infra OK for Phase 3B ==="
else
  echo "=== Infra usable with warnings — review above ==="
fi
