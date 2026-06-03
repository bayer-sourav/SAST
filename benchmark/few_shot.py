"""Few-shot exemplar blocks for Phase 2 triage (frozen train-split cases)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DEFAULT_EXAMPLES = Path(__file__).resolve().parent / "few_shot_examples.json"
_EXCERPT_PAD_LINES = 18


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


def _alert_region(case: dict[str, Any]) -> dict[str, int] | None:
    raw = case.get("raw_output") or {}
    alerts = raw.get("CodeQL") if isinstance(raw, dict) else None
    if not isinstance(alerts, list) or not alerts:
        return None
    loc = alerts[0].get("locations") or []
    if not loc:
        return None
    region = (loc[0].get("physicalLocation") or {}).get("region") or {}
    if not region:
        return None
    out: dict[str, int] = {}
    for key in ("startLine", "endLine"):
        if key in region:
            out[key] = int(region[key])
    return out or None


def _source_excerpt(repo_root: Path, rel_file: str, region: dict[str, int] | None) -> str:
    path = repo_root / rel_file
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if region and "startLine" in region:
        start = max(1, int(region["startLine"]) - _EXCERPT_PAD_LINES)
        end = min(len(lines), int(region.get("endLine", region["startLine"])) + _EXCERPT_PAD_LINES)
    else:
        start, end = 1, min(len(lines), 80)
    chunk = lines[start - 1 : end]
    numbered = [f"{start + i:4d}| {line}" for i, line in enumerate(chunk)]
    return "\n".join(numbered)


def _finding_summary(case: dict[str, Any]) -> str:
    raw = case.get("raw_output") or {}
    alerts = raw.get("CodeQL") if isinstance(raw, dict) else None
    if isinstance(alerts, list) and alerts:
        msg = (alerts[0].get("message") or {}).get("text", "")
        rule = (alerts[0].get("ruleId") or alerts[0].get("rule", {}).get("id", ""))
        return f"{rule}: {msg}".strip(": ")
    return str(case.get("tool", "CodeQL"))


def _resolve_bundle_path(bundle: str) -> Path:
    p = Path(bundle)
    if p.is_absolute():
        return p.resolve()
    return (_sast_root() / bundle).resolve()


def build_few_shot_task_section(*, k: int, config_path: Path | None = None) -> str:
    """Markdown block prepended to the user task when k > 0 (visible in task.md)."""
    if k <= 0:
        return ""
    cfg = load_few_shot_config(config_path)
    exemplars = list(cfg.get("exemplars") or [])
    if k != len(exemplars):
        raise ValueError(f"few-shot k={k} but config has {len(exemplars)} exemplars")
    parts = [
        "\n## Few-shot examples (reference format only)\n",
        "These are **completed triage examples** showing the JSON shape and reasoning style. "
        "They are **not** the case you are scoring now. Do **not** copy their labels; "
        "decide the **current** case only from its source and finding below.\n",
    ]
    for i, ex in enumerate(exemplars, start=1):
        bundle = _resolve_bundle_path(str(ex["bundle"]))
        case = json.loads((bundle / "case.json").read_text(encoding="utf-8"))
        cid = str(ex.get("case_id") or case.get("case_id"))
        rel = str(case.get("file", ""))
        region = _alert_region(case)
        excerpt = _source_excerpt(bundle, rel, region)
        finding = _finding_summary(case)
        expected = dict(ex.get("expected_output") or {})
        expected.setdefault("agent", "llm")
        expected.setdefault("case_id", cid)
        slot = str(ex.get("slot", f"example{i}"))
        parts.append(f"\n### Example {i} (reference case_id `{cid}`, slot `{slot}`)\n")
        parts.append(f"- **Alert**: {finding}\n")
        parts.append(f"- **File**: `{rel}`\n")
        parts.append(f"- **Source excerpt**:\n```java\n{excerpt}\n```\n")
        parts.append(
            "- **Expected JSON**:\n```json\n"
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
