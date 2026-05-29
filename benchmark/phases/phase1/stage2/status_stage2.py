#!/usr/bin/env python3
"""Phase 1 Stage 2 progress, metrics (FPRR/VDR/SRS/F1), borderline, and timing."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import sys

_SAST = Path(__file__).resolve().parents[3].parent
_BENCH = _SAST / "benchmark"
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))
from timing import format_duration  # noqa: E402

from benchmark.triage_labels import VALID_LABELS  # noqa: E402

PROFILES = ("qwen3_4b_bnb", "qwen3_8b_bnb", "qwen3_14b_bnb")
THINKING = "off"
SEED = 42
BL_N = 200


def _count(runs_root: Path, profile: str) -> int:
    d = runs_root / f"thinking_{THINKING}" / profile / "llm"
    if not d.is_dir():
        return 0
    n = 0
    for p in d.iterdir():
        rp = p / "agent-llm-triage-result.json"
        if not rp.is_file():
            continue
        try:
            lbl = str(json.loads(rp.read_text(encoding="utf-8")).get("label", "")).strip().upper()
        except json.JSONDecodeError:
            continue
        if lbl in VALID_LABELS:
            n += 1
    return n


def _cell_timing(runs_root: Path, profile: str) -> dict | None:
    p = runs_root / f"thinking_{THINKING}" / profile / "cell_timing.json"
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def main() -> None:
    sast = Path(__file__).resolve().parents[3].parent
    n_fp, n_tp, n_bl = 904, 1373, BL_N
    targets = {"fp": n_fp, "tp": n_tp, "bl": n_bl}
    roots = {
        "fp": sast / "runs/phase1/stage2/fp",
        "tp": sast / "runs/phase1/stage2/tp",
        "bl": sast / "runs/phase1/stage2/bl",
    }

    total_done = 0
    total_target = sum(targets.values()) * len(PROFILES)

    print("Phase 1 Stage 2 progress (thinking off; Qwen 4B/8B/14B)\n")
    for track, n in targets.items():
        root = roots[track]
        print(f"=== {track.upper()} (target {n}/profile) ===")
        for profile in PROFILES:
            c = _count(root, profile)
            total_done += c
            bar = "done" if c >= n else f"{c}/{n}"
            extra = ""
            ct = _cell_timing(root, profile)
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
            print(f"  {profile:<28} {bar}{extra}")
        print()

    pct = 100 * total_done / total_target if total_target else 0
    print(f"Overall: {total_done}/{total_target} case runs ({pct:.1f}%)\n")

    matrix = sast / "runs/phase1/stage2/summaries/phase1_stage2_matrix_thinking_off.json"
    if matrix.is_file():
        data = json.loads(matrix.read_text(encoding="utf-8"))
        print("\n--- Results: thinking_off ---")
        print(
            f"{'Profile':<28} {'FPRR':>7} {'VDR':>7} {'SRS':>7} "
            f"{'F1':>7} {'F1-FP':>7} {'F1-TP':>7} {'Cov-FP':>7} {'Cov-TP':>7}"
        )
        for profile, m in data.get("models", {}).items():
            fp = m.get("fp_track", {})
            tp = m.get("tp_track", {})
            print(
                f"{profile:<28} "
                f"{100 * m['fprr']:6.1f}% "
                f"{100 * m['vdr']:6.1f}% "
                f"{100 * m['srs']:6.1f}% "
                f"{100 * m.get('f1', 0):6.1f}% "
                f"{100 * m.get('f1_fp_track', 0):6.1f}% "
                f"{100 * m.get('f1_tp_track', 0):6.1f}% "
                f"{100 * fp.get('coverage', 0):6.1f}% "
                f"{100 * tp.get('coverage', 0):6.1f}%"
            )

        bl = data.get("borderline", {})
        if bl:
            print("\n--- Borderline metrics ---")
            print(
                f"{'Profile':<28} {'Cov':>7} {'TP%':>7} {'FP%':>7} {'BL%':>7} "
                f"{'LenAcc':>7} {'BenchAg':>7} {'AmbIdx':>7}"
            )
            for profile, m in bl.items():
                print(
                    f"{profile:<28} "
                    f"{100 * m.get('coverage', 0):6.1f}% "
                    f"{100 * m.get('tp_rate', 0):6.1f}% "
                    f"{100 * m.get('fp_rate', 0):6.1f}% "
                    f"{100 * m.get('bl_rate', 0):6.1f}% "
                    f"{100 * m.get('lenient_accuracy', 0):6.1f}% "
                    f"{100 * m.get('benchmark_agreement', 0):6.1f}% "
                    f"{m.get('ambiguity_index', 0):7.3f}"
                )
    else:
        print(f"(No matrix yet — run refresh after some cells: {matrix})")

    tr = sast / "benchmark/phase1_stage2_timing_report.json"
    if tr.is_file():
        report = json.loads(tr.read_text(encoding="utf-8"))
        o = report.get("overall", {})
        ct = o.get("case_timing", {})
        if ct.get("count"):
            print(
                f"\nTiming ({ct['count']} cases): "
                f"total={ct.get('total_human', format_duration(ct['total_sec']))} "
                f"mean={ct.get('mean_human', format_duration(ct['mean_sec']))}"
            )
        tok = o.get("tokens", {}).get("total", {})
        if tok.get("count"):
            print(
                f"Tokens: sum={tok['sum']:,} mean={tok['mean']:,.0f} "
                f"(n={tok['count']})"
            )

    if subprocess.run(["pgrep", "-f", "run_phase1_stage2"], capture_output=True).returncode == 0:
        print("\nStatus: run_phase1_stage2.sh is RUNNING")
    else:
        print("\nStatus: run_phase1_stage2.sh is NOT running")


if __name__ == "__main__":
    main()
