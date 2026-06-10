"""Few-shot exemplar blocks for Phase 2 triage (frozen train-split cases)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEFAULT_EXAMPLES = Path(__file__).resolve().parent / "few_shot_examples.json"
_EXCERPT_PAD_LINES = 18
_EXCERPT_PAD_LINES_COMPACT = 6


def _sast_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_few_shot_config(path: Path | None = None) -> dict[str, Any]:
    p = (path or _DEFAULT_EXAMPLES).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"few-shot config not found: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def few_shot_case_ids(path: Path | None = None) -> frozenset[str]:
    cfg = load_few_shot_config(path)
    return frozenset(str(e["case_id"]) for e in cfg.get("exemplars") or [])


def _all_alert_regions(case: dict[str, Any]) -> list[dict[str, int]]:
    raw = case.get("raw_output") or {}
    alerts = raw.get("CodeQL") if isinstance(raw, dict) else None
    if not isinstance(alerts, list):
        return []
    regions: list[dict[str, int]] = []
    for alert in alerts:
        loc = alert.get("locations") or []
        if not loc:
            continue
        region = (loc[0].get("physicalLocation") or {}).get("region") or {}
        if not region or "startLine" not in region:
            continue
        regions.append(
            {
                "startLine": int(region["startLine"]),
                "endLine": int(region.get("endLine", region["startLine"])),
            }
        )
    return regions


def _merged_region(regions: list[dict[str, int]]) -> dict[str, int] | None:
    if not regions:
        return None
    return {
        "startLine": min(r["startLine"] for r in regions),
        "endLine": max(r["endLine"] for r in regions),
    }


def _source_excerpt(
    repo_root: Path,
    rel_file: str,
    region: dict[str, int] | None,
    *,
    pad: int,
) -> str:
    path = repo_root / rel_file
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if region and "startLine" in region:
        start = max(1, int(region["startLine"]) - pad)
        end = min(len(lines), int(region.get("endLine", region["startLine"])) + pad)
    else:
        start, end = 1, min(len(lines), 80)
    chunk = lines[start - 1 : end]
    numbered = [f"{start + i:4d}| {line}" for i, line in enumerate(chunk)]
    return "\n".join(numbered)


def _alerts_brief(case: dict[str, Any]) -> list[str]:
    raw = case.get("raw_output") or {}
    alerts = raw.get("CodeQL") if isinstance(raw, dict) else None
    if not isinstance(alerts, list) or not alerts:
        return []
    out: list[str] = []
    for i, alert in enumerate(alerts, start=1):
        rule = alert.get("ruleId") or (alert.get("rule") or {}).get("id", "")
        msg = (alert.get("message") or {}).get("text", "")
        out.append(f"Alert {i} `{rule}`: {msg}".strip(": "))
    return out


def _resolve_bundle_path(bundle: str) -> Path:
    p = Path(bundle)
    if p.is_absolute():
        return p.resolve()
    return (_sast_root() / bundle).resolve()


def _format_alerts_assessed(ex: dict[str, Any]) -> str:
    assessed = ex.get("alerts_assessed") or []
    if not assessed:
        return ""
    lines = ["- **Per-alert verdicts**:"]
    for item in assessed:
        alert_no = item.get("alert", "?")
        rule = item.get("rule", "")
        verdict = item.get("verdict", "")
        resolved = item.get("resolved_sink", "")
        lines.append(
            f"  - Alert {alert_no} (`{rule}`): **{verdict}** — resolved sink: {resolved}"
        )
    return "\n".join(lines) + "\n"


def build_few_shot_task_section(*, k: int, config_path: Path | None = None) -> str:
    """Markdown block inserted after **Your task** when k > 0 (visible in task.md)."""
    if k <= 0:
        return ""
    cfg = load_few_shot_config(config_path)
    exemplars = list(cfg.get("exemplars") or [])
    if k != len(exemplars):
        raise ValueError(f"few-shot k={k} but config has {len(exemplars)} exemplars")

    layout = str(cfg.get("layout") or "full")
    compact = layout == "compact"
    pad = int(cfg.get("excerpt_pad_lines") or (_EXCERPT_PAD_LINES_COMPACT if compact else _EXCERPT_PAD_LINES))

    parts = [
        "\n## Few-shot examples (reasoning shape only)\n",
        "These worked examples show **how to apply** the per-alert procedure above. "
        "They are **not** the case you are scoring. **Do not** match by superficial similarity "
        "(e.g. `encodeForHTML` present, `doSomething` helper, or list/map in the path). "
        "Re-derive each alert's **resolved sink value** from the **current** case inputs below.\n",
    ]

    for i, ex in enumerate(exemplars, start=1):
        bundle = _resolve_bundle_path(str(ex["bundle"]))
        case = json.loads((bundle / "case.json").read_text(encoding="utf-8"))
        cid = str(ex.get("case_id") or case.get("case_id"))
        rel = str(case.get("file", ""))
        region = _merged_region(_all_alert_regions(case))
        excerpt = _source_excerpt(bundle, rel, region, pad=pad)
        slot = str(ex.get("slot", f"example{i}"))
        gold = str(ex.get("gold_track", ""))
        pattern = str(ex.get("pattern", ""))
        expected = dict(ex.get("expected_output") or {})
        expected.setdefault("agent", "llm")
        expected.setdefault("case_id", cid)

        parts.append(f"\n### Example {i} ({gold} · `{cid}` · slot `{slot}`)\n")
        if pattern:
            parts.append(f"- **Pattern**: {pattern}\n")

        brief = _alerts_brief(case)
        if brief:
            parts.append("- **Alerts in reference case**:\n")
            for line in brief:
                parts.append(f"  - {line}\n")

        assessed_block = _format_alerts_assessed(ex)
        if assessed_block:
            parts.append(assessed_block)

        parts.append(f"- **Case label**: **{expected.get('label', '?')}**\n")
        parts.append(f"- **Reason style**: {expected.get('reason', '')}\n")
        parts.append(f"- **Source excerpt** (sink-resolution focus):\n```java\n{excerpt}\n```\n")

        if ex.get("include_full_json", not compact):
            parts.append(
                "- **JSON format reference** (shape only — do not copy labels):\n```json\n"
                + json.dumps(expected, ensure_ascii=False, indent=2)
                + "\n```\n"
            )

    return "".join(parts)


def build_few_shot_system_suffix(*, k: int, config_path: Path | None = None) -> str:
    """Deprecated: few-shot lives in task.md; kept for callers that still import this name."""
    return build_few_shot_task_section(k=k, config_path=config_path)


def assert_no_test_leakage(*, test_case_ids: set[str], config_path: Path | None = None) -> None:
    overlap = few_shot_case_ids(config_path) & test_case_ids
    if overlap:
        raise ValueError(f"few-shot exemplar case_ids overlap test set: {sorted(overlap)}")
