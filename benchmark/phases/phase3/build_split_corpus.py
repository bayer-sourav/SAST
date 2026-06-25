#!/usr/bin/env python3
"""Materialize BenchmarkJava train/validation corpora for Phase 3B batch infer."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.build_phase2_corpora import _dataset_root, _publish_case  # noqa: E402
from benchmark.phases.phase3.export_sft_dataset import _split_entries  # noqa: E402

_TRACKS = (
    ("fp", "FP"),
    ("tp", "TP"),
    ("borderline", "BL"),
)


def build_split_corpus(
    *,
    dataset: Path,
    split: str,
    out_root: Path,
    max_per_class: int | None = None,
    case_ids: set[str] | None = None,
) -> dict:
    out_root.mkdir(parents=True, exist_ok=True)
    manifest_rows: list[dict] = []
    per_class: dict[str, int] = {}

    for cls, gold in _TRACKS:
        mpath = dataset / cls / "manifest.json"
        entries = _split_entries(json.loads(mpath.read_text(encoding="utf-8")), split)
        if case_ids is not None:
            entries = [e for e in entries if e["case_id"] in case_ids]
        if max_per_class is not None:
            entries = entries[:max_per_class]
        per_class[cls] = len(entries)
        track_dir = out_root / cls
        track_dir.mkdir(parents=True, exist_ok=True)
        keep_ids = {row["case_id"] for row in entries}
        if case_ids is not None:
            for stale in track_dir.glob("*.json"):
                if stale.name == "corpus_manifest.json":
                    continue
                if stale.stem not in keep_ids:
                    stale.unlink()
        for row in entries:
            bundle = (dataset / row["bundle"]).resolve()
            out_path = track_dir / f"{row['case_id']}.json"
            pub = _publish_case(bundle_dir=bundle, out_path=out_path, gold_track=cls)
            pub["gold_label"] = gold
            pub["split"] = split
            manifest_rows.append(pub)

    meta = {
        "split": split,
        "n_cases": len(manifest_rows),
        "per_class": per_class,
        "out_root": str(out_root.resolve()),
    }
    (out_root / "corpus_manifest.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset-root", type=Path, default=None)
    ap.add_argument("--split", choices=("train", "validation"), required=True)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=_sast / "runs/phase3/stage3b/corpora",
    )
    ap.add_argument("--max-per-class", type=int, default=None)
    ap.add_argument(
        "--case-ids-file",
        type=Path,
        default=None,
        help="Optional JSON list of case_ids to include (fast CSS val subset).",
    )
    args = ap.parse_args()

    dataset = _dataset_root(args.dataset_root)
    out_root = args.out_dir.expanduser().resolve() / args.split
    case_ids = None
    if args.case_ids_file:
        case_ids = set(json.loads(args.case_ids_file.read_text(encoding="utf-8")))

    meta = build_split_corpus(
        dataset=dataset,
        split=args.split,
        out_root=out_root,
        max_per_class=args.max_per_class,
        case_ids=case_ids,
    )
    print(f"[corpus] {args.split}: {meta['n_cases']} cases -> {out_root}")


if __name__ == "__main__":
    main()
