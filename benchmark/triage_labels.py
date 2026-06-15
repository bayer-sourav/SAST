"""Shared triage label set and task.md version markers."""

from __future__ import annotations

from pathlib import Path

from benchmark.prompt_versions import DEFAULT_PROMPT_VERSION, task_prompt_version_string

VALID_LABELS = frozenset({"TP", "FP", "BL", "UNKNOWN"})

# Default tag when no version override (invalidates cached task.md on bump).
TASK_PROMPT_VERSION = task_prompt_version_string(DEFAULT_PROMPT_VERSION)
FEWSHOT_LAYOUT_VERSION = "v2-2shot"  # default when no config path supplied
TASK_TITLE_MARKER = "# SAST Unified Security Triage"


def task_prompt_tag(
    *,
    few_shot: int = 0,
    layout_version: str | None = None,
    prompt_version: str | None = None,
) -> str:
    """Version string embedded in task.md (few-shot variants get a distinct tag)."""
    base = task_prompt_version_string(prompt_version)
    if few_shot > 0:
        layout = layout_version or FEWSHOT_LAYOUT_VERSION
        return f"{base}-fewshot{few_shot}-{layout}"
    return base


def task_markdown_current(
    task_path: Path,
    *,
    few_shot: int = 0,
    layout_version: str | None = None,
    prompt_version: str | None = None,
) -> bool:
    if not task_path.is_file() or task_path.stat().st_size <= 100:
        return False
    text = task_path.read_text(encoding="utf-8", errors="replace")
    head = text[:800]
    tag = task_prompt_tag(
        few_shot=few_shot,
        layout_version=layout_version,
        prompt_version=prompt_version,
    )
    if tag not in head:
        return False
    if few_shot > 0 and "## Few-shot examples" not in text:
        return False
    if few_shot == 0 and "## Few-shot examples" in text:
        return False
    if few_shot > 0:
        your_task = text.find("## Your task")
        few_shot_hdr = text.find("## Few-shot examples")
        inputs_hdr = text.find("## Inputs")
        if not (0 <= your_task < few_shot_hdr < inputs_hdr):
            return False
    # Reject prompts that leak corpus track via host paths (v1 bug).
    for leak in ("/fp/test/", "/tp/test/", "/borderline/test/", "repo_root (host)"):
        if leak in head:
            return False
    return TASK_TITLE_MARKER in head
