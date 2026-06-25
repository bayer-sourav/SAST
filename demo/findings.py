"""CodeQL finding views and source snippets for the demo UI."""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from demo.pipeline import (
    case_meta,
    codeql_alert_count,
    load_case_entry,
    resolve_repo,
)

# Research taxonomy (maps CodeQL CWE buckets → presentation categories).
VULN_CATEGORIES: dict[str, str] = {
    "SSRF": "Full taint-to-sink control (output / reflection sinks)",
    "P-SSRF": "Partial control of structured target (path, query, command)",
    "Type Confusion": "Type or context mismatch at sink (primitives, format strings)",
}

CATEGORY_STYLES: dict[str, str] = {
    "SSRF": "cat-ssrf",
    "P-SSRF": "cat-pssrf",
    "Type Confusion": "cat-typeconf",
}


@dataclass
class HighlightSpan:
    line: int
    start_col: int
    end_col: int
    kind: str = "sink"  # sink | flow


@dataclass
class AlertView:
    index: int
    rule_id: str
    message: str
    sink_file: str
    sink_lines: str
    sink_start: int | None
    sink_end: int | None
    source_hint: str | None
    sink_hint: str | None
    flow_steps: list[str] = field(default_factory=list)
    highlight_spans: list[HighlightSpan] = field(default_factory=list)


@dataclass
class FindingView:
    case_id: str
    gold: str
    title: str
    vuln_category: str
    rule: str
    file_path: str
    file_name: str
    alert_count: int
    alerts: list[AlertView]
    featured: AlertView | None
    snippet: str
    snippet_start_line: int
    highlight_lines: set[int]
    highlight_spans: list[HighlightSpan]
    borderline_rationale: str = ""
    acceptable_labels: list[str] = field(default_factory=list)


def _region_str(region: dict[str, Any]) -> str:
    start = region.get("startLine")
    end = region.get("endLine", start)
    if start is None:
        return "?"
    if end is None or end == start:
        return f"L{start}"
    return f"L{start}–L{end}"


def _spans_from_region(region: dict[str, Any], *, kind: str = "sink") -> list[HighlightSpan]:
    start_line = region.get("startLine")
    end_line = region.get("endLine", start_line)
    start_col = region.get("startColumn")
    end_col = region.get("endColumn")
    if start_line is None or start_col is None:
        return []
    if end_line is None:
        end_line = start_line
    if end_col is None:
        end_col = start_col + 1
    spans: list[HighlightSpan] = []
    for line in range(int(start_line), int(end_line) + 1):
        sc = int(start_col) if line == int(start_line) else 1
        ec = int(end_col) if line == int(end_line) else 10_000
        spans.append(HighlightSpan(line=line, start_col=sc, end_col=ec, kind=kind))
    return spans


def _codeflow_endpoints(alert: dict[str, Any]) -> tuple[str | None, str | None, list[str], list[HighlightSpan]]:
    flows = alert.get("codeFlows") or []
    flow_spans: list[HighlightSpan] = []
    if not flows:
        return None, None, [], flow_spans
    threads = flows[0].get("threadFlows") or []
    if not threads:
        return None, None, [], flow_spans
    steps = threads[0].get("locations") or []
    if not steps:
        return None, None, [], flow_spans

    def step_label(step: dict[str, Any]) -> str | None:
        loc = step.get("location") or {}
        msg = (loc.get("message") or {}).get("text")
        if msg:
            return str(msg).strip()
        region = ((loc.get("physicalLocation") or {}).get("region") or {})
        line = region.get("startLine")
        return f"L{line}" if line is not None else None

    key_steps: list[str] = []
    for step in steps:
        label = step_label(step)
        if label and (not key_steps or key_steps[-1] != label):
            key_steps.append(label)
        loc = step.get("location") or {}
        phys = loc.get("physicalLocation") or {}
        region = phys.get("region") or {}
        role = None
        for t in step.get("taxa") or []:
            role = (t.get("properties") or {}).get("CodeQL/DataflowRole") or role
        kind = "sink" if role in ("sink", "barrier") else "flow"
        if role == "source":
            kind = "flow"
        flow_spans.extend(_spans_from_region(region, kind=kind))

    source: str | None = None
    sink: str | None = None
    for step in steps:
        role = None
        for t in step.get("taxa") or []:
            role = (t.get("properties") or {}).get("CodeQL/DataflowRole") or role
        label = step_label(step)
        if not label:
            continue
        if role == "source" and source is None:
            source = label
        if role in ("sink", "barrier"):
            sink = label
    if sink is None and steps:
        sink = step_label(steps[-1])
    if source is None and steps:
        source = step_label(steps[0])
    return source, sink, key_steps, flow_spans


