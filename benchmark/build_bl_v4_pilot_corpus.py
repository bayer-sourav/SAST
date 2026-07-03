#!/usr/bin/env python3
"""Materialize BL v4 pilot cases into benchmark/corpora/bl_v4_pilot/."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parent.parent
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))


def _pilot_root(arg: Path | None) -> Path:
    if arg is not None:
        return arg.expanduser().resolve()
    for candidate in (
        _sast.parent / "SAST-Benchmark-Dataset" / "BenchmarkJava" / "borderline_pilot",
        _sast / "benchmark" / "external" / "SAST-Benchmark-Dataset" / "BenchmarkJava" / "borderline_pilot",
    ):
        if (candidate / "manifest.json").is_file():
            return candidate.resolve()
    raise FileNotFoundError("borderline_pilot not found; run build_borderline_v4_pilot.py first")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pilot-root", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=_sast / "benchmark" / "corpora" / "bl_v4_pilot",
    )
    args = ap.parse_args()

    pilot = _pilot_root(args.pilot_root)
    manifest = json.loads((pilot / "manifest.json").read_text(encoding="utf-8"))
    out_dir = args.out_dir.expanduser().resolve()
    if out_dir.exists():
        for old in out_dir.glob("*.json"):
            old.unlink()
    else:
        out_dir.mkdir(parents=True)

    published: list[dict] = []
    pilot_dir = pilot / "pilot"
    for bundle in sorted(p for p in pilot_dir.iterdir() if p.is_dir()):
        case_path = bundle / "case.json"
        case = json.loads(case_path.read_text(encoding="utf-8"))
        cid = str(case.get("case_id") or bundle.name)
        case["bundle_root"] = str(bundle.resolve())
        case["repo_root"] = str(bundle.resolve())
        case["dataset_bundle"] = True
        case["_eval_gold_track"] = "BL"
        out_json = out_dir / f"{cid}.json"
        out_json.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        published.append({"case_id": cid, "borderline_category": case.get("borderline_category")})

    meta = {
        "n_cases": len(published),
        "pilot_root": str(pilot),
        "corpus_dir": str(out_dir),
        "cases": published,
    }
    (out_dir / "slice_manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"n_cases": len(published), "corpus_dir": str(out_dir)}, indent=2))


if __name__ == "__main__":
    main()
