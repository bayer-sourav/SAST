#!/usr/bin/env python3
"""Summarize borderline-corpus triage runs (4-label unified prompt)."""

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
from benchmark.summarize_triage import _f1_for_positive_class  # noqa: E402


def _load_label(result_path: Path) -> str | None:
    if not result_path.is_file():
        return None
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    lbl = str(data.get("label", "")).strip().upper()
    return lbl if lbl in VALID_LABELS else None


def _benchmark_gold_label(case: dict) -> str:
    return "TP" if case.get("benchmark_real_vuln") else "FP"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case-dir", type=Path, required=True)
    ap.add_argument("--runs", type=Path, required=True, help="runs root thinking_off/")
    ap.add_argument("--profile", action="append", dest="profiles", required=True)
    ap.add_argument("--json-out", type=Path, required=True)
    args = ap.parse_args()

    case_dir = args.case_dir.expanduser().resolve()
    runs_root = args.runs.expanduser().resolve()
    case_files = sorted(p for p in case_dir.glob("*.json") if p.name != "slice_manifest.json")

    rows: dict[str, dict] = {}
    for profile in args.profiles:
        model_dir = profile.replace("/", "_")
        dist: Counter[str] = Counter()
        missing = 0
        lenient_correct = 0
        bench_agree = 0
        bl_label = 0
        evaluated = 0
        n = len(case_files)

        for p in case_files:
            case = json.loads(p.read_text(encoding="utf-8"))
            cid = str(case.get("case_id") or p.stem)
            bench_lbl = _benchmark_gold_label(case)
            acceptable = set(case.get("acceptable_labels") or ["TP", "FP", "BL"])
            result_path = runs_root / model_dir / "llm" / cid / "agent-llm-triage-result.json"
            pred = _load_label(result_path)
            if pred is None:
                missing += 1
                dist["(missing)"] += 1
                continue
            evaluated += 1
            dist[pred] += 1
            if pred in acceptable:
                lenient_correct += 1
            if pred == bench_lbl:
                bench_agree += 1
            if pred == "BL":
                bl_label += 1

        tp_rate = dist.get("TP", 0) / evaluated if evaluated else 0.0
        fp_rate = dist.get("FP", 0) / evaluated if evaluated else 0.0
        bl_rate = bl_label / evaluated if evaluated else 0.0
        ambiguity = 1.0 - abs(tp_rate - 0.5) * 2 if evaluated else 0.0

        rows[f"SLM ({profile})"] = {
            "profile": profile,
            "n_cases": n,
            "evaluated": evaluated,
            "missing": missing,
            "coverage": evaluated / n if n else 0.0,
            "distribution": dict(dist),
            "tp_rate": tp_rate,
            "fp_rate": fp_rate,
            "bl_rate": bl_rate,
            "lenient_accuracy": lenient_correct / evaluated if evaluated else 0.0,
            "benchmark_agreement": bench_agree / evaluated if evaluated else 0.0,
            "ambiguity_index": ambiguity,
            "f1_bl": _f1_for_positive_class("BL", dist, evaluated=evaluated),
        }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print(f"Borderline corpus: {case_dir}  |  Cases: {len(case_files)}")
    print(
        f"{'System':<32} {'Cov':>6} {'TP%':>6} {'FP%':>6} {'BL%':>6} "
        f"{'LenAcc':>7} {'BenchAg':>7} {'AmbIdx':>6}"
    )
    for name, m in rows.items():
        print(
            f"{name:<32} "
            f"{100 * m['coverage']:5.1f}% "
            f"{100 * m['tp_rate']:5.1f}% "
            f"{100 * m['fp_rate']:5.1f}% "
            f"{100 * m['bl_rate']:5.1f}% "
            f"{100 * m['lenient_accuracy']:6.1f}% "
            f"{100 * m['benchmark_agreement']:6.1f}% "
            f"{m['ambiguity_index']:6.3f}"
        )
    print(f"\nWrote {args.json_out}")


if __name__ == "__main__":
    main()
