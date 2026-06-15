#!/usr/bin/env bash
# Launch the live SAST triage demo (Streamlit).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

export QWEN3_CODER_BACKEND="${QWEN3_CODER_BACKEND:-bedrock}"
export PYTHONPATH="$ROOT:$ROOT/benchmark${PYTHONPATH:+:$PYTHONPATH}"

# Install streamlit if missing (demo-only dep)
if ! "$ROOT/.venv/bin/python3" -c "import streamlit" 2>/dev/null; then
  echo "Installing demo dependencies (streamlit)…"
  if command -v uv >/dev/null 2>&1; then
    uv pip install -q -r "$ROOT/demo/requirements.txt" -p "$ROOT/.venv"
  else
    "$ROOT/.venv/bin/python3" -m pip install -q -r "$ROOT/demo/requirements.txt"
  fi
fi

PORT="${DEMO_PORT:-8501}"
echo "Warming demo cache (quick pack)…"
"$ROOT/.venv/bin/python3" "$ROOT/demo/build_cache.py" || true
echo "Starting demo at http://localhost:${PORT}"
echo "  Model: qwen3_coder_30b_bnb via ${QWEN3_CODER_BACKEND}"
echo "  Use 'Cached' mode for instant metrics; 'Live Bedrock' for real inference."

exec "$ROOT/.venv/bin/streamlit" run "$ROOT/demo/app.py" \
  --server.port "$PORT" \
  --server.address 0.0.0.0 \
  --browser.gatherUsageStats false
