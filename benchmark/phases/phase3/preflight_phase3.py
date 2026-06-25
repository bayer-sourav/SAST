#!/usr/bin/env python3
"""Phase 3 preflight: dataset counts, leakage, SFT/distill export presence."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.build_phase2_corpora import _dataset_root  # noqa: E402
from benchmark.few_shot import assert_no_test_leakage, resolve_few_shot_config_path  # noqa: E402
from benchmark.phases.phase3._phase3b_common import load_manifest, output_path  # noqa: E402
from benchmark.phases.phase3.export_sft_dataset import _phase2_test_ids_by_track, _split_entries  # noqa: E402


def _check_dataset(test_by_track: dict[str, set[str]]) -> None:
    dataset = _dataset_root(None)
    all_test_ids = set().union(*test_by_track.values())
    for cls in ("fp", "tp", "borderline"):
        mdata = json.loads((dataset / cls / "manifest.json").read_text(encoding="utf-8"))
        for split, expected in (("train", 500), ("validation", 200), ("test", 200)):
            n = len(_split_entries(mdata, split))
            if n != expected:
                print(f"[warn] {cls}/{split}: expected {expected}, got {n}", file=sys.stderr)
            else:
                print(f"[preflight] {cls}/{split}: {n} cases OK")

        train_ids = {r["case_id"] for r in _split_entries(mdata, "train")}
        test_ids = {r["case_id"] for r in _split_entries(mdata, "test")}
        intra = train_ids & test_ids
        if intra:
            raise SystemExit(f"{cls} train/test overlap in dataset: {sorted(intra)[:20]}")
        phase2_overlap = train_ids & (test_by_track.get(cls) or set())
        if phase2_overlap:
            raise SystemExit(
                f"{cls} train overlaps Phase 2 {cls} test: {sorted(phase2_overlap)[:20]}"
            )
        print(f"[preflight] {cls} train vs test / Phase 2 eval: disjoint OK")


def preflight_3a(manifest: dict) -> None:
    fs_cfg = manifest["inference_eval"]["few_shot_config"]
    test_by_track = _phase2_test_ids_by_track(_sast)
    assert_no_test_leakage(
        test_case_ids=set().union(*test_by_track.values()),
        config_path=resolve_few_shot_config_path(fs_cfg),
    )
    print(f"[preflight] few-shot vs Phase 2 test: OK ({len(set().union(*test_by_track.values()))} test ids)")
    _check_dataset(test_by_track)

    data_dir = _sast / manifest["outputs"]["sft_data"]
    train_jsonl = data_dir / "sft_train.jsonl"
    if train_jsonl.is_file():
        n = sum(1 for _ in train_jsonl.open(encoding="utf-8"))
        exp = manifest["dataset"]["sft_n_expected"]
        if n != exp:
            print(f"[warn] sft_train.jsonl: expected {exp}, got {n}", file=sys.stderr)
        else:
            print(f"[preflight] sft_train.jsonl: {n} records OK")
    else:
        print("[preflight] sft_train.jsonl not found (run export_sft_dataset.py)")
    print("[preflight] Phase 3A checks passed")


def preflight_3b(manifest: dict) -> None:
    fs_cfg = manifest["train_prompt"]["few_shot_config"]
    test_by_track = _phase2_test_ids_by_track(_sast)
    assert_no_test_leakage(
        test_case_ids=set().union(*test_by_track.values()),
        config_path=resolve_few_shot_config_path(fs_cfg),
    )
    print(f"[preflight] few-shot vs Phase 2 test: OK")
    _check_dataset(test_by_track)

    distill = output_path(manifest, "sft_data") / "distill_train.jsonl"
    if distill.is_file():
        n = sum(1 for _ in distill.open(encoding="utf-8"))
        print(f"[preflight] distill_train.jsonl: {n} records")
        meta_path = distill.with_suffix(".meta.json")
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            print(f"[preflight] distill stats: {meta.get('stats')}")
    else:
        print("[preflight] distill_train.jsonl not found (run export_distill_dataset.py after teacher)")

    print("[preflight] Phase 3B checks passed")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", choices=("3a", "3b"), default="3a")
    args = ap.parse_args()

    if args.stage == "3b":
        manifest = load_manifest(_sast / "benchmark/phases/phase3/stage3b/MANIFEST.json")
        preflight_3b(manifest)
    else:
        manifest = json.loads((_sast / "benchmark/phases/phase3/MANIFEST.json").read_text(encoding="utf-8"))
        preflight_3a(manifest)


if __name__ == "__main__":
    main()
