"""Shared decoding settings for agent JSON outputs (env: AGENT_*)."""

from __future__ import annotations

import os
from typing import Any

# Align with model loaders (Qwen/Gemma/GPT-OSS default max_seq_length=32768).
DEFAULT_MAX_SEQ_LEN = 32768
DEFAULT_MAX_NEW_TOKENS = 32768
MIN_GENERATION_TOKENS = 256


def model_max_seq_len() -> int:
    """Upper bound on prompt + completion length (env: AGENT_MAX_SEQ_LEN or per-family vars)."""
    for key in (
        "AGENT_MAX_SEQ_LEN",
        "QWEN_MAX_SEQ_LEN",
        "GEMMA_UNSLOTH_MAX_SEQ_LEN",
        "GPT_OSS_MAX_SEQ_LEN",
    ):
        raw = os.environ.get(key, "").strip()
        if raw:
            return int(raw)
    return DEFAULT_MAX_SEQ_LEN


def agent_max_new_tokens_requested(*, enable_thinking: bool = False) -> int:
    """Requested cap before context clamping. Same default for thinking on/off."""
    _ = enable_thinking  # reserved; use AGENT_MAX_NEW_TOKENS_THINKING only if explicitly set
    if enable_thinking and os.environ.get("AGENT_MAX_NEW_TOKENS_THINKING", "").strip():
        return int(os.environ["AGENT_MAX_NEW_TOKENS_THINKING"])
    return int(os.environ.get("AGENT_MAX_NEW_TOKENS", str(DEFAULT_MAX_NEW_TOKENS)))


def cap_max_new_tokens(
    gen_kwargs: dict[str, Any],
    *,
    input_token_len: int,
    max_seq_len: int | None = None,
) -> dict[str, Any]:
    """Clamp max_new_tokens so prompt + completion fits in the model context window."""
    ctx = max_seq_len if max_seq_len is not None else model_max_seq_len()
    requested = int(gen_kwargs.get("max_new_tokens", DEFAULT_MAX_NEW_TOKENS))
    remaining = max(MIN_GENERATION_TOKENS, ctx - int(input_token_len) - 16)
    gen_kwargs["max_new_tokens"] = min(requested, remaining)
    return gen_kwargs


def apply_triage_run_token_limits(*, thinking: bool) -> None:
    """Phase-2-style decode caps so thinking runs do not budget ~32k new tokens per case."""
    if thinking:
        os.environ.setdefault("AGENT_MAX_SEQ_LEN", os.environ.get("PHASE2_ON_MAX_SEQ_LEN", "32768"))
        os.environ.setdefault("AGENT_MAX_NEW_TOKENS", os.environ.get("PHASE2_ON_MAX_NEW_TOKENS", "8192"))
        os.environ.setdefault(
            "AGENT_MAX_NEW_TOKENS_THINKING",
            os.environ.get("PHASE2_ON_MAX_NEW_TOKENS_THINKING", "8192"),
        )
        os.environ.setdefault("QWEN_MAX_SEQ_LEN", os.environ.get("PHASE2_ON_MAX_SEQ_LEN", "32768"))
    else:
        os.environ.setdefault("AGENT_MAX_SEQ_LEN", os.environ.get("PHASE2_OFF_MAX_SEQ_LEN", "16384"))
        os.environ.setdefault("AGENT_MAX_NEW_TOKENS", os.environ.get("PHASE2_OFF_MAX_NEW_TOKENS", "4096"))


def agent_decoding_kwargs(*, enable_thinking: bool = False) -> dict[str, Any]:
    """
    Decoding kwargs for triage JSON generation.
    Default max_new_tokens=32768 (capped per-call via cap_max_new_tokens to fit context).
    repetition_penalty (>1) reduces degenerate repeats; set AGENT_REPETITION_PENALTY=1 to disable.
    """
    max_new = agent_max_new_tokens_requested(enable_thinking=enable_thinking)
    temp = float(os.environ.get("AGENT_TEMPERATURE", "0.2"))
    out: dict[str, Any] = {"max_new_tokens": max_new, "do_sample": temp > 0}
    if temp > 0:
        out["temperature"] = temp
    rp_raw = os.environ.get("AGENT_REPETITION_PENALTY", "1.12").strip()
    try:
        rpv = float(rp_raw)
        if rpv > 1.0:
            out["repetition_penalty"] = rpv
    except ValueError:
        pass
    return out
