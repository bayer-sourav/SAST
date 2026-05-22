"""Timing helpers for benchmark triage runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_run_meta(run_dir: Path) -> dict[str, Any]:
    p = run_dir / "run_meta.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def case_elapsed_sec(run_dir: Path) -> float | None:
    meta = read_run_meta(run_dir)
    if "elapsed_sec" in meta:
        return float(meta["elapsed_sec"])
    result = run_dir / "agent-llm-triage-result.json"
    if not result.is_file():
        return None
    end = result.stat().st_mtime
    task = run_dir / "task.md"
    start = task.stat().st_mtime if task.is_file() else run_dir.stat().st_mtime
    return max(0.0, end - start)


def tokens_from_meta(meta: dict) -> dict[str, int | None]:
    inp = meta.get("input_tokens")
    out = meta.get("output_tokens")
    if inp is None and out is None:
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    i = int(inp) if inp is not None and int(inp) >= 0 else None
    o = int(out) if out is not None and int(out) >= 0 else None
    total = (i or 0) + (o or 0) if i is not None or o is not None else None
    if i is None and o is None:
        total = None
    return {"input_tokens": i, "output_tokens": o, "total_tokens": total}


def aggregate_tokens(cases: list[dict], key: str = "total_tokens") -> dict[str, float | int]:
    vals = [int(c[key]) for c in cases if c.get(key) is not None]
    if not vals:
        return {"count": 0, "sum": 0, "mean": 0.0, "min": 0, "max": 0}
    return {
        "count": len(vals),
        "sum": sum(vals),
        "mean": sum(vals) / len(vals),
        "min": min(vals),
        "max": max(vals),
    }


def aggregate_seconds(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "count": 0,
            "total_sec": 0.0,
            "mean_sec": 0.0,
            "min_sec": 0.0,
            "max_sec": 0.0,
        }
    return {
        "count": len(values),
        "total_sec": sum(values),
        "mean_sec": sum(values) / len(values),
        "min_sec": min(values),
        "max_sec": max(values),
    }


def format_duration(sec: float) -> str:
    if sec < 60:
        return f"{sec:.1f}s"
    if sec < 3600:
        return f"{sec / 60:.1f}m"
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    return f"{h}h{m}m"


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
