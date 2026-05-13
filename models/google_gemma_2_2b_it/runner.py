"""Google Gemma 2 2B IT — Unsloth FastModel when available; else HF.

Defaults: unsloth/gemma-2-2b-it-bnb-4bit (Y) and unsloth/gemma-2-2b-it (N).
Override: GEMMA_2_2B_MODEL_ID, GEMMA_2_2B_UNSLOTH_BNB_MODEL_ID, GEMMA_2_2B_UNSLOTH_FP_MODEL_ID.
"""

from __future__ import annotations

import importlib.util
import os

import torch
from langchain_core.tools import BaseTool

from core.gpu_info import cuda_error_suggests_poisoned_context
from core.parsing import parse_tool_selection
from core.prompts import fold_system_into_user_for_gemma2, tool_selection_chat_messages

_DEFAULT_UNSLOTH_4BIT = "unsloth/gemma-2-2b-it-bnb-4bit"
_DEFAULT_UNSLOTH_FP = "unsloth/gemma-2-2b-it"


def _hf_model_id(*, use_4bit: bool) -> str:
    env = os.environ.get("GEMMA_2_2B_MODEL_ID")
    if env is not None and env.strip() != "":
        return env.strip()
    return _unsloth_model_id(use_4bit=use_4bit)


def _unsloth_importable() -> bool:
    if importlib.util.find_spec("unsloth") is None:
        return False
    return torch.cuda.is_available()


def _unsloth_model_id(*, use_4bit: bool) -> str:
    if use_4bit:
        return os.environ.get("GEMMA_2_2B_UNSLOTH_BNB_MODEL_ID", _DEFAULT_UNSLOTH_4BIT)
    return os.environ.get("GEMMA_2_2B_UNSLOTH_FP_MODEL_ID", _DEFAULT_UNSLOTH_FP)


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
                cache_key="gemma2_2b_unsloth",
                model_name=_unsloth_model_id(use_4bit=use_4bit),
                messages=messages,
                use_4bit=use_4bit,
            )
        except ImportError as exc:
            print(f"[Gemma 2 2B] Unsloth unavailable ({exc}); using Hugging Face.")
            unsloth_failed = True
        except Exception as exc:
            print(f"[Gemma 2 2B] Unsloth failed ({exc!r}).")
            es = str(exc).lower()
            if torch.cuda.is_available() and cuda_error_suggests_poisoned_context(exc):
                print(
                    "[Gemma 2 2B] CUDA context is invalid after this error. "
                    "  → Exit and run `python3 main.py` again."
                )
                raise RuntimeError(
                    "CUDA context invalid after Gemma Unsloth device-side assert; restart Python before HF or GPU."
                ) from exc
            print("[Gemma 2 2B] Falling back to Hugging Face.")
            unsloth_failed = True
            if "429" in es or "too many requests" in es:
                print("[Gemma 2 2B] Hub rate limit (429). Wait, set HF_TOKEN, avoid parallel downloads.")
            if "cuda" in es or "device-side" in es or "index" in es:
                print(
                    "[Gemma 2 2B] Tip: try GEMMA_UNSLOTH_MAX_PROMPT_TOKENS=2048, "
                    "GEMMA_UNSLOTH_MAX_SEQ_LEN=4096, AGENT_MAX_NEW_TOKENS=512, or 4-bit off (N)."
                )
    elif importlib.util.find_spec("unsloth") is None:
        print("[Gemma 2 2B] Package `unsloth` not found; using Hugging Face.")
    else:
        print("[Gemma 2 2B] CUDA unavailable; Unsloth skipped — using Hugging Face.")

    if unsloth_failed:
        print(f"[Gemma 2 2B] HF fallback loading {hf_id!r} (set GEMMA_2_2B_MODEL_ID to override).")
        if hf_id.startswith("google/"):
            print(
                "[Gemma 2 2B] google/* checkpoints are gated — use `huggingface-cli login` and accept "
                "the license on the model card."
            )

    from core.hf_backend import hf_generate_from_messages

    return hf_generate_from_messages(
        hf_id,
        cache_key="gemma2_2b_hf_fallback",
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
