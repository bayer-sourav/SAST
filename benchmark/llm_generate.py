"""Dispatch vanilla triage generation to the correct local model backend."""

from __future__ import annotations

from typing import Any

QWEN_PROFILES = frozenset(
    {
        "2_5_7b",
        "qwen3_4b_bnb",
        "qwen3_8b_bnb",
        "qwen3_14b_bnb",
        "qwen3_5_4b_bnb",
        "qwen3_5_9b_bnb",
        "qwen3_6_27b_bnb",
        "qwen3_6_35b_a3b_bnb",
        "qwen3_coder_30b_bnb",
        "qwen3_next_80b_bnb",
    }
)
GEMMA_PROFILES = frozenset({"google_gemma_3_12b_it", "gemma_4_e4b_bnb"})
GPT_PROFILES = frozenset({"gpt_oss_20b"})


def profile_family(profile: str) -> str:
    if profile in QWEN_PROFILES:
        return "qwen"
    if profile in GEMMA_PROFILES:
        return "gemma"
    if profile in GPT_PROFILES:
        return "gpt_oss"
    raise ValueError(
        f"unknown profile {profile!r}; expected one of {sorted(QWEN_PROFILES | GEMMA_PROFILES | GPT_PROFILES)}"
    )


def preload_profile(profile: str, *, use_4bit: bool = True) -> None:
    """Load model weights once before a batch cell (fails fast instead of per-case retry)."""
    family = profile_family(profile)
    print(f"[preload] warming profile={profile!r} (family={family})", flush=True)
    if family == "qwen":
        from models.qwen.runner import preload_qwen_profile

        preload_qwen_profile(profile, use_4bit=use_4bit)
        return
    if family == "gemma":
        if profile == "gemma_4_e4b_bnb":
            from models.gemma_4_e4b_it.runner import preload_gemma4_profile

            preload_gemma4_profile(use_4bit=use_4bit)
            return
        from core.gemma3_hf_backend import get_hf_model_and_tokenizer as gemma_load

        gemma_load("google/gemma-3-12b-it", cache_key="gemma_preload", use_4bit=use_4bit)
        return
    from core.hf_backend import get_hf_model_and_tokenizer

    get_hf_model_and_tokenizer(
        "openai/gpt-oss-20b",
        cache_key="gpt_oss_preload",
        use_4bit=use_4bit,
    )


def infer_triage(
    messages: list[dict[str, Any]],
    profile: str,
    *,
    thinking: bool = False,
    use_4bit: bool = True,
    max_new: int | None = None,
) -> str:
    """Triage inference honoring QWEN_INFER_BACKEND (vLLM when enabled for Qwen profiles)."""
    family = profile_family(profile)
    if family == "qwen":
        from models.qwen.vllm_backend import should_use_vllm, vllm_generate_from_chat

        if should_use_vllm(profile):
            return vllm_generate_from_chat(
                messages,
                profile=profile,
                enable_thinking=thinking,
                max_new=max_new,
            )
    return generate_triage(messages, profile, thinking=thinking, use_4bit=use_4bit)


def generate_triage(
    messages: list[dict[str, Any]],
    profile: str,
    *,
    thinking: bool = False,
    use_4bit: bool = True,
) -> str:
    family = profile_family(profile)
    if family == "qwen":
        from models.qwen.runner import generate_from_chat_messages

        return generate_from_chat_messages(
            messages,
            profile=profile,
            use_4bit=use_4bit,
            tools=None,
            enable_thinking=thinking,
        )
    if family == "gemma":
        if profile == "gemma_4_e4b_bnb":
            from models.gemma_4_e4b_it.runner import generate_from_chat_messages as gemma4_generate

            return gemma4_generate(messages, use_4bit=use_4bit, enable_thinking=thinking)
        from models.google_gemma_3_12b_it.runner import generate_from_chat_messages

        return generate_from_chat_messages(messages, use_4bit=use_4bit, enable_thinking=thinking)
    from models.open_ai_gpt_oss_20B.runner import generate_from_chat_messages

    return generate_from_chat_messages(messages, use_4bit=use_4bit, enable_thinking=thinking)
