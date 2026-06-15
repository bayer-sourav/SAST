"""Ensure SAST and benchmark/ are importable (timing, repo_root, etc.)."""

from __future__ import annotations

import sys
from pathlib import Path

SAST_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_ROOT = SAST_ROOT / "benchmark"


def ensure_import_paths() -> None:
    for p in (SAST_ROOT, BENCHMARK_ROOT):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)
