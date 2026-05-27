#!/usr/bin/env python3
"""Merge FP + TP track summaries into a Phase 1 matrix (SRS, macro F1, per-track metrics)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _slm_row(rows: dict, profile: str) -> dict | None:
    key = f"SLM ({profile})"
    return rows.get(key)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fp-json", type=Path, required=True, help="summarize_triage FP track JSON")
    ap.add_argument("--tp-json", type=Path, required=True, help="summarize_triage TP track JSON")
    ap.add_argument("--profiles", nargs="+", required=True)
    ap.add_argument("--thinking", choices=("off", "on"), required=True)
    ap.add_argument("--json-out", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, default=None)
    args = ap.parse_args()

    fp_rows = json.loads(args.fp_json.read_text(encoding="utf-8"))
    tp_rows = json.loads(args.tp_json.read_text(encoding="utf-8"))

    matrix: dict[str, dict] = {
        "_meta": {
            "thinking": args.thinking,
            "srs_weight": 0.5,
            "f1_weight": 0.5,
            "profiles": args.profiles,
            "fp_json": str(args.fp_json),
            "tp_json": str(args.tp_json),
        },
        "models": {},
    }
    if args.manifest and args.manifest.is_file():
        matrix["_meta"]["slice_manifest"] = str(args.manifest)

    for profile in args.profiles:
        fp_m = _slm_row(fp_rows, profile)
        tp_m = _slm_row(tp_rows, profile)
        if not fp_m or not tp_m:
            continue
        fprr = float(fp_m.get("fprr", fp_m.get("fp_removal_rate", 0.0)))
        vdr = float(tp_m.get("vdr", tp_m.get("tp_rate", 0.0)))
        f1_fp = float(fp_m.get("f1", 0.0))
        f1_tp = float(tp_m.get("f1", 0.0))
        srs = 0.5 * fprr + 0.5 * vdr
        f1 = 0.5 * f1_fp + 0.5 * f1_tp
        matrix["models"][profile] = {
            "fprr": fprr,
            "vdr": vdr,
            "srs": srs,
            "f1_fp_track": f1_fp,
            "f1_tp_track": f1_tp,
            "f1": f1,
            "fp_track": fp_m,
            "tp_track": tp_m,
        }

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
    print(f"Wrote {args.json_out}")
    print(
        f"{'Profile':<28} {'FPRR':>7} {'VDR':>7} {'SRS':>7} "
        f"{'F1':>7} {'F1-FP':>7} {'F1-TP':>7}"
    )
    for profile, m in matrix["models"].items():
        print(
            f"{profile:<28} "
            f"{100 * m['fprr']:6.1f}% "
            f"{100 * m['vdr']:6.1f}% "
            f"{100 * m['srs']:6.1f}% "
            f"{100 * m['f1']:6.1f}% "
            f"{100 * m['f1_fp_track']:6.1f}% "
            f"{100 * m['f1_tp_track']:6.1f}%"
        )


if __name__ == "__main__":
    main()
