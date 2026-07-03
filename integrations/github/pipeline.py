"""End-to-end advisory job: SARIF → cases → inference → optional publish."""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from integrations.github.config import github_config, load_manifest
from integrations.github.github_client import GitHubClient, load_sarif
from integrations.github.github_publish import publish_advisory
from integrations.github.sarif_to_case import sarif_to_cases, write_cases
from integrations.github.triage_worker import run_cases


def process_advisory_job(
    *,
    owner: str,
    repo: str,
    commit_sha: str,
    sarif_path: Path,
    repo_clone_path: Path,
    work_dir: Path,
    installation_id: int | str | None = None,
    pr_number: int | None = None,
    publish: bool = False,
    sast_root: Path | None = None,
) -> dict[str, Any]:
    manifest = load_manifest()
    sarif = load_sarif(sarif_path)
    cases = sarif_to_cases(
        sarif,
        repo_root=repo_clone_path,
        owner=owner,
        repo=repo,
        commit_sha=commit_sha,
        attach_snippets=True,
    )
    cases_dir = work_dir / "cases"
    write_cases(cases, cases_dir)
    job = run_cases(sorted(cases_dir.glob("*.json")), work_dir / "advisory", sast_root=sast_root)
    job["repository"] = {"owner": owner, "name": repo}
    job["commit_sha"] = commit_sha
    job["pr_number"] = pr_number

    if publish and installation_id is not None:
        pub = publish_advisory(
            job,
            owner=owner,
            repo=repo,
            commit_sha=commit_sha,
            installation_id=installation_id,
            pr_number=pr_number,
        )
        job["publish"] = pub
    return job


def process_workflow_run_event(
    event: dict[str, Any],
    *,
    installation_token: str,
    work_root: Path,
    sast_root: Path | None = None,
    publish: bool = True,
) -> dict[str, Any]:
    """Handle a workflow_run.completed webhook payload."""
    manifest = load_manifest()
    gh = github_config(manifest)
    wr = event.get("workflow_run") or {}
    if wr.get("status") != "completed":
        return {"status": "ignored", "reason": "workflow not completed"}

    name = str(wr.get("name") or "")
    if gh.get("codeql_workflow_name_filter", "CodeQL") not in name:
        return {"status": "ignored", "reason": f"workflow name {name!r} does not match filter"}

    repo_meta = (event.get("repository") or {})
    owner = (repo_meta.get("owner") or {}).get("login") or ""
    repo = repo_meta.get("name") or ""
    commit_sha = wr.get("head_sha") or ""
    run_id = wr.get("id")
    clone_url = repo_meta.get("clone_url") or ""
    installation_id = (event.get("installation") or {}).get("id")
    prs = wr.get("pull_requests") or []
    pr_number = prs[0].get("number") if prs else None

    work_dir = work_root / f"{owner}-{repo}-{commit_sha[:12]}"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    client = GitHubClient(installation_token)
    sarif_path = client.download_workflow_artifact(
        owner,
        repo,
        int(run_id),
        gh["sarif_artifact_name"],
        work_dir / "artifact",
    )
    clone_path = client.clone_repo_at_sha(clone_url, commit_sha, work_dir / "repo", token=installation_token)

    return process_advisory_job(
        owner=owner,
        repo=repo,
        commit_sha=commit_sha,
        sarif_path=sarif_path,
        repo_clone_path=clone_path,
        work_dir=work_dir,
        installation_id=installation_id,
        pr_number=pr_number,
        publish=publish and installation_id is not None,
        sast_root=sast_root,
    )
