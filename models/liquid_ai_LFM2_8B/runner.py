"""LFM2-8B: Unsloth first, then Hugging Face Transformers."""

from __future__ import annotations

import os
from typing import Any

import torch
from langchain_core.tools import BaseTool

from core.generation_defaults import agent_decoding_kwargs
from core.gpu_info import log_gpu_status
from core.hf_backend import hf_generate_from_messages
from core.parsing import parse_tool_selection
from core.prompts import tool_selection_chat_messages

_DEFAULT_UNSLOTH = "unsloth/LFM2-8B-A1B"
_DEFAULT_HF = "LiquidAI/LFM2-8B-A1B"

_MODEL: Any = None
_TOKENIZER: Any = None
_LOADED_4BIT: bool | None = None


def unload_lfm2_8b_unsloth() -> None:
    global _MODEL, _TOKENIZER, _LOADED_4BIT
    _MODEL = None
    _TOKENIZER = None
    _LOADED_4BIT = None


def _hf_fallback_id() -> str:
    return os.environ.get("LFM2_HF_MODEL_ID") or os.environ.get(
        "LFM2_MODEL_ID", _DEFAULT_HF
    )


def _load_unsloth(*, use_4bit: bool) -> tuple[Any, Any]:
    global _MODEL, _TOKENIZER, _LOADED_4BIT
    if _MODEL is not None and _LOADED_4BIT == use_4bit:
        assert _TOKENIZER is not None
        return _MODEL, _TOKENIZER
    if _MODEL is not None:
        unload_lfm2_8b_unsloth()

    from unsloth import FastLanguageModel  # type: ignore[import-not-found]

    log_gpu_status("LFM2-8B Unsloth")
    model_id = os.environ.get("LFM2_UNSLOTH_MODEL_ID", _DEFAULT_UNSLOTH)
    max_seq = int(os.environ.get("LFM2_MAX_SEQ_LEN", "4096"))
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=model_id,
        max_seq_length=max_seq,
        dtype=None,
        load_in_4bit=use_4bit,
    )
    FastLanguageModel.for_inference(model)
    _MODEL, _TOKENIZER = model, tokenizer
    _LOADED_4BIT = use_4bit
    print(f"[LFM2-8B] Unsloth loaded model={model_id!r} load_in_4bit={use_4bit}")
    return model, tokenizer


def _generate_unsloth(messages: list[dict[str, str]], *, use_4bit: bool) -> str:
    model, tokenizer = _load_unsloth(use_4bit=use_4bit)
    prompt = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    device = next(model.parameters()).device
    print(f"[GPU] LFM2-8B generate: first param device={device}")
    inputs = tokenizer(prompt, return_tensors="pt").to(device)
    gen_kwargs = agent_decoding_kwargs()
    with torch.inference_mode():
        out = model.generate(**inputs, **gen_kwargs)
    input_len = inputs["input_ids"].shape[1]
    new_tokens = out[0][input_len:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


def generate_tool_selection_raw(
    user_message: str,
    tools: list[BaseTool],
    *,
    use_4bit: bool = True,
) -> str:
    messages = tool_selection_chat_messages(tools, user_message)
    try:
        return _generate_unsloth(messages, use_4bit=use_4bit)
    except ImportError:
        print("[LFM2-8B] unsloth not installed; using Hugging Face Transformers.")
    except Exception as exc:  # noqa: BLE001
        print(f"[LFM2-8B] Unsloth failed ({exc}); using Hugging Face Transformers.")
    model_id = _hf_fallback_id()
    return hf_generate_from_messages(
        model_id,
        cache_key="lfm2_8b",
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
