"""Demo metrics: confusion matrix, VDR, FPRR, SRS, and business-friendly KPIs."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CaseOutcome:
    case_id: str
    gold: str
    predicted: str | None
    title: str = ""
    rule: str = ""
    reason: str = ""
    confidence: str = ""
    elapsed_sec: float | None = None
    source: str = "live"
    profile: str = ""
    acceptable_labels: list[str] = field(default_factory=list)
    borderline_rationale: str = ""


def _norm(label: str | None) -> str | None:
    if label is None:
        return None
    u = str(label).strip().upper()
    return u if u else None


def outcome_status(
    gold: str,
    predicted: str | None,
    *,
    acceptable_labels: list[str] | None = None,
) -> tuple[str, str]:
    """Return (short_label, detail) for UI."""
    g, p = _norm(gold), _norm(predicted)
    if p is None:
        return "Missing", "No triage result"
    if g == "TP" and p == "TP":
        return "Correct", "Real vuln kept"
    if g == "FP" and p == "FP":
        return "Correct", "False alarm dismissed"
    if g == "TP" and p == "FP":
        return "Missed vuln", "False negative — real threat dismissed"
    if g == "FP" and p == "TP":
        return "False alarm", "Noise kept — would waste reviewer time"
    if g == "BL":
        acc = {_norm(x) for x in (acceptable_labels or ["TP", "FP", "BL"]) if _norm(x)}
        if p == "BL":
            return "Escalated", "Borderline — routed to human review (ideal)"
        if p in acc:
            return "Acceptable", f"Borderline — {p} is defensible (models disagree on this case)"
        return "Overconfident", f"Borderline — {p} outside acceptable set {sorted(acc)}"
    return "Needs review", f"Ambiguous ({p}) — escalate to human"


def confusion_vuln_vs_safe(outcomes: list[CaseOutcome]) -> dict[str, int]:
    """Binary CM on TP/FP gold only (excludes borderline)."""
    cm = {
        "tp": 0,
        "fn": 0,
        "fp": 0,
        "tn": 0,
        "review_vuln": 0,
        "review_safe": 0,
        "missing": 0,
    }
    for o in outcomes:
        g = _norm(o.gold)
        if g not in ("TP", "FP"):
            continue
        p = _norm(o.predicted)
        if p is None:
            cm["missing"] += 1
            continue
        if g == "TP":
            if p == "TP":
                cm["tp"] += 1
            elif p == "FP":
                cm["fn"] += 1
            else:
                cm["review_vuln"] += 1
        elif g == "FP":
            if p == "FP":
                cm["tn"] += 1
            elif p == "TP":
                cm["fp"] += 1
            else:
                cm["review_safe"] += 1
    return cm


def _bl_acceptable(o: CaseOutcome) -> bool:
    p = _norm(o.predicted)
    if p is None:
        return False
    acc = {_norm(x) for x in (o.acceptable_labels or ["TP", "FP", "BL"]) if _norm(x)}
    return p == "BL" or p in acc


def track_breakdown(outcomes: list[CaseOutcome]) -> dict[str, Any]:
    tp_cases = [o for o in outcomes if _norm(o.gold) == "TP"]
    fp_cases = [o for o in outcomes if _norm(o.gold) == "FP"]
    bl_cases = [o for o in outcomes if _norm(o.gold) == "BL"]

    def hits(cases: list[CaseOutcome], want: str) -> tuple[int, int]:
        evaluated = [o for o in cases if _norm(o.predicted) is not None]
        hit = sum(1 for o in evaluated if _norm(o.predicted) == want)
        return hit, len(evaluated)

    tp_hit, tp_n = hits(tp_cases, "TP")
    fp_hit, fp_n = hits(fp_cases, "FP")
    bl_eval = [o for o in bl_cases if _norm(o.predicted) is not None]
    bl_ok = sum(1 for o in bl_eval if _bl_acceptable(o))
    bl_escalated = sum(1 for o in bl_eval if _norm(o.predicted) == "BL")

    strict_correct = sum(
        1
        for o in outcomes
        if _norm(o.predicted) is not None and _norm(o.gold) == _norm(o.predicted)
    )
    lenient_correct = strict_correct + sum(
        1
        for o in outcomes
        if _norm(o.gold) == "BL"
        and _norm(o.predicted) is not None
        and _bl_acceptable(o)
        and _norm(o.predicted) != "BL"
    )
    evaluated = sum(1 for o in outcomes if _norm(o.predicted) is not None)

    return {
        "correct": strict_correct,
        "lenient_correct": lenient_correct,
        "evaluated": evaluated,
        "total": len(outcomes),
        "tp_track": {"hits": tp_hit, "n": tp_n, "label": "Threat detection (VDR)"},
        "fp_track": {"hits": fp_hit, "n": fp_n, "label": "Noise reduction (FPRR)"},
        "bl_track": {
            "acceptable": bl_ok,
            "escalated": bl_escalated,
            "n": len(bl_eval),
            "label": "Borderline handling",
        },
    }


def compute_metrics(
    outcomes: list[CaseOutcome],
    *,
    vdr_target: float = 0.95,
    fprr_target: float = 0.90,
) -> dict[str, Any]:
    tp_gold = [o for o in outcomes if _norm(o.gold) == "TP"]
    fp_gold = [o for o in outcomes if _norm(o.gold) == "FP"]

    def rate(cases: list[CaseOutcome], want: str) -> float | None:
        evaluated = [o for o in cases if _norm(o.predicted) is not None]
        if not evaluated:
            return None
        hit = sum(1 for o in evaluated if _norm(o.predicted) == want)
        return hit / len(evaluated)

    vdr = rate(tp_gold, "TP")
    fprr = rate(fp_gold, "FP")
    srs = (vdr + fprr) / 2 if vdr is not None and fprr is not None else None

    cm = confusion_vuln_vs_safe(outcomes)
    tpr = cm["tp"] / (cm["tp"] + cm["fn"] + cm["review_vuln"]) if (cm["tp"] + cm["fn"] + cm["review_vuln"]) else None
    tnr = cm["tn"] / (cm["tn"] + cm["fp"] + cm["review_safe"]) if (cm["tn"] + cm["fp"] + cm["review_safe"]) else None
    precision = cm["tp"] / (cm["tp"] + cm["fp"]) if (cm["tp"] + cm["fp"]) else None
    fpr = cm["fp"] / (cm["fp"] + cm["tn"] + cm["review_safe"]) if (cm["fp"] + cm["tn"] + cm["review_safe"]) else None

    tracks = track_breakdown(outcomes)
    bl_tr = tracks["bl_track"]
    bl_rate = bl_tr["acceptable"] / bl_tr["n"] if bl_tr["n"] else None

    gates_pass = (
        vdr is not None
        and fprr is not None
        and vdr >= vdr_target
        and fprr >= fprr_target
    )

    return {
        "n": len(outcomes),
        "vdr": vdr,
        "fprr": fprr,
        "srs": srs,
        "bl_handling": bl_rate,
        "tpr": tpr,
        "tnr": tnr,
        "precision": precision,
        "fpr": fpr,
        "confusion": cm,
        "tracks": tracks,
        "gates_pass": gates_pass,
        "targets": {"vdr_min": vdr_target, "fprr_min": fprr_target},
        "distribution": dict(Counter(_norm(o.predicted) or "(missing)" for o in outcomes)),
        "codeql_baseline": {
            "vdr": 1.0 if tp_gold else None,
            "fprr": 0.0,
            "srs": 0.5 if tp_gold and fp_gold else (1.0 if tp_gold else None),
            "note": "CodeQL flags every alert — no AI noise filter",
        },
    }


def format_pct(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{100 * x:.1f}%"


def format_fraction(hits: int, n: int) -> str:
    if n == 0:
        return "—"
    return f"{hits}/{n}"


def outcomes_table_rows(outcomes: list[CaseOutcome]) -> list[dict[str, str]]:
    rows = []
    for o in outcomes:
        status, detail = outcome_status(
            o.gold, o.predicted, acceptable_labels=o.acceptable_labels
        )
        rows.append(
            {
                "Finding": o.case_id,
                "Truth": o.gold,
                "AI label": o.predicted or "—",
                "Status": status,
                "Detail": detail,
                "Rule": o.rule,
            }
        )
    return rows
