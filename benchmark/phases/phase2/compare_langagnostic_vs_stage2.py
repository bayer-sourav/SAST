#!/usr/bin/env python3
"""Compare 600-case merged metrics: candidate vs Stage 2 baseline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.phases.phase2.merge_prod_ship_600_summary import _slm_row  # noqa: E402
from benchmark.srs import compute_srs, srs_penalty_from_tracks  # noqa: E402
from benchmark.summarize_triage import macro_f1_from_track_f1s  # noqa: E402


def _track_paths(sum_dir: Path, track: str) -> Path:
    for name in (f"comparison_{track}.json", f"comparison_{track}_think_on_fs3.json"):
        p = sum_dir / name
        if p.is_file():
            return p
    raise FileNotFoundError(f"no {track} summary in {sum_dir}")


def _merged_from_sum_dir(sum_dir: Path, profile: str) -> dict:
    merged_path = sum_dir / "merged_600.json"
    if merged_path.is_file():
        data = json.loads(merged_path.read_text(encoding="utf-8"))
        return {**data["merged"], "fp_track": data["fp_track"], "tp_track": data["tp_track"], "bl_track": data["bl_track"]}

    fp = _slm_row(json.loads(_track_paths(sum_dir, "fp").read_text()), profile)
    tp = _slm_row(json.loads(_track_paths(sum_dir, "tp").read_text()), profile)
    bl = _slm_row(json.loads(_track_paths(sum_dir, "bl").read_text()), profile)
    srs = compute_srs(fp, tp, bl, test_n=600)
    macro = macro_f1_from_track_f1s(
        float(fp.get("f1", 0.0)),
        float(tp.get("f1", 0.0)),
        float(bl.get("f1_bl", 0.0)),
    )
    return {
        "srs": srs,
        "fprr": fp.get("fprr", fp.get("fp_removal_rate")),
        "vdr": tp.get("vdr", tp.get("tp_rate")),
        "bl_rate_on_bl_gold": bl.get("bl_rate"),
        "bl_lenient_accuracy": bl.get("lenient_accuracy"),
        "macro_f1": macro["macro_f1"],
        "srs_breakdown": srs_penalty_from_tracks(fp, tp, bl, test_n=600),
        "fp_track": fp,
        "tp_track": tp,
        "bl_track": bl,
    }


def _delta(candidate: float | None, baseline: float | None) -> str:
    if candidate is None or baseline is None:
        return "—"
    d = 100 * (float(candidate) - float(baseline))
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:.1f}pp"


def _pct(x: float | None) -> str:
    return f"{100 * float(x or 0):.1f}%"


def _tp_fp_confusion(tp_track: dict) -> int:
    dist = tp_track.get("distribution") or {}
    return int(dist.get("FP", 0))


def _fp_tp_confusion(fp_track: dict) -> int:
    dist = fp_track.get("distribution") or {}
    return int(dist.get("TP", 0))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate-sum-dir", type=Path, required=True)
    ap.add_argument("--baseline-sum-dir", type=Path, required=True)
    ap.add_argument("--profile", default="qwen3_5_9b_bnb")
    ap.add_argument("--candidate-label", required=True)
    ap.add_argument("--baseline-label", required=True)
    ap.add_argument("--json-out", type=Path, required=True)
    ap.add_argument("--md-out", type=Path, required=True)
    args = ap.parse_args()

    cand = _merged_from_sum_dir(args.candidate_sum_dir.resolve(), args.profile)
    base = _merged_from_sum_dir(args.baseline_sum_dir.resolve(), args.profile)

    metrics = ("srs", "fprr", "vdr", "bl_rate_on_bl_gold", "macro_f1")
    comparison = {
        "profile": args.profile,
        "candidate_label": args.candidate_label,
        "baseline_label": args.baseline_label,
        "candidate": {k: cand.get(k) for k in metrics},
        "baseline": {k: base.get(k) for k in metrics},
        "delta_pp": {
            k: (float(cand.get(k) or 0) - float(base.get(k) or 0)) * 100 for k in metrics
        },
        "critical_errors": {
            "candidate_tp_as_fp": _tp_fp_confusion(cand.get("tp_track") or {}),
            "baseline_tp_as_fp": _tp_fp_confusion(base.get("tp_track") or {}),
            "candidate_fp_as_tp": _fp_tp_confusion(cand.get("fp_track") or {}),
            "baseline_fp_as_tp": _fp_tp_confusion(base.get("fp_track") or {}),
        },
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(comparison, indent=2), encoding="utf-8")

    lines = [
        "# Lang-agnostic v7-balanced fs3 vs Stage 2 baseline",
        "",
        f"**Profile:** `{args.profile}` · **600 cases** (200 FP + 200 TP + 200 BL)",
        "",
        "## Headline comparison",
        "",
        "| Metric | "
        + args.baseline_label.split("(")[0].strip()
        + " | "
        + args.candidate_label
        + " | Δ |",
        "|--------|------:|------:|----:|",
    ]
    labels = {
        "srs": "SRS",
        "fprr": "FPRR",
        "vdr": "VDR",
        "bl_rate_on_bl_gold": "BL rate (BL-gold)",
        "macro_f1": "Macro-F1",
    }
    for key, label in labels.items():
        lines.append(
            f"| **{label}** | {_pct(base.get(key))} | {_pct(cand.get(key))} | "
            f"**{_delta(cand.get(key), base.get(key))}** |"
        )

    ce = comparison["critical_errors"]
    lines.extend(
        [
            "",
            "## Critical confusion (lower is better)",
            "",
            "| Error | Stage 2 | Lang-agnostic | Δ |",
            "|-------|--------:|--------------:|----:|",
            f"| TP → FP (missed vulns) | {ce['baseline_tp_as_fp']} | {ce['candidate_tp_as_fp']} | "
            f"{ce['candidate_tp_as_fp'] - ce['baseline_tp_as_fp']:+d} |",
            f"| FP → TP (false alarms kept) | {ce['baseline_fp_as_tp']} | {ce['candidate_fp_as_tp']} | "
            f"{ce['candidate_fp_as_tp'] - ce['baseline_fp_as_tp']:+d} |",
            "",
            f"JSON: `{args.json_out}`",
            "",
        ]
    )
    args.md_out.write_text("\n".join(lines), encoding="utf-8")

    print(
        f"Baseline SRS={_pct(base.get('srs'))}  Candidate SRS={_pct(cand.get('srs'))}  "
        f"Δ={_delta(cand.get('srs'), base.get('srs'))}"
    )
    print(f"Wrote {args.json_out}")
    print(f"Wrote {args.md_out}")


if __name__ == "__main__":
    main()
