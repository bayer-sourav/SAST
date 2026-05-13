"""Google Gemma 2 9B IT — Unsloth FastModel when available; else HF (same Unsloth Hub id).

Primary checkpoints: unsloth/gemma-2-9b-it-bnb-4bit (menu Y) and unsloth/gemma-2-9b-it (menu N).
Optional Unsloth 8-bit: menu N + export GEMMA_UNSLOTH_LOAD_8BIT=1 (bitsandbytes via FastModel).
Non–Unsloth formats (AWQ, GGUF, etc.) are out of scope for this runner.
"""

from __future__ import annotations

import importlib.util
import os

import torch
from langchain_core.tools import BaseTool

from core.gpu_info import cuda_error_suggests_poisoned_context
from core.parsing import parse_tool_selection
from core.prompts import fold_system_into_user_for_gemma2, tool_selection_chat_messages

_DEFAULT_UNSLOTH_4BIT = "unsloth/gemma-2-9b-it-bnb-4bit"
_DEFAULT_UNSLOTH_FP = "unsloth/gemma-2-9b-it"


def _hf_model_id(*, use_4bit: bool) -> str:
    env = os.environ.get("GEMMA_2_9B_MODEL_ID")
    if env is not None and env.strip() != "":
        return env.strip()
    return _unsloth_model_id(use_4bit=use_4bit)


def _unsloth_importable() -> bool:
    if importlib.util.find_spec("unsloth") is None:
        return False
    return torch.cuda.is_available()


def _unsloth_model_id(*, use_4bit: bool) -> str:
    if use_4bit:
        return os.environ.get("GEMMA_2_9B_UNSLOTH_BNB_MODEL_ID", _DEFAULT_UNSLOTH_4BIT)
    return os.environ.get("GEMMA_2_9B_UNSLOTH_FP_MODEL_ID", _DEFAULT_UNSLOTH_FP)


def generate_tool_selection_raw(
    user_message: str,
    tools: list[BaseTool],
    *,
    use_4bit: bool = True,
) -> str:
    hf_id = _hf_model_id(use_4bit=use_4bit)
    messages = fold_system_into_user_for_gemma2(
        tool_selection_chat_messages(tools, user_message)
    )
    unsloth_failed = False

    if _unsloth_importable():
        try:
            from core.gemma3_unsloth_backend import gemma3_unsloth_generate_from_messages

            return gemma3_unsloth_generate_from_messages(
                cache_key="gemma2_9b_unsloth",
                model_name=_unsloth_model_id(use_4bit=use_4bit),
                messages=messages,
                use_4bit=use_4bit,
            )
        except ImportError as exc:
            print(f"[Gemma 2 9B] Unsloth unavailable ({exc}); using Hugging Face.")
            unsloth_failed = True
        except Exception as exc:
            print(f"[Gemma 2 9B] Unsloth failed ({exc!r}).")
            es = str(exc).lower()
            if torch.cuda.is_available() and cuda_error_suggests_poisoned_context(exc):
                print(
                    "[Gemma 2 9B] CUDA context is invalid after this error. HF fallback will almost "
                    "always fail the same way in this process.\n"
                    "  → Exit and run `python3 main.py` again. If it still asserts: lower "
                    "`GEMMA_UNSLOTH_MAX_PROMPT_TOKENS`, `GEMMA_UNSLOTH_MAX_SEQ_LEN`, or "
                    "`AGENT_MAX_NEW_TOKENS`; try 4-bit off (answer N at the quantization prompt); or use HF "
                    "after a clean restart."
                )
                raise RuntimeError(
                    "CUDA context invalid after Gemma Unsloth device-side assert; restart Python before HF or GPU."
                ) from exc
            print("[Gemma 2 9B] Falling back to Hugging Face.")
            unsloth_failed = True
            if "429" in es or "too many requests" in es:
                print(
                    "[Gemma 2 9B] Hub rate limit (429). Wait a few minutes, set HF_TOKEN / "
                    "`huggingface-cli login`, and avoid parallel downloads."
                )
            if "cuda" in es or "device-side" in es or "index" in es:
                print(
                    "[Gemma 2 9B] Tip: CUDA index asserts often follow a prompt that is too long for the "
                    "FastModel canvas — try GEMMA_UNSLOTH_MAX_PROMPT_TOKENS=2048, GEMMA_UNSLOTH_MAX_SEQ_LEN=4096, "
                    "AGENT_MAX_NEW_TOKENS=512, or 4-bit off (N). Restart Python after any assert."
                )
    elif importlib.util.find_spec("unsloth") is None:
        print("[Gemma 2 9B] Package `unsloth` not found; using Hugging Face.")
    else:
        print(
            "[Gemma 2 9B] CUDA unavailable (driver / torch mismatch or no GPU); "
            "Unsloth skipped — using Hugging Face."
        )

    if unsloth_failed:
        print(f"[Gemma 2 9B] HF fallback loading {hf_id!r} (set GEMMA_2_9B_MODEL_ID to override).")
        if hf_id.startswith("google/"):
            print(
                "[Gemma 2 9B] google/* checkpoints are gated — use `huggingface-cli login` and accept "
                "the license, or unset GEMMA_2_9B_MODEL_ID to use the default Unsloth Hub id."
            )

    from core.hf_backend import hf_generate_from_messages

    return hf_generate_from_messages(
        hf_id,
        cache_key="gemma2_9b_hf_fallback",
        messages=messages,
        use_4bit=use_4bit,
    )


def run_tool_selection(
    user_message: str,
    tools: list[BaseTool],
    *,
    use_4bit: bool = True,
) -> dict:
    raw = generate_tool_selection_raw(user_message, tools, use_4bit=use_4bit)
    return parse_tool_selection(raw).model_dump()
