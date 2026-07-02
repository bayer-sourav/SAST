#!/usr/bin/env python3
"""LoRA training disk hygiene + checkpoint helpers (vLLM merge cache, auto-resume)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

_CKPT_RE = re.compile(r"^checkpoint-\d+$")


def dir_size_bytes(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def free_gb(path: Path) -> float:
    return shutil.disk_usage(path.expanduser().resolve()).free / (1024**3)


def list_vllm_merged_dirs(lora_run_dir: Path) -> list[Path]:
    lora_run_dir = lora_run_dir.expanduser().resolve()
    return sorted(lora_run_dir.glob("checkpoint-*-vllm-merged"))


def prune_vllm_merged(lora_run_dir: Path, *, keep: Path | None = None) -> tuple[int, float]:
    """Delete stale ``checkpoint-*-vllm-merged`` trees (~17 GB each)."""
    lora_run_dir = lora_run_dir.expanduser().resolve()
    keep_resolved = keep.expanduser().resolve() if keep else None
    n = 0
    freed = 0.0
    for d in list_vllm_merged_dirs(lora_run_dir):
        if keep_resolved and d.resolve() == keep_resolved:
            continue
        if not d.is_dir():
            continue
        sz = dir_size_bytes(d)
        shutil.rmtree(d)
        n += 1
        freed += sz / (1024**3)
    if n:
        print(
            f"[disk] pruned {n} vllm-merged dir(s), freed {freed:.1f} GB under {lora_run_dir.name}",
            flush=True,
        )
    return n, freed


def ensure_disk_gb(
    path: Path,
    min_gb: float,
    *,
    lora_run_dir: Path | None = None,
) -> float:
    """Prune vLLM merge caches if low, then fail if still below ``min_gb``."""
    path = path.expanduser().resolve()
    free = free_gb(path)
    if free >= min_gb:
        return free
    if lora_run_dir is not None:
        prune_vllm_merged(lora_run_dir)
        free = free_gb(path)
    if free < min_gb:
        raise RuntimeError(
            f"disk free {free:.1f} GB on {path} < required {min_gb:.1f} GB "
            f"(set PHASE3_MIN_DISK_GB or free space / prune manually)"
        )
    print(f"[disk] free {free:.1f} GB after prune (required {min_gb:.1f} GB)", flush=True)
    return free


def training_checkpoints(lora_run_dir: Path) -> list[Path]:
    lora_run_dir = lora_run_dir.expanduser().resolve()
    ckpts = [p for p in lora_run_dir.glob("checkpoint-*") if _CKPT_RE.match(p.name)]
    return sorted(ckpts, key=lambda p: int(p.name.rsplit("-", 1)[-1]))


def latest_training_checkpoint(lora_run_dir: Path) -> Path | None:
    ckpts = training_checkpoints(lora_run_dir)
    return ckpts[-1] if ckpts else None


def checkpoint_step(ckpt: Path) -> int:
    return int(ckpt.name.rsplit("-", 1)[-1])


def expected_final_step(lora_run_dir: Path) -> int:
    """Target global_step when all training epochs are complete."""
    meta = lora_run_dir.expanduser().resolve() / "train_meta.json"
    if meta.is_file():
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            if data.get("target_global_step"):
                return int(data["target_global_step"])
        except Exception:
            pass
    env_target = os.environ.get("PHASE3_TARGET_STEPS", "").strip()
    if env_target:
        return int(env_target)
    return 1700


def training_finished(lora_run_dir: Path) -> bool:
    lora_run_dir = lora_run_dir.expanduser().resolve()
    if (lora_run_dir / "pending_css.json").is_file():
        return False
    meta_path = lora_run_dir / "train_meta.json"
    if not meta_path.is_file():
        return False
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not data.get("finished_at"):
        return False
    if data.get("status") == "paused_for_css":
        return False
    latest = latest_training_checkpoint(lora_run_dir)
    if latest is None:
        return False
    return checkpoint_step(latest) >= expected_final_step(lora_run_dir)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_prune = sub.add_parser("prune", help="Remove stale *-vllm-merged dirs")
    p_prune.add_argument("--lora-dir", type=Path, required=True)
    p_prune.add_argument("--keep", type=Path, default=None)

    p_latest = sub.add_parser("latest-checkpoint", help="Print latest checkpoint-N path")
    p_latest.add_argument("--lora-dir", type=Path, required=True)

    p_done = sub.add_parser("training-finished", help="Exit 0 if train_meta.json has finished_at")
    p_done.add_argument("--lora-dir", type=Path, required=True)

    p_disk = sub.add_parser("ensure-disk", help="Ensure minimum free GB (prune first)")
    p_disk.add_argument("--path", type=Path, default=Path("/"))
    p_disk.add_argument("--min-gb", type=float, default=25.0)
    p_disk.add_argument("--lora-dir", type=Path, default=None)

    args = ap.parse_args()
    if args.cmd == "prune":
        prune_vllm_merged(args.lora_dir, keep=args.keep)
    elif args.cmd == "latest-checkpoint":
        ckpt = latest_training_checkpoint(args.lora_dir)
        if ckpt is None:
            sys.exit(1)
        print(ckpt)
    elif args.cmd == "training-finished":
        sys.exit(0 if training_finished(args.lora_dir) else 1)
    elif args.cmd == "ensure-disk":
        ensure_disk_gb(args.path, args.min_gb, lora_run_dir=args.lora_dir)


if __name__ == "__main__":
    main()
