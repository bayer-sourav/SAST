#!/usr/bin/env python3
"""Run Stage 2 teacher (Qwen3.5-9B fs3 CoT) on BenchmarkJava train split for distillation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.phases.phase3._phase3b_common import load_manifest, output_path, sast_root  # noqa: E402
from benchmark.phases.phase3.build_split_corpus import build_split_corpus  # noqa: E402
from benchmark.build_phase2_corpora import _dataset_root  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", choices=("train",), default="train")
    ap.add_argument("--max-per-class", type=int, default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--smoke-max", type=int, default=0, help="Max cases per track (smoke).")
    args = ap.parse_args()

    manifest = load_manifest()
    tcfg = manifest["teacher"]
    profile = tcfg["profile"]
    prompt = tcfg["prompt_version"]
    fs = tcfg["fewshot"]
    fs_config = tcfg["few_shot_config"]

    corpus_root = output_path(manifest, "teacher_cache").parent / "corpora" / args.split
    max_pc = args.max_per_class
    if args.smoke_max > 0:
        max_pc = args.smoke_max

    build_split_corpus(
        dataset=_dataset_root(None),
        split=args.split,
        out_root=corpus_root,
        max_per_class=max_pc,
    )

    teacher_root = output_path(manifest, "teacher_cache")
    log_dir = output_path(manifest, "summaries").parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"teacher_{args.split}.log"

    env = os.environ.copy()
    env["SAST_PROMPT_VERSION"] = prompt

    tracks = (
        ("fp", "FP", corpus_root / "fp"),
        ("tp", "TP", corpus_root / "tp"),
        ("borderline", "BL", corpus_root / "borderline"),
    )

    print(f"[teacher] profile={profile} prompt={prompt} fs={fs} split={args.split}", flush=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n=== teacher {args.split} start ===\n")

    for track, gold, case_dir in tracks:
        runs_root = teacher_root / track
        cmd = [
            sys.executable,
            str(_sast / "benchmark/run_batch.py"),
            "--agent",
            "llm",
            "--profile",
            profile,
            "--case-dir",
            str(case_dir),
            "--runs-root",
            str(runs_root / f"thinking_on/fewshot_{fs}"),
            "--gold",
            gold,
            "--thinking",
            "--few-shot",
            str(fs),
            "--few-shot-config",
            fs_config,
            "--prompt-version",
            prompt,
            "--retry-missing",
        ]
        if args.force:
            cmd.append("--force")
        print(f"[teacher] track={gold} cases={len(list(case_dir.glob('*.json')))}", flush=True)
        proc = subprocess.run(cmd, cwd=str(_sast), env=env, check=False)
        with log_path.open("a", encoding="utf-8") as log:
            log.write(f"track={gold} exit={proc.returncode}\n")
        if proc.returncode != 0:
            raise SystemExit(f"teacher batch failed for track {gold} (exit {proc.returncode})")

    meta = {
        "split": args.split,
        "profile": profile,
        "prompt_version": prompt,
        "fewshot": fs,
        "few_shot_config": fs_config,
        "teacher_root": str(teacher_root),
        "corpus_root": str(corpus_root),
    }
    meta_path = teacher_root / f"teacher_{args.split}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[teacher] done -> {teacher_root}")


if __name__ == "__main__":
    main()
