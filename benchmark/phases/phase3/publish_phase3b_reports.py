#!/usr/bin/env python3
"""Copy Phase 3B summaries + benchmark tables into reports/ for git-friendly publishing."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

_SAST = Path(__file__).resolve().parents[3]
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

from benchmark.phases.phase3.phase3b_benchmark import (  # noqa: E402
    load_all_test_cells,
    load_best_epoch,
    load_fs0_off_rerank,
)

REPORTS = _SAST / "reports/phase3b"
SUM = _SAST / "runs/phase3/stage3b/summaries"
BENCH = _SAST / "runs/phase3/stage3b/benchmark"

COPY_MARKDOWN = (
    "PHASE3B_TEST_REPORT.md",
    "PHASE3B_ABLATIONS_REPORT.md",
    "PHASE3B_FS0_OFF_BEST_TEST.md",
)

COPY_JSON = (
    "css_rescore_summary.json",
    "css_fs0_off_rerank.json",
    "comparison_fp_phase3a.json",
    "comparison_tp_phase3a.json",
    "comparison_bl_phase3a.json",
    "comparison_fp_phase3a_fs0_off.json",
    "comparison_tp_phase3a_fs0_off.json",
    "comparison_bl_phase3a_fs0_off.json",
    "comparison_fp_phase3a_fs0_off_best.json",
    "comparison_tp_phase3a_fs0_off_best.json",
    "comparison_bl_phase3a_fs0_off_best.json",
)

COPY_BENCH = (
    "PHASE3B_BENCHMARK.html",
    "phase3b_benchmark_summary.json",
    "phase3b_confusion_comparison.json",
)


def _relativize_paths(obj: object) -> object:
    if isinstance(obj, dict):
        return {k: _relativize_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_relativize_paths(v) for v in obj]
    if isinstance(obj, str) and obj.startswith(str(_SAST)):
        return str(Path(obj).relative_to(_SAST))
    return obj


def _write_complete_md() -> None:
    baseline = {"srs": 0.925, "vdr": 0.925, "fprr": 0.735}
    train = load_best_epoch()
    rerank = load_fs0_off_rerank()
    cells = {c["id"]: c for c in load_all_test_cells()}
    ship = cells.get("phase3b_fs0_off_best") or {}

    lines = [
        "# Phase 3B — Complete Record",
        "",
        "**Status:** Primary path complete (distilled LoRA r=32)  ",
        "**Ship adapter:** `runs/phase3/stage3b/lora/best_fs0_off` (epoch 4, val rerank)  ",
        "**Next:** Phase 3C — fs0-aligned retrain to close FPRR gap vs Stage 2",
        "",
        "## Headline test results (600-case holdout)",
        "",
        "| Config | Epoch | SRS | FPRR | VDR | Missing | TP→FP |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    order = ("phase3b_fs3_on", "phase3b_fs0_off", "phase3b_fs0_off_best")
    labels = {
        "phase3b_fs3_on": "fs3 + CoT (teacher-matched)",
        "phase3b_fs0_off": "fs0 direct (ep6 adapter)",
        "phase3b_fs0_off_best": "fs0 ship (rerank pick)",
    }
    for cid in order:
        c = cells.get(cid)
        if not c:
            continue
        lines.append(
            f"| {labels[cid]} | {c['epoch']} | {c['srs']*100:.1f}% | "
            f"{c['fprr']*100:.1f}% | {c['vdr']*100:.1f}% | {c['missing']} | {c['critical_tp_fp']} |"
        )

    if ship:
        delta = (ship["srs"] - baseline["srs"]) * 100
        sign = "+" if delta >= 0 else ""
        lines.extend(
            [
                "",
                f"**Stage 2 baseline:** SRS {baseline['srs']*100:.1f}% · "
                f"**Best ship:** SRS {ship['srs']*100:.1f}% ({sign}{delta:.1f}pp) · "
                f"main gap is **FPRR** ({ship['fprr']*100:.1f}% vs {baseline['fprr']*100:.1f}%)",
                "",
                "## Checkpoint selection",
                "",
                f"- **Training CSS (fs3+CoT val):** epoch {train.get('epoch')} · "
                f"CSS {_fmt(train.get('css'))}",
                f"- **Ship rerank (fs0_off val):** epoch {rerank.get('epoch')} · "
                f"val SRS {_pct(rerank.get('val_srs'))}",
                "",
                "## Artifacts in this folder",
                "",
                "| File | Description |",
                "| --- | --- |",
                "| `PHASE3B_COMPLETE.md` | This document |",
                "| `PHASE3B_BENCHMARK.html` | CSS + confusion matrices |",
                "| `PHASE3B_ABLATIONS_REPORT.md` | Inference ablation table |",
                "| `PHASE3B_TEST_REPORT.md` | fs3-on primary test report |",
                "| `PHASE3B_FS0_OFF_BEST_TEST.md` | Ship config test summary |",
                "| `css_fs0_off_rerank.json` | Val rerank per epoch |",
                "| `comparison_*_phase3a*.json` | Track-level test metrics |",
                "",
                "## Regenerate",
                "",
                "```bash",
                "cd /path/to/SAST",
                "./benchmark/phases/phase3/rebuild_benchmarks.sh",
                "```",
            ]
        )

    (REPORTS / "PHASE3B_COMPLETE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(x: float | None) -> str:
    return f"{float(x):.3f}" if x is not None else "—"


def _pct(x: float | None) -> str:
    return f"{float(x)*100:.1f}%" if x is not None else "—"


def main() -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    for name in COPY_MARKDOWN:
        src = SUM / name
        if src.is_file():
            shutil.copy2(src, REPORTS / name)
    for name in COPY_JSON:
        src = SUM / name
        if not src.is_file():
            continue
        doc = json.loads(src.read_text(encoding="utf-8"))
        (REPORTS / name).write_text(
            json.dumps(_relativize_paths(doc), indent=2) + "\n",
            encoding="utf-8",
        )
    for name in COPY_BENCH:
        src = BENCH / name
        if src.is_file():
            shutil.copy2(src, REPORTS / name)
    _write_complete_md()
    readme = REPORTS / "README.md"
    readme.write_text(
        "# Phase 3B reports\n\n"
        "Git-friendly bundle of Phase 3B benchmark results. "
        "Heavy run artifacts (LoRA weights, per-case eval JSON) stay local under "
        "`runs/phase3/stage3b/` and are gitignored.\n\n"
        "Start with **[PHASE3B_COMPLETE.md](PHASE3B_COMPLETE.md)**.\n",
        encoding="utf-8",
    )
    print(f"Published {REPORTS}")


if __name__ == "__main__":
    main()
