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


def _format_alerts_summary(alerts: list[dict[str, Any]], default_file: str) -> str:
    if not alerts:
        return (
            "## Alerts to assess\n\n"
            "No structured CodeQL alerts were parsed; use `Finding (raw)` below.\n"
        )
    n = len(alerts)
    lines = [
        "## Alerts to assess",
        "",
        f"The finding contains **{n}** CodeQL alert{'s' if n != 1 else ''}. "
        "**Evaluate every alert independently** (rule, sink, codeFlow), then apply the "
        "case-level label rules in **Your task**.",
        "",
    ]
    for i, alert in enumerate(alerts, start=1):
        rule_id = alert.get("ruleId") or (alert.get("rule") or {}).get("id") or "unknown"
        message = (alert.get("message") or {}).get("text") or ""
        sink_file, sink_lines = _alert_sink(alert, default_file)
        source, sink, key_steps = _codeflow_endpoints(alert)
        lines.append(f"### Alert {i} of {n}")
        lines.append(f"- **ruleId**: `{rule_id}`")
        if message:
            lines.append(f"- **message**: {message}")
        lines.append(f"- **sink**: `{sink_file}` {sink_lines}")
        if source:
            lines.append(f"- **source (codeFlow)**: {source}")
        if sink and sink != source:
            lines.append(f"- **sink (codeFlow)**: {sink}")
        if key_steps:
            lines.append(f"- **key steps (codeFlow)**: {' → '.join(key_steps)}")
        lines.append("")
    return "\n".join(lines)


