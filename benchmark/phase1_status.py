#!/usr/bin/env python3
"""Print Phase 1 matrix progress, metrics, and timing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from timing import format_duration

PROFILES = (
    "qwen3_4b_bnb",
    "qwen3_8b_bnb",
    "qwen3_14b_bnb",
    "gpt_oss_20b",
    "qwen3_coder_30b_bnb",
)
N = 50


def _count(root: Path, profile: str) -> int:
    d = root / profile / "llm"
    if not d.is_dir():
        return 0
    return sum(1 for p in d.iterdir() if (p / "agent-llm-triage-result.json").is_file())


def _cell_timing(runs: Path, profile: str) -> dict | None:
    p = runs / profile / "cell_timing.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def main() -> None:
    sast = Path(__file__).resolve().parent.parent
    fp_root = sast / "FP-runs" / "phase1_n50"
    tp_root = sast / "TP-runs" / "phase1_n50"

    print("Phase 1 progress (target 50 cases per cell)\n")
    total_done = 0
    total_target = len(PROFILES) * 2 * 2 * N

    for thinking in ("off", "on"):
        print(f"=== thinking_{thinking} ===")
        for track, root in (("FP", fp_root), ("TP", tp_root)):
            runs = root / f"thinking_{thinking}"
            print(f"  [{track}]")
            for profile in PROFILES:
                c = _count(runs, profile)
                total_done += c
                bar = "done" if c >= N else f"{c}/{N}"
                extra = ""
                ct = _cell_timing(runs, profile)
                if ct:
                    agg = ct.get("aggregate", {})
                    wall = ct.get("elapsed_sec") or agg.get("wall_clock_sec")
                    mean = agg.get("per_case", {}).get("mean_sec")
                    tok = agg.get("tokens", {}).get("total", {})
                    if wall:
                        extra = f"  wall={format_duration(float(wall))}"
                    if mean:
                        extra += f" mean/case={format_duration(float(mean))}"
                    if tok.get("mean"):
                        extra += f" mean_tok={tok['mean']:,.0f}"
                print(f"    {profile:<28} {bar}{extra}")
        print()

    pct = 100 * total_done / total_target if total_target else 0
    print(f"Overall: {total_done}/{total_target} case runs ({pct:.1f}%)")

    timing_report = sast / "benchmark" / "phase1_timing_report.json"
    if timing_report.is_file():
        tr = json.loads(timing_report.read_text(encoding="utf-8"))
        o = tr.get("overall", {})
        ct = o.get("case_timing", {})
        if ct.get("count"):
            print(
                f"\nTiming ({ct['count']} cases): "
                f"total={ct.get('total_human', format_duration(ct['total_sec']))} "
                f"mean={ct.get('mean_human', format_duration(ct['mean_sec']))} "
                f"min={ct['min_sec']:.1f}s max={ct['max_sec']:.1f}s"
            )
        tok_o = o.get("tokens", {}).get("total", {})
        if tok_o.get("count"):
            print(
                f"Tokens ({tok_o['count']} cases with counts): "
                f"sum={tok_o['sum']:,} mean={tok_o['mean']:,.0f} "
                f"in={o.get('tokens', {}).get('input', {}).get('sum', 0):,} "
                f"out={o.get('tokens', {}).get('output', {}).get('sum', 0):,}"
            )
        exps = tr.get("experiments", [])
        if exps:
            print(f"\n{'Trk':<4} {'Th':<3} {'Profile':<26} {'N':>4} {'Wall':>9} {'Mean':>9}")
            for e in exps[-8:]:
                print(
                    f"{e['track']:<4} {e['thinking']:<3} {e['profile']:<26} "
                    f"{e['n_cases']:4d} {e.get('wall_clock_human','?'):>9} "
                    f"{e.get('mean_case_human','?'):>9}"
                )
            if len(exps) > 8:
                print(f"  ... {len(exps) - 8} more in {timing_report}")

    for thinking in ("off", "on"):
        matrix = fp_root / f"phase1_matrix_thinking_{thinking}.json"
        if matrix.is_file():
            print(f"\n--- Results: thinking_{thinking} ---")
            data = json.loads(matrix.read_text())
            print(
                f"{'Profile':<28} {'FPRR':>7} {'VDR':>7} {'SRS':>7} "
                f"{'F1':>7} {'F1-FP':>7} {'F1-TP':>7} {'Cov-FP':>7} {'Cov-TP':>7}"
            )
            for profile, m in data.get("models", {}).items():
                f1_fp = float(m.get("f1_fp_track", m.get("fp_track", {}).get("f1", 0.0)))
                f1_tp = float(m.get("f1_tp_track", m.get("tp_track", {}).get("f1", 0.0)))
                f1 = float(m.get("f1", 0.5 * (f1_fp + f1_tp)))
                print(
                    f"{profile:<28} "
                    f"{100 * m['fprr']:6.1f}% "
                    f"{100 * m['vdr']:6.1f}% "
                    f"{100 * m['srs']:6.1f}% "
                    f"{100 * f1:6.1f}% "
                    f"{100 * f1_fp:6.1f}% "
                    f"{100 * f1_tp:6.1f}% "
                    f"{100 * m['fp_track']['coverage']:6.1f}% "
                    f"{100 * m['tp_track']['coverage']:6.1f}%"
                )

    combined = sast / "benchmark" / "phase1_combined_summary.json"
    if combined.is_file():
        print(f"\nFull summary: {combined}")
    if timing_report.is_file():
        print(f"Timing report: {timing_report}")

    if subprocess.run(["pgrep", "-f", "run_phase1_matrix.sh"], capture_output=True).returncode == 0:
        print("\nStatus: run_phase1_matrix.sh is RUNNING")
    else:
        print("\nStatus: run_phase1_matrix.sh is NOT running (finished or stopped)")


if __name__ == "__main__":
    main()
