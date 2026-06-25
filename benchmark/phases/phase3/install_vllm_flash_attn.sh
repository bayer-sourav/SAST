#!/usr/bin/env bash
# Install vLLM + flash-attn for Phase 3B fast inference.
# Run with GPU idle. flash-attn compile takes 15–45 min without nvcc in PATH.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$ROOT"

VLLM_VERSION="${VLLM_VERSION:-0.17.0}"
FLASH_ATTN="${INSTALL_FLASH_ATTN:-1}"
MAX_JOBS="${MAX_JOBS:-4}"

echo "=== Install vLLM + flash-attn $(date -Iseconds) ==="
echo "vLLM version: $VLLM_VERSION"
echo "Install flash-attn: $FLASH_ATTN"

if ! command -v nvidia-smi >/dev/null; then
  echo "ERROR: nvidia-smi not found"
  exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo
echo "--- Current torch ---"
uv run python3 -c "import torch; print(torch.__version__, 'cuda', torch.cuda.is_available())"

echo
echo "--- Installing vLLM $VLLM_VERSION (pins transformers 4.x; conflicts with Unsloth training) ---"
uv pip install "vllm==${VLLM_VERSION}"

echo
if [[ "$FLASH_ATTN" == "1" ]]; then
  echo "--- Installing flash-attn (compile; needs ~8GB RAM + CUDA toolkit or prebuilt wheel) ---"
  if ! command -v nvcc >/dev/null; then
    echo "NOTE: nvcc not in PATH — trying prebuilt wheel / pip compile anyway"
    echo "      If build fails: sudo dnf install cuda-nvcc-12-8 or set CUDA_HOME"
  fi
  MAX_JOBS="$MAX_JOBS" uv pip install flash-attn --no-build-isolation
else
  echo "Skipping flash-attn (INSTALL_FLASH_ATTN=0)"
fi

echo
echo "--- Verify ---"
uv run python3 - <<'PY'
import importlib.util
for mod in ("vllm", "flash_attn"):
    ok = bool(importlib.util.find_spec(mod))
    print(f"{mod}: {'OK' if ok else 'MISSING'}")
try:
    import torch
    print(f"torch: {torch.__version__}")
except Exception as e:
    print(f"torch: {e}")
try:
    import transformers
    print(f"transformers: {transformers.__version__}")
except Exception as e:
    print(f"transformers: {e}")
PY

cat <<'EOF'

=== Usage ===
export QWEN_INFER_BACKEND=vllm
export QWEN_VLLM_MODEL_ID=Qwen/Qwen3.5-9B   # optional; default for qwen3_5_9b_bnb
source benchmark/phases/phase3/phase3b_env.sh
source benchmark/phase2_cell_env.sh
phase2_apply_token_limits on qwen3_5_9b_bnb

# Smoke benchmark (vLLM vs prior Unsloth timings)
PYTHONPATH="$PWD:$PWD/benchmark" QWEN_INFER_BACKEND=vllm \
  .venv/bin/python benchmark/phases/phase3/bench_vllm_speed.py

=== Before LoRA training (Unsloth) ===
Restore transformers 5.5.x if needed:
  uv pip install 'transformers>=5.5.0,<5.6.0' 'unsloth>=2026.5.2'
Unset QWEN_INFER_BACKEND or set QWEN_INFER_BACKEND=unsloth

EOF
