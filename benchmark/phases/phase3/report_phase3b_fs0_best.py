#!/usr/bin/env python3
"""Phase 3B ship config test report (fs0_off_best / epoch 4 rerank pick)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.confusion_matrix import confusion_for_run  # noqa: E402
from benchmark.srs import compute_srs  # noqa: E402
from benchmark.summarize_triage import _model_row_name  # noqa: E402

MANIFEST = _sast / "benchmark/phases/phase3/stage3b/MANIFEST.json"
SUM = _sast / "runs/phase3/stage3b/summaries"
OUT = SUM / "PHASE3B_FS0_OFF_BEST_TEST.md"
EVAL = _sast / "runs/phase3/stage3b/eval_ablation/fs0_off_best"
STAGE2_BASE = _sast / "runs/phase2/stage2"
PROFILE = "qwen3_5_9b_bnb"
ROW = _model_row_name(PROFILE)
SUFFIX = "_fs0_off_best"
TEST_N = 600


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def _row(data: dict) -> dict:
    return data.get(ROW) or {}


def _fmt_matrix(cm: dict) -> list[str]:
    labels = ("TP", "FP", "BL")
    lines = [
        "| Gold \\ Pred | → TP | → FP | → BL | miss |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    matrix = cm.get("matrix") or {}
    missing = cm.get("missing_by_gold") or {}
    for gold in labels:
        row = matrix.get(gold) or {}
        miss = int(missing.get(gold, 0))
        lines.append(
            f"| **{gold}** | {int(row.get('TP', 0))} | {int(row.get('FP', 0))} | "
            f"{int(row.get('BL', 0))} | {miss} |"
        )
    return lines


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    baseline = manifest["baseline_stage2"]
    rerank = _load(SUM / "css_fs0_off_rerank.json").get("best") or {}
    epoch = int(rerank.get("epoch") or 4)

    fp_m = _row(_load(SUM / f"comparison_fp_phase3a{SUFFIX}.json"))
    tp_m = _row(_load(SUM / f"comparison_tp_phase3a{SUFFIX}.json"))
    bl_m = _row(_load(SUM / f"comparison_bl_phase3a{SUFFIX}.json"))
    fprr = fp_m.get("fprr")
    vdr = tp_m.get("vdr")
    srs = compute_srs(fp_m, tp_m, bl_m or None, test_n=TEST_N)

    stage2_cm = confusion_for_run(STAGE2_BASE, PROFILE, thinking="on", fewshot=3)
    phase3_cm = confusion_for_run(EVAL, PROFILE, thinking="off", fewshot=0)

    lines = [
        "# Phase 3B ship test — fs0_off rerank pick",
        "",
        f"**Adapter:** epoch **{epoch}** (`runs/phase3/stage3b/lora/best_fs0_off`)  ",
        f"**Infer:** zero-shot · thinking off · v7-ship  ",
        f"**Val pick:** SRS {rerank.get('val_srs', 0)*100:.1f}% on 600-case validation",
        "",
        f"Baseline (Phase 2 Stage 2 GOOD): SRS **{baseline['srs']*100:.1f}%** "
        f"(VDR {baseline['vdr']*100:.1f}%, FPRR {baseline['fprr']*100:.1f}%)",
        "",
        "## Headline metrics",
        "",
        "| Metric | Phase 3B ship | Stage 2 baseline | Delta |",
        "| --- | --- | --- | --- |",
    ]

    def metric_row(name: str, val: float | None, base: float) -> str:
        if val is None:
            return f"| {name} | — | {base*100:.1f}% | — |"
        delta = (val - base) * 100
        sign = "+" if delta >= 0 else ""
        return f"| {name} | {val*100:.1f}% | {base*100:.1f}% | {sign}{delta:.1f}pp |"

    lines.append(metric_row("SRS", srs, baseline["srs"]))
    lines.append(metric_row("VDR", vdr, baseline["vdr"]))
    lines.append(metric_row("FPRR", fprr, baseline["fprr"]))
    lines.extend(
        [
            "",
            "## Coverage",
            "",
            f"| Track | Coverage | Missing |",
            f"| --- | ---: | ---: |",
            f"| FP | {fp_m.get('coverage', 0)*100:.1f}% | {fp_m.get('missing', '—')} |",
            f"| TP | {tp_m.get('coverage', 0)*100:.1f}% | {tp_m.get('missing', '—')} |",
            f"| BL | {bl_m.get('coverage', 0)*100:.1f}% | {bl_m.get('missing', '—')} |",
            "",
            f"**Verdict:** {'PASS' if srs and srs >= baseline['srs'] else 'NOT YET'} — "
            f"ship SRS {'≥' if srs and srs >= baseline['srs'] else '<'} Stage 2 baseline.",
            "",
            "## Confusion matrix — Phase 3B ship (600 cases)",
            "",
        ]
    )
    lines.extend(_fmt_matrix(phase3_cm))
    lines.extend(
        [
            "",
            f"- **TP→FP critical:** {phase3_cm['critical_tp_fp']}",
            f"- **Missing predictions:** {phase3_cm['missing']}",
            "",
            "## vs fs3-on test (epoch 6, teacher-matched infer)",
            "",
            "Train/serve mismatch: model distilled with fs3+CoT but deployed fs0+direct. "
            "Reranking checkpoints under ship infer improves SRS ~6pp vs fs3-on test and ~1pp vs fs0 on ep6.",
        ]
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    if srs is not None:
        print(f"SRS={srs:.4f} FPRR={fprr:.3f} VDR={vdr:.3f} epoch={epoch}")


if __name__ == "__main__":
    main()
