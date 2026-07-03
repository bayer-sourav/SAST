"""Publish advisory triage results to GitHub (neutral check run + PR comment)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_SAST = Path(__file__).resolve().parents[2]
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

from integrations.github.config import github_config, load_manifest, ui_label  # noqa: E402
from integrations.github.github_auth import installation_token  # noqa: E402
from integrations.github.github_client import GitHubClient  # noqa: E402


def _annotation_level(label: str) -> str:
    return "warning" if label in ("BL", "UNKNOWN") else "notice"


def build_annotations(findings: list[dict[str, Any]], manifest: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    manifest = manifest or load_manifest()
    annotations: list[dict[str, Any]] = []
    for item in findings:
        adv = item.get("advisory") or {}
        label = str(adv.get("label") or "UNKNOWN")
        headline = adv.get("ui_headline") or ui_label(label, manifest)
        reason = adv.get("reason") or ""
        rule_id = item.get("rule_id") or "unknown"
        body = (
            f"Advisory triage: {headline}\n\n"
            f"Reason: {reason}\n\n"
            f"CodeQL rule: {rule_id}\n\n"
            "This is a suggestion only. Review and dismiss or fix alerts in Code Scanning yourself."
        )
        annotations.append(
            {
                "path": item.get("file") or "README.md",
                "start_line": int(item.get("start_line") or 1),
                "end_line": int(item.get("end_line") or item.get("start_line") or 1),
                "annotation_level": _annotation_level(label),
                "message": body[:65535],
                "title": headline[:255],
            }
        )
    return annotations[:50]


def build_pr_summary(
    findings: list[dict[str, Any]],
    *,
    commit_sha: str,
    manifest: dict[str, Any] | None = None,
) -> str:
    manifest = manifest or load_manifest()
    counts = {"TP": 0, "FP": 0, "BL": 0, "UNKNOWN": 0}
    for item in findings:
        label = str((item.get("advisory") or {}).get("label") or "UNKNOWN")
        counts[label] = counts.get(label, 0) + 1
    marker = f"<!-- sast-advisory-triage:{commit_sha[:12]} -->"
    lines = [
        marker,
        "## AI Triage Advisory (informational)",
        "",
        f"Commit `{commit_sha[:12]}` · **not a blocking check**",
        "",
        "| Label | Count |",
        "| --- | ---: |",
    ]
    for key in ("TP", "FP", "BL", "UNKNOWN"):
        lines.append(f"| {ui_label(key, manifest)} | {counts.get(key, 0)} |")
    lines.extend(
        [
            "",
            "Review each Code Scanning alert in the Security tab. These annotations are suggestions only.",
        ]
    )
    return "\n".join(lines)


def publish_advisory(
    job: dict[str, Any],
    *,
    owner: str,
    repo: str,
    commit_sha: str,
    installation_id: int | str,
    pr_number: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    manifest = load_manifest()
    gh = github_config(manifest)
    findings = job.get("findings") or []
    annotations = build_annotations(findings, manifest)
    output = {
        "title": gh["check_run_name"],
        "summary": f"Advisory triage for {len(findings)} CodeQL finding(s).",
        "annotations": annotations,
    }
    if dry_run:
        return {"dry_run": True, "output": output, "pr_summary": build_pr_summary(findings, commit_sha=commit_sha)}

    token = installation_token(installation_id)
    client = GitHubClient(token)
    check = client.create_check_run(
        owner,
        repo,
        name=gh["check_run_name"],
        head_sha=commit_sha,
        conclusion=gh.get("check_conclusion", "neutral"),
        output=output,
    )
    comment = None
    if pr_number is not None:
        comment = client.upsert_pr_comment(
            owner,
            repo,
            pr_number,
            marker=f"<!-- sast-advisory-triage:{commit_sha[:12]} -->",
            body=build_pr_summary(findings, commit_sha=commit_sha),
        )
    return {"check_run": check, "pr_comment": comment}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--advisory", required=True, help="job.json from triage_worker")
    ap.add_argument("--owner", required=True)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--commit", required=True)
    ap.add_argument("--installation-id", required=True)
    ap.add_argument("--pr", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    job = json.loads(Path(args.advisory).read_text(encoding="utf-8"))
    result = publish_advisory(
        job,
        owner=args.owner,
        repo=args.repo,
        commit_sha=args.commit,
        installation_id=args.installation_id,
        pr_number=args.pr,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
