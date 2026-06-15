#!/usr/bin/env python3
"""Quick progress check for Phase 2 Stage 3 runs."""

from __future__ import annotations

import json
from pathlib import Path

SAST = Path(__file__).resolve().parents[4]
MANIFEST = SAST / "benchmark/phases/phase2/stage3/MANIFEST.json"
RUNS = SAST / "runs/phase2/stage3"
VALID = frozenset({"TP", "FP", "BL", "UNKNOWN"})


def _count_done(runs_root: Path, profile: str) -> int:
    llm = runs_root / profile / "llm"
    if not llm.is_dir():
        return 0
    n = 0
    for d in llm.iterdir():
        p = d / "agent-llm-triage-result.json"
        if not p.is_file():
            continue
        try:
            lbl = str(json.loads(p.read_text()).get("label", "")).strip().upper()
        except json.JSONDecodeError:
            continue
        if lbl in VALID:
            n += 1
    return n


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    expected = 200
    print(f"Stage 3 progress (expected {expected} per track per cell)\n")
    print(f"{'cell':<12} {'profile':<22} {'prompt':<16} {'FP':>8} {'TP':>8} {'BL':>8}")
    for cell in manifest["cells"]:
        cid = cell["id"]
        prof = cell["profile"]
        pv = cell["prompt_version"]
        fs = cell["fewshot"]
        base = RUNS
        fp_n = _count_done(base / "fp" / f"thinking_on/fewshot_{fs}" / pv, prof)
        tp_n = _count_done(base / "tp" / f"thinking_on/fewshot_{fs}" / pv, prof)
        bl_n = _count_done(base / "bl" / f"thinking_on/fewshot_{fs}" / pv, prof)
        print(f"{cid:<12} {prof:<22} {pv:<16} {fp_n:>4}/{expected} {tp_n:>4}/{expected} {bl_n:>4}/{expected}")

    smoke = RUNS / "smoke" / "smoke_summary.json"
    if smoke.is_file():
        data = json.loads(smoke.read_text())
        print("\nHard-slice smoke:")
        for r in data.get("scores", []):
            mark = "PASS" if r.get("smoke_pass") else "fail"
            print(
                f"  {r['cell_id']}: VDR {r['vdr']}/10 FPRR {r['fprr']}/10 [{mark}]"
            )


if __name__ == "__main__":
    main()
