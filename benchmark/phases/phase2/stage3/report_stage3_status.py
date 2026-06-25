#!/usr/bin/env python3
"""Stage 3 status report with target gate check (VDR > 95%, FPRR >= 90%)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SAST = Path(__file__).resolve().parents[4]
if str(SAST) not in sys.path:
    sys.path.insert(0, str(SAST))

from benchmark.srs import compute_srs  # noqa: E402

SUM = SAST / "runs/phase2/stage3/summaries"
MANIFEST = SAST / "benchmark/phases/phase2/stage3/MANIFEST.json"
OUT = SUM / "STAGE3_REPORT.md"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text())
    target = manifest["target"]
    vdr_min = float(target["vdr_min"])
    fprr_min = float(target["fprr_min"])
    lines = [
        "# Phase 2 Stage 3 report\n",
        f"Target: VDR > {vdr_min*100:.0f}%, FPRR >= {fprr_min*100:.0f}%\n",
        f"Manifest: `{MANIFEST.relative_to(SAST)}`\n\n",
        "| Cell | Profile | Prompt | FPRR | VDR | SRS | Pass |\n",
        "| --- | --- | --- | --- | --- | --- | --- |\n",
    ]
    for cell in manifest["cells"]:
        cid = cell["id"]
        prof = cell["profile"]
        pv = cell["prompt_version"]
        fp_p = SUM / f"{cid}_fp.json"
        tp_p = SUM / f"{cid}_tp.json"
        bl_p = SUM / f"{cid}_bl.json"
        if not fp_p.is_file() and not tp_p.is_file():
            lines.append(f"| {cid} | {prof} | {pv} | — | — | — | — |\n")
            continue
        fp = json.loads(fp_p.read_text()) if fp_p.is_file() else {}
        tp = json.loads(tp_p.read_text()) if tp_p.is_file() else {}
        bl = json.loads(bl_p.read_text()) if bl_p.is_file() else {}
        key = f"SLM ({prof})"
        fp_m = fp.get(key, {})
        tp_m = tp.get(key, {})
        bl_m = bl.get(key)
        fprr = fp_m.get("fprr")
        vdr = tp_m.get("vdr")
        if fprr is None and vdr is None:
            lines.append(f"| {cid} | {prof} | {pv} | — | — | — | — |\n")
            continue
        srs = compute_srs(fp_m, tp_m, bl_m)
        if srs is None and fprr is not None and vdr is not None:
            srs = (float(fprr) + float(vdr)) / 2
        passed = (
            vdr is not None
            and fprr is not None
            and float(vdr) > vdr_min
            and float(fprr) >= fprr_min
        )
        lines.append(
            f"| {cid} | {prof} | {pv} | "
            f"{fprr*100:.1f}% | {vdr*100:.1f}% | {srs*100:.1f}% | "
            f"{'YES' if passed else 'no'} |\n"
        )
    lines.append("\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
