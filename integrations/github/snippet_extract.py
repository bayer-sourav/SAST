"""Extract source snippets from CodeQL alerts (multi-file source→sink paths)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


@dataclass(frozen=True, order=True)
class _RegionKey:
    file: str
    start: int
    end: int


def normalize_repo_uri(uri: str) -> str:
    """Convert SARIF artifact URI to a repo-relative path."""
    if not uri:
        return ""
    raw = uri.strip()
    if raw.startswith("file:"):
        parsed = urlparse(raw)
        raw = unquote(parsed.path or "")
    for prefix in ("%SRCROOT%/", "%SRCROOT%", "./"):
        if raw.startswith(prefix):
            raw = raw[len(prefix) :]
            break
    return raw.lstrip("/")


def _region_from_phys(phys: dict[str, Any]) -> tuple[int | None, int | None]:
    region = phys.get("region") or {}
    start = region.get("startLine")
    end = region.get("endLine", start)
    try:
        start_i = int(start) if start is not None else None
    except (TypeError, ValueError):
        start_i = None
    try:
        end_i = int(end) if end is not None else start_i
    except (TypeError, ValueError):
        end_i = start_i
    return start_i, end_i


def _codeflow_role(step: dict[str, Any]) -> str | None:
    for taxon in step.get("taxa") or []:
        props = (taxon.get("properties") or {}) if isinstance(taxon, dict) else {}
        role = props.get("CodeQL/DataflowRole")
        if role:
            return str(role)
    return None


def collect_regions_from_alert(alert: dict[str, Any]) -> list[tuple[str, int | None, int | None, str | None]]:
    """Return ordered (file, start, end, role) tuples from locations + codeFlows."""
    regions: list[tuple[str, int | None, int | None, str | None]] = []
    default_file = ""

    for loc in alert.get("locations") or []:
        phys = (loc.get("physicalLocation") or {}) if isinstance(loc, dict) else {}
        uri = normalize_repo_uri(((phys.get("artifactLocation") or {}).get("uri") or ""))
        if uri:
            default_file = uri
        start, end = _region_from_phys(phys)
        if uri:
            regions.append((uri, start, end, "sink"))

    for flow in alert.get("codeFlows") or []:
        for thread in flow.get("threadFlows") or []:
            for step in thread.get("locations") or []:
                loc = (step.get("location") or {}) if isinstance(step, dict) else {}
                phys = loc.get("physicalLocation") or {}
                uri = normalize_repo_uri(((phys.get("artifactLocation") or {}).get("uri") or default_file))
                if not uri:
                    continue
                start, end = _region_from_phys(phys)
                role = _codeflow_role(step)
                regions.append((uri, start, end, role))

    return regions


def _dedupe_regions(
    regions: list[tuple[str, int | None, int | None, str | None]],
) -> list[tuple[str, int | None, int | None, str | None]]:
    seen: set[_RegionKey] = set()
    out: list[tuple[str, int | None, int | None, str | None]] = []
    for file, start, end, role in regions:
        if not file:
            continue
        if start is None:
            key = _RegionKey(file=file, start=0, end=0)
        else:
            key = _RegionKey(file=file, start=start, end=end or start)
        if key in seen:
            continue
        seen.add(key)
        out.append((file, start, end, role))
    return out


def read_line_range(repo_root: Path, rel_path: str, start_line: int | None, end_line: int | None, *, pad: int = 2) -> str:
    path = repo_root / rel_path
    if not path.is_file():
        return f"(source unavailable: {rel_path})"
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if start_line is None:
        return "\n".join(lines)
    start = max(1, int(start_line) - pad)
    end = int(end_line) if end_line is not None else int(start_line)
    end = min(len(lines), max(start, end) + pad)
    numbered = [f"{i:4d}| {line}" for i, line in enumerate(lines[start - 1 : end], start=start)]
    return "\n".join(numbered)


def build_code_snippets(
    alert: dict[str, Any],
    repo_root: Path,
    *,
    pad: int = 2,
    max_snippets: int = 12,
) -> list[dict[str, Any]]:
    """
    Build snippet objects for an alert, including multi-file codeFlow steps.

    Each snippet: {file, start_line, end_line, role, text}
    """
    regions = _dedupe_regions(collect_regions_from_alert(alert))
    snippets: list[dict[str, Any]] = []
    for file, start, end, role in regions[:max_snippets]:
        snippets.append(
            {
                "file": file,
                "start_line": start,
                "end_line": end,
                "role": role,
                "text": read_line_range(repo_root, file, start, end, pad=pad),
            }
        )
    return snippets


def primary_file_from_alert(alert: dict[str, Any]) -> str:
    for loc in alert.get("locations") or []:
        phys = (loc.get("physicalLocation") or {}) if isinstance(loc, dict) else {}
        uri = normalize_repo_uri(((phys.get("artifactLocation") or {}).get("uri") or ""))
        if uri:
            return uri
    regions = collect_regions_from_alert(alert)
    return regions[0][0] if regions else ""


def attach_snippets_to_case(case: dict[str, Any], repo_root: Path) -> dict[str, Any]:
    """Enrich a case dict with code_snippets from its first CodeQL alert."""
    alerts = ((case.get("raw_output") or {}).get("CodeQL") or [])
    if not alerts:
        return case
    alert = alerts[0]
    snippets = build_code_snippets(alert, repo_root)
    if not snippets:
        return case
    enriched = dict(case)
    enriched["code_snippets"] = snippets
    if not enriched.get("file"):
        enriched["file"] = primary_file_from_alert(alert)
    return enriched
