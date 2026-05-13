"""Google Gemma 3 12B IT — Unsloth FastModel when available; else HF ImageTextToText.

Branch experiment/gemma3-system-user: passes separate system + user chat roles (no fold).
For the folded prompt (one user turn), use experiment/compact-prompt-json instead.

Speed (Unsloth): set GEMMA_UNSLOTH_USE_CACHE=1 (not GEMMA_UNSLOTH_CACHE) when your stack is stable;
see core/gemma3_unsloth_backend.py and eval/gemma3_12b_speed_notes.txt.
"""

from __future__ import annotations

import importlib.util
import os

import torch
from langchain_core.tools import BaseTool

from core.gpu_info import cuda_error_suggests_poisoned_context
from core.parsing import parse_tool_selection
from core.prompts import tool_selection_chat_messages

# Supported Gemma 3 checkpoints for this harness = Unsloth Hub ids below (FastModel). HF fallback uses
# the same ids when Unsloth is unavailable. AWQ / QAT-only / GGUF checkpoints are not Unsloth FastModel
# targets here — use Unsloth’s bnb-4bit or -it repos only unless you override with a compatible Hub id.
_DEFAULT_UNSLOTH_4BIT = "unsloth/gemma-3-12b-it-unsloth-bnb-4bit"
# Must match the **IT** instruct checkpoint (same family as the 4-bit repo above). `unsloth/gemma-3-12b`
# (no `-it`) is a different / missing Hub id and makes FastModel fail with "No config file found".
_DEFAULT_UNSLOTH_FP = "unsloth/gemma-3-12b-it"


def _hf_model_id(*, use_4bit: bool) -> str:
    env = os.environ.get("GEMMA_3_12B_MODEL_ID")
    if env is not None and env.strip() != "":
        return env.strip()
    return _unsloth_model_id(use_4bit=use_4bit)


def _unsloth_importable() -> bool:
    # Package on disk is not enough: unsloth raises if CUDA is unavailable at import time.
    if importlib.util.find_spec("unsloth") is None:
        return False
    return torch.cuda.is_available()


def _unsloth_model_id(*, use_4bit: bool) -> str:
    if use_4bit:
        return os.environ.get("GEMMA_3_12B_UNSLOTH_BNB_MODEL_ID", _DEFAULT_UNSLOTH_4BIT)
    return os.environ.get("GEMMA_3_12B_UNSLOTH_FP_MODEL_ID", _DEFAULT_UNSLOTH_FP)


def _unsloth_max_seq_length() -> int | None:
    """Optional tighter canvas for 12B only; falls back to GEMMA_UNSLOTH_MAX_SEQ_LEN in backend."""
    raw = os.environ.get("GEMMA_3_12B_UNSLOTH_MAX_SEQ_LEN", "").strip()
    if raw:
        return int(raw)
    return None


def generate_tool_selection_raw(
    user_message: str,
    tools: list[BaseTool],
    *,
    use_4bit: bool = True,
) -> str:
    hf_id = _hf_model_id(use_4bit=use_4bit)
    # Native system + user (like Qwen). Folded single-user turn lives on experiment/compact-prompt-json.
    messages = tool_selection_chat_messages(tools, user_message)
    unsloth_failed = False

    if _unsloth_importable():
        try:
            from core.gemma3_unsloth_backend import gemma3_unsloth_generate_from_messages

            return gemma3_unsloth_generate_from_messages(
                cache_key="gemma3_12b_unsloth",
                model_name=_unsloth_model_id(use_4bit=use_4bit),
                messages=messages,
                use_4bit=use_4bit,
                max_seq_length=_unsloth_max_seq_length(),
            )
        except ImportError as exc:
            print(f"[Gemma 3 12B] Unsloth unavailable ({exc}); using Hugging Face.")
            unsloth_failed = True
        except Exception as exc:
            print(f"[Gemma 3 12B] Unsloth failed ({exc!r}).")
            es = str(exc).lower()
            if torch.cuda.is_available() and cuda_error_suggests_poisoned_context(exc):
                print(
                    "[Gemma 3 12B] CUDA context is invalid after this error. Hugging Face fallback will almost "
                    "always fail the same way in this process.\n"
                    "  → Exit and run `python3 main.py` again. Prefer Gemma 2 (default Gemma menu) or HF. "
                    "If you stay on 12B: lower `GEMMA_UNSLOTH_MAX_PROMPT_TOKENS`, "
                    "`GEMMA_3_12B_UNSLOTH_MAX_SEQ_LEN` / `GEMMA_UNSLOTH_MAX_SEQ_LEN`, or `AGENT_MAX_NEW_TOKENS`; "
                    "try Y↔N (fp); keep `GEMMA_UNSLOTH_USE_CACHE=0` (default) or set `=1` if stable; "
                    "or use HF after a clean restart."
                )
                raise RuntimeError(
                    "CUDA context invalid after Gemma Unsloth device-side assert; restart Python before HF or GPU."
                ) from exc
            print("[Gemma 3 12B] Falling back to Hugging Face.")
            unsloth_failed = True
            if "429" in es or "too many requests" in es:
                print(
                    "[Gemma 3 12B] Hub rate limit (429). Wait a few minutes, set HF_TOKEN / "
                    "`huggingface-cli login`, and avoid parallel downloads. HF fallback may hit the same limit."
                )
            if "cuda" in es or "device-side" in es or "index" in es:
                print(
                    "[Gemma 3 12B] Tip: CUDA index asserts on Unsloth FastModel are common for 12B — use Gemma 2 "
                    "or HF. If you persist: GEMMA_3_12B_UNSLOTH_MAX_SEQ_LEN=2048, tighter prompt caps, "
                    "GEMMA_UNSLOTH_DEBUG=1, Y↔N. Restart Python after any assert."
                )
    elif importlib.util.find_spec("unsloth") is None:
        print("[Gemma 3 12B] Package `unsloth` not found; using Hugging Face.")
    else:
        print(
            "[Gemma 3 12B] CUDA unavailable (driver / torch mismatch or no GPU); "
            "Unsloth skipped — using Hugging Face."
        )

    if unsloth_failed:
        print(f"[Gemma 3 12B] HF fallback loading {hf_id!r} (set GEMMA_3_12B_MODEL_ID to override).")
        if hf_id.startswith("google/"):
            print(
                "[Gemma 3 12B] google/* checkpoints are gated — use `huggingface-cli login` and accept "
                "the license, or unset GEMMA_3_12B_MODEL_ID to use the default Unsloth Hub id."
            )

    from core.gemma3_hf_backend import gemma3_generate_from_messages

    return gemma3_generate_from_messages(
        hf_id,
        cache_key="gemma3_12b_it",
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