def _alert_view(alert: dict[str, Any], *, index: int, default_file: str) -> AlertView:
    locs = alert.get("locations") or []
    phys = (locs[0].get("physicalLocation") if locs else {}) or {}
    uri = (phys.get("artifactLocation") or {}).get("uri") or default_file
    region = phys.get("region") or {}
    source, sink, steps, flow_spans = _codeflow_endpoints(alert)
    sink_spans = _spans_from_region(region, kind="sink")
    return AlertView(
        index=index,
        rule_id=str(alert.get("ruleId") or (alert.get("rule") or {}).get("id") or "?"),
        message=str((alert.get("message") or {}).get("text") or ""),
        sink_file=str(uri),
        sink_lines=_region_str(region),
        sink_start=region.get("startLine"),
        sink_end=region.get("endLine", region.get("startLine")),
        source_hint=source,
        sink_hint=sink,
        flow_steps=steps,
        highlight_spans=sink_spans + flow_spans,
    )


def _alert_views(case: dict[str, Any]) -> list[AlertView]:
    default_file = str(case.get("file") or "")
    raw = case.get("raw_output") or {}
    alerts = raw.get("CodeQL") if isinstance(raw, dict) else []
    return [
        _alert_view(a, index=i, default_file=default_file)
        for i, a in enumerate(alerts if isinstance(alerts, list) else [], start=1)
    ]


def _pick_featured(alerts: list[AlertView], entry: dict[str, Any]) -> AlertView | None:
    if not alerts:
        return None
    prefer = entry.get("featured_rule")
    if prefer:
        for a in alerts:
            if a.rule_id == prefer:
                return a
    return alerts[0]


def _merge_spans(spans: list[HighlightSpan]) -> dict[int, list[tuple[int, int, str]]]:
    """Line → merged (start_col, end_col, kind) intervals."""
    by_line: dict[int, list[tuple[int, int, str]]] = {}
    for sp in spans:
        by_line.setdefault(sp.line, []).append((sp.start_col, sp.end_col, sp.kind))
    merged: dict[int, list[tuple[int, int, str]]] = {}
    for line, parts in by_line.items():
        parts.sort()
        out: list[tuple[int, int, str]] = []
        for sc, ec, kind in parts:
            if not out:
                out.append((sc, ec, kind))
                continue
            psc, pec, pk = out[-1]
            if sc <= pec + 1 and kind == pk:
                out[-1] = (psc, max(pec, ec), pk)
            else:
                out.append((sc, ec, kind))
        merged[line] = out
    return merged


def _snippet_window(
    source: str,
    highlight_lines: set[int],
    *,
    context: int = 5,
) -> tuple[str, int, set[int]]:
    if not source.strip():
        return "", 1, set()
    lines = source.splitlines()
    if not highlight_lines:
        start = 1
        end = min(len(lines), 40)
    else:
        lo = max(1, min(highlight_lines) - context)
        hi = min(len(lines), max(highlight_lines) + context)
        start, end = lo, hi
    snippet = "\n".join(lines[start - 1 : end])
    rel_highlight = {ln - start + 1 for ln in highlight_lines if start <= ln <= end}
    return snippet, start, rel_highlight


def _highlight_line_text(text: str, intervals: list[tuple[int, int, str]]) -> str:
    if not text:
        return " "
    if not intervals:
        return html.escape(text)
    n = len(text)
    out: list[str] = []
    pos = 0
    for sc, ec, kind in intervals:
        start = max(0, sc - 1)
        end = min(n, ec - 1) if ec > sc else min(n, start + 1)
        if start > pos:
            out.append(html.escape(text[pos:start]))
        if end > start:
            cls = "hl-sink" if kind == "sink" else "hl-flow"
            out.append(f'<mark class="{cls}">{html.escape(text[start:end])}</mark>')
            pos = end
    if pos < n:
        out.append(html.escape(text[pos:]))
    return "".join(out) or " "


