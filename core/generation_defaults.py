"""Shared decoding settings for agent JSON outputs (env: AGENT_*)."""

from __future__ import annotations

import os
from typing import Any


def agent_decoding_kwargs() -> dict[str, Any]:
    """
    max_new_tokens default 1024 reduces truncated JSON (e.g. long email body).
    repetition_penalty (>1) reduces degenerate repeats like endless '0' in strings.
    Set AGENT_REPETITION_PENALTY=1 to disable.
    """
    max_new = int(os.environ.get("AGENT_MAX_NEW_TOKENS", "1024"))
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
