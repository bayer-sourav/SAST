#!/usr/bin/env python3
"""Aggregate Stage 2 timing/tokens for FP, TP, and BL tracks (thinking off)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BENCH = Path(__file__).resolve().parents[3]
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))
from report_timing import PROFILES, _build_track, _scan_cell  # noqa: E402
from timing import aggregate_seconds, aggregate_tokens, format_duration, utc_now_iso, write_json

STAGE2_PROFILES = (
    "qwen3_4b_bnb",
    "qwen3_8b_bnb",
    "qwen3_14b_bnb",
)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json-out", type=Path, default=Path("benchmark/phase1_stage2_timing_report.json"))
    ap.add_argument("--n-fp", type=int, default=904)
    ap.add_argument("--n-tp", type=int, default=1373)
    ap.add_argument("--n-bl", type=int, default=200)
    args = ap.parse_args()

    sast = Path(__file__).resolve().parents[3].parent
    fp_root = sast / "runs/phase1/stage2/fp"
    tp_root = sast / "runs/phase1/stage2/tp"
    bl_root = sast / "runs/phase1/stage2/bl"
    thinking = "off"

    report: dict = {
        "generated_at": utc_now_iso(),
        "stage": "phase1_stage2",
        "thinking": thinking,
        "n_cases": {"FP": args.n_fp, "TP": args.n_tp, "BL": args.n_bl},
        "tracks": {"FP": {}, "TP": {}, "BL": {}},
        "experiments": [],
        "overall": {},
    }

    all_case: list[float] = []
    all_case_tokens: list[dict] = []
    all_cell_wall: list[float] = []

    for track_name, root, n_target in (
        ("FP", fp_root, args.n_fp),
        ("TP", tp_root, args.n_tp),
        ("BL", bl_root, args.n_bl),
    ):
        block = _build_track(root, thinking, n_target=n_target)
        report["tracks"][track_name][thinking] = block
        for profile, cell in block.get("cells", {}).items():
            if profile not in STAGE2_PROFILES:
                continue
            agg = cell.get("aggregate", {})
            per = agg.get("per_case", {})
            wall = float(agg.get("wall_clock_sec", per.get("total_sec", 0)))
            if wall > 0:
                all_cell_wall.append(wall)
            tok_agg = agg.get("tokens", {})
            tot_tok = tok_agg.get("total", {})
            for c in cell.get("cases", []):
                if c.get("elapsed_sec") is not None:
                    all_case.append(float(c["elapsed_sec"]))
                if c.get("total_tokens") is not None:
                    all_case_tokens.append(c)
            report["experiments"].append(
                {
                    "track": track_name,
                    "thinking": thinking,
                    "profile": profile,
                    "n_cases": cell.get("n_cases", 0),
                    "n_target": n_target,
                    "wall_clock_sec": wall,
                    "wall_clock_human": format_duration(wall),
                    "mean_case_sec": per.get("mean_sec", 0),
                    "mean_case_human": format_duration(per.get("mean_sec", 0)),
                    "tokens": tok_agg,
                    "mean_total_tokens": tot_tok.get("mean", 0),
                    "sum_total_tokens": tot_tok.get("sum", 0),
                }
            )

    report["overall"] = {
        "n_experiments_with_timing": len(report["experiments"]),
        "n_case_timings": len(all_case),
        "case_timing": aggregate_seconds(all_case),
        "cell_wall_clock": aggregate_seconds(all_cell_wall),
        "tokens": {
            "input": aggregate_tokens(all_case_tokens, "input_tokens"),
            "output": aggregate_tokens(all_case_tokens, "output_tokens"),
            "total": aggregate_tokens(all_case_tokens, "total_tokens"),
        },
    }
    o = report["overall"]
    if o["case_timing"].get("count"):
        o["case_timing"]["total_human"] = format_duration(o["case_timing"]["total_sec"])
        o["case_timing"]["mean_human"] = format_duration(o["case_timing"]["mean_sec"])

    out = (sast / args.json_out).resolve()
    write_json(out, report)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
