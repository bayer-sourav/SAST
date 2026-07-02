"""Build a short triage prompt from an existing task.md for JSON-only retries."""

from __future__ import annotations

import re
from pathlib import Path

_COMPACT_SYSTEM = """You are a security-oriented SAST triage assistant.
Assess every CodeQL alert, then assign one case-level label.

Output requirements (strict):
- Reply with EXACTLY ONE JSON object. No markdown fences. No prose before or after.
- Start with { and end with }.
- "label" must be one of: TP, FP, BL, UNKNOWN.
- TP: at least one alert is a true positive on its path.
- FP: every alert is a false positive with path-specific evidence.
- BL: no alert is TP, and at least one alert is genuinely ambiguous.
- UNKNOWN: insufficient source or flow to assess one or more alerts.
- Required keys: label, confidence, confidence_score, reason, evidence, agent, case_id.
- Set "agent" to "llm" and "case_id" exactly as given.
"""


def _extract_case_id(task_md: str) -> str | None:
    m = re.search(r"\*\*case_id\*\*:\s*`([^`]+)`", task_md)
    return m.group(1).strip() if m else None


def _section_from(task_md: str, heading: str) -> str:
    """Return text from ``heading`` until the next ``## `` heading."""
    idx = task_md.find(heading)
    if idx < 0:
        return ""
    start = idx + len(heading)
    rest = task_md[start:]
    m = re.search(r"\n## ", rest)
    body = rest[: m.start()] if m else rest
    return body.strip()


def _cap_file_section(body: str, *, max_file_chars: int) -> str:
    """Truncate the ### File source block while keeping alert metadata intact."""
    marker = "### File"
    idx = body.find(marker)
    if idx < 0:
        return body[: max_file_chars * 2]
    head = body[: idx + len(marker)]
    tail = body[idx + len(marker) :].lstrip("\n")
    if len(tail) <= max_file_chars:
        return head + "\n" + tail
    return head + "\n" + tail[:max_file_chars] + "\n\n... [source truncated for compact retry] ..."


def compact_user_from_task_md(
    task_md: str,
    *,
    case_id: str | None = None,
    max_chars: int = 12000,
    max_file_chars: int = 6000,
) -> tuple[str, str]:
    """
    Build compact system + user messages from a full task.md.

    Returns (system_text, user_text).
    """
    cid = case_id or _extract_case_id(task_md) or "unknown"
    alerts = _section_from(task_md, "## Alerts to assess")
    if not alerts:
        alerts = _section_from(task_md, "## Inputs")
    if not alerts:
        alerts = task_md[-8000:]

    body = f"## case_id\n`{cid}`\n\n## Alerts to assess\n\n{alerts}"
    body = _cap_file_section(body, max_file_chars=max_file_chars)
    if len(body) > max_chars:
        body = body[:max_chars] + "\n\n... [truncated] ..."

    user = (
        body
        + "\n\nAssess all alerts and assign ONE case-level label. "
        f'Output JSON only. Set "case_id" to "{cid}" and "agent" to "llm".'
    )
    return _COMPACT_SYSTEM, user


def compact_messages_from_task_path(
    task_path: Path,
    *,
    case_id: str | None = None,
    max_chars: int = 12000,
    max_file_chars: int = 6000,
    alerts_only: bool = False,
) -> tuple[str, list[dict[str, str]]]:
    """Load task.md and return (case_id, chat messages)."""
    task_md = task_path.read_text(encoding="utf-8")
    cid = case_id or _extract_case_id(task_md) or task_path.parent.name
    if alerts_only:
        alerts = _section_from(task_md, "## Alerts to assess")
        body = f"## case_id\n`{cid}`\n\n## Alerts to assess\n\n{alerts}"
        user = (
            body
            + "\n\nAssign ONE case-level label (TP/FP/BL/UNKNOWN) from the alert metadata above. "
            f'Output JSON only — no analysis. Set "case_id" to "{cid}" and "agent" to "llm".'
        )
        system = (
            _COMPACT_SYSTEM
            + "\nCRITICAL: Your entire response must be one JSON object. "
            "Do not analyze in prose. Start with {."
        )
        return cid, [
            {"role": "system", "content": system},
            {"role": "user", "content": user[:4000]},
        ]

    system_text, user_text = compact_user_from_task_md(
        task_md,
        case_id=cid,
        max_chars=max_chars,
        max_file_chars=max_file_chars,
    )
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]
    return cid, messages
