#!/usr/bin/env python3
"""Aggregate per-case, per-cell (experiment), and overall Phase 1 timing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from timing import (
    aggregate_seconds,
    aggregate_tokens,
    case_elapsed_sec,
    format_duration,
    read_run_meta,
    tokens_from_meta,
    utc_now_iso,
    write_json,
)

PROFILES = (
    "qwen3_4b_bnb",
    "qwen3_8b_bnb",
    "qwen3_14b_bnb",
    "gpt_oss_20b",
    "qwen3_coder_30b_bnb",
)


def _enrich_case_tokens(cell_path: Path, cases: list[dict]) -> list[dict]:
    out = []
    for c in cases:
        row = dict(c)
        if row.get("total_tokens") is not None:
            out.append(row)
            continue
        run_dir = cell_path / str(row.get("case_id", ""))
        if run_dir.is_dir():
            row.update(tokens_from_meta(read_run_meta(run_dir)))
        out.append(row)
    return out


def _scan_cell(runs_root: Path, profile: str) -> dict | None:
    cell_path = runs_root / profile / "llm"
    if not cell_path.is_dir():
        return None
    cell_timing_path = runs_root / profile / "cell_timing.json"
    if cell_timing_path.is_file():
        data = json.loads(cell_timing_path.read_text(encoding="utf-8"))
        cases = _enrich_case_tokens(cell_path, data.get("cases", []))
        data["cases"] = cases
        elapsed = [float(c["elapsed_sec"]) for c in cases if c.get("elapsed_sec") is not None]
        infer = [float(c["inference_sec"]) for c in cases if c.get("inference_sec") is not None]
        agg = data.setdefault("aggregate", {})
        agg["tokens"] = {
            "input": aggregate_tokens(cases, "input_tokens"),
            "output": aggregate_tokens(cases, "output_tokens"),
            "total": aggregate_tokens(cases, "total_tokens"),
        }
        if elapsed:
            agg["per_case"] = aggregate_seconds(elapsed)
        if infer:
            agg["inference"] = aggregate_seconds(infer)
        return data

    cases: list[dict] = []
    for case_dir in sorted(cell_path.iterdir()):
        if not case_dir.is_dir():
            continue
        cid = case_dir.name
        meta = read_run_meta(case_dir)
        elapsed = case_elapsed_sec(case_dir)
        if elapsed is None:
            continue
        tok = tokens_from_meta(meta)
        cases.append(
            {
                "case_id": cid,
                "elapsed_sec": round(elapsed, 3),
                "inference_sec": meta.get("inference_sec"),
                "skipped": not (case_dir / "agent-llm-triage-result.json").is_file(),
                **tok,
            }
        )
    if not cases:
        return None
    elapsed = [float(c["elapsed_sec"]) for c in cases]
    infer = [float(c["inference_sec"]) for c in cases if c.get("inference_sec") is not None]
    return {
        "profile": profile,
        "n_cases": len(cases),
        "cases": cases,
        "aggregate": {
            "per_case": aggregate_seconds(elapsed),
            "inference": aggregate_seconds(infer),
            "tokens": {
                "input": aggregate_tokens(cases, "input_tokens"),
                "output": aggregate_tokens(cases, "output_tokens"),
                "total": aggregate_tokens(cases, "total_tokens"),
            },
        },
    }


def _build_track(
    track_root: Path,
    thinking: str,
    *,
    n_target: int,
) -> dict:
    runs = track_root / f"thinking_{thinking}"
    cells: dict[str, dict] = {}
    for profile in PROFILES:
        cell = _scan_cell(runs, profile)
        if cell:
            cells[profile] = cell
    return {"thinking": thinking, "runs_root": str(runs), "cells": cells}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fp-runs", type=Path, default=Path("FP-runs/phase1_n50"))
    ap.add_argument("--tp-runs", type=Path, default=Path("TP-runs/phase1_n50"))
    ap.add_argument("--n-cases", type=int, default=50)
    ap.add_argument("--json-out", type=Path, default=Path("benchmark/phase1_timing_report.json"))
    ap.add_argument("--started-at", type=Path, default=Path("benchmark/phase1_logs/started_at.txt"))
    args = ap.parse_args()

    sast = Path(__file__).resolve().parent.parent
    fp_root = (sast / args.fp_runs).resolve()
    tp_root = (sast / args.tp_runs).resolve()

    report: dict = {
        "generated_at": utc_now_iso(),
        "n_cases_per_cell": args.n_cases,
        "tracks": {"FP": {}, "TP": {}},
        "experiments": [],
        "overall": {},
    }

    if args.started_at.is_file():
        report["experiment_started_at"] = args.started_at.read_text(encoding="utf-8").strip()

    all_cell_wall: list[float] = []
    all_case: list[float] = []
    all_case_tokens: list[dict] = []

    for track_name, root in (("FP", fp_root), ("TP", tp_root)):
        for thinking in ("off", "on"):
            block = _build_track(root, thinking, n_target=args.n_cases)
            report["tracks"][track_name][thinking] = block
            for profile, cell in block.get("cells", {}).items():
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
                        "wall_clock_sec": wall,
                        "wall_clock_human": format_duration(wall),
                        "mean_case_sec": per.get("mean_sec", 0),
                        "mean_case_human": format_duration(per.get("mean_sec", 0)),
                        "total_case_sec": per.get("total_sec", 0),
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
    if o["case_timing"]["count"]:
        o["case_timing"]["total_human"] = format_duration(o["case_timing"]["total_sec"])
        o["case_timing"]["mean_human"] = format_duration(o["case_timing"]["mean_sec"])
    if o["cell_wall_clock"]["count"]:
        o["cell_wall_clock"]["total_human"] = format_duration(o["cell_wall_clock"]["total_sec"])

    out = (sast / args.json_out).resolve()
    write_json(out, report)

    print(f"Wrote {out}")
    print(f"\nOverall: {o['n_case_timings']} cases timed")
    if o["case_timing"]["count"]:
        ct = o["case_timing"]
        print(
            f"  Per-case: total={ct['total_human']} mean={ct['mean_human']} "
            f"min={ct['min_sec']:.1f}s max={ct['max_sec']:.1f}s"
        )
    tok_o = o.get("tokens", {}).get("total", {})
    if tok_o.get("count"):
        print(
            f"  Tokens: sum={tok_o['sum']:,} mean={tok_o['mean']:,.0f} "
            f"min={tok_o['min']:,} max={tok_o['max']:,} (n={tok_o['count']})"
        )
    if report["experiments"]:
        print(
            f"\n{'Track':<4} {'Think':<4} {'Profile':<28} {'Cases':>5} "
            f"{'Wall':>10} {'Mean/case':>10} {'Mean tok':>9}"
        )
        for e in report["experiments"]:
            mt = e.get("mean_total_tokens") or 0
            mt_s = f"{mt:,.0f}" if mt else "—"
            print(
                f"{e['track']:<4} {e['thinking']:<4} {e['profile']:<28} "
                f"{e['n_cases']:5d} {e['wall_clock_human']:>10} {e['mean_case_human']:>10} {mt_s:>9}"
            )


if __name__ == "__main__":
    main()
