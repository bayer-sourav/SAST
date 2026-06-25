"""Asymmetric-penalty Security Risk Score (SRS) from gold→predicted transitions."""

from __future__ import annotations

from collections import Counter

MAX_PENALTY = 3.0

# Penalty table (BL = borderline track gold).
_TRANSITION_PENALTY: dict[tuple[str, str], float] = {
    ("TP", "FP"): 3.0,  # CRITICAL — missed vulnerability
    ("BL", "FP"): 1.5,  # HIGH — dismissed ambiguous finding
    ("TP", "BL"): 1.0,  # MODERATE — still queued for review
    ("FP", "TP"): 1.0,  # ACCEPTABLE — false alarm kept
    ("FP", "BL"): 1.0,  # ACCEPTABLE — false alarm kept
}


def transition_penalty(gold: str, pred: str) -> float:
    gold = gold.upper()
    pred = pred.upper()
    if gold == pred:
        return 0.0
    return _TRANSITION_PENALTY.get((gold, pred), 0.0)


def penalty_from_distribution(
    gold: str,
    distribution: dict | Counter,
    *,
    evaluated: int,
) -> tuple[float, int]:
    """Sum penalties for one track given gold label and predicted-label counts."""
    if evaluated <= 0:
        return 0.0, 0
    total = 0.0
    n = 0
    for pred, count in Counter(distribution).items():
        if pred in ("(missing)",):
            continue
        c = int(count)
        n += c
        total += transition_penalty(gold, pred) * c
    return total, n


def srs_penalty_from_tracks(
    fp_track: dict | None,
    tp_track: dict | None,
    bl_track: dict | None,
    *,
    test_n: int | None = None,
) -> dict | None:
    """
    SRS = 1 - (Σ penalty) / (N × 3.0)
    N = evaluated cases across FP + TP + BL tracks (defaults to 600 when complete).
    """
    parts: list[tuple[str, dict | None]] = [
        ("FP", fp_track),
        ("TP", tp_track),
        ("BL", bl_track),
    ]
    total_penalty = 0.0
    evaluated = 0
    breakdown: dict[str, dict] = {}
    for gold, track in parts:
        if not track:
            continue
        ev = int(track.get("evaluated", 0))
        dist = track.get("distribution") or {}
        pen, n = penalty_from_distribution(gold, dist, evaluated=ev)
        missing = int(track.get("missing", 0))
        missing_pen = missing * MAX_PENALTY
        total_penalty += pen + missing_pen
        evaluated += ev + missing
        breakdown[gold] = {
            "evaluated": ev,
            "missing": missing,
            "penalty": pen + missing_pen,
        }
    if evaluated <= 0:
        return None
    n = test_n if test_n is not None and test_n >= evaluated else evaluated
    srs = 1.0 - total_penalty / (n * MAX_PENALTY)
    return {
        "srs_penalty": srs,
        "total_penalty": total_penalty,
        "n": n,
        "evaluated": evaluated,
        "breakdown": breakdown,
    }


def compute_srs(
    fp_track: dict | None,
    tp_track: dict | None,
    bl_track: dict | None = None,
    *,
    test_n: int | None = None,
) -> float | None:
    """Canonical SRS for merged eval rows (FP + TP + optional BL track summaries)."""
    pack = srs_penalty_from_tracks(fp_track, tp_track, bl_track, test_n=test_n)
    return float(pack["srs_penalty"]) if pack else None
