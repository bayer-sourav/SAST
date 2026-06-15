#!/usr/bin/env python3
"""Pre-populate runs/demo/cache per model for the quick demo pack."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from demo.bootstrap import SAST_ROOT, ensure_import_paths
from demo.pipeline import cached_result_path, list_models, load_manifest

ensure_import_paths()

CACHE = SAST_ROOT / "runs" / "demo" / "cache"
PROMPT = "v7-balanced"
FEWSHOT = 3


def dest(profile: str, case_id: str) -> Path:
    return (
        CACHE
        / "thinking_on"
        / f"fewshot_{FEWSHOT}"
        / PROMPT
        / profile
        / "llm"
        / case_id
        / "agent-llm-triage-result.json"
    )


def main() -> None:
    manifest = load_manifest()
    cases = manifest["packs"]["quick"]["cases"]
    copied = skipped = missing = 0

    for model in list_models():
        profile = model["id"]
        for entry in cases:
            cid = entry["case_id"]
            out = dest(profile, cid)
            if out.is_file():
                skipped += 1
                continue
            src = cached_result_path(
                case_id=cid,
                profile=profile,
                prompt_version=PROMPT,
                fewshot=FEWSHOT,
                gold=entry["gold"],
            )
            if src is None:
                missing += 1
                print(f"[miss] {profile} {cid}")
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out)
            (out.parent / "cache_meta.json").write_text(
                json.dumps({"source": str(src.relative_to(SAST_ROOT)), "profile": profile}, indent=2),
                encoding="utf-8",
            )
            copied += 1
            print(f"[ok] {profile} {cid} <- {src.relative_to(SAST_ROOT)}")

    print(f"\nDone: copied={copied} skipped={skipped} missing={missing}")


if __name__ == "__main__":
    main()
