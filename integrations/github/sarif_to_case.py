"""Convert CodeQL SARIF 2.1.0 runs into benchmark-compatible case JSON files."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from integrations.github.snippet_extract import (
    attach_snippets_to_case,
    normalize_repo_uri,
    primary_file_from_alert,
)

_SLUG_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.strip().lower()).strip("-") or "repo"


def _alert_fingerprint(result: dict[str, Any]) -> str:
    fps = result.get("partialFingerprints") or {}
    if isinstance(fps, dict):
        primary = fps.get("primaryLocationLineHash")
        if primary:
            return str(primary)
    payload = json.dumps(
        {
            "ruleId": result.get("ruleId"),
            "locations": result.get("locations"),
            "message": result.get("message"),
        },
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _result_rule_id(result: dict[str, Any]) -> str:
    return str(result.get("ruleId") or (result.get("rule") or {}).get("id") or "unknown")


def _result_lines(result: dict[str, Any]) -> tuple[int | None, int | None]:
    for loc in result.get("locations") or []:
        phys = (loc.get("physicalLocation") or {}) if isinstance(loc, dict) else {}
        region = phys.get("region") or {}
        start = region.get("startLine")
        end = region.get("endLine", start)
        try:
            return (int(start), int(end)) if start is not None else (None, None)
        except (TypeError, ValueError):
            continue
    return None, None


def sarif_result_to_alert(result: dict[str, Any]) -> dict[str, Any]:
    """Map one SARIF result to benchmark CodeQL alert shape."""
    alert: dict[str, Any] = {
        "ruleId": _result_rule_id(result),
        "message": result.get("message") or {},
        "locations": result.get("locations") or [],
    }
    if result.get("codeFlows"):
        alert["codeFlows"] = result["codeFlows"]
    if result.get("partialFingerprints"):
        alert["partialFingerprints"] = result["partialFingerprints"]
    if result.get("rule"):
        alert["rule"] = result["rule"]
    return alert


def build_case_from_result(
    result: dict[str, Any],
    *,
    repo_root: Path,
    owner: str = "local",
    repo: str = "repo",
    commit_sha: str | None = None,
    attach_snippets: bool = True,
) -> dict[str, Any]:
    alert = sarif_result_to_alert(result)
    file_path = primary_file_from_alert(alert)
    fingerprint = _alert_fingerprint(result)
    case_id = f"gh-{_slug(owner)}-{_slug(repo)}-{fingerprint.replace(':', '-')}"

    case: dict[str, Any] = {
        "case_id": case_id,
        "tool": ["CodeQL"],
        "file": file_path,
        "scan_root": ".",
        "repo_root": str(repo_root.resolve()),
        "raw_output": {"CodeQL": [alert]},
        "metadata": {
            "alert_fingerprint": fingerprint,
            "rule_id": _result_rule_id(result),
            "commit_sha": commit_sha,
            "repository": f"{owner}/{repo}",
        },
    }
    start, end = _result_lines(result)
    if start is not None:
        case["metadata"]["start_line"] = start
        case["metadata"]["end_line"] = end

    if attach_snippets and repo_root.is_dir():
        case = attach_snippets_to_case(case, repo_root)
    return case


def parse_sarif_document(sarif: dict[str, Any]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for run in sarif.get("runs") or []:
        if not isinstance(run, dict):
            continue
        for result in run.get("results") or []:
            if isinstance(result, dict):
                results.append(result)
    return results


def sarif_to_cases(
    sarif: dict[str, Any],
    *,
    repo_root: Path,
    owner: str = "local",
    repo: str = "repo",
    commit_sha: str | None = None,
    attach_snippets: bool = True,
) -> list[dict[str, Any]]:
    return [
        build_case_from_result(
            result,
            repo_root=repo_root,
            owner=owner,
            repo=repo,
            commit_sha=commit_sha,
            attach_snippets=attach_snippets,
        )
        for result in parse_sarif_document(sarif)
    ]


def write_cases(cases: list[dict[str, Any]], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for case in cases:
        case_id = case.get("case_id") or "case"
        safe = _slug(str(case_id))
        path = out_dir / f"{safe}.json"
        path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        paths.append(path)
    return paths


def load_sarif(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sarif", required=True, help="Path to SARIF JSON file")
    ap.add_argument("--repo", required=True, help="Path to repository clone at commit")
    ap.add_argument("--out", required=True, help="Output directory for case JSON files")
    ap.add_argument("--owner", default="local")
    ap.add_argument("--repo-name", default="repo")
    ap.add_argument("--commit", default=None)
    ap.add_argument("--no-snippets", action="store_true")
    args = ap.parse_args()

    sarif = load_sarif(Path(args.sarif).expanduser().resolve())
    cases = sarif_to_cases(
        sarif,
        repo_root=Path(args.repo).expanduser().resolve(),
        owner=args.owner,
        repo=args.repo_name,
        commit_sha=args.commit,
        attach_snippets=not args.no_snippets,
    )
    paths = write_cases(cases, Path(args.out).expanduser().resolve())
    print(json.dumps({"n_cases": len(paths), "out_dir": str(Path(args.out).resolve())}, indent=2))


if __name__ == "__main__":
    main()
