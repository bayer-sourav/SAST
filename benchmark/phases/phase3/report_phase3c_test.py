#!/usr/bin/env python3
"""Phase 3C test eval report vs Stage 2 and Phase 3B ship baselines."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.confusion_matrix import confusion_for_run  # noqa: E402
from benchmark.srs import compute_srs, srs_penalty_from_tracks  # noqa: E402
from benchmark.summarize_triage import _model_row_name  # noqa: E402

MANIFEST = _sast / "benchmark/phases/phase3/stage3c/MANIFEST.json"
SUM = _sast / "runs/phase3/stage3c/summaries"
SUM3B = _sast / "runs/phase3/stage3b/summaries"
OUT = SUM / "PHASE3C_TEST_REPORT.md"
OUT_NEXT = SUM / "PHASE3C_NEXT.md"
OUT_CM = SUM / "confusion_matrix_comparison.json"
EVAL = _sast / "runs/phase3/stage3c/eval"
PROFILE = "qwen3_5_9b_bnb"
ROW = _model_row_name(PROFILE)
PHASE3_TEST_N = 600
STAGE2_BASE = _sast / "runs/phase2/stage2"


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


def _metric_row(name: str, val: float | None, base: float) -> str:
    if val is None:
        return f"| {name} | — | {base*100:.1f}% | — |"
    delta = (val - base) * 100
    sign = "+" if delta >= 0 else ""
    return f"| {name} | {val*100:.1f}% | {base*100:.1f}% | {sign}{delta:.1f}pp |"


def _load_track_metrics(summ: Path, suffix: str = "") -> tuple[dict, dict, dict]:
    fp_m = _row(_load(summ / f"comparison_fp_phase3a{suffix}.json"))
    tp_m = _row(_load(summ / f"comparison_tp_phase3a{suffix}.json"))
    bl_m = _row(_load(summ / f"comparison_bl_phase3a{suffix}.json"))
    return fp_m, tp_m, bl_m


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    baseline = manifest["baseline_stage2"]
    ship3b = manifest.get("baseline_phase3b_ship") or {}
    best = manifest.get("outputs", {}).get("global_best", "runs/phase3/stage3c/lora/best")

    fp_m, tp_m, bl_m = _load_track_metrics(SUM)
    fprr = fp_m.get("fprr")
    vdr = tp_m.get("vdr")
    srs = compute_srs(fp_m, tp_m, bl_m or None, test_n=PHASE3_TEST_N)
    penalty = srs_penalty_from_tracks(fp_m, tp_m, bl_m or None, test_n=PHASE3_TEST_N)

    fp3b, tp3b, bl3b = _load_track_metrics(SUM3B, "_fs0_off_best")
    srs3b = compute_srs(fp3b, tp3b, bl3b or None, test_n=PHASE3_TEST_N)

    stage2_cm = confusion_for_run(STAGE2_BASE, PROFILE, thinking="on", fewshot=3)
    phase3_cm = confusion_for_run(EVAL, PROFILE, thinking="off", fewshot=0)

    missing = int(fp_m.get("missing", 0)) + int(tp_m.get("missing", 0)) + int(bl_m.get("missing", 0))

    lines = [
        "# Phase 3C test eval report",
        "",
        f"**Adapter:** epoch **6** (`{best}`) · full-val CSS pick  ",
        f"**Infer:** fs0 · thinking off · v7-ship (language-agnostic)  ",
        f"**Train:** json_only targets · fs0_off user prompts · 1283 records · r=32",
        "",
        f"Baseline (Stage 2 GOOD): SRS **{baseline['srs']*100:.1f}%** "
        f"(VDR {baseline['vdr']*100:.1f}%, FPRR {baseline['fprr']*100:.1f}%)  ",
        f"Reference (3B ship ep4): SRS **{ship3b.get('srs', 0)*100:.1f}%** "
        f"(VDR {ship3b.get('vdr', 0)*100:.1f}%, FPRR {ship3b.get('fprr', 0)*100:.1f}%)",
        "",
        "## Headline metrics (594/600 evaluated after gap-fill)",
        "",
        "| Metric | Phase 3C | 3B ship | Stage 2 | Δ vs S2 |",
        "| --- | --- | --- | --- | --- |",
    ]

    def tri(name: str, val: float | None, b3: float, s2: float) -> str:
        if val is None:
            return f"| {name} | — | {b3*100:.1f}% | {s2*100:.1f}% | — |"
        return f"| {name} | {val*100:.1f}% | {b3*100:.1f}% | {s2*100:.1f}% | {(val-s2)*100:+.1f}pp |"

    lines.append(tri("SRS", srs, srs3b or 0, baseline["srs"]))
    lines.append(tri("FPRR", fprr, fp3b.get("fprr"), baseline["fprr"]))
    lines.append(tri("VDR", vdr, tp3b.get("vdr"), baseline["vdr"]))
    lines.extend(
        [
            "",
            "## Coverage",
            "",
            "| Track | Coverage | Missing |",
            "| --- | ---: | ---: |",
            f"| FP | {fp_m.get('coverage', 0)*100:.1f}% | {fp_m.get('missing', '—')} |",
            f"| TP | {tp_m.get('coverage', 0)*100:.1f}% | {tp_m.get('missing', '—')} |",
            f"| BL | {bl_m.get('coverage', 0)*100:.1f}% | {bl_m.get('missing', '—')} |",
            f"| **Total** | | **{missing}** |",
            "",
            "Gap-fill (`rescore_test_eval.py`, 5 rounds) recovered 59/65 missing cases. "
            "Six cases still fail JSON parse at inference (CoT without JSON tail).",
            "",
        ]
    )

    if srs is not None:
        beat = srs >= baseline["srs"]
        lines.append(
            f"**Verdict:** {'PASS' if beat else 'NOT YET'} — "
            f"SRS {'≥' if beat else '<'} Stage 2 baseline."
        )

    lines.extend(
        [
            "",
            "## SRS penalty breakdown (600-case denominator)",
            "",
            "| Track | Evaluated | Missing | Penalty | Main driver |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )
    if penalty:
        drivers = {
            "FP": "FP→TP (1.0 each)",
            "TP": "TP→FP (3.0 each, CRITICAL)",
            "BL": "BL→FP (1.5 each); BL→TP is free",
        }
        for gold, row in penalty.get("breakdown", {}).items():
            lines.append(
                f"| {gold} | {row['evaluated']} | {row['missing']} | "
                f"{row['penalty']:.1f} | {drivers.get(gold, '')} |"
            )
        lines.append(
            f"| **Total** | | | **{penalty['total_penalty']:.1f}** | "
            f"SRS = 1 − penalty / (600×3) = **{srs*100:.1f}%** |"
        )

    lines.extend(["", "## Confusion matrix — Phase 3C (fs0_off)", ""])
    lines.extend(_fmt_matrix(phase3_cm))
    lines.extend(
        [
            "",
            f"- **TP→FP (CRITICAL):** {phase3_cm['critical_tp_fp']} "
            f"(3B ship: 17 · Stage 2: {stage2_cm['critical_tp_fp']})",
            f"- **BL→FP (HIGH):** {phase3_cm['high_bl_fp']} "
            f"(3B ship: 16 · Stage 2: {stage2_cm['high_bl_fp']})",
            f"- **FP→TP:** {phase3_cm['fp_tp']} (3B ship: 63 · Stage 2: {stage2_cm['fp_tp']})",
            f"- **BL→TP (zero penalty):** {phase3_cm['matrix'].get('BL', {}).get('TP', 0)}/200",
            f"- **Predicted BL on any gold:** "
            f"{sum(phase3_cm['matrix'].get(g, {}).get('BL', 0) for g in ('TP','FP','BL'))} "
            "(ship never emits BL — expected)",
            "",
            "## vs Phase 3B ship (same SRS, different error mix)",
            "",
            "3C matches 3B ship on **SRS (~89.9%)** but trades **+12pp FPRR** for **−4pp VDR**:",
            "",
            "- **Win:** fewer false alarms kept (FP→TP 42 vs 63) — FPRR 78.3% vs 66.2%",
            "- **Loss:** more missed vulns (TP→FP 27 vs 17) — VDR 86.3% vs 90.3%",
            "- **Train/serve alignment validated:** val CSS pick epoch 6 = full-val rerank best "
            "(no post-hoc fs0 rerank needed, unlike 3B)",
            "",
            "## Artifacts",
            "",
            "- `runs/phase3/stage3c/summaries/css_rerank_best.json` — val pick epoch 6",
            "- `runs/phase3/stage3c/logs/test_rescore.log` — gap-fill log",
            "- `benchmark/phases/phase3/rescore_test_eval.py` — gap-fill tool",
        ]
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    next_lines = [
        "# Phase 3C — Next course of action",
        "",
        "## Is BL the problem?",
        "",
        "**Not primarily.** BL-gold cases are scored on whether the model dismisses them as FP:",
        "",
        "- BL→**TP** = **zero SRS penalty** (172/199 cases in 3C — good)",
        "- BL→**FP** = 1.5 penalty each (27/199 — similar to Stage 2’s 26/200)",
        "- The model **never predicts BL** at ship time (same as Stage 2) — this is correct",
        "",
        "3C’s main gap vs Stage 2 is **TP→FP** (27 vs 14, CRITICAL ×3 penalty), not BL track volume.",
        "BL penalties contribute ~43.5 / 182.5 total penalty points; TP track contributes ~90.",
        "",
        "## Would removing BL from fine-tuning help?",
        "",
        "**Probably not — low confidence, possible harm.**",
        "",
        "| Argument | Detail |",
        "| --- | --- |",
        "| Train set | 362/1283 export records are BL-gold; teacher labels them TP or FP |",
        "| What BL teaches | Ambiguous boundary between TP and FP — not the BL output class |",
        "| 3A failure mode | Model **over-predicted BL**; 3C fixed that via teacher + json_only |",
        "| Removing BL | Drops ~28% of training signal on hard cases; val/test still penalize BL→FP |",
        "",
        "A cleaner ablation (**3D-a**): train on FP+TP only (~920 records after export drops) "
        "and compare VDR/FPRR tradeoff — but expect **VDR regression** unless boundary cases "
        "are replaced (e.g. hard-negative mining from BL→FP errors).",
        "",
        "## Recommended next steps (priority order)",
        "",
        "### 1. Phase 3D — VDR-focused correction (highest leverage)",
        "",
        "Target the **27 TP→FP** errors (not BL removal):",
        "",
        "- **Hard-negative mining:** oversample train cases matching 3C TP→FP confusion "
        "(same rule families / code patterns from error analysis)",
        "- **CSS reweight:** add TP→FP penalty to val CSS or use constrained pick "
        "(VDR floor 0.90 + max FPRR) instead of pure CSS",
        "- **Rank 64** json_only with same ship config — more capacity for subtle TP recall",
        "",
        "### 2. Recover training data (cheap win)",
        "",
        "- Export dropped **217** cases (99 missing teacher, 97 unparseable, 21 too long) — "
        "re-run teacher JSON repair or raise seq cap selectively",
        "- Full 1500 distillation may stabilize VDR without changing architecture",
        "",
        "### 3. Pareto ensemble / dual adapter (no retrain)",
        "",
        "- 3C epoch 6 = high FPRR; 3B ship ep4 = high VDR — evaluate **val-weighted blend** "
        "or route by rule class if error analysis clusters",
        "",
        "### 4. Preference tuning (3E)",
        "",
        "- DPO/KTO on pairs from Stage 2 vs 3C delta: TP→FP (reject), FP→TP (reject), "
        "BL→FP (reject) using Stage 2 as preferred",
        "",
        "### 5. Inference robustness",
        "",
        "- Six test cases fail JSON parse — add stricter json_only retry at serve time "
        "(does not affect SRS much but affects coverage)",
        "",
        "## Success criteria for 3D",
        "",
        "| Gate | Target |",
        "| --- | --- |",
        "| SRS | ≥ 92.5% (Stage 2) |",
        "| VDR | ≥ 90% |",
        "| FPRR | ≥ 73.5% (maintain 3C gain vs 3B) |",
        "| TP→FP | ≤ 17 |",
        "",
        "## Not recommended",
        "",
        "- Removing BL from train/val/test splits (changes benchmark)",
        "- Returning to fs3+CoT train (reintroduces train/serve mismatch)",
        "- Gold-label SFT (3A showed VDR collapse)",
    ]
    OUT_NEXT.write_text("\n".join(next_lines) + "\n", encoding="utf-8")

    OUT_CM.write_text(
        json.dumps(
            {
                "phase3c": phase3_cm,
                "stage2_good": stage2_cm,
                "metrics": {
                    "srs": srs,
                    "fprr": fprr,
                    "vdr": vdr,
                    "missing": missing,
                    "penalty_breakdown": penalty.get("breakdown") if penalty else None,
                },
                "baseline_stage2": baseline,
                "baseline_3b_ship": ship3b,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Wrote {OUT}")
    print(f"Wrote {OUT_NEXT}")
    print(f"Wrote {OUT_CM}")
    if srs is not None:
        print(
            f"SRS={srs:.4f} FPRR={fprr:.3f} VDR={vdr:.3f} missing={missing}"
        )


if __name__ == "__main__":
    main()
