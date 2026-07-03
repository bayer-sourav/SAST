"""Resolve OWASP BenchmarkJava repo root (sibling ``BenchmarkJava/`` next to ``SAST/`` by default)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def resolve_benchmark_java_root(
    sast_root: Path,
    case: dict[str, Any],
    repo_arg: str | Path | None,
    *,
    case_path: Path | None = None,
) -> Path:
    if repo_arg is not None and str(repo_arg).strip():
        return Path(repo_arg).expanduser().resolve()
    explicit = case.get("repo_root")
    if isinstance(explicit, str) and explicit.strip():
        return Path(explicit).expanduser().resolve()
    rel = case.get("file")
    sibling = (sast_root.parent / "BenchmarkJava").resolve()
    if isinstance(rel, str) and sibling.is_dir():
        if (sibling / rel).is_file():
            return sibling
    if case.get("dataset_bundle") and case_path is not None:
        bundle = case_path.parent.resolve()
        if isinstance(rel, str) and (bundle / rel).is_file():
            return bundle
    folder = case.get("folder_root")
    if folder and str(folder) not in (".", ""):
        return Path(folder).expanduser().resolve()
    if case_path is not None:
        bundle = case_path.parent.resolve()
        if isinstance(rel, str) and (bundle / rel).is_file():
            return bundle
    return Path(".").expanduser().resolve()


def resolve_repo_root(
    sast_root: Path,
    case: dict[str, Any],
    repo_arg: str | Path | None,
    *,
    case_path: Path | None = None,
) -> Path:
    """Resolve repository root for benchmark bundles or enterprise git clones."""
    return resolve_benchmark_java_root(sast_root, case, repo_arg, case_path=case_path)
