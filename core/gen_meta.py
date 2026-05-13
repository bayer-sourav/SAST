"""
Shared last-generation metadata written by every inference backend and read by
eval/run_eval.py to capture per-row token counts without changing runner signatures.

Each backend calls set_gen_meta() immediately after model.generate() returns.
The eval runner calls get_gen_meta() right after generate_tool_selection_raw() returns.
Thread-safety note: single-threaded eval loop only — no locking needed.
"""

from __future__ import annotations

_last: dict[str, int] = {"input_tokens": -1, "output_tokens": -1}


def set_gen_meta(input_tokens: int, output_tokens: int) -> None:
    """Called by each inference backend after every generate() call."""
    _last["input_tokens"] = int(input_tokens)
    _last["output_tokens"] = int(output_tokens)


def get_gen_meta() -> dict[str, int]:
    """Called by the eval runner after each generate_tool_selection_raw() call."""
    return dict(_last)


def reset_gen_meta() -> None:
    """Reset to sentinel -1 before each generate call so stale values are never used."""
    _last["input_tokens"] = -1
    _last["output_tokens"] = -1
