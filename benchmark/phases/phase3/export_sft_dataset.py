#!/usr/bin/env python3
"""Export BenchmarkJava train/val splits as chat JSONL for LoRA SFT."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.build_phase2_corpora import _dataset_root  # noqa: E402
from benchmark.make_task import DEFAULT_OUTPUT_SCHEMA, build_task_markdown, stable_case_id  # noqa: E402
from benchmark.run_llm_local import _SYSTEM_PROMPT  # noqa: E402

_TRACKS = (
    ("fp", "FP"),
    ("tp", "TP"),
    ("borderline", "BL"),
)


def _split_entries(manifest: dict, split: str) -> list[dict]:
    needle = f"/{split}/"
    rows = []
    for row in manifest.get("cases") or []:
        bundle = str(row.get("bundle", ""))
        if needle in bundle.replace("\\", "/"):
            rows.append(row)
    return sorted(rows, key=lambda r: r["case_id"])


def _phase2_test_ids_by_track(sast_root: Path) -> dict[str, set[str]]:
    manifest_path = sast_root / "benchmark/phases/phase2/MANIFEST.json"
    if not manifest_path.is_file():
        return {"fp": set(), "tp": set(), "borderline": set()}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    tracks = data.get("tracks") or {}
    return {
        "fp": set((tracks.get("fp") or {}).get("case_ids") or []),
        "tp": set((tracks.get("tp") or {}).get("case_ids") or []),
        "borderline": set((tracks.get("borderline") or {}).get("case_ids") or []),
    }


def _gold_label(track: str) -> str:
    for cls, label in _TRACKS:
        if cls == track:
            return label
    raise ValueError(f"unknown track {track!r}")


def _first_evidence(case: dict[str, Any]) -> list[dict[str, str]]:
    rel = str(case.get("file") or "unknown.java")
    raw = case.get("raw_output") or {}
    alerts = raw.get("CodeQL") if isinstance(raw, dict) else None
    lines = "unknown"
    if isinstance(alerts, list) and alerts:
        locs = alerts[0].get("locations") or []
        if locs:
            region = (locs[0].get("physicalLocation") or {}).get("region") or {}
            start = region.get("startLine")
            end = region.get("endLine", start)
            if start is not None:
                lines = f"L{start}" if end in (None, start) else f"L{start}-L{end}"
    return [{"file": rel, "lines": lines, "note": "gold-label training target"}]


def _assistant_json(*, case_id: str, label: str, case: dict[str, Any]) -> str:
    payload = {
        "label": label,
        "confidence": "high",
        "confidence_score": 0.95,
        "reason": f"Gold {label} label for training (dataset supervision).",
        "evidence": _first_evidence(case),
        "agent": "llm",
        "case_id": case_id,
    }
    # Validate keys match schema expectation
    for key in DEFAULT_OUTPUT_SCHEMA:
        if key not in payload:
            raise KeyError(f"missing key {key!r} in training target")
    return json.dumps(payload, ensure_ascii=False)


def _build_record(
    *,
    bundle_dir: Path,
    gold_label: str,
    few_shot: int,
    few_shot_config: str | None,
    prompt_version: str,
) -> dict[str, Any]:
    case_path = bundle_dir / "case.json"
    case = json.loads(case_path.read_text(encoding="utf-8"))
    case_id = stable_case_id(case)
    repo_root = bundle_dir.resolve()
    task_text = build_task_markdown(
        case=case,
        repo_root=repo_root,
        scan_root=case.get("scan_root") or ".",
        agent="llm",
        few_shot=few_shot,
        few_shot_config=few_shot_config,
        prompt_version=prompt_version,
    )
    assistant = _assistant_json(case_id=case_id, label=gold_label, case=case)
    return {
        "case_id": case_id,
        "gold_label": gold_label,
        "bundle": str(bundle_dir),
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": task_text},
            {"role": "assistant", "content": assistant},
        ],
    }


def export_split(
    *,
    dataset: Path,
    split: str,
    out_path: Path,
    few_shot: int,
    few_shot_config: str | None,
    prompt_version: str,
    max_per_class: int | None,
    test_ids_by_track: dict[str, set[str]],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    stats: dict[str, int] = {}
    leaks: list[str] = []

    for cls, _ in _TRACKS:
        mpath = dataset / cls / "manifest.json"
        entries = _split_entries(json.loads(mpath.read_text(encoding="utf-8")), split)
        if max_per_class is not None:
            entries = entries[:max_per_class]
        stats[cls] = len(entries)
        track_test = test_ids_by_track.get(cls) or set()
        for row in entries:
            cid = row["case_id"]
            if cid in track_test:
                leaks.append(f"{cls}:{cid}")
            bundle = (dataset / row["bundle"]).resolve()
            rec = _build_record(
                bundle_dir=bundle,
                gold_label=_gold_label(cls),
                few_shot=few_shot,
                few_shot_config=few_shot_config,
                prompt_version=prompt_version,
            )
            records.append(rec)

    if leaks:
        raise ValueError(
            f"{split} export overlaps Phase 2 test on same track ({len(leaks)}): {leaks[:10]}..."
        )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    meta = {
        "split": split,
        "n_records": len(records),
        "per_class": stats,
        "out_path": str(out_path),
        "few_shot": few_shot,
        "prompt_version": prompt_version,
    }
    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dataset-root", type=Path, default=None)
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=_sast / "runs/phase3/stage3a/data",
    )
    ap.add_argument(
        "--split",
        choices=("train", "validation", "both"),
        default="both",
    )
    ap.add_argument("--few-shot", type=int, default=0)
    ap.add_argument("--few-shot-config", default=None)
    ap.add_argument("--prompt-version", default="v7-balanced")
    ap.add_argument(
        "--max-per-class",
        type=int,
        default=None,
        help="Limit cases per class (smoke export).",
    )
    args = ap.parse_args()

    dataset = _dataset_root(args.dataset_root)
    out_dir = args.out_dir.expanduser().resolve()
    test_ids_by_track = _phase2_test_ids_by_track(_sast)

    splits = ["train", "validation"] if args.split == "both" else [args.split]
    for split in splits:
        suffix = "_smoke" if args.max_per_class else ""
        out_path = out_dir / f"sft_{split}{suffix}.jsonl"
        meta = export_split(
            dataset=dataset,
            split=split,
            out_path=out_path,
            few_shot=args.few_shot,
            few_shot_config=args.few_shot_config,
            prompt_version=args.prompt_version,
            max_per_class=args.max_per_class,
            test_ids_by_track=test_ids_by_track,
        )
        print(f"[export] {split}: {meta['n_records']} records -> {out_path}")


if __name__ == "__main__":
    main()
