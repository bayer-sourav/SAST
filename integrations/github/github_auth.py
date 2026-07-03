"""GitHub App authentication (JWT + installation tokens)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import jwt


def _load_private_key(path: str | Path | None = None) -> str:
    key_path = path or os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")
    if not key_path:
        inline = os.environ.get("GITHUB_APP_PRIVATE_KEY")
        if inline:
            return inline.replace("\\n", "\n")
        raise RuntimeError("Set GITHUB_APP_PRIVATE_KEY_PATH or GITHUB_APP_PRIVATE_KEY")
    return Path(key_path).expanduser().read_text(encoding="utf-8")


def build_app_jwt(
    *,
    app_id: str | None = None,
    private_key_path: str | Path | None = None,
    ttl_seconds: int = 540,
) -> str:
    app_id = app_id or os.environ.get("GITHUB_APP_ID")
    if not app_id:
        raise RuntimeError("GITHUB_APP_ID is required")
    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + ttl_seconds, "iss": str(app_id)}
    return jwt.encode(payload, _load_private_key(private_key_path), algorithm="RS256")


def installation_token(
    installation_id: int | str,
    *,
    api_base: str | None = None,
    app_id: str | None = None,
    private_key_path: str | Path | None = None,
) -> str:
    import httpx

    base = (api_base or os.environ.get("GITHUB_API_BASE") or "https://api.github.com").rstrip("/")
    jwt_token = build_app_jwt(app_id=app_id, private_key_path=private_key_path)
    url = f"{base}/app/installations/{installation_id}/access_tokens"
    resp = httpx.post(
        url,
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    token = data.get("token")
    if not token:
        raise RuntimeError(f"installation token missing in response: {data}")
    return str(token)
