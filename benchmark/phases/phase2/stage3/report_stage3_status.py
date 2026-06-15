#!/usr/bin/env python3
"""Stage 3 status report with target gate check (VDR > 95%, FPRR >= 90%)."""

from __future__ import annotations

import json
from pathlib import Path

SAST = Path(__file__).resolve().parents[4]
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
        if not fp_p.is_file() and not tp_p.is_file():
            lines.append(f"| {cid} | {prof} | {pv} | — | — | — | — |\n")
            continue
        fp = json.loads(fp_p.read_text()) if fp_p.is_file() else {}
        tp = json.loads(tp_p.read_text()) if tp_p.is_file() else {}
        key = f"SLM ({prof})"
        fprr = fp.get(key, {}).get("fprr")
        vdr = tp.get(key, {}).get("vdr")
        if fprr is None and vdr is None:
            lines.append(f"| {cid} | {prof} | {pv} | — | — | — | — |\n")
            continue
        srs = (float(fprr or 0) + float(vdr or 0)) / 2 if fprr is not None and vdr is not None else None
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
