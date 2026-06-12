"""Google Gemma 4 E4B IT — Unsloth FastModel (text-only triage, thinking on/off)."""

from __future__ import annotations

import os

_DEFAULT_UNSLOTH_4BIT = "unsloth/gemma-4-E4B-it-unsloth-bnb-4bit"
_DEFAULT_HF = "google/gemma-4-E4B-it"


def _unsloth_model_id(*, use_4bit: bool) -> str:
    if use_4bit:
        return os.environ.get("GEMMA_4_E4B_UNSLOTH_MODEL_ID", _DEFAULT_UNSLOTH_4BIT)
    return os.environ.get("GEMMA_4_E4B_UNSLOTH_FP_MODEL_ID", _DEFAULT_HF)


def _hf_model_id(*, use_4bit: bool) -> str:
    env = os.environ.get("GEMMA_4_E4B_HF_MODEL_ID", "").strip()
    if env:
        return env
    return _unsloth_model_id(use_4bit=use_4bit)


def _max_seq_length(*, enable_thinking: bool) -> int:
    key = "GEMMA_4_E4B_MAX_SEQ_LEN_THINKING" if enable_thinking else "GEMMA_4_E4B_MAX_SEQ_LEN"
    default = "32768" if enable_thinking else "16384"
    raw = os.environ.get(key, os.environ.get("GEMMA_4_E4B_MAX_SEQ_LEN", default)).strip()
    return int(raw) if raw else int(default)


def preload_gemma4_profile(*, use_4bit: bool = True) -> None:
    from core.gemma3_unsloth_backend import _load_fastmodel

    _load_fastmodel(
        "gemma4_e4b_preload",
        model_name=_unsloth_model_id(use_4bit=use_4bit),
        use_4bit=use_4bit,
        max_seq_length=_max_seq_length(enable_thinking=False),
    )


def generate_from_chat_messages(
    messages: list[dict[str, str]],
    *,
    use_4bit: bool = True,
    enable_thinking: bool = False,
) -> str:
    """Vanilla chat triage; Gemma 4 uses apply_chat_template(enable_thinking=...)."""
    model_name = _unsloth_model_id(use_4bit=use_4bit)
    print(f"[Gemma 4 E4B] enable_thinking={enable_thinking}", flush=True)
    try:
        from core.gemma3_unsloth_backend import gemma3_unsloth_generate_from_messages

        return gemma3_unsloth_generate_from_messages(
            cache_key="gemma4_e4b_unsloth",
            model_name=model_name,
            messages=messages,
            use_4bit=use_4bit,
            max_seq_length=_max_seq_length(enable_thinking=enable_thinking),
            enable_thinking=enable_thinking,
        )
    except Exception as exc:
        print(f"[Gemma 4 E4B] Unsloth failed ({exc!r}); using Hugging Face.")
    from core.gemma3_hf_backend import gemma3_generate_from_messages

    return gemma3_generate_from_messages(
        _hf_model_id(use_4bit=use_4bit),
        cache_key="gemma4_e4b_it",
        messages=messages,
        use_4bit=use_4bit,
        enable_thinking=enable_thinking,
    )
