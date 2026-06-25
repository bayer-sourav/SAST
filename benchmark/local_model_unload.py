"""Release in-process GPU weights between benchmark cells (best-effort)."""

from __future__ import annotations

import gc
import sys
from pathlib import Path


def release_gpu_memory(*, verbose: bool = False) -> None:
    """Drop cached local models so the next cell/profile can allocate cleanly."""
    sast_root = Path(__file__).resolve().parent.parent
    if str(sast_root) not in sys.path:
        sys.path.insert(0, str(sast_root))

    def _step(label: str, fn) -> None:
        try:
            fn()
            if verbose:
                print(f"[gpu cleanup] {label}", flush=True)
        except Exception as exc:
            if verbose:
                print(f"[gpu cleanup] {label} skipped: {exc}", flush=True)

    _step("qwen", lambda: __import__("models.qwen.runner", fromlist=["unload_qwen"]).unload_qwen())
    _step(
        "vllm workers",
        lambda: __import__(
            "models.qwen.vllm_backend", fromlist=["kill_vllm_workers"]
        ).kill_vllm_workers(),
    )
    _step(
        "gpt-oss unsloth",
        lambda: __import__(
            "models.open_ai_gpt_oss_20B.runner", fromlist=["unload_gpt_oss_unsloth"]
        ).unload_gpt_oss_unsloth(),
    )
    try:
        from core.gemma3_unsloth_backend import clear_gemma3_unsloth_cache

        _step("gemma unsloth", clear_gemma3_unsloth_cache)
    except ImportError:
        pass
    _step("hf cache", lambda: __import__("core.hf_backend", fromlist=["clear_hf_cache"]).clear_hf_cache())

    try:
        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.synchronize()
            if verbose:
                free = torch.cuda.mem_get_info()[0] / (1024**3)
                print(f"[gpu cleanup] cuda empty_cache ok (~{free:.1f} GiB free)", flush=True)
    except Exception:
        pass