def build_finding_view(entry: dict[str, Any], repo: Path | None) -> FindingView | None:
    try:
        case_path, case = load_case_entry(entry)
    except FileNotFoundError:
        return None

    meta = case_meta(entry, case)
    file_path = str(case.get("file") or "?")
    file_name = file_path.split("/")[-1] if file_path else "?"
    alerts = _alert_views(case)
    featured = _pick_featured(alerts, entry)

    highlight_spans: list[HighlightSpan] = []
    highlight_lines: set[int] = set()
    if featured:
        highlight_spans = list(featured.highlight_spans)
        if featured.sink_start:
            end = featured.sink_end or featured.sink_start
            highlight_lines.update(range(featured.sink_start, end + 1))
        for sp in highlight_spans:
            highlight_lines.add(sp.line)

    snippet, snippet_start, _rel = "", 1, set()
    try:
        root = resolve_repo(case_path, case, repo)
        src_path = root / file_path
        if src_path.is_file():
            source = src_path.read_text(encoding="utf-8", errors="replace")
            snippet, snippet_start, _rel = _snippet_window(source, highlight_lines)
    except OSError:
        pass

    vuln_category = entry.get("vuln_category") or "SSRF"
    rule = entry.get("rule") or (featured.rule_id if featured else "?")

    return FindingView(
        case_id=entry["case_id"],
        gold=entry["gold"],
        title=entry.get("title", ""),
        vuln_category=vuln_category,
        rule=rule,
        file_path=file_path,
        file_name=file_name,
        alert_count=codeql_alert_count(case),
        alerts=alerts,
        featured=featured,
        snippet=snippet,
        snippet_start_line=snippet_start,
        highlight_lines=highlight_lines,
        highlight_spans=highlight_spans,
        borderline_rationale=meta.get("borderline_rationale") or "",
        acceptable_labels=meta.get("acceptable_labels") or [],
    )


def build_finding_views(entries: list[dict[str, Any]], repo: Path | None) -> list[FindingView]:
    views: list[FindingView] = []
    for entry in entries:
        v = build_finding_view(entry, repo)
        if v:
            views.append(v)
    return views


def snippet_html(
    snippet: str,
    start_line: int,
    highlight_lines: set[int],
    highlight_spans: list[HighlightSpan] | None = None,
) -> str:
    """Numbered source block; sink tokens wrapped in <mark>, line nums always visible."""
    if not snippet:
        return '<pre class="code-empty">Source file not available</pre>'
    span_map = _merge_spans(highlight_spans or [])
    rows: list[str] = []
    for i, line in enumerate(snippet.splitlines()):
        ln = start_line + i
        intervals = span_map.get(ln, [])
        has_mark = bool(intervals)
        hot = ln in highlight_lines or has_mark
        cls = "code-line hot" if hot else "code-line"
        body = _highlight_line_text(line, intervals)
        rows.append(
            f'<div class="{cls}">'
            f'<span class="ln{" ln-hot" if hot else ""}">{ln:4d}</span>'
            f"<code>{body}</code></div>"
        )
    return f'<div class="code-block">{"".join(rows)}</div>'


def gold_badge(gold: str) -> tuple[str, str]:
    g = gold.upper()
    return {
        "TP": ("True positive (real vuln)", "badge-tp"),
        "FP": ("False positive (noise)", "badge-fp"),
        "BL": ("Borderline (ambiguous)", "badge-bl"),
    }.get(g, ("Unknown", "badge-unknown"))


def label_badge(label: str | None) -> tuple[str, str]:
    if not label:
        return ("Pending", "badge-pending")
    u = label.upper()
    return {
        "TP": ("Vulnerability", "label-tp"),
        "FP": ("Dismiss — false alarm", "label-fp"),
        "BL": ("Human review", "label-bl"),
        "UNKNOWN": ("Unknown", "label-unknown"),
    }.get(u, (label, "label-unknown"))
