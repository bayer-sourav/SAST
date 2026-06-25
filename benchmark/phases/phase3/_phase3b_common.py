"""Shared Phase 3B helpers (manifest, paths, CSS val subset)."""

from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Any

_SAST = Path(__file__).resolve().parents[3]
_DEFAULT_MANIFEST = _SAST / "benchmark/phases/phase3/stage3b/MANIFEST.json"

_TRACKS = (
    ("fp", "FP"),
    ("tp", "TP"),
    ("borderline", "BL"),
)


def sast_root() -> Path:
    return _SAST


def load_manifest(path: Path | None = None) -> dict[str, Any]:
    if path is None:
        env = os.environ.get("PHASE3_MANIFEST") or os.environ.get("PHASE3B_MANIFEST")
        path = Path(env) if env else _DEFAULT_MANIFEST
    return json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))


def stage3b_root(manifest: dict[str, Any] | None = None) -> Path:
    m = manifest or load_manifest()
    rel = m["outputs"]["teacher_cache"].split("/stage3b/")[0]
    return (_SAST / rel / "stage3b").resolve()


def output_path(manifest: dict[str, Any], key: str) -> Path:
    return (_SAST / manifest["outputs"][key]).resolve()


def teacher_run_dir(
    manifest: dict[str, Any],
    *,
    case_id: str,
    track: str,
) -> Path:
    t = manifest["teacher"]
    base = output_path(manifest, "teacher_cache")
    return (
        base
        / track
        / ("thinking_on" if t["thinking"] else "thinking_off")
        / f"fewshot_{t['fewshot']}"
        / t["profile"]
        / "llm"
        / case_id
    )


def css_val_case_ids(
    manifest: dict[str, Any],
    *,
    seed: int | None = None,
) -> list[str]:
    """Stratified validation subset for fast CSS (50 per track by default)."""
    from benchmark.build_phase2_corpora import _dataset_root
    from benchmark.phases.phase3.export_sft_dataset import _split_entries

    perf = manifest.get("performance", {}).get("css_val_during_training", {})
    per_track = int(perf.get("per_track", 50))
    rng_seed = seed if seed is not None else int(perf.get("seed", 3407))

    dataset = _dataset_root(None)
    ids: list[str] = []
    for cls, _ in _TRACKS:
        mpath = dataset / cls / "manifest.json"
        entries = _split_entries(json.loads(mpath.read_text(encoding="utf-8")), "validation")
        rng = random.Random(rng_seed + hash(cls) % 10000)
        picked = entries if len(entries) <= per_track else rng.sample(entries, per_track)
        ids.extend(row["case_id"] for row in picked)
    return sorted(ids)


def write_css_val_ids(path: Path, manifest: dict[str, Any]) -> list[str]:
    ids = css_val_case_ids(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ids, indent=2), encoding="utf-8")
    return ids
