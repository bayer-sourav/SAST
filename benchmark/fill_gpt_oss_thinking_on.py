#!/usr/bin/env python3
"""Copy gpt_oss_20b thinking_off runs to thinking_on (model ignores thinking flag)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

FILES = ("agent-llm-triage-result.json", "llm_raw.txt", "run_meta.json", "task.md")


def copy_cell(src_case: Path, dst_case: Path) -> None:
    dst_case.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        sp = src_case / name
        if sp.is_file():
            shutil.copy2(sp, dst_case / name)
    meta_p = dst_case / "run_meta.json"
    if meta_p.is_file():
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        meta["thinking"] = True
        meta["note"] = "copied_from_thinking_off; gpt_oss ignores enable_thinking"
        meta_p.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def main() -> None:
    sast = Path(__file__).resolve().parent.parent
    for track in ("FP-runs", "TP-runs"):
        base = sast / track / "phase1_n50"
        src_root = base / "thinking_off" / "gpt_oss_20b" / "llm"
        dst_root = base / "thinking_on" / "gpt_oss_20b" / "llm"
        if not src_root.is_dir():
            print(f"skip missing {src_root}")
            continue
        n = 0
        for src in sorted(src_root.iterdir()):
            if not src.is_dir() or not (src / "agent-llm-triage-result.json").is_file():
                continue
            copy_cell(src, dst_root / src.name)
            n += 1
        print(f"{track}: copied {n} cases -> {dst_root}")


if __name__ == "__main__":
    main()
