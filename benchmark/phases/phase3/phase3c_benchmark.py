#!/usr/bin/env python3
"""Shared Phase 3C benchmark cell loaders (ship-aligned test eval)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SAST = Path(__file__).resolve().parents[3]
PHASE3C_SUM = _SAST / "runs/phase3/stage3c/summaries"
PHASE3C_EVAL = _SAST / "runs/phase3/stage3c/eval"
PHASE3C_RERANK = PHASE3C_SUM / "css_rerank_best.json"
PHASE3C_BLV4_SUM = _SAST / "runs/phase3/stage3c_blv4/summaries"
PHASE3C_BLV4_EVAL = _SAST / "runs/phase3/stage3c_blv4/eval"
PHASE3C_BLV4_RERANK = PHASE3C_BLV4_SUM / "css_rerank_best.json"
PHASE2_TEST_N = 600
PROFILE = "qwen3_5_9b_bnb"
BEST_EPOCH_DEFAULT = 6

PHASE3C_TEST_CELLS: tuple[dict[str, Any], ...] = (
    {
        "id": "phase3c_fs0_off",
        "label": "Phase 3C LoRA · epoch {epoch} · fs0 ship",
        "eval_root": PHASE3C_EVAL,
        "sum_dir": PHASE3C_SUM,
        "rerank_path": PHASE3C_RERANK,
        "sum_suffix": "",
        "thinking": "off",
        "fewshot": 0,
        "category": "Phase 3C LoRA (ship-aligned)",
        "epoch_source": "rerank",
        "source_stem": "phase3/stage3c",
        "confusion_key": "phase3c",
        "note": "Original 3C (retired BLSynthetic* train): json_only · fs0_off · v7-ship · epoch 6 · SRS 89.9% after gap-fill.",
    },
    {
        "id": "phase3c_blv4_fs0_off",
        "label": "Phase 3C blv4 LoRA · epoch {epoch} · fs0 confirm",
        "eval_root": PHASE3C_BLV4_EVAL,
        "sum_dir": PHASE3C_BLV4_SUM,
        "rerank_path": PHASE3C_BLV4_RERANK,
        "sum_suffix": "",
        "thinking": "off",
        "fewshot": 0,
        "category": "Phase 3C LoRA (BL v4 confirm)",
        "epoch_source": "rerank",
        "source_stem": "phase3/stage3c_blv4",
        "confusion_key": "blv4",
        "note": (
            "Confirmatory 3C on curated_v4 BL synthetics (BenchmarkTest28xxx). "
            "Gates NOT met: SRS 88.1% · VDR 72.5% · FPRR 76.5% (600/600). "
            "Do not ship — VDR collapsed vs original 3C / Stage 2."
        ),
    },
)


def _row_key(profile: str = PROFILE) -> str:
    from benchmark.summarize_triage import _model_row_name

    return _model_row_name(profile)


def load_rerank_best(rerank_path: Path | None = None) -> dict[str, Any]:
    path = rerank_path or PHASE3C_RERANK
    if not path.is_file():
        return {"epoch": BEST_EPOCH_DEFAULT, "metrics": {}}
    doc = json.loads(path.read_text(encoding="utf-8"))
    best = doc.get("best") or {}
    return {
        "epoch": int(best.get("epoch") or BEST_EPOCH_DEFAULT),
        "css": (best.get("css") or {}).get("css"),
        "metrics": best.get("metrics") or {},
        "adapter": best.get("adapter"),
    }


def load_cell_epoch(cell: dict[str, Any]) -> int:
    if cell.get("epoch_source") == "rerank":
        return load_rerank_best(cell.get("rerank_path"))["epoch"]
    return int(cell.get("epoch") or BEST_EPOCH_DEFAULT)


def load_test_cell_metrics(cell: dict[str, Any]) -> dict[str, Any] | None:
    from benchmark.confusion_matrix import confusion_for_run
    from benchmark.srs import compute_srs
    from benchmark.summarize_triage import macro_f1_from_track_f1s

    sum_dir = Path(cell.get("sum_dir") or PHASE3C_SUM)
    suffix = cell["sum_suffix"]
    fp_path = sum_dir / f"comparison_fp_phase3a{suffix}.json"
    tp_path = sum_dir / f"comparison_tp_phase3a{suffix}.json"
    bl_path = sum_dir / f"comparison_bl_phase3a{suffix}.json"
    if not fp_path.is_file() or not tp_path.is_file():
        return None

    row_key = _row_key()
    fp_m = json.loads(fp_path.read_text(encoding="utf-8")).get(row_key) or {}
    tp_m = json.loads(tp_path.read_text(encoding="utf-8")).get(row_key) or {}
    bl_m = (
        json.loads(bl_path.read_text(encoding="utf-8")).get(row_key) or {}
        if bl_path.is_file()
        else {}
    )
    if int(fp_m.get("evaluated") or 0) < 150 or int(tp_m.get("evaluated") or 0) < 150:
        return None

    cm = confusion_for_run(
        cell["eval_root"],
        PROFILE,
        thinking=cell["thinking"],
        fewshot=int(cell["fewshot"]),
    )
    # Prefer live eval; fall back to archived summary when eval trees were cleaned.
    if int(cm.get("n_cases") or 0) == 0:
        cm_path = sum_dir / "confusion_matrix_comparison.json"
        key = cell.get("confusion_key")
        if key and cm_path.is_file():
            archived = json.loads(cm_path.read_text(encoding="utf-8")).get(key) or {}
            if archived:
                cm = archived
    srs = compute_srs(fp_m, tp_m, bl_m or None, test_n=PHASE2_TEST_N)
    macro = macro_f1_from_track_f1s(
        float(fp_m.get("f1") or 0),
        float(tp_m.get("f1") or 0),
        float(bl_m.get("f1") or 0) if bl_m else None,
    )["macro_f1"]

    epoch = load_cell_epoch(cell)
    return {
        **cell,
        "epoch": epoch,
        "label": cell["label"].format(epoch=epoch),
        "profile": PROFILE,
        "fp_m": fp_m,
        "tp_m": tp_m,
        "bl_m": bl_m,
        "fprr": float(fp_m.get("fprr") or 0),
        "vdr": float(tp_m.get("vdr") or tp_m.get("tp_rate") or 0),
        "srs": float(srs or 0),
        "macro_f1": float(macro),
        "missing": int(fp_m.get("missing") or 0)
        + int(tp_m.get("missing") or 0)
        + int(bl_m.get("missing") or 0),
        "critical_tp_fp": cm.get("critical_tp_fp", 0),
        "high_bl_fp": cm.get("high_bl_fp", 0),
        "fp_tp": cm.get("fp_tp", 0),
        "confusion": cm,
    }


def load_all_test_cells() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cell in PHASE3C_TEST_CELLS:
        m = load_test_cell_metrics(cell)
        if m:
            rows.append(m)
    return rows


def experiment_row_from_cell(m: dict[str, Any]) -> dict[str, Any]:
    fp_t, tp_t = m["fp_m"], m["tp_m"]
    correct = int(fp_t.get("correct") or 0) + int(tp_t.get("correct") or 0)
    denom = int(fp_t.get("evaluated") or 0) + int(tp_t.get("evaluated") or 0)
    accuracy = correct / denom if denom else 0.0
    stem = m.get("source_stem") or "phase3/stage3c"
    return {
        "model": m["label"],
        "profile": m["profile"],
        "category": m["category"],
        "row_class": "cat-phase3c",
        "band_order": 7,
        "thinking": m["thinking"],
        "fewshot": m["fewshot"],
        "source": f"{stem}/epoch-{m['epoch']}",
        "phase": "Phase 3C",
        "epoch": m["epoch"],
        "vdr": m["vdr"],
        "fprr": m["fprr"],
        "macro_f1": m["macro_f1"],
        "srs": m["srs"],
        "critical": int(m["confusion"].get("critical_tp_fp") or 0),
        "accuracy": accuracy,
        "test_n": PHASE2_TEST_N,
        "missing": m["missing"],
        "cell_id": m["id"],
    }
