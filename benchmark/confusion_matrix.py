"""Full gold×predicted confusion matrices for FP / TP / BL tracks."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from benchmark.triage_labels import VALID_LABELS

LABELS = ("TP", "FP", "BL")
TRACK_GOLD = {"fp": "FP", "tp": "TP", "bl": "BL"}


def load_label(result_path: Path) -> str | None:
    if not result_path.is_file():
        return None
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    lbl = str(data.get("label", "")).strip().upper()
    return lbl if lbl in VALID_LABELS else None


def collect_outcomes(
    base: Path,
    profile: str,
    *,
    thinking: str = "on",
    fewshot: int = 3,
    tracks: dict[str, str] | None = None,
) -> list[dict[str, str | None]]:
    """Collect per-case gold/predicted from triage result JSON files."""
    tracks = tracks or TRACK_GOLD
    out: list[dict[str, str | None]] = []
    for track_key, gold in tracks.items():
        llm_root = (
            base
            / track_key
            / f"thinking_{thinking}"
            / f"fewshot_{fewshot}"
            / profile
            / "llm"
        )
        if not llm_root.is_dir():
            continue
        for case_dir in sorted(llm_root.iterdir()):
            if not case_dir.is_dir():
                continue
            pred = load_label(case_dir / "agent-llm-triage-result.json")
            out.append(
                {
                    "case_id": case_dir.name,
                    "gold": gold,
                    "predicted": pred,
                }
            )
    return out


def confusion_from_outcomes(outcomes: list[dict[str, str | None]]) -> dict[str, Any]:
    matrix: dict[str, Counter[str]] = {g: Counter() for g in LABELS}
    missing_by_gold: Counter[str] = Counter()
    for row in outcomes:
        gold = str(row["gold"]).upper()
        pred = row.get("predicted")
        if pred is None:
            missing_by_gold[gold] += 1
        else:
            matrix[gold][str(pred).upper()] += 1
    total = len(outcomes)
    correct = sum(
        1 for row in outcomes if row.get("predicted") == row.get("gold")
    )
    evaluated = sum(1 for row in outcomes if row.get("predicted") is not None)
    return {
        "n_cases": total,
        "evaluated": evaluated,
        "missing": total - evaluated,
        "correct": correct,
        "accuracy_all_tracks": correct / total if total else 0.0,
        "matrix": {g: dict(matrix[g]) for g in LABELS},
        "missing_by_gold": dict(missing_by_gold),
        "critical_tp_fp": int(matrix["TP"].get("FP", 0)),
        "high_bl_fp": int(matrix["BL"].get("FP", 0)),
        "fp_tp": int(matrix["FP"].get("TP", 0)),
        "diagonal": {
            g: int(matrix[g].get(g, 0)) for g in LABELS
        },
    }


def confusion_for_run(
    base: Path,
    profile: str,
    *,
    thinking: str = "on",
    fewshot: int = 3,
) -> dict[str, Any]:
    outcomes = collect_outcomes(base, profile, thinking=thinking, fewshot=fewshot)
    return confusion_from_outcomes(outcomes)


def track_metrics_from_matrix(cm: dict[str, Any], gold: str, *, n: int = 200) -> dict[str, Any]:
    """Build summarize_triage-compatible track dict from a confusion row."""
    gold = gold.upper()
    row = cm["matrix"].get(gold) or {}
    missing = int((cm.get("missing_by_gold") or {}).get(gold, 0))
    dist = dict(row)
    evaluated = sum(dist.values())
    correct = int(dist.get(gold, 0))
    return {
        "n_cases": n,
        "evaluated": evaluated,
        "missing": missing,
        "correct": correct,
        "distribution": dist,
    }
