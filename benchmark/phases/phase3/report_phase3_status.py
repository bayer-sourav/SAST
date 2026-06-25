#!/usr/bin/env python3
"""Phase 3A metrics report vs Phase 2 Stage 2 baseline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.confusion_matrix import confusion_for_run  # noqa: E402
from benchmark.srs import compute_srs  # noqa: E402

SUM = _sast / "runs/phase3/stage3a/summaries"
MANIFEST = _sast / "benchmark/phases/phase3/MANIFEST.json"
OUT = SUM / "PHASE3A_REPORT.md"
PROFILE = "qwen3_5_9b_bnb"
ROW = f"SLM ({PROFILE})"
PHASE3_TEST_N = 600
STAGE2_BASE = _sast / "runs/phase2/stage2"
PHASE3_EVAL = _sast / "runs/phase3/stage3a/eval"


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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

    fp_m = _row(_load(SUM / "comparison_fp_phase3a.json"))
    tp_m = _row(_load(SUM / "comparison_tp_phase3a.json"))
    bl_m = _row(_load(SUM / "comparison_bl_phase3a.json"))
    fprr = fp_m.get("fprr")
    vdr = tp_m.get("vdr")
    srs = compute_srs(fp_m, tp_m, bl_m or None, test_n=PHASE3_TEST_N)
    if srs is None and fprr is not None and vdr is not None:
        srs = (float(fprr) + float(vdr)) / 2

    stage2_cm = confusion_for_run(STAGE2_BASE, PROFILE, thinking="on", fewshot=3)
    phase3_cm = confusion_for_run(PHASE3_EVAL, PROFILE, thinking="on", fewshot=3)

    lines = [
        "# Phase 3A eval report",
        f"Profile: `{PROFILE}` + LoRA adapter (`SAST_LORA_ADAPTER`)",
        f"Baseline (Phase 2 Stage 2 GOOD): SRS **{baseline['srs']*100:.1f}%** "
        f"(VDR {baseline['vdr']*100:.1f}%, FPRR {baseline['fprr']*100:.1f}%)",
        "",
        "## Headline metrics",
        "",
        "| Metric | Phase 3A | Stage 2 baseline | Delta |",
        "| --- | --- | --- | --- |",
    ]

    def metric_row(name: str, val: float | None, base: float) -> str:
        if val is None:
            return f"| {name} | — | {base*100:.1f}% | — |"
        delta = (val - base) * 100
        sign = "+" if delta >= 0 else ""
        return f"| {name} | {val*100:.1f}% | {base*100:.1f}% | {sign}{delta:.1f}pp |"

    lines.append(metric_row("FPRR", fprr, baseline["fprr"]))
    lines.append(metric_row("VDR", vdr, baseline["vdr"]))
    lines.append(metric_row("SRS", srs, baseline["srs"]))
    lines.append("")

    if srs is not None:
        beat = srs >= baseline["srs"]
        lines.append(
            f"**Verdict:** {'PASS' if beat else 'NOT YET'} — "
            f"SRS {'≥' if beat else '<'} Stage 2 baseline."
        )
    else:
        lines.append("**Verdict:** incomplete — run eval first.")

    lines.extend(["", "## Confusion matrix — Phase 3A LoRA (600 cases)", ""])
    lines.extend(_fmt_matrix(phase3_cm))
    lines.extend(
        [
            "",
            f"- **TP track diagonal:** {phase3_cm['diagonal']['TP']}/200 "
            f"({phase3_cm['diagonal']['TP']/200*100:.1f}%) — "
            f"TP→FP critical: **{phase3_cm['critical_tp_fp']}**",
            f"- **FP track diagonal:** {phase3_cm['diagonal']['FP']}/200 "
            f"({phase3_cm['diagonal']['FP']/200*100:.1f}%)",
            f"- **BL track diagonal:** {phase3_cm['diagonal']['BL']}/200 "
            f"({phase3_cm['diagonal']['BL']/200*100:.1f}%)",
            f"- **Missing predictions:** {phase3_cm['missing']}",
            "",
            "## Confusion matrix — Stage 2 GOOD baseline (5.9b_fs3_legacy)",
            "",
        ]
    )
    lines.extend(_fmt_matrix(stage2_cm))
    lines.extend(
        [
            "",
            f"- **TP track diagonal:** {stage2_cm['diagonal']['TP']}/200 "
            f"({stage2_cm['diagonal']['TP']/200*100:.1f}%) — "
            f"TP→FP critical: **{stage2_cm['critical_tp_fp']}**",
            f"- **FP track diagonal:** {stage2_cm['diagonal']['FP']}/200 "
            f"({stage2_cm['diagonal']['FP']/200*100:.1f}%)",
            f"- **BL track diagonal:** {stage2_cm['diagonal']['BL']}/200 "
            f"({stage2_cm['diagonal']['BL']/200*100:.1f}%)",
            "",
            "## Critical misclassifications vs Stage 2 GOOD",
            "",
            "| Transition | Stage 2 GOOD | Phase 3A | Δ |",
            "| --- | ---: | ---: | ---: |",
            f"| TP→FP (missed vuln) | {stage2_cm['critical_tp_fp']} | "
            f"{phase3_cm['critical_tp_fp']} | "
            f"+{phase3_cm['critical_tp_fp'] - stage2_cm['critical_tp_fp']} |",
            f"| BL→FP (over-dismiss) | {stage2_cm['high_bl_fp']} | "
            f"{phase3_cm['high_bl_fp']} | "
            f"+{phase3_cm['high_bl_fp'] - stage2_cm['high_bl_fp']} |",
            f"| FP→TP (noise kept) | {stage2_cm['fp_tp']} | "
            f"{phase3_cm['fp_tp']} | "
            f"{phase3_cm['fp_tp'] - stage2_cm['fp_tp']:+d} |",
            "",
            "Full three-way comparison (Stage 2 GOOD · Phase 2 MINIMUM · Phase 3A) is in "
            "`runs/phase2/phase2_benchmark_tables/BENCHMARK_RESULTS.html` and "
            "`runs/phase2/phase2_benchmark_tables/benchmark_confusion_comparison.json`.",
        ]
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
