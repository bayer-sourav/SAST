"""GitHub REST helpers: artifacts, clone, webhook verification."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


def verify_webhook_signature(payload: bytes, signature_header: str | None, secret: str) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature_header)


class GitHubClient:
    def __init__(self, token: str, *, api_base: str | None = None) -> None:
        self.api_base = (api_base or os.environ.get("GITHUB_API_BASE") or "https://api.github.com").rstrip("/")
        self.token = token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        url = path if path.startswith("http") else f"{self.api_base}{path}"
        return httpx.get(url, headers=self._headers, timeout=60.0, **kwargs)

    def _post(self, path: str, json_body: dict[str, Any] | None = None, **kwargs: Any) -> httpx.Response:
        url = path if path.startswith("http") else f"{self.api_base}{path}"
        return httpx.post(url, headers=self._headers, json=json_body, timeout=60.0, **kwargs)

    def _patch(self, path: str, json_body: dict[str, Any] | None = None, **kwargs: Any) -> httpx.Response:
        url = path if path.startswith("http") else f"{self.api_base}{path}"
        return httpx.patch(url, headers=self._headers, json=json_body, timeout=60.0, **kwargs)

    def download_workflow_artifact(
        self,
        owner: str,
        repo: str,
        run_id: int,
        artifact_name: str,
        dest_dir: Path,
    ) -> Path:
        resp = self._get(f"/repos/{owner}/{repo}/actions/runs/{run_id}/artifacts")
        resp.raise_for_status()
        artifacts = resp.json().get("artifacts") or []
        match = next((a for a in artifacts if a.get("name") == artifact_name), None)
        if not match:
            names = [a.get("name") for a in artifacts]
            raise FileNotFoundError(f"artifact {artifact_name!r} not found; available: {names}")
        archive_url = match["archive_download_url"]
        zip_resp = self._get(archive_url)
        zip_resp.raise_for_status()
        dest_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
            zf.extractall(dest_dir)
        sarif_files = list(dest_dir.rglob("*.sarif")) + list(dest_dir.rglob("*.json"))
        if not sarif_files:
            raise FileNotFoundError(f"no SARIF file in artifact {artifact_name}")
        return sarif_files[0]

    def clone_repo_at_sha(
        self,
        clone_url: str,
        commit_sha: str,
        dest: Path,
        *,
        token: str | None = None,
    ) -> Path:
        dest = dest.resolve()
        if dest.exists():
            return dest
        dest.parent.mkdir(parents=True, exist_ok=True)
        auth_url = clone_url
        if token and clone_url.startswith("https://"):
            parsed = urlparse(clone_url)
            auth_url = f"{parsed.scheme}://x-access-token:{token}@{parsed.netloc}{parsed.path}"
        subprocess.run(
            ["git", "clone", "--depth", "1", auth_url, str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(["git", "fetch", "--depth", "1", "origin", commit_sha], cwd=dest, check=True, capture_output=True)
        subprocess.run(["git", "checkout", commit_sha], cwd=dest, check=True, capture_output=True)
        return dest

    def create_check_run(
        self,
        owner: str,
        repo: str,
        *,
        name: str,
        head_sha: str,
        conclusion: str,
        output: dict[str, Any],
        details_url: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "name": name,
            "head_sha": head_sha,
            "status": "completed",
            "conclusion": conclusion,
            "output": output,
        }
        if details_url:
            body["details_url"] = details_url
        resp = self._post(f"/repos/{owner}/{repo}/check-runs", json_body=body)
        resp.raise_for_status()
        return resp.json()

    def upsert_pr_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        *,
        marker: str,
        body: str,
    ) -> dict[str, Any]:
        resp = self._get(f"/repos/{owner}/{repo}/issues/{pr_number}/comments")
        resp.raise_for_status()
        for comment in resp.json():
            if marker in (comment.get("body") or ""):
                comment_id = comment["id"]
                patch = self._patch(
                    f"/repos/{owner}/{repo}/issues/comments/{comment_id}",
                    json_body={"body": body},
                )
                patch.raise_for_status()
                return patch.json()
        create = self._post(f"/repos/{owner}/{repo}/issues/{pr_number}/comments", json_body={"body": body})
        create.raise_for_status()
        return create.json()


def load_sarif(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
