#!/usr/bin/env python3
"""Assert qwen3_8_27b_nvfp4 is wired (no GPU). Fail if the profile mapping breaks."""

from __future__ import annotations

import os
import sys
from pathlib import Path

SAST = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SAST))
os.chdir(SAST)

from benchmark.llm_generate import QWEN_PROFILES, profile_family
from models.qwen.runner import QWEN3_PROFILES, _resolve_ids
from models.qwen.vllm_backend import NVFP4_PROFILES, _vllm_model_id, gpu_supports_nvfp4, should_use_vllm


def main() -> None:
    p = "qwen3_8_27b_nvfp4"
    assert p in QWEN_PROFILES
    assert p in QWEN3_PROFILES
    assert p in NVFP4_PROFILES
    assert profile_family(p) == "qwen"
    u, h = _resolve_ids(p)
    assert u == "unsloth/Qwen3.8-27B"
    assert h == "Qwen/Qwen3.8-27B"
    os.environ.pop("QWEN_VLLM_MODEL_ID", None)
    os.environ.pop("QWEN_QWEN3_8_27B_NVFP4_VLLM_MODEL_ID", None)
    assert _vllm_model_id(p) == "unsloth/Qwen3.8-27B-NVFP4"
    os.environ["QWEN_INFER_BACKEND"] = "vllm"
    if not gpu_supports_nvfp4():
        assert should_use_vllm(p) is False
        # An Ada-compatible checkpoint must still be allowed through on the same profile.
        os.environ["QWEN_QWEN3_8_27B_NVFP4_VLLM_MODEL_ID"] = "Qwen/Qwen3.8-27B-FP8"
        assert should_use_vllm(p) is True
        os.environ.pop("QWEN_QWEN3_8_27B_NVFP4_VLLM_MODEL_ID", None)
    os.environ["QWEN_INFER_BACKEND"] = "unsloth"
    assert should_use_vllm(p) is False
    print("qwen3_8_27b_nvfp4 profile OK", flush=True)


if __name__ == "__main__":
    main()
