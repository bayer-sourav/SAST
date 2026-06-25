#!/usr/bin/env python3
"""Print Phase 3B training / CSS eval status from logs and artifacts."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
LOG = _sast / "runs/phase3/stage3b/logs/phase3b.log"
LORA = _sast / "runs/phase3/stage3b/lora/r32"


def _tail_loss_lines(text: str, n: int = 3) -> list[str]:
    return [ln for ln in text.splitlines() if "'loss'" in ln][-n:]


def _step_progress(text: str) -> str | None:
    for ln in reversed(text.splitlines()):
        m = re.search(r"(\d+)%\|.*?(\d+)/(\d+)", ln)
        if m:
            return f"step {m.group(2)}/{m.group(3)} ({m.group(1)}%)"
    return None


def _css_epochs() -> list[dict]:
    out: list[dict] = []
    root = _sast / "runs/phase3/stage3b/val_eval/r32"
    if not root.is_dir():
        return out
    for d in sorted(root.glob("epoch-*")):
        css = d / "css_result.json"
        if css.is_file():
            out.append(json.loads(css.read_text()))
    return out


def main() -> None:
    print("=== Phase 3B status ===")
    if not LOG.is_file():
        print(f"log missing: {LOG}")
        sys.exit(1)
    text = LOG.read_text(errors="replace")
    for ln in _tail_loss_lines(text):
        print(f"  {ln.strip()}")
    prog = _step_progress(text)
    if prog:
        print(f"  progress: {prog}")

    if "[css]" in text:
        css_lines = [ln.strip() for ln in text.splitlines() if "[css]" in ln or "[Qwen/vLLM]" in ln]
        print("\n--- CSS / vLLM (last 8 lines) ---")
        for ln in css_lines[-8:]:
            print(f"  {ln}")

    rc0 = text.count("[rc=0]")
    rc1 = text.count("[rc=1]")
    if rc0 or rc1:
        print(f"\n--- infer rc counts (log) --- rc=0: {rc0}  rc=1: {rc1}")

    css_done = _css_epochs()
    if css_done:
        print("\n--- CSS results ---")
        for r in css_done:
            c = r.get("css") or {}
            print(
                f"  epoch={r.get('epoch')} css={c.get('css')} "
                f"eligible={not c.get('disqualified')} srs={r.get('metrics', {}).get('srs')}"
            )

    ckpts = sorted(LORA.glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[-1])) if LORA.is_dir() else []
    if ckpts:
        print(f"\n--- checkpoints --- latest: {ckpts[-1].name}")


if __name__ == "__main__":
    main()
