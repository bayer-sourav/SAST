#!/usr/bin/env python3
"""Phase 2 progress across thinking × few-shot × profile × track."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SAST = Path(__file__).resolve().parents[3]
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

from benchmark.triage_labels import VALID_LABELS  # noqa: E402

CORE_PROFILES = (
    "qwen3_4b_bnb",
    "qwen3_8b_bnb",
    "qwen3_14b_bnb",
    "qwen3_coder_30b_bnb",
)
EXTENSION_PROFILES = (
    "qwen3_5_4b_bnb",
    "qwen3_5_9b_bnb",
)
PROFILES = CORE_PROFILES + EXTENSION_PROFILES
TARGET = 200
TRACKS = {
    "fp": _SAST / "runs/phase2/fp",
    "tp": _SAST / "runs/phase2/tp",
    "bl": _SAST / "runs/phase2/bl",
}


def _count(runs_root: Path, profile: str, thinking: str, fewshot: int) -> int:
    d = runs_root / f"thinking_{thinking}" / f"fewshot_{fewshot}" / profile / "llm"
    if not d.is_dir():
        return 0
    n = 0
    for p in d.iterdir():
        rp = p / "agent-llm-triage-result.json"
        if not rp.is_file():
            continue
        try:
            lbl = str(json.loads(rp.read_text(encoding="utf-8")).get("label", "")).strip().upper()
        except json.JSONDecodeError:
            continue
        if lbl in VALID_LABELS:
            n += 1
    return n


def main() -> None:
    total_done = 0
    total_target = TARGET * len(PROFILES) * len(TRACKS) * 2 * 2  # thinking × fewshot

    print("Phase 2 progress (test 200/track; thinking off+on; fewshot 0+3)")
    print(f"Profiles: {', '.join(PROFILES)}\n")
    for thinking in ("off", "on"):
        print(f"=== thinking {thinking} ===")
        for track, root in TRACKS.items():
            for fewshot in (0, 3):
                print(f"  -- {track.upper()} fewshot={fewshot} --")
                for profile in PROFILES:
                    c = _count(root, profile, thinking, fewshot)
                    total_done += c
                    status = "done" if c >= TARGET else f"{c}/{TARGET}"
                    print(f"    {profile:<28} {status}")
        print()

    print(f"Overall valid results: {total_done}/{total_target}")


if __name__ == "__main__":
    main()
