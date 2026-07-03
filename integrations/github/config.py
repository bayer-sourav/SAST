"""Load pinned ship config from integrations/github/MANIFEST.json."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

_PKG = Path(__file__).resolve().parent
DEFAULT_MANIFEST = _PKG / "MANIFEST.json"


@lru_cache(maxsize=1)
def load_manifest(path: str | Path | None = None) -> dict[str, Any]:
    manifest_path = Path(path or os.environ.get("GITHUB_ADVISORY_MANIFEST", DEFAULT_MANIFEST))
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def inference_config(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict((manifest or load_manifest())["inference"])


def github_config(manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    return dict((manifest or load_manifest())["github"])


def ui_label(label: str, manifest: dict[str, Any] | None = None) -> str:
    labels = (manifest or load_manifest()).get("ui_labels") or {}
    return str(labels.get(label, label))
