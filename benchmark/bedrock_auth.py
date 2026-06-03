"""Resolve Amazon Bedrock Mantle credentials for OpenAI-compatible clients."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

CredentialSource = Literal[
    "QWEN_BEDROCK_API_KEY",
    "AWS_BEARER_TOKEN_BEDROCK",
    "OPENAI_API_KEY",
    "none",
]


def _load_dotenv_if_present() -> None:
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    if not env_path.is_file():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
    except ImportError:
        pass


def _is_temporary_mantle_openai_key(key: str) -> bool:
    """Mantle short-lived keys are URL-encoded SigV4 blobs prefixed for OpenAI clients."""
    k = key.strip()
    return k.startswith("bedrock-api-key-") or "X-Amz-Expires" in k or "X-Amz-Credential" in k


def _mask_key(key: str) -> str:
    k = key.strip()
    if len(k) <= 12:
        return "***"
    return f"{k[:8]}...{k[-4:]}"


def resolve_bedrock_credentials(
    *,
    prefer: str | None = None,
) -> tuple[str, str, CredentialSource]:
    """
    Return (base_url, api_key, source).

    Default priority for Bedrock Mantle:
      1. QWEN_BEDROCK_API_KEY (explicit override)
      2. AWS_BEARER_TOKEN_BEDROCK (long-lived Bedrock API key, ABSK...)
      3. OPENAI_API_KEY (only if not a known short-lived mantle wrapper when bearer exists)
    """
    _load_dotenv_if_present()

    base = (
        os.environ.get("BEDROCK_MANTLE_BASE_URL", "").strip()
        or os.environ.get("OPENAI_BASE_URL", "").strip()
    )

    explicit = os.environ.get("QWEN_BEDROCK_API_KEY", "").strip()
    bearer = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

    order = prefer or os.environ.get("QWEN_BEDROCK_AUTH_ORDER", "").strip().lower()
    if order == "openai_first":
        candidates: list[tuple[str, CredentialSource]] = [
            (explicit, "QWEN_BEDROCK_API_KEY"),
            (openai_key, "OPENAI_API_KEY"),
            (bearer, "AWS_BEARER_TOKEN_BEDROCK"),
        ]
    else:
        # Default: stable bearer before possibly-expired OPENAI_API_KEY mantle token.
        candidates = [
            (explicit, "QWEN_BEDROCK_API_KEY"),
            (bearer, "AWS_BEARER_TOKEN_BEDROCK"),
        ]
        if bearer and openai_key and _is_temporary_mantle_openai_key(openai_key):
            pass  # skip expired-prone temp key when long-lived bearer is set
        else:
            candidates.append((openai_key, "OPENAI_API_KEY"))

    for key, source in candidates:
        if key:
            return base, key, source

    return base, "", "none"


def bedrock_configured() -> bool:
    base, key, _ = resolve_bedrock_credentials()
    return bool(base and key)


def format_bedrock_auth_log(source: CredentialSource, api_key: str) -> str:
    return f"auth_source={source} key={_mask_key(api_key)}"


def alternate_bedrock_key(
    current_source: CredentialSource,
) -> tuple[str, CredentialSource] | None:
    """Return fallback key after 401 (e.g. expired OPENAI_API_KEY -> bearer)."""
    _load_dotenv_if_present()
    bearer = os.environ.get("AWS_BEARER_TOKEN_BEDROCK", "").strip()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if current_source == "OPENAI_API_KEY" and bearer:
        return bearer, "AWS_BEARER_TOKEN_BEDROCK"
    if current_source == "AWS_BEARER_TOKEN_BEDROCK" and openai_key:
        return openai_key, "OPENAI_API_KEY"
    return None
