"""Shared triage label set and task.md version markers."""

from __future__ import annotations

from pathlib import Path

VALID_LABELS = frozenset({"TP", "FP", "BL", "UNKNOWN"})

# Bump when task prompt / label schema changes (invalidates cached task.md).
TASK_PROMPT_VERSION = "unified-4label-v1"
TASK_TITLE_MARKER = "# SAST Unified Security Triage"


def task_markdown_current(task_path: Path) -> bool:
    if not task_path.is_file() or task_path.stat().st_size <= 100:
        return False
    head = task_path.read_text(encoding="utf-8", errors="replace")[:600]
    return TASK_TITLE_MARKER in head and TASK_PROMPT_VERSION in head
