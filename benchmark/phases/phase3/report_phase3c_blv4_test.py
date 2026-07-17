#!/usr/bin/env python3
"""Phase 3C blv4 test report vs Stage 2, original 3C, and 3B ship."""

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

MANIFEST = _sast / "benchmark/phases/phase3/stage3c_blv4/MANIFEST.json"
SUM = _sast / "runs/phase3/stage3c_blv4/summaries"
SUM3C = _sast / "runs/phase3/stage3c/summaries"
SUM3B = _sast / "runs/phase3/stage3b/summaries"
EVAL = _sast / "runs/phase3/stage3c_blv4/eval"
STAGE2_BASE = _sast / "runs/phase2/stage2"
OUT = SUM / "PHASE3C_BLV4_TEST_REPORT.md"
OUT_CM = SUM / "confusion_matrix_comparison.json"
PROFILE = "qwen3_5_9b_bnb"
ROW = _model_row_name(PROFILE)
TEST_N = 600


def _load(path: Path) -> dict:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _row(data: dict) -> dict:
    return data.get(ROW) or {}


def _load_track_metrics(summ: Path, suffix: str = "") -> tuple[dict, dict, dict]:
    fp_m = _row(_load(summ / f"comparison_fp_phase3a{suffix}.json"))
    tp_m = _row(_load(summ / f"comparison_tp_phase3a{suffix}.json"))
    bl_m = _row(_load(summ / f"comparison_bl_phase3a{suffix}.json"))
    return fp_m, tp_m, bl_m


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


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:.1f}%"


