"""Dispatch vanilla triage generation to the correct local model backend."""

from __future__ import annotations

from typing import Any

# Ascending parameter size (Phase 1 matrix order).
PHASE1_PROFILES: tuple[str, ...] = (
    "qwen3_4b_bnb",
    "qwen3_8b_bnb",
    "google_gemma_3_12b_it",
    "qwen3_14b_bnb",
    "gpt_oss_20b",
    "qwen3_coder_30b_bnb",
)

QWEN_PROFILES = frozenset(
    {
        "2_5_7b",
        "qwen3_4b_bnb",
        "qwen3_8b_bnb",
        "qwen3_14b_bnb",
        "qwen3_coder_30b_bnb",
    }
)
GEMMA_PROFILES = frozenset({"google_gemma_3_12b_it"})
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
        from models.google_gemma_3_12b_it.runner import generate_from_chat_messages

        return generate_from_chat_messages(messages, use_4bit=use_4bit, enable_thinking=thinking)
    from models.open_ai_gpt_oss_20B.runner import generate_from_chat_messages

    return generate_from_chat_messages(messages, use_4bit=use_4bit, enable_thinking=thinking)