def build_task_markdown(
    case: dict[str, Any],
    repo_root: Path,
    scan_root: str = ".",
    agent: str = "generic",
    *,
    few_shot: int = 0,
    few_shot_config: str | Path | None = None,
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
    alerts = _codeql_alerts(case.get("raw_output"))
    alerts_summary = _format_alerts_summary(alerts, str(file_path or ""))

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

    return f"""{TASK_TITLE_MARKER} ({task_prompt_tag(few_shot=few_shot, layout_version=layout_version)})

## Context
{context_block}

## Environment notes
{env_hint}

## Your task
You are a **security-oriented code reviewer** triaging **SAST findings** for one source file.
The finding may contain **multiple CodeQL alerts** for the same file. You must **assess every alert**
before assigning **one case-level label**.

Use CodeQL `codeFlows`, `locations`, and the shown source. Treat tool messages as starting points;
verify each alert's path in code.

### Per-alert assessment (do this for every alert)
For **each** alert listed in **Alerts to assess**:

1. **Scope** — Use that alert's `ruleId`, sink lines, and `codeFlow` only (do not borrow mitigation from a different alert).
   Match the rule to the expected sink context: `java/xss` → HTML/response output; `java/sql-injection` → SQL string passed to query/execute; `java/ldap-injection` → LDAP filter/search argument; etc.

2. **Trace to sink expression first** — Identify the **exact variable or expression** at the reported sink (e.g. the `bar` in `"…'" + bar + "'…"`, the argument to `getWriter().print…`, the LDAP `filter` string).
   Follow data flow from source to **that** expression, including through helper methods and inner classes. Use **key steps (codeFlow)** as a guide, but **verify in source** — CodeQL paths can be misleading.
   - Track **reassignments**: the value used at the sink is the **final** assignment on the taken path, not an earlier tainted assignment.
   - For **`java/xss`**: if codeFlow or source shows reach to an HTML/response sink (`getWriter`, `print`, JSP output, etc.), treat that as the sink context — **do not** dismiss the alert because taint passed through cookies, headers, or session APIs without re-checking what reaches the HTML sink lines.
   - For **`java/insecure-randomness`**: **alert-TP** when a weak RNG (e.g. `java.util.Random`) feeds **session IDs, cookies, remember-me tokens, or other security/key material** on the executed path.
   - **Do not** label **alert-TP** merely because user input exists in the same method; prove it reaches **this** sink expression.

3. **Resolve sink value (mandatory)** — Before any **alert-FP** or final verdict, state the **resolved value** of the sink expression on the **executed path**.
   - **Required** when the sink reads from a **list/map** (`.get(i)`, `.get(key)`, indexed access), a **helper/callee return**, or a **switch/guard** branch that picks the string used at the sink.
   - **Walk the taken branch**: which index/key/return/switch case actually feeds the sink? What string or value does that produce?
   - **alert-FP** (structural or otherwise) only if you can name the **resolved sink value** as a **literal constant** or a **non-user** string on that path (e.g. `get(1)` → `"safeConstant"` after `remove`, map `get("fixedKey")` → hardcoded literal, switch branch assigns fixed safe text).
   - **alert-TP** when the **resolved sink value** still **depends on user/attacker input** (parameter, request field, tainted variable concatenated into the sink), even if the codeFlow still shows taint elsewhere or a container was involved.
   - If you cannot compute the resolved value on the executed path → **alert-unclear**, **not** **alert-FP**.

4. **Structural FP only with proved resolved value** — Only **after** steps 2–3, consider structural false positives. A structural **alert-FP** requires the **resolved sink value** from step 3 to be a constant or provably non-user — not merely that a list/map/switch/helper appears in the path.
   - **Required evidence form**: "resolved sink value = `<literal>`" or "`get(i)` / `get(key)` on this path returns `<constant>`, not the user parameter".
   - **Provable structural patterns** (general):
     - **List/container**: add user value, then `remove` and `get` (or pick an index) so the sink reads a **constant** or non-user element — prove which index/value is read at the sink.
     - **Map overwrite**: `put` tainted data under one key, then the sink uses `get` of a **different key** or a constant literal.
     - **Switch/guard**: the taken branch assigns a **hardcoded safe** string to the variable used at the sink.
     - **Helper return trace**: follow callee returns; if the **returned value** reaching the sink is a constant or guarded-safe value, with proof at the sink expression.
- If the pattern is suggested but the **resolved sink value** is not established → **alert-unclear**, **not** **alert-FP**.

5. **Mitigate on this path (balanced encoding)** — Only after steps 2–4, check encoding/sanitization **between source and this sink expression**.
   - Mitigation must apply to the **same expression** that reaches the sink.
   - **Balanced rule**: do **not** auto-label **alert-FP** because `encodeForHTML`, ESAPI, or similar appears in the codeFlow when steps 2–3 show **attacker-controlled data is still the resolved sink value** — prefer **alert-TP** in that case.
   - **alert-FP** via encoding only when the **resolved sink value** is **not** attacker-controlled (encoding applied to a different value, wrong output context for the rule, or unreachable branch).

6. **Verdict** — For this alert alone:
   - When **multiple alerts** exist, an **alert-FP** on one does **not** prevent **alert-TP** on another; verdict each alert on its own path.
   - **alert-TP**: the **resolved sink value** on the executed path is attacker-controlled or unsafe, and steps 3–5 did not prove otherwise.
   - **alert-FP**: **resolved sink value** is a literal constant, non-user string, safe/unreachable, or wrong context — cite the resolved value and line-level evidence.
   - **alert-unclear**: steps 1–5 leave genuine ambiguity (unresolved sink value, unproved structural FP, partial mitigation, debatable guard) — not merely because another alert differs.

### Case-level label (exactly one)
After all alerts are assessed:
- **TP** — **At least one** alert is **alert-TP**. Do not downgrade because other alerts are **alert-FP**.
- **FP** — **Every** alert is **alert-FP**, each with its own path-specific evidence; in `reason`, name each alert's **resolved sink value** that justified **alert-FP**.
- **BL** — **No** alert is **alert-TP**, and **at least one** is **alert-unclear**.
- **UNKNOWN** — Source or flow is missing from the snippet for one or more alerts.

### Label definitions
- **TP** — Real vulnerability on at least one assessed alert path (unsafe data in the sink expression).
- **FP** — No alert is exploitable on its reported path.
- **BL** — No clear TP; at least one alert genuinely ambiguous.
- **UNKNOWN** — Insufficient information to assess one or more alerts.

Output a single JSON object matching this schema:

{json.dumps(DEFAULT_OUTPUT_SCHEMA, ensure_ascii=False, indent=2)}

### Rules (strict)
1. **READ-ONLY**: Do not edit files or request patches.
2. Assess **all** alerts; in `reason`, name which alert(s) are **alert-TP**, **alert-FP**, or **alert-unclear**, each alert's **resolved sink value** when relevant, and which drove the case label.
3. Verify the **sink expression** per alert; do not conflate paths across alerts or rule types.
4. Label case **FP** only when **every** alert is **alert-FP** with concrete evidence; for each **alert-FP**, state that alert's **resolved sink value** in `reason`.
5. When the **resolved sink value** on the executed path is attacker-controlled, count **alert-TP** (supports case **TP**) — do not dismiss because a *different* alert is mitigated or because a list/map/switch appears without proving a constant resolved value.
6. Do not label case **BL** because alerts disagree — any **alert-TP** ⇒ case **TP**.
7. `label` must be exactly **TP**, **FP**, **BL**, or **UNKNOWN**.
8. `evidence` must include at least one item when label is TP, FP, or BL.
9. Output **one JSON object only** — no markdown fences, no prose before or after.
10. Escape inner double quotes in JSON string values, or use backticks inside values.
{few_shot_block}
## Inputs

{alerts_summary}
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
        ),
        encoding="utf-8",
    )
    print(out_path)


if __name__ == "__main__":
    main()
