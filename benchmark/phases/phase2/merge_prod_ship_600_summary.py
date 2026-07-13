#!/usr/bin/env python3
"""Merge FP + TP + BL track summaries into 600-case SRS / VDR / FPRR report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.srs import compute_srs, srs_penalty_from_tracks  # noqa: E402
from benchmark.summarize_triage import macro_f1_from_track_f1s  # noqa: E402


def _slm_row(data: dict, profile: str) -> dict:
    key = f"SLM ({profile})"
    if key not in data:
        raise KeyError(f"missing {key!r} in summary")
    return data[key]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sum-dir", type=Path, required=True)
    ap.add_argument("--profile", default="qwen3_5_9b_bnb")
    ap.add_argument("--json-out", type=Path, required=True)
    ap.add_argument("--md-out", type=Path, required=True)
    args = ap.parse_args()

    sum_dir = args.sum_dir.expanduser().resolve()
    fp = _slm_row(json.loads((sum_dir / "comparison_fp.json").read_text()), args.profile)
    tp = _slm_row(json.loads((sum_dir / "comparison_tp.json").read_text()), args.profile)
    bl = _slm_row(json.loads((sum_dir / "comparison_bl.json").read_text()), args.profile)

    srs_pack = srs_penalty_from_tracks(fp, tp, bl, test_n=600)
    srs = compute_srs(fp, tp, bl, test_n=600)
    macro = macro_f1_from_track_f1s(
        float(fp.get("f1", 0.0)),
        float(tp.get("f1", 0.0)),
        float(bl.get("f1_bl", 0.0)),
    )
    macro_f1 = macro["macro_f1"]

    out = {
        "profile": args.profile,
        "n_cases": 600,
        "fp_track": fp,
        "tp_track": tp,
        "bl_track": bl,
        "merged": {
            "srs": srs,
            "fprr": fp.get("fprr", fp.get("fp_removal_rate")),
            "vdr": tp.get("vdr", tp.get("tp_rate")),
            "bl_rate_on_bl_gold": bl.get("bl_rate"),
            "bl_lenient_accuracy": bl.get("lenient_accuracy"),
            "macro_f1": macro_f1,
            "srs_breakdown": srs_pack,
        },
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(out, indent=2), encoding="utf-8")

    def pct(x: float | None) -> str:
        return f"{100 * float(x or 0):.1f}%"

    lines = [
        "# Prod ship 600-case test report",
        "",
        f"**Profile:** `{args.profile}`",
        "",
        "## Merged metrics",
        "",
        f"| Metric | Value |",
        f"|--------|------:|",
        f"| **SRS** | **{pct(srs)}** |",
        f"| FPRR (FP track) | {pct(fp.get('fprr'))} |",
        f"| VDR (TP track) | {pct(tp.get('vdr'))} |",
        f"| BL rate (BL-gold track) | {pct(bl.get('bl_rate'))} |",
        f"| BL lenient accuracy | {pct(bl.get('lenient_accuracy'))} |",
        f"| Macro-F1 | {pct(macro_f1)} |",
        "",
        "## Per-track distribution",
        "",
        f"| Track | Gold | Evaluated | TP | FP | BL | UNKNOWN | Missing |",
        f"|-------|------|----------:|---:|---:|---:|--------:|--------:|",
    ]
    for name, row, gold in (("FP", fp, "FP"), ("TP", tp, "TP"), ("BL", bl, "BL")):
        dist = row.get("distribution") or {}
        lines.append(
            f"| {name} | {gold} | {row.get('evaluated', 0)} | "
            f"{dist.get('TP', 0)} | {dist.get('FP', 0)} | {dist.get('BL', 0)} | "
            f"{dist.get('UNKNOWN', 0)} | {row.get('missing', 0)} |"
        )
    lines.extend(["", f"JSON: `{args.json_out}`", ""])
    args.md_out.write_text("\n".join(lines), encoding="utf-8")

    print(f"SRS={pct(srs)}  FPRR={pct(fp.get('fprr'))}  VDR={pct(tp.get('vdr'))}  BL={pct(bl.get('bl_rate'))}")
    print(f"Wrote {args.json_out}")
    print(f"Wrote {args.md_out}")


if __name__ == "__main__":
    main()
