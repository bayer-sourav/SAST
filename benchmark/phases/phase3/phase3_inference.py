"""Shared Phase 3B inference env and vLLM-only guards for val/test eval."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def vllm_env_for_adapter(adapter: Path) -> dict[str, str]:
    """Build subprocess env: merged BF16 weights + vLLM backend (no runtime PEFT LoRA)."""
    from benchmark.phases.phase3.export_lora_for_vllm import ensure_vllm_merged_adapter

    env = os.environ.copy()
    merged_dir = ensure_vllm_merged_adapter(adapter)
    env["QWEN_INFER_BACKEND"] = "vllm"
    env["QWEN_VLLM_MODEL_ID"] = str(merged_dir.resolve())
    env["QWEN_VLLM_USE_LORA"] = "0"
    env["SAST_REQUIRE_VLLM"] = "1"
    env.pop("SAST_LORA_ADAPTER", None)
    return env


def require_vllm_for_eval(profile: str) -> None:
    """Fail fast when Phase 3 eval must use vLLM but backend is not vllm."""
    stage = os.environ.get("PHASE3_STAGE", "").strip()
    require = os.environ.get("SAST_REQUIRE_VLLM", "").strip().lower() in ("1", "true", "yes")
    if not require and stage != "3b":
        return

    from benchmark.llm_generate import QWEN_PROFILES
    from models.qwen.vllm_backend import infer_backend, should_use_vllm

    if profile not in QWEN_PROFILES:
        return
    if should_use_vllm(profile):
        return
    raise RuntimeError(
        f"Phase 3 eval requires vLLM for profile={profile!r} "
        f"but QWEN_INFER_BACKEND={infer_backend()!r}. "
        "Set QWEN_INFER_BACKEND=vllm and export merged LoRA via export_lora_for_vllm.py."
    )


def run_batch_tracks(
    tracks: list[dict[str, str]],
    *,
    env: dict[str, str] | None = None,
    sast_root: Path | None = None,
    profile: str,
    thinking: bool = True,
    few_shot: int,
    few_shot_config: str,
    prompt_version: str,
    retry_missing: bool = False,
    force: bool = False,
    max_cases: int | None = None,
) -> None:
    """Run FP/TP/BL (or any track list) in one process — single vLLM load."""
    root = (sast_root or Path(__file__).resolve().parents[3]).resolve()
    run_env = dict(env or os.environ)
    run_env.setdefault("PYTHONPATH", f"{root}:{root / 'benchmark'}")

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as tf:
        json.dump(tracks, tf, indent=2)
        tracks_path = Path(tf.name)

    cmd = [
        sys.executable,
        str(root / "benchmark/run_batch.py"),
        "--agent",
        "llm",
        "--profile",
        profile,
        "--tracks-json",
        str(tracks_path),
        "--few-shot",
        str(few_shot),
        "--few-shot-config",
        few_shot_config,
        "--prompt-version",
        prompt_version,
    ]
    if thinking:
        cmd.append("--thinking")
    if retry_missing:
        cmd.append("--retry-missing")
    if force:
        cmd.append("--force")
    if max_cases is not None:
        cmd.extend(["--max-cases", str(max_cases)])

    try:
        print(
            f"[infer] run_batch multi-track n={len(tracks)} profile={profile} "
            f"retry_missing={retry_missing}",
            flush=True,
        )
        subprocess.run(cmd, cwd=str(root), env=run_env, check=True)
    finally:
        tracks_path.unlink(missing_ok=True)
