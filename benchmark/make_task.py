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
from benchmark.triage_labels import TASK_TITLE_MARKER, task_prompt_tag  # noqa: E402

DEFAULT_OUTPUT_SCHEMA = {
    "label": "TP|FP|BL|UNKNOWN",
    "confidence": "high|medium|low",
    "confidence_score": 0.0,
    "reason": "short explanation grounded in concrete code evidence; cite which alert(s) drove the label",
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


def _codeql_alerts(raw_output: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_output, dict):
        return []
    alerts = raw_output.get("CodeQL")
    return list(alerts) if isinstance(alerts, list) else []


def _region_str(region: dict[str, Any]) -> str:
    start = region.get("startLine")
    end = region.get("endLine", start)
    if start is None:
        return "unknown"
    if end is None or end == start:
        return f"L{start}"
    return f"L{start}-L{end}"


def _alert_sink(alert: dict[str, Any], default_file: str) -> tuple[str, str]:
    locs = alert.get("locations") or []
    if not locs:
        return default_file, "unknown"
    phys = (locs[0].get("physicalLocation") or {})
    uri = (phys.get("artifactLocation") or {}).get("uri") or default_file
    region = phys.get("region") or {}
    return str(uri), _region_str(region)


def _codeflow_step_label(step: dict[str, Any]) -> str | None:
    loc = step.get("location") or {}
    msg = (loc.get("message") or {}).get("text")
    if msg:
        return str(msg).strip()
    region = ((loc.get("physicalLocation") or {}).get("region") or {})
    line = region.get("startLine")
    return f"L{line}" if line is not None else None


def _codeflow_endpoints(
    alert: dict[str, Any],
) -> tuple[str | None, str | None, list[str]]:
    """Return (source_hint, sink_hint, key_steps) from the first codeFlow thread."""
    flows = alert.get("codeFlows") or []
    if not flows:
        return None, None, []
    threads = flows[0].get("threadFlows") or []
    if not threads:
        return None, None, []
    steps = threads[0].get("locations") or []
    if not steps:
        return None, None, []

    key_steps: list[str] = []
    for step in steps:
        label = _codeflow_step_label(step)
        if not label:
            continue
        if not key_steps or key_steps[-1] != label:
            key_steps.append(label)

    source: str | None = None
    sink: str | None = None
    for step in steps:
        taxa = step.get("taxa") or []
        role = None
        for t in taxa:
            props = t.get("properties") or {}
            role = props.get("CodeQL/DataflowRole") or role
        label = _codeflow_step_label(step)
        if not label:
            continue
        if role == "source" and source is None:
            source = label
        if role in ("sink", "barrier"):
            sink = label
    if sink is None and steps:
        sink = _codeflow_step_label(steps[-1])
    if source is None and steps:
        source = _codeflow_step_label(steps[0])
    return source, sink, key_steps


def _format_alerts_summary(
    alerts: list[dict[str, Any]],
    default_file: str,
    *,
    prompt_version: str | None = None,
) -> str:
    from benchmark.prompt_versions import is_ship_prompt, normalize_rule_id

    ship = is_ship_prompt(prompt_version)
    tool_label = "SAST tool" if ship else "CodeQL"
    flow_label = "data flow" if ship else "codeFlow"
    if not alerts:
        return (
            "## Alerts to assess\n\n"
            f"No structured {tool_label} alerts were parsed; use `Finding (raw)` below.\n"
        )
    n = len(alerts)
    lines = [
        "## Alerts to assess",
        "",
        f"The finding contains **{n}** {tool_label} alert{'s' if n != 1 else ''}. "
        "**Evaluate every alert independently** (rule, sink, "
        f"{flow_label}), then apply the case-level label rules in **Your task**.",
        "",
    ]
    for i, alert in enumerate(alerts, start=1):
        rule_id = alert.get("ruleId") or (alert.get("rule") or {}).get("id") or "unknown"
        rule_id = normalize_rule_id(str(rule_id), ship=ship)
        message = (alert.get("message") or {}).get("text") or ""
        sink_file, sink_lines = _alert_sink(alert, default_file)
        source, sink, key_steps = _codeflow_endpoints(alert)
        lines.append(f"### Alert {i} of {n}")
        lines.append(f"- **ruleId**: `{rule_id}`")
        if message:
            lines.append(f"- **message**: {message}")
        lines.append(f"- **sink**: `{sink_file}` {sink_lines}")
        if source:
            lines.append(f"- **source ({flow_label})**: {source}")
        if sink and sink != source:
            lines.append(f"- **sink ({flow_label})**: {sink}")
        if key_steps:
            lines.append(f"- **key steps ({flow_label})**: {' → '.join(key_steps)}")
        lines.append("")
    return "\n".join(lines)


def _render_source_section(
    case: dict[str, Any],
    repo_root: Path,
    file_path: str | None,
) -> str:
    """Render primary file or multi-file source→sink snippets for the prompt."""
    snippets = case.get("code_snippets")
    if isinstance(snippets, list) and snippets:
        lines = ["### Code (source → sink path)", ""]
        for snip in snippets:
            if not isinstance(snip, dict):
                continue
            rel = snip.get("file") or file_path or "unknown"
            start = snip.get("start_line")
            end = snip.get("end_line", start)
            role = snip.get("role")
            header = f"#### `{rel}`"
            if start is not None:
                header += f" L{start}" if end in (None, start) else f" L{start}-L{end}"
            if role:
                header += f" ({role})"
            text = snip.get("text")
            if not isinstance(text, str):
                text = _read_line_range(repo_root, str(rel), start, end)
            lines.extend([header, "```", text.rstrip(), "```", ""])
        return "\n".join(lines).rstrip()

    if not file_path:
        return "### Code\n\n(no source file in case)\n"
    src_text = (repo_root / file_path).read_text(encoding="utf-8")
    return f"### File\n{src_text}"


def _read_line_range(
    repo_root: Path,
    rel_path: str,
    start_line: int | None,
    end_line: int | None,
) -> str:
    path = repo_root / rel_path
    if not path.is_file():
        return f"(source unavailable: {rel_path})"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if start_line is None:
        return "\n".join(lines)
    start = max(1, int(start_line))
    end = int(end_line) if end_line is not None else start
    end = min(len(lines), max(start, end))
    return "\n".join(lines[start - 1 : end])


def build_task_markdown(
    case: dict[str, Any],
    repo_root: Path,
    scan_root: str = ".",
    agent: str = "generic",
    *,
    few_shot: int = 0,
    few_shot_config: str | Path | None = None,
    prompt_version: str | None = None,
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
    source_section = _render_source_section(case, repo_root, file_path)
    alerts = _codeql_alerts(case.get("raw_output"))
    alerts_summary = _format_alerts_summary(
        alerts, str(file_path or ""), prompt_version=prompt_version
    )

    few_shot_block = ""
    layout_version = None
    if few_shot > 0 and agent == "llm":
        from benchmark.few_shot import build_few_shot_task_section, layout_tag_from_config

        few_shot_block = build_few_shot_task_section(k=few_shot, config_path=few_shot_config)
        layout_version = layout_tag_from_config(few_shot_config)

    # Do not include repo_root or corpus paths in the prompt (track leakage).
    context_lines = [f"- **case_id**: `{cid}`"]
    if agent != "llm":
        context_lines.append(f"- **scan_root (relative)**: `{effective_scan_root}`")
    context_block = "\n".join(context_lines)

    from benchmark.prompt_versions import build_task_procedure

    procedure = build_task_procedure(
        prompt_version=prompt_version,
        output_schema=DEFAULT_OUTPUT_SCHEMA,
    )

    return f"""{TASK_TITLE_MARKER} ({task_prompt_tag(few_shot=few_shot, layout_version=layout_version, prompt_version=prompt_version)})

## Context
{context_block}

## Environment notes
{env_hint}

## Your task
{procedure}
{few_shot_block}
## Inputs

{alerts_summary}
{source_section}

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
    ap.add_argument(
        "--few-shot",
        type=int,
        default=0,
        help="Include N few-shot exemplars in task body (0 or configured exemplar count).",
    )
    ap.add_argument(
        "--few-shot-config",
        default=None,
        help="Few-shot config name (e.g. v2_3shot_2tp_fp) or path to JSON. "
        "Default: few_shot_examples.json or SAST_FEWSHOT_CONFIG env.",
    )
    ap.add_argument(
        "--prompt-version",
        default=None,
        help="Prompt version key (v7-balanced, v8-dual-gate, v9-fprr-first). "
        "Default: SAST_PROMPT_VERSION env or v7-balanced.",
    )
    ap.add_argument("--print-schema", action="store_true")
    args = ap.parse_args()
    from benchmark.few_shot import validate_few_shot_k

    validate_few_shot_k(args.few_shot, args.few_shot_config)

    if args.print_schema:
        print(json.dumps({"case_id": "BenchmarkTest00001", "tool": ["CodeQL"], "file": "src/Foo.java"}, indent=2))
        return

    case_path = Path(args.case).expanduser().resolve()
    case = json.loads(case_path.read_text(encoding="utf-8"))
    repo_root = Path(args.repo or case.get("repo_root") or case.get("folder_root") or ".").expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        build_task_markdown(
            case=case,
            repo_root=repo_root,
            scan_root=args.scan_root,
            agent=args.agent,
            few_shot=args.few_shot,
            few_shot_config=args.few_shot_config,
            prompt_version=args.prompt_version,
        ),
        encoding="utf-8",
    )
    print(out_path)


if __name__ == "__main__":
    main()
