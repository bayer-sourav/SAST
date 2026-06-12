#!/usr/bin/env python3
"""Phase 2 Stage 2 progress: selected cells × FP/TP/BL tracks."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SAST = Path(__file__).resolve().parents[4]
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

from benchmark.triage_labels import VALID_LABELS  # noqa: E402

MANIFEST = Path(__file__).resolve().parent / "MANIFEST.json"
LOG_DIR = _SAST / "runs/phase2/stage2/logs"
TARGET = 200
TRACKS = {
    "fp": _SAST / "runs/phase2/stage2/fp",
    "tp": _SAST / "runs/phase2/stage2/tp",
    "bl": _SAST / "runs/phase2/stage2/bl",
}


def _load_cells() -> list[dict]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return list(data.get("cells") or [])


def _count(runs_root: Path, profile: str, fewshot: int) -> int:
    d = runs_root / "thinking_on" / f"fewshot_{fewshot}" / profile / "llm"
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


def _run_state() -> str:
    finished = LOG_DIR / "finished_at.txt"
    if finished.is_file():
        return f"finished ({finished.read_text(encoding='utf-8').strip()})"
    master = LOG_DIR / "master.log"
    if master.is_file() and master.stat().st_size > 0:
        return "running (see runs/phase2/stage2/logs/master.log)"
    return "not started"


def main() -> None:
    cells = _load_cells()
    total_done = 0
    total_target = TARGET * len(cells) * len(TRACKS)

    print("Phase 2 Stage 2 progress (200/track; thinking ON only)")
    print(f"State: {_run_state()}")
    print(f"Manifest: {MANIFEST.relative_to(_SAST)}")
    print(f"Prompt: unified-4label-v7-balanced\n")

    for cell in cells:
        cid = cell.get("id", "?")
        profile = cell["profile"]
        fewshot = int(cell["fewshot"])
        cfg = cell.get("few_shot_config") or "—"
        note = cell.get("note", "")
        print(f"=== {cid} ({profile}, fs={fewshot}, config={cfg}) ===")
        if note:
            print(f"    {note}")
        cell_done = 0
        cell_target = TARGET * len(TRACKS)
        for track, root in TRACKS.items():
            c = _count(root, profile, fewshot)
            cell_done += c
            total_done += c
            status = "done" if c >= TARGET else f"{c}/{TARGET}"
            print(f"  {track.upper():3s}  {status}")
        pct = 100.0 * cell_done / cell_target if cell_target else 0.0
        print(f"  cell total: {cell_done}/{cell_target} ({pct:.1f}%)\n")

    pct_all = 100.0 * total_done / total_target if total_target else 0.0
    print(f"Overall valid results: {total_done}/{total_target} ({pct_all:.1f}%)")
    print("\nLogs:  tail -f runs/phase2/stage2/logs/master.log")
    print("Report: runs/phase2/stage2/summaries/STAGE2_REPORT.md (after completion)")


if __name__ == "__main__":
    main()
