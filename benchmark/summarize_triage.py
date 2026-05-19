#!/usr/bin/env python3
"""Summarize LLM triage runs vs CodeQL baseline (gold label: FP or TP)."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

VALID_LABELS = frozenset({"TP", "FP", "UNKNOWN"})


def _load_label(result_path: Path) -> str | None:
    if not result_path.is_file():
        return None
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    lbl = str(data.get("label", "")).strip().upper()
    return lbl if lbl in VALID_LABELS else None


def _metrics_for_cases(
    case_ids: list[str],
    *,
    gold: str,
    predicted: dict[str, str | None],
) -> dict[str, float | int]:
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
    return {
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
        "distribution": dict(dist),
    }


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
        help="Runs root (default: ./runs)",
    )
    ap.add_argument(
        "--profile",
        action="append",
        dest="profiles",
        help="Qwen profile dir under runs/ (repeatable). Default: qwen3_4b_bnb qwen3_8b_bnb",
    )
    ap.add_argument("--agent", default="llm")
    ap.add_argument("--max-cases", type=int, default=None)
    ap.add_argument("--json-out", type=Path, default=None)
    args = ap.parse_args()

    profiles = args.profiles or ["qwen3_4b_bnb", "qwen3_8b_bnb"]
    case_dir = args.case_dir.expanduser().resolve()
    runs_root = args.runs.expanduser().resolve()

    case_files = sorted(case_dir.glob("*.json"))
    if args.max_cases is not None:
        case_files = case_files[: args.max_cases]

    case_ids = []
    for p in case_files:
        case = json.loads(p.read_text(encoding="utf-8"))
        cid = case.get("case_id") or p.stem
        case_ids.append(str(cid))

    rows: dict[str, dict] = {}

    gold_u = args.gold.strip().upper()
    codeql_label = "TP"  # reported finding = keep alert
    codeql_pred = {cid: codeql_label for cid in case_ids}

    # CodeQL baseline: tool reported alert → triage treats as "not dismissed" (TP from filter POV)
    rows["CodeQL (no filter)"] = _metrics_for_cases(case_ids, gold=args.gold, predicted=codeql_pred)

    for profile in profiles:
        model_dir = profile.replace("/", "_")
        predicted: dict[str, str | None] = {}
        for cid in case_ids:
            result_path = runs_root / model_dir / args.agent / cid / f"agent-{args.agent}-triage-result.json"
            predicted[cid] = _load_label(result_path)
        rows[f"Qwen ({profile})"] = _metrics_for_cases(case_ids, gold=args.gold, predicted=predicted)

    print(f"Corpus: {case_dir}")
    print(f"Gold label: {args.gold}  |  Cases: {len(case_ids)}")
    print()
    header = (
        f"{'System':<28} {'Acc*':>6} {'All':>6} {'Cov':>6} "
        f"{'FP':>6} {'TP':>5} {'Miss':>5} {'N':>4}"
    )
    print(header)
    print("-" * len(header))
    for name, m in rows.items():
        print(
            f"{name:<28} "
            f"{100 * m['accuracy']:5.1f}% "
            f"{100 * m['accuracy_all']:5.1f}% "
            f"{100 * m['coverage']:5.1f}% "
            f"{100 * m['fp_removal_rate']:5.1f}% "
            f"{100 * m['tp_rate']:4.1f}% "
            f"{m['missing']:5d} "
            f"{m['n_cases']:4d}"
        )
    print()
    print(f"Gold={gold_u}. Acc*=correct/evaluated; All=correct/N; Cov=evaluated/N.")
    print("CodeQL baseline = no filtering (keeps every alert as TP). FP/TP columns = model label rates.")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"\nWrote {args.json_out}")


if __name__ == "__main__":
    main()
