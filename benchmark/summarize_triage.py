#!/usr/bin/env python3
"""Summarize LLM triage runs vs CodeQL baseline (gold label: FP or TP)."""

from __future__ import annotations

import argparse
import json
from collections import Counter
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parent.parent
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))
from benchmark.triage_labels import VALID_LABELS  # noqa: E402


def _load_label(result_path: Path) -> str | None:
    if not result_path.is_file():
        return None
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    lbl = str(data.get("label", "")).strip().upper()
    return lbl if lbl in VALID_LABELS else None


def _f1_for_positive_class(
    gold: str,
    dist: Counter[str],
    *,
    evaluated: int,
) -> float:
    """F1 with positive class = gold (FP-removal or TP-retention task)."""
    if evaluated <= 0:
        return 0.0
    gold = gold.upper()
    tp = dist.get(gold, 0)
    pred_pos = tp + sum(dist.get(l, 0) for l in VALID_LABELS if l != gold)
    fn = sum(dist.get(l, 0) for l in VALID_LABELS if l != gold)
    precision = tp / pred_pos if pred_pos else 0.0
    recall = tp / evaluated
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def _enrich_metrics(base: dict[str, float | int], *, gold: str) -> dict:
    gold_u = gold.upper()
    dist = Counter(base.get("distribution") or {})
    evaluated = int(base["evaluated"])
    out = dict(base)
    if gold_u == "FP":
        out["fprr"] = base["fp_removal_rate"]
        out["tp_retention_rate"] = base["tp_rate"]
    else:
        out["vdr"] = base["tp_rate"]
        out["fp_removal_rate_alias"] = base["fp_removal_rate"]
    out["f1"] = _f1_for_positive_class(gold_u, dist, evaluated=evaluated)
    return out


def _metrics_for_cases(
    case_ids: list[str],
    *,
    gold: str,
    predicted: dict[str, str | None],
) -> dict:
    gold = gold.upper()
    n = len(case_ids)
    correct = 0
    dist: Counter[str] = Counter()
    missing = 0
    for cid in case_ids:
        pred = predicted.get(cid)
        if pred is None:
            missing += 1
            dist["(missing)"] += 1
            continue
        dist[pred] += 1
        if pred == gold:
            correct += 1
    evaluated = n - missing
    base = {
        "n_cases": n,
        "evaluated": evaluated,
        "missing": missing,
        "correct": correct,
        "accuracy": (correct / evaluated) if evaluated else 0.0,
        "accuracy_all": correct / n if n else 0.0,
        "coverage": evaluated / n if n else 0.0,
        "fp_removal_rate": (dist.get("FP", 0) / evaluated) if evaluated else 0.0,
        "tp_rate": (dist.get("TP", 0) / evaluated) if evaluated else 0.0,
        "unknown_rate": (dist.get("UNKNOWN", 0) / evaluated) if evaluated else 0.0,
        "bl_rate": (dist.get("BL", 0) / evaluated) if evaluated else 0.0,
        "distribution": dict(dist),
    }
    return _enrich_metrics(base, gold=gold)


def _model_row_name(profile: str) -> str:
    return f"SLM ({profile})"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case-dir", type=Path, required=True, help="Case JSON directory")
    ap.add_argument(
        "--gold",
        default="FP",
        help="Gold triage label for this corpus (RQ1 OWASP FP set: FP)",
    )
    ap.add_argument(
        "--runs",
        type=Path,
        default=Path("runs"),
        help="Runs root containing <profile>/llm/<case_id>/",
    )
    ap.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        help="Model profile dir under runs/ (repeatable). Default: qwen3_4b_bnb qwen3_8b_bnb",
    )
    ap.add_argument("--agent", default="llm")
    ap.add_argument("--max-cases", type=int, default=None)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    profiles = args.profiles or ["qwen3_4b_bnb", "qwen3_8b_bnb"]
    case_dir = args.case_dir.expanduser().resolve()
    runs_root = args.runs.expanduser().resolve()

    case_files = sorted(p for p in case_dir.glob("*.json") if p.name != "slice_manifest.json")
    if args.max_cases is not None:
        case_files = case_files[: args.max_cases]

    case_ids = []
    for p in case_files:
        case = json.loads(p.read_text(encoding="utf-8"))
        cid = case.get("case_id") or p.stem
        case_ids.append(str(cid))

    rows: dict[str, dict] = {}

    gold_u = args.gold.strip().upper()
    codeql_label = "TP"
    codeql_pred = {cid: codeql_label for cid in case_ids}

    rows["CodeQL (no filter)"] = _metrics_for_cases(case_ids, gold=args.gold, predicted=codeql_pred)

    for profile in profiles:
        model_dir = profile.replace("/", "_")
        predicted: dict[str, str | None] = {}
        for cid in case_ids:
            result_path = runs_root / model_dir / args.agent / cid / f"agent-{args.agent}-triage-result.json"
            predicted[cid] = _load_label(result_path)
        rows[_model_row_name(profile)] = _metrics_for_cases(
            case_ids, gold=args.gold, predicted=predicted
        )
        rows[_model_row_name(profile)]["profile"] = profile

    print(f"Corpus: {case_dir}")
    print(f"Gold label: {args.gold}  |  Cases: {len(case_ids)}")
    print()
    metric_col = "FPRR" if gold_u == "FP" else "VDR"
    header = (
        f"{'System':<32} {'Acc*':>6} {'Cov':>6} {metric_col:>6} {'F1':>6} "
        f"{'Miss':>5} {'N':>4}"
    )
    print(header)
    print("-" * len(header))
    for name, m in rows.items():
        key_metric = m.get("fprr", m.get("vdr", 0.0))
        print(
            f"{name:<32} "
            f"{100 * m['accuracy']:5.1f}% "
            f"{100 * m['coverage']:5.1f}% "
            f"{100 * key_metric:5.1f}% "
            f"{100 * m['f1']:5.1f}% "
            f"{m['missing']:5d} "
            f"{m['n_cases']:4d}"
        )
    print()
    print(f"Gold={gold_u}. FPRR/VDR and F1 use positive class = gold label.")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_out}")


if __name__ == "__main__":
    main()
