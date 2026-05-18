"""Resolve OWASP BenchmarkJava repo root (sibling ``BenchmarkJava/`` next to ``SAST/`` by default)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_benchmark_java_root(
    sast_root: Path,
    case: dict[str, Any],
    repo_arg: str | Path | None,
) -> Path:
    if repo_arg is not None and str(repo_arg).strip():
        return Path(repo_arg).expanduser().resolve()
    rel = case.get("file")
    sibling = (sast_root.parent / "BenchmarkJava").resolve()
    if isinstance(rel, str) and sibling.is_dir():
        if (sibling / rel).is_file():
            return sibling
    return Path(
        case.get("repo_root") or case.get("folder_root") or ".",
    ).expanduser().resolve()
