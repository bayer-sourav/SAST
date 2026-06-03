"""Shared triage label set and task.md version markers."""

from __future__ import annotations

from pathlib import Path

VALID_LABELS = frozenset({"TP", "FP", "BL", "UNKNOWN"})

# Bump when task prompt / label schema changes (invalidates cached task.md).
TASK_PROMPT_VERSION = "unified-4label-v2"
TASK_TITLE_MARKER = "# SAST Unified Security Triage"


def task_prompt_tag(*, few_shot: int = 0) -> str:
    """Version string embedded in task.md (few-shot variants get a distinct tag)."""
    if few_shot > 0:
        return f"{TASK_PROMPT_VERSION}-fewshot{few_shot}"
    return TASK_PROMPT_VERSION


def task_markdown_current(task_path: Path, *, few_shot: int = 0) -> bool:
    if not task_path.is_file() or task_path.stat().st_size <= 100:
        return False
    head = task_path.read_text(encoding="utf-8", errors="replace")[:800]
    tag = task_prompt_tag(few_shot=few_shot)
    if tag not in head:
        return False
    if few_shot > 0 and "## Few-shot examples" not in head:
        return False
    if few_shot == 0 and "## Few-shot examples" in head:
        return False
    # Reject prompts that leak corpus track via host paths (v1 bug).
    for leak in ("/fp/test/", "/tp/test/", "/borderline/test/", "repo_root (host)"):
        if leak in head:
            return False
    return TASK_TITLE_MARKER in head