def _delta_pp(val: float | None, base: float) -> str:
    if val is None:
        return "—"
    d = (val - base) * 100
    return f"{'+' if d >= 0 else ''}{d:.1f}pp"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    baseline = manifest["baseline_stage2"]
    ship3b = manifest.get("baseline_phase3b_ship") or {}
    best = manifest.get("outputs", {}).get("global_best", "runs/phase3/stage3c_blv4/lora/best")
    rerank = _load(SUM / "css_rerank_best.json")
    best_epoch = (rerank.get("best") or {}).get("epoch")
    best_css = ((rerank.get("best") or {}).get("css") or {}).get("css")

    fp_m, tp_m, bl_m = _load_track_metrics(SUM)
    fprr = fp_m.get("fprr")
    vdr = tp_m.get("vdr")
    srs = compute_srs(fp_m, tp_m, bl_m or None, test_n=TEST_N)
    penalty = srs_penalty_from_tracks(fp_m, tp_m, bl_m or None, test_n=TEST_N)
    missing = (
        int(fp_m.get("missing", 0))
        + int(tp_m.get("missing", 0))
        + int(bl_m.get("missing", 0))
    )
    evaluated = TEST_N - missing

    # Original 3C (HTML / reports)
    fp3c, tp3c, bl3c = _load_track_metrics(SUM3C)
    srs3c = compute_srs(fp3c, tp3c, bl3c or None, test_n=TEST_N) if fp3c or tp3c else None

    # 3B ship
    fp3b, tp3b, bl3b = _load_track_metrics(SUM3B, "_fs0_off_best")
    srs3b = compute_srs(fp3b, tp3b, bl3b or None, test_n=TEST_N) if fp3b or tp3b else ship3b.get("srs")

    stage2_cm = confusion_for_run(STAGE2_BASE, PROFILE, thinking="on", fewshot=3)
    phase3_cm = confusion_for_run(EVAL, PROFILE, thinking="off", fewshot=0)

    s2_srs = float(baseline["srs"])
    s2_vdr = float(baseline["vdr"])
    s2_fprr = float(baseline["fprr"])

    gates = manifest.get("success_gates") or {}
    beat_s2 = srs is not None and srs > s2_srs
    fprr_ok = fprr is not None and fprr >= float(gates.get("fprr_target") or s2_fprr)
    vdr_ok = vdr is not None and vdr >= float(gates.get("vdr_floor") or 0.9)

    lines = [
        "# Phase 3C blv4 test eval report",
        "",
        f"**Adapter:** epoch **{best_epoch}** (`{best}`) · full-val CSS={best_css}  ",
        "**Infer:** fs0 · thinking off · v7-ship  ",
        "**Train:** confirmatory 3C on BL v4 synthetics (`BenchmarkTest28xxx`) · json_only · r=32",
        "",
        f"**Coverage:** {evaluated}/{TEST_N} evaluated · **missing={missing}**",
        "",
        "## Headline metrics",
        "",
        "| Metric | blv4 | Original 3C | 3B ship | Stage 2 | Δ vs S2 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| SRS | {_pct(srs)} | {_pct(srs3c)} | {_pct(srs3b if isinstance(srs3b, float) else ship3b.get('srs'))} | {_pct(s2_srs)} | {_delta_pp(srs, s2_srs)} |",
        f"| VDR | {_pct(vdr)} | {_pct(tp3c.get('vdr'))} | {_pct(tp3b.get('vdr') or ship3b.get('vdr'))} | {_pct(s2_vdr)} | {_delta_pp(vdr, s2_vdr)} |",
        f"| FPRR | {_pct(fprr)} | {_pct(fp3c.get('fprr'))} | {_pct(fp3b.get('fprr') or ship3b.get('fprr'))} | {_pct(s2_fprr)} | {_delta_pp(fprr, s2_fprr)} |",
        "",
        "## Success gates",
        "",
        f"| Gate | Target | Result |",
        f"| --- | --- | --- |",
        f"| Beat Stage 2 SRS | > {_pct(s2_srs)} | {'PASS' if beat_s2 else 'FAIL'} ({_pct(srs)}) |",
        f"| FPRR target | ≥ {_pct(float(gates.get('fprr_target') or s2_fprr))} | {'PASS' if fprr_ok else 'FAIL'} ({_pct(fprr)}) |",
        f"| VDR floor | ≥ {_pct(float(gates.get('vdr_floor') or 0.9))} | {'PASS' if vdr_ok else 'FAIL'} ({_pct(vdr)}) |",
        "",
        f"**Verdict:** {'SHIP CANDIDATE' if beat_s2 and fprr_ok and vdr_ok else 'NOT YET — does not beat Stage 2 / miss gates'}",
        "",
        "## Coverage by track",
        "",
        "| Track | Evaluated | Missing |",
        "| --- | ---: | ---: |",
        f"| FP | {int(fp_m.get('evaluated') or 0)} | {int(fp_m.get('missing') or 0)} |",
        f"| TP | {int(tp_m.get('evaluated') or 0)} | {int(tp_m.get('missing') or 0)} |",
        f"| BL | {int(bl_m.get('evaluated') or 0)} | {int(bl_m.get('missing') or 0)} |",
        "",
        "## SRS penalty breakdown",
        "",
    ]
    if penalty:
        bd = penalty.get("breakdown") or {}
        lines.extend(
            [
                "| Track | Penalty | Main driver |",
                "| --- | ---: | --- |",
                f"| FP | {float((bd.get('FP') or {}).get('penalty', 0)):.1f} | FP→TP |",
                f"| TP | {float((bd.get('TP') or {}).get('penalty', 0)):.1f} | TP→FP (×3) |",
                f"| BL | {float((bd.get('BL') or {}).get('penalty', 0)):.1f} | BL→FP (×1.5) |",
                f"| **Total** | **{float(penalty.get('total_penalty', 0)):.1f}** | SRS = 1 − total/(600×3) |",
                "",
            ]
        )

    lines.extend(
        [
            "## Confusion matrix — blv4 (fs0_off)",
            "",
            *_fmt_matrix(phase3_cm),
            "",
            "## Confusion matrix — Stage 2 GOOD (think-on fs3)",
            "",
            *_fmt_matrix(stage2_cm),
            "",
            "## Interpretation",
            "",
            "- **vs original 3C:** same recipe on refreshed BL train; compare FPRR/VDR tradeoff.",
            "- **vs 3B ship:** 3B = higher VDR; 3C-family = higher FPRR when it works.",
            "- **vs Stage 2:** Stage 2 remains the quality bar (think-on fs3, slower).",
            "- **Integration:** only consider blv4 if gates pass; otherwise keep Stage 2 recipe or 3B ep4 as interim latency path.",
            "",
            "## Artifacts",
            "",
            f"- Summaries: `{SUM.relative_to(_sast)}/`",
            f"- Eval: `{EVAL.relative_to(_sast)}/`",
            f"- Gap-fill log: `runs/phase3/stage3c_blv4/logs/test_rescore.log`",
            "",
        ]
    )

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    OUT_CM.write_text(
        json.dumps(
            {
                "blv4": phase3_cm,
                "stage2": stage2_cm,
                "metrics": {
                    "srs": srs,
                    "vdr": vdr,
                    "fprr": fprr,
                    "missing": missing,
                    "srs_original_3c": srs3c,
                    "srs_3b_ship": srs3b if isinstance(srs3b, float) else ship3b.get("srs"),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {OUT}", flush=True)
    print(
        f"SRS={_pct(srs)} VDR={_pct(vdr)} FPRR={_pct(fprr)} missing={missing} "
        f"gates beat_s2={beat_s2} fprr_ok={fprr_ok} vdr_ok={vdr_ok}",
        flush=True,
    )


if __name__ == "__main__":
    main()
