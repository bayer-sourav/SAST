#!/usr/bin/env python3
"""Quick smoke: verify Qwen + Gemma backends after transformers bump."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SAST = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SAST))
sys.path.insert(0, str(SAST / "benchmark"))
os.chdir(SAST)

import transformers  # noqa: E402

from benchmark.local_model_unload import release_gpu_memory  # noqa: E402


def _check(name: str, fn) -> None:
    print(f"\n=== {name} ===", flush=True)
    try:
        out = fn()
        print(f"OK ({len(out)} chars): {out[:120]!r}", flush=True)
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", flush=True)
        raise
    finally:
        release_gpu_memory()


def main() -> None:
    print(f"transformers {transformers.__version__}", flush=True)

    _check(
        "qwen3_5_9b_bnb thinking=off",
        lambda: __import__("benchmark.llm_generate", fromlist=["generate_triage"]).generate_triage(
            [{"role": "user", "content": "Reply with exactly: QWEN_OK"}],
            "qwen3_5_9b_bnb",
            thinking=False,
        ),
    )

    _check(
        "gemma_4_e4b_bnb thinking=off",
        lambda: __import__("benchmark.llm_generate", fromlist=["generate_triage"]).generate_triage(
            [{"role": "user", "content": "Reply with exactly: GEMMA_OFF_OK"}],
            "gemma_4_e4b_bnb",
            thinking=False,
        ),
    )

    _check(
        "gemma_4_e4b_bnb thinking=on",
        lambda: __import__("benchmark.llm_generate", fromlist=["generate_triage"]).generate_triage(
            [{"role": "user", "content": "Reply with exactly: GEMMA_ON_OK"}],
            "gemma_4_e4b_bnb",
            thinking=True,
        ),
    )

    print("\nAll compat checks passed.", flush=True)


if __name__ == "__main__":
    main()
