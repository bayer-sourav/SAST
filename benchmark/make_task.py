#!/usr/bin/env python3
"""Build unified SAST triage task prompts (TP / FP / BL / UNKNOWN)."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

_sast = Path(__file__).resolve().parent.parent
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))
from benchmark.triage_labels import TASK_PROMPT_VERSION, TASK_TITLE_MARKER  # noqa: E402

DEFAULT_OUTPUT_SCHEMA = {
    "label": "TP|FP|BL|UNKNOWN",
    "confidence": "high|medium|low",
    "confidence_score": 0.0,
    "reason": "short explanation grounded in concrete code evidence",
    "evidence": [
        {"file": "path/relative/to/repo", "lines": "Lx-Ly", "note": "what this shows"}
    ],
    "agent": "swe-agent|openhands|aider|llm",
    "case_id": "string",
}


def stable_case_id(case: dict[str, Any]) -> str:
    """Stable case_id from case JSON (or fingerprint if missing)."""
    if isinstance(case.get("case_id"), str) and case["case_id"].strip():
        return case["case_id"].strip()

    tool_list = case.get("tool")
    if isinstance(tool_list, str):
        tool_list = [tool_list]
    payload = {
        "tool": tool_list,
        "file": case.get("file"),
        "scan_root": case.get("scan_root"),
        "raw_output": case.get("raw_output"),
    }
    h = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    return f"case-{h}"


def build_task_markdown(
    case: dict[str, Any],
    repo_root: Path,
    scan_root: str = ".",
    agent: str = "generic",
) -> str:
    cid = stable_case_id(case)
    tool = case.get("tool", "unknown-tool")
    tool_list = [tool] if isinstance(tool, str) else (tool or [])
    file_path = case.get("file")
    effective_scan_root = case.get("scan_root") or scan_root

    finding = {
        "tool": tool_list,
        "file": file_path,
        "scan_root": effective_scan_root,
        "raw_output": case.get("raw_output"),
    }

    if agent == "openhands":
        env_hint = (
            "- You are running under OpenHands headless.\n"
            "- Treat your current working directory as the repository root.\n"
            "- Do NOT modify any files.\n"
            "- FINISH after you have output the result JSON once.\n"
        )
    elif agent == "swe-agent":
        env_hint = (
            "- You are running under SWE-agent.\n"
            "- Treat your current working directory as the repository root.\n"
            "- Do NOT modify any files.\n"
        )
    elif agent == "aider":
        env_hint = (
            "- You are running under Aider in scripting mode.\n"
            "- The runner executes in the repository directory.\n"
            "- You MUST NOT request or perform edits.\n"
        )
    elif agent == "llm":
        env_hint = (
            "- You are a pure LLM baseline with no tools.\n"
            "- You cannot execute commands; rely solely on the provided prompt text.\n"
            "- Do NOT request edits or additional interactions.\n"
            "- OUTPUT the JSON result only, with no extra text. You may reason internally first.\n"
        )
    else:
        env_hint = (
            "- You are running in an automated headless environment.\n"
            "- Treat your working directory as the repository root.\n"
            "- Do NOT modify any files.\n"
        )

    finding_json = json.dumps(finding, ensure_ascii=False, indent=2)
    src_text = (repo_root / file_path).read_text(encoding="utf-8")

    return f"""{TASK_TITLE_MARKER} ({TASK_PROMPT_VERSION})

## Context
- **case_id**: `{cid}`
- **repo_root (host)**: `{repo_root}`
- **scan_root (relative)**: `{effective_scan_root}`

## Environment notes
{env_hint}

## Your task
You are a **security-oriented code reviewer** triaging **one SAST finding** (CodeQL or similar).
Treat tool messages and raw output as hints only; base your decision on the **shown source** and data/control flow on the **reported path**.

Classify the finding using **exactly one** label:

- **TP** — A **real vulnerability** exists on the reported path (user-controlled or unsafe data can reach a dangerous sink: XSS, injection, path traversal, etc.).
- **FP** — **Not** a real vulnerability on the reported path (effective mitigation on that path, unreachable code, wrong sink, hardcoded safe value, benign API use).
- **BL** — **Borderline / ambiguous**: sanitization or encoding may exist but is **incomplete**, on the **wrong path**, or **bypassable**; reasonable reviewers could disagree between TP and FP. Use BL when you cannot defend a clear TP or FP with code evidence.
- **UNKNOWN** — **Insufficient information** in the snippet to decide (missing file, unclear flow). Do not use UNKNOWN when the shown code is enough to choose TP, FP, or BL.

Output a single JSON object matching this schema:

{json.dumps(DEFAULT_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)}

### Rules (strict)
1. **READ-ONLY**: Do not edit files or request patches.
2. Inspect the reported file and lines; follow data flow to the sink referenced by the alert.
3. Do **not** rely on the SAST message alone; verify impact on the reported path.
4. Do **not** default to TP or FP; use **BL** when both TP and FP are defensible.
5. `label` must be exactly **TP**, **FP**, **BL**, or **UNKNOWN**.
6. `evidence` must include at least one item when label is TP, FP, or BL.
7. Output **one JSON object only** — no markdown fences, no prose before or after.
8. Escape inner double quotes in JSON string values, or use backticks inside values.

## Inputs

### File
{src_text}

### Finding (raw)
{finding_json}
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", required=True, help="Path to a normalized case JSON file.")
    ap.add_argument("--repo", default=None, help="Repository root (overrides case.repo_root).")
    ap.add_argument("--scan-root", default=".", help="Scan root relative to repo.")
    ap.add_argument(
        "--agent",
        default="generic",
        choices=["generic", "swe-agent", "openhands", "aider", "llm"],
    )
    ap.add_argument("--out", default="triage_task.md", help="Output task markdown path.")
    ap.add_argument("--print-schema", action="store_true")
    args = ap.parse_args()

    if args.print_schema:
        print(json.dumps({"case_id": "BenchmarkTest00001", "tool": ["CodeQL"], "file": "src/Foo.java"}, indent=2))
        return

    case_path = Path(args.case).expanduser().resolve()
    case = json.loads(case_path.read_text(encoding="utf-8"))
    repo_root = Path(args.repo or case.get("repo_root") or case.get("folder_root") or ".").expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        build_task_markdown(case=case, repo_root=repo_root, scan_root=args.scan_root, agent=args.agent),
        encoding="utf-8",
    )
    print(out_path)


if __name__ == "__main__":
    main()
