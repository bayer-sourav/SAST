#!/usr/bin/env python3
"""Stage 2 status report from comparison JSONs."""

from __future__ import annotations

import json
from pathlib import Path

SAST = Path(__file__).resolve().parents[4]
SUM = SAST / "runs/phase2/stage2/summaries"
MANIFEST = SAST / "benchmark/phases/phase2/stage2/MANIFEST.json"
OUT = SUM / "STAGE2_REPORT.md"


def main() -> None:
    cells = json.loads(MANIFEST.read_text())["cells"]
    lines = ["# Phase 2 Stage 2 report\n", f"Manifest: `{MANIFEST.relative_to(SAST)}`\n"]

    for fs in (0, 3):
        fp_p = SUM / f"comparison_fp_think_on_fs{fs}.json"
        tp_p = SUM / f"comparison_tp_think_on_fs{fs}.json"
        if not fp_p.is_file() and not tp_p.is_file():
            continue
        lines.append(f"## Thinking ON · Few-shot {fs}\n")
        lines.append("| Profile | FPRR (FP track) | VDR (TP track) | SRS |\n")
        lines.append("| --- | --- | --- | --- |\n")
        fp = json.loads(fp_p.read_text()) if fp_p.is_file() else {}
        tp = json.loads(tp_p.read_text()) if tp_p.is_file() else {}
        for c in cells:
            if c["fewshot"] != fs:
                continue
            prof = c["profile"]
            key = f"SLM ({prof})"
            fprr = fp.get(key, {}).get("fprr")
            vdr = tp.get(key, {}).get("vdr")
            if fprr is None and vdr is None:
                continue
            srs = (float(fprr or 0) + float(vdr or 0)) / 2 if fprr is not None and vdr is not None else None
            lines.append(
                f"| {prof} | {fprr*100:.1f}% | {vdr*100:.1f}% | {srs*100:.1f}% |\n"
                if srs is not None
                else f"| {prof} | — | — | — |\n"
            )
        lines.append("\n")

    OUT.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
