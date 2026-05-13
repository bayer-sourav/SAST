"""Small helpers to log whether CUDA is visible and which device tensors should use."""

from __future__ import annotations

import torch


def log_gpu_status(prefix: str = "") -> None:
    p = f"{prefix} " if prefix else ""
    print(f"[GPU] {p}torch.cuda.is_available()={torch.cuda.is_available()}")
    if torch.cuda.is_available():
        try:
            name = torch.cuda.get_device_name(0)
            cap = torch.cuda.get_device_capability(0)
            mem_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
            print(f"[GPU] {p}device0={name!r} capability={cap} total_mem_GB~{mem_gb:.1f}")
        except Exception as exc:  # noqa: BLE001
            print(f"[GPU] {p}could not read device details: {exc}")
    else:
        print(f"[GPU] {p}Running on CPU (no CUDA device).")
        built_cuda = getattr(torch.version, "cuda", None)
        if built_cuda:
            print(
                f"[GPU] {p}This PyTorch build targets CUDA {built_cuda}. "
                "If `nvidia-smi` shows a GPU but PyTorch says the driver is too old, your "
                "torch wheel expects a newer driver than this machine has — reinstall torch and "
                "torchvision from https://pytorch.org/ using a *lower* CUDA tag (e.g. cu121 or cu124 "
                "for AWS g5 / driver 535), then restart Python."
            )


def primary_cuda_device() -> torch.device:
    if torch.cuda.is_available():
        return torch.device("cuda:0")
    return torch.device("cpu")


def cuda_error_suggests_poisoned_context(exc: BaseException) -> bool:
    """
    After a device-side assert, further CUDA calls in the same process often fail until Python exits.
    empty_cache / synchronize cannot repair this.
    """
    s = str(exc).lower()
    if "device-side assert" in s:
        return True
    return "cuda error" in s and "assert" in s
