#!/usr/bin/env python3
"""Materialize Phase 2 test corpora from SAST-Benchmark-Dataset (200 per track)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parent.parent
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))


def _dataset_root(arg: Path | None) -> Path:
    if arg is not None:
        return arg.expanduser().resolve()
    for candidate in (
        _sast.parent / "SAST-Benchmark-Dataset" / "BenchmarkJava",
        _sast / "benchmark" / "external" / "SAST-Benchmark-Dataset" / "BenchmarkJava",
    ):
        if (candidate / "fp" / "manifest.json").is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        "SAST-Benchmark-Dataset not found. Pass --dataset-root "
        "(BenchmarkJava dir with fp/tp/borderline manifests)."
    )


def _git_commit(dataset_java: Path) -> str | None:
    repo = dataset_java.parent
    if not (repo / ".git").is_dir():
        return None
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def _test_entries(manifest: dict) -> list[dict]:
    rows = []
    for row in manifest.get("cases") or []:
        bundle = str(row.get("bundle", ""))
        if "/test/" in bundle.replace("\\", "/"):
            rows.append(row)
    return sorted(rows, key=lambda r: r["case_id"])


def _publish_case(*, bundle_dir: Path, out_path: Path, gold_track: str) -> dict:
    case_path = bundle_dir / "case.json"
    if not case_path.is_file():
        raise FileNotFoundError(case_path)
    case = json.loads(case_path.read_text(encoding="utf-8"))
    bundle_dir = bundle_dir.resolve()
    # bundle_root: internal only (file I/O); never written into task.md prompts.
    case["bundle_root"] = str(bundle_dir)
    case["repo_root"] = str(bundle_dir)
    case["dataset_bundle"] = True
    # gold_track kept for offline eval only — not included in make_task.md.
    case["_eval_gold_track"] = gold_track
    case["phase2_split"] = "test"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "case_id": str(case.get("case_id") or bundle_dir.name),
        "bundle": str(bundle_dir),
        "corpus_json": str(out_path.resolve()),
        "cwe_bucket": case.get("cwe_bucket"),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dataset-root",
        type=Path,
        default=None,
        help="BenchmarkJava root (fp/tp/borderline + manifests).",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=_sast / "benchmark" / "corpora",
        help="Parent dir for phase2_*_test folders.",
    )
    ap.add_argument("--manifest-out", type=Path, default=None)
    args = ap.parse_args()

    dataset = _dataset_root(args.dataset_root)
    out_parent = args.out_dir.expanduser().resolve()
    manifest_out = (
        args.manifest_out.expanduser().resolve()
        if args.manifest_out
        else _sast / "benchmark" / "phases" / "phase2" / "MANIFEST.json"
    )

    tracks = {
        "fp": ("FP", out_parent / "phase2_fp_test"),
        "tp": ("TP", out_parent / "phase2_tp_test"),
        "borderline": ("BL", out_parent / "phase2_bl_test"),
    }

    manifest: dict = {
        "phase": 2,
        "dataset_root": str(dataset),
        "dataset_commit": _git_commit(dataset),
        "seed": 42,
        "n_per_track": 200,
        "tracks": {},
    }

    for cls, (gold, corpus_dir) in tracks.items():
        mpath = dataset / cls / "manifest.json"
        mdata = json.loads(mpath.read_text(encoding="utf-8"))
        entries = _test_entries(mdata)
        if len(entries) != 200:
            print(f"[warn] {cls}: expected 200 test cases, got {len(entries)}", file=sys.stderr)

        if corpus_dir.exists():
            for old in corpus_dir.glob("*.json"):
                if old.name != "slice_manifest.json":
                    old.unlink()
        else:
            corpus_dir.mkdir(parents=True)

        published = []
        for row in entries:
            cid = row["case_id"]
            bundle = dataset / row["bundle"]
            out_json = corpus_dir / f"OWASP_{cid}.json"
            published.append(_publish_case(bundle_dir=bundle, out_path=out_json, gold_track=gold))

        manifest["tracks"][cls] = {
            "gold": gold,
            "corpus_dir": str(corpus_dir),
            "n_cases": len(published),
            "case_ids": [p["case_id"] for p in published],
        }
        print(f"[phase2] {cls}: {len(published)} cases -> {corpus_dir}")

    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"[phase2] Wrote {manifest_out}")


if __name__ == "__main__":
    main()
