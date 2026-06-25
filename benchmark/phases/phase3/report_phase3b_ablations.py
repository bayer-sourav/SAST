#!/usr/bin/env python3
"""Compare Phase 3B test eval cells (fs3/on ship vs zero-shot / thinking-off ablations)."""

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
OUT = SUM / "PHASE3B_ABLATIONS_REPORT.md"
PROFILE = "qwen3_5_9b_bnb"
ROW = _model_row_name(PROFILE)
TEST_N = 600

# cell_id -> (eval_root, sum_suffix, thinking, fewshot, label)
CELLS: dict[str, tuple[str, str, str, int, str]] = {
    "fs3_on": ("runs/phase3/stage3b/eval", "", "on", 3, "Ship (teacher-matched) · ep6"),
    "fs0_off": ("runs/phase3/stage3b/eval_ablation/fs0_off", "_fs0_off", "off", 0, "Zero-shot · thinking off · ep6"),
    "fs0_off_best": (
        "runs/phase3/stage3b/eval_ablation/fs0_off_best",
        "_fs0_off_best",
        "off",
        0,
        "Zero-shot · thinking off · ep4 (rerank)",
    ),
    "fs3_off": ("runs/phase3/stage3b/eval_ablation/fs3_off", "_fs3_off", "off", 3, "3-shot · thinking off"),
    "fs0_on": ("runs/phase3/stage3b/eval_ablation/fs0_on", "_fs0_on", "on", 0, "Zero-shot · thinking on"),
}


def _row_from_suffix(suffix: str) -> dict:
    fp = json.loads((SUM / f"comparison_fp_phase3a{suffix}.json").read_text(encoding="utf-8"))
    tp = json.loads((SUM / f"comparison_tp_phase3a{suffix}.json").read_text(encoding="utf-8"))
    bl = json.loads((SUM / f"comparison_bl_phase3a{suffix}.json").read_text(encoding="utf-8"))
    return {
        "fp": fp.get(ROW) or {},
        "tp": tp.get(ROW) or {},
        "bl": bl.get(ROW) or {},
    }


def _cell_metrics(cell_id: str, spec: tuple[str, str, str, int, str]) -> dict | None:
    eval_root, suffix, thinking, fewshot, _label = spec
    fp_path = SUM / f"comparison_fp_phase3a{suffix}.json"
    if not fp_path.is_file():
        return None
    rows = _row_from_suffix(suffix)
    fp_m, tp_m, bl_m = rows["fp"], rows["tp"], rows["bl"]
    srs = compute_srs(fp_m, tp_m, bl_m or None, test_n=TEST_N)
    cm = confusion_for_run(
        _sast / eval_root,
        PROFILE,
        thinking=thinking,
        fewshot=fewshot,
    )
    return {
        "cell_id": cell_id,
        "label": spec[4],
        "srs": srs,
        "fprr": fp_m.get("fprr"),
        "vdr": tp_m.get("vdr"),
        "coverage": {
            "fp": fp_m.get("coverage"),
            "tp": tp_m.get("coverage"),
            "bl": bl_m.get("coverage"),
        },
        "missing": int(fp_m.get("missing") or 0) + int(tp_m.get("missing") or 0) + int(bl_m.get("missing") or 0),
        "critical_tp_fp": cm.get("critical_tp_fp"),
    }


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    baseline = manifest["baseline_stage2"]

    results: list[dict] = []
    for cell_id, spec in CELLS.items():
        m = _cell_metrics(cell_id, spec)
        if m:
            results.append(m)

    lines = [
        "# Phase 3B inference ablations",
        "",
        "Fine-tuned LoRA (rank 32, teacher distillation) on 600-case Phase 2 test holdout.",
        f"Phase 2 Stage 2 baseline: SRS **{baseline['srs']*100:.1f}%** "
        f"(VDR {baseline['vdr']*100:.1f}%, FPRR {baseline['fprr']*100:.1f}%)",
        "",
        "**Ship pick:** epoch **4** adapter (`lora/best_fs0_off`) after val rerank under fs0_off infer.",
        "Training-time fs3+CoT CSS pick was epoch **6** — train/serve mismatch hurts FPRR.",
        "",
        "**Rationale:** Distillation bakes triage policy into weights. Zero-shot drops "
        "few-shot tokens (shorter prompts, less truncation). Thinking-off avoids long CoT "
        "and should improve JSON reliability vs thinking-on.",
        "",
        "## Cell comparison",
        "",
        "| Cell | SRS | FPRR | VDR | Missing | TP→FP |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]

    best_srs = -1.0
    best_id = ""
    for m in results:
        srs = m.get("srs")
        srs_s = f"{srs*100:.1f}%" if srs is not None else "—"
        fprr = m.get("fprr")
        vdr = m.get("vdr")
        lines.append(
            f"| {m['label']} (`{m['cell_id']}`) | {srs_s} | "
            f"{fprr*100:.1f}% | {vdr*100:.1f}% | {m['missing']} | {m['critical_tp_fp']} |"
            if fprr is not None and vdr is not None
            else f"| {m['label']} (`{m['cell_id']}`) | {srs_s} | — | — | {m['missing']} | {m['critical_tp_fp']} |"
        )
        if srs is not None and srs > best_srs:
            best_srs = srs
            best_id = m["cell_id"]

    lines.extend(["", f"**Best cell so far:** `{best_id}` (SRS {best_srs*100:.1f}%)" if best_id else ""])
    if best_srs >= 0:
        delta = (best_srs - baseline["srs"]) * 100
        sign = "+" if delta >= 0 else ""
        lines.append(f"**Vs Stage 2 baseline:** {sign}{delta:.1f}pp SRS")
    lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    for m in results:
        srs = m.get("srs")
        srs_s = f"{srs:.4f}" if srs is not None else "n/a"
        print(f"  {m['cell_id']:8s} SRS={srs_s} missing={m['missing']}")


if __name__ == "__main__":
    main()
