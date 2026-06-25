#!/usr/bin/env python3
"""Merge Stage 2 FP + TP matrix (FPRR/VDR/SRS/F1) and borderline summaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BENCH = Path(__file__).resolve().parents[3]  # benchmark/
_SAST = _BENCH.parent
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))
from merge_phase1_summary import _slm_row
from benchmark.srs import compute_srs  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fp-json", type=Path, required=True)
    ap.add_argument("--tp-json", type=Path, required=True)
    ap.add_argument("--bl-json", type=Path, required=True)
    ap.add_argument("--profiles", nargs="+", required=True)
    ap.add_argument("--json-out", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=None)
    args = ap.parse_args()

    fp_rows = json.loads(args.fp_json.read_text(encoding="utf-8"))
    tp_rows = json.loads(args.tp_json.read_text(encoding="utf-8"))
    bl_rows = json.loads(args.bl_json.read_text(encoding="utf-8"))

    out: dict = {
        "_meta": {
            "stage": "phase1_stage2",
            "thinking": "off",
            "profiles": args.profiles,
            "fp_json": str(args.fp_json),
            "tp_json": str(args.tp_json),
            "bl_json": str(args.bl_json),
        },
        "models": {},
        "borderline": {},
    }
    if args.manifest and args.manifest.is_file():
        out["_meta"]["manifest"] = str(args.manifest)

    for profile in args.profiles:
        fp_m = _slm_row(fp_rows, profile)
        tp_m = _slm_row(tp_rows, profile)
        bl_m = bl_rows.get(f"SLM ({profile})")
        if not fp_m or not tp_m:
            continue
        fprr = float(fp_m.get("fprr", fp_m.get("fp_removal_rate", 0.0)))
        vdr = float(tp_m.get("vdr", tp_m.get("tp_rate", 0.0)))
        f1_fp = float(fp_m.get("f1", 0.0))
        f1_tp = float(tp_m.get("f1", 0.0))
        srs = compute_srs(fp_m, tp_m, bl_m)
        if srs is None:
            srs = 0.5 * fprr + 0.5 * vdr
        out["models"][profile] = {
            "fprr": fprr,
            "vdr": vdr,
            "srs": srs,
            "f1_fp_track": f1_fp,
            "f1_tp_track": f1_tp,
            "f1": 0.5 * f1_fp + 0.5 * f1_tp,
            "fp_track": fp_m,
            "tp_track": tp_m,
        }
        if bl_m:
            out["borderline"][profile] = bl_m

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {args.json_out}")

    thinking = out["_meta"].get("thinking", "off")
    print(f"\n--- Results: thinking_{thinking} ---")
    print(
        f"{'Profile':<28} {'FPRR':>7} {'VDR':>7} {'SRS':>7} "
        f"{'F1':>7} {'F1-FP':>7} {'F1-TP':>7} {'Cov-FP':>7} {'Cov-TP':>7}"
    )
    for profile, m in out["models"].items():
        fp = m.get("fp_track", {})
        tp = m.get("tp_track", {})
        print(
            f"{profile:<28} "
            f"{100 * m['fprr']:6.1f}% "
            f"{100 * m['vdr']:6.1f}% "
            f"{100 * m['srs']:6.1f}% "
            f"{100 * m['f1']:6.1f}% "
            f"{100 * m['f1_fp_track']:6.1f}% "
            f"{100 * m['f1_tp_track']:6.1f}% "
            f"{100 * fp.get('coverage', 0):6.1f}% "
            f"{100 * tp.get('coverage', 0):6.1f}%"
        )

    bl = out.get("borderline", {})
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


if __name__ == "__main__":
    main()
