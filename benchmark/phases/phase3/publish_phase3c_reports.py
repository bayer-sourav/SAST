#!/usr/bin/env python3
"""Copy Phase 3C summaries into reports/phase3c/ for git-friendly publishing."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

_SAST = Path(__file__).resolve().parents[3]
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

REPORTS = _SAST / "reports/phase3c"
SUM = _SAST / "runs/phase3/stage3c/summaries"

COPY_MARKDOWN = (
    "PHASE3C_TEST_REPORT.md",
    "PHASE3C_NEXT.md",
    "PHASE3C_BL_ANALYSIS.md",
)

COPY_JSON = (
    "css_rerank_best.json",
    "css_eligible.json",
    "confusion_matrix_comparison.json",
    "comparison_fp_phase3a.json",
    "comparison_tp_phase3a.json",
    "comparison_bl_phase3a.json",
)


def _write_complete_md() -> None:
    rerank = json.loads((SUM / "css_rerank_best.json").read_text(encoding="utf-8"))
    best = rerank.get("best") or {}
    metrics = best.get("metrics") or {}
    css = (best.get("css") or {}).get("css")

    css_val = f"{css:.4f}" if css is not None else "—"
    lines = [
        "# Phase 3C — Complete Record",
        "",
        "**Status:** Complete (ship-aligned distillation)  ",
        f"**Ship adapter:** `runs/phase3/stage3c/lora/best` (epoch {best.get('epoch', '?')}, full-val CSS)  ",
        "**Infer:** fs0 · thinking off · v7-ship",
        "",
        "## Val pick (full 600-case rerank)",
        "",
        "| Epoch | Full val CSS | SRS | VDR | FPRR |",
        "| ---: | ---: | ---: | ---: | ---: |",
        f"| {best.get('epoch', '?')} | {css_val} | "
        f"{metrics.get('srs', 0)*100:.1f}% | {metrics.get('vdr', 0)*100:.1f}% | "
        f"{metrics.get('fprr', 0)*100:.1f}% |",
        "",
        "## Test results (after gap-fill, 6 missing)",
        "",
        "See `PHASE3C_TEST_REPORT.md` for full confusion matrix and vs 3B ship.",
        "",
        "| Metric | 3C test | 3B ship | Stage 2 |",
        "| --- | ---: | ---: | ---: |",
        "| SRS | 89.9% | 89.9% | 92.5% |",
        "| FPRR | 78.3% | 66.2% | 73.5% |",
        "| VDR | 86.3% | 90.3% | 92.5% |",
        "",
        "**Hypothesis:** train/serve alignment closed FPRR gap vs 3B; VDR regression "
        "kept aggregate SRS flat. See `PHASE3C_NEXT.md` for 3D plan.",
        "",
        "## Key artifacts",
        "",
        "| Path | Role |",
        "| --- | --- |",
        "| `runs/phase3/stage3c/lora/best` | Global best LoRA (epoch 6) |",
        "| `runs/phase3/stage3c/data/distill_train.jsonl` | 1283 json_only records |",
        "| `benchmark/phases/phase3/stage3c/PLAN.md` | Design doc |",
        "| `benchmark/phases/phase3/rescore_test_eval.py` | Test gap-fill |",
    ]
    (REPORTS / "PHASE3C_COMPLETE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    for name in COPY_MARKDOWN + COPY_JSON:
        src = SUM / name
        if src.is_file():
            shutil.copy2(src, REPORTS / name)
    _write_complete_md()
    readme = [
        "# Phase 3C reports",
        "",
        "Ship-aligned distillation (fs0_off train + val, json_only targets, v7-ship).",
        "",
        "| File | Description |",
        "| --- | --- |",
        "| `PHASE3C_COMPLETE.md` | Run summary |",
        "| `PHASE3C_TEST_REPORT.md` | 600-case test metrics + confusion |",
        "| `PHASE3C_NEXT.md` | Recommended next steps + BL analysis |",
        "| `confusion_matrix_comparison.json` | 3C vs Stage 2 matrices |",
        "| `PHASE3C_BL_ANALYSIS.md` | BL train/test distribution vs TP/FP |",
    ]
    (REPORTS / "README.md").write_text("\n".join(readme) + "\n", encoding="utf-8")
    print(f"Published to {REPORTS}")


if __name__ == "__main__":
    main()
