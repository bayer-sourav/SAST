#!/usr/bin/env python3
"""Build benchmark results + ops tables (200-case test runs) and HTML report."""

from __future__ import annotations

import html
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BENCH = _HERE.parents[1]
_SAST = _HERE.parents[2]
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

from timing import format_duration, utc_now_iso  # noqa: E402

from benchmark.confusion_matrix import (  # noqa: E402
    collect_outcomes,
    confusion_for_run,
    track_metrics_from_matrix,
)
from benchmark.srs import compute_srs  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "report_phase2_status", _HERE.parent / "phase2" / "report_phase2_status.py"
)
_rps = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_rps)

_merge_matrix = _rps._merge_matrix
_timing_row = _rps._timing_row
_scan_cell = _rps._scan_cell
TARGET = _rps.TARGET
TRACKS = _rps.TRACKS
CONFIGS = _rps.CONFIGS

PHASE2_SUM = _SAST / "runs/phase2/summaries"
STAGE2_SUM = _SAST / "runs/phase2/stage2/summaries"
STAGE2_MANIFEST = _BENCH / "phases/phase2/stage2/MANIFEST.json"
OUT_DIR = _SAST / "runs/phase2/phase2_benchmark_tables"
HTML_OUT = OUT_DIR / "BENCHMARK_RESULTS.html"
EXP_JSON = OUT_DIR / "benchmark_experiment_summary.json"
OPS_JSON = OUT_DIR / "benchmark_ops_timing_summary.json"
META_JSON = OUT_DIR / "benchmark_build_meta.json"

PROFILE_DISPLAY = {
    "qwen3_4b_bnb": "Qwen3-4B",
    "qwen3_8b_bnb": "Qwen3-8B",
    "qwen3_14b_bnb": "Qwen3-14B",
    "qwen3_coder_30b_bnb": "Qwen3-Coder-30B",
    "qwen3_5_4b_bnb": "Qwen3.5-4B",
    "qwen3_5_9b_bnb": "Qwen3.5-9B",
}

# Reference PoC baselines (n=27 slice) — copied from publication screenshot, not in repo.
SCREENSHOT_BASELINES: tuple[dict, ...] = (
    {
        "model": "Rule-based SAST",
        "vdr": 0.889,
        "fprr": 0.333,
        "macro_f1": 0.489,
        "srs": 0.861,
        "critical": 0,
        "accuracy": 0.518,
        "source": "screenshot/n27_poc",
    },
    {
        "model": "CodeQL",
        "vdr": 0.556,
        "fprr": 0.556,
        "macro_f1": 0.298,
        "srs": 0.682,
        "critical": 4,
        "accuracy": 0.370,
        "source": "screenshot/n27_poc",
    },
    {
        "model": "Combined (R+CQL)",
        "vdr": 0.556,
        "fprr": 0.333,
        "macro_f1": 0.481,
        "srs": 0.843,
        "critical": 0,
        "accuracy": 0.481,
        "source": "screenshot/n27_poc",
    },
)

POC_TIERS: tuple[tuple[str, float, float, float, float], ...] = (
    ("EXCELLENT", 0.95, 0.75, 0.75, 0.93),
    ("GOOD", 0.90, 0.65, 0.55, 0.80),
    ("MINIMUM", 0.85, 0.50, 0.50, 0.75),
)

POC_TEST_N = 27  # PoC total test cases (all labels)
PHASE2_TEST_N = 600  # Phase 2 held-out test (200 FP + 200 TP + 200 BL)
POC_CRITICAL_LIMIT = 3
BASELINE_BAND = (-1, "Baseline", "cat-baseline")
CATEGORY_BAND = {
    ("off", 0): (0, "Zero-shot", "cat-zero"),
    ("off", 3): (1, "Few-shot", "cat-few"),
    ("on", 0): (2, "Zero-shot (CoT)", "cat-zero-cot"),
    ("on", 3): (3, "Few-shot (CoT)", "cat-few-cot"),
}
STAGE2_BAND = (4, "Stage 2 ship", "cat-stage2")
PHASE3_BAND = (5, "Phase 3 LoRA", "cat-phase3")
PHASE3B_BAND = (6, "Phase 3B LoRA", "cat-phase3b")
PHASE3C_BAND = (7, "Phase 3C LoRA", "cat-phase3c")
PHASE3_SUM = _SAST / "runs/phase3/stage3a/summaries"
PHASE3_EVAL = _SAST / "runs/phase3/stage3a/eval"
CONFUSION_JSON = OUT_DIR / "benchmark_confusion_comparison.json"

CONFUSION_COMPARISONS: tuple[dict, ...] = (
    {
        "id": "stage2_good",
        "label": "Stage 2 GOOD · 5.9b_fs3_legacy",
        "base": _SAST / "runs/phase2/stage2",
        "profile": "qwen3_5_9b_bnb",
        "thinking": "on",
        "fewshot": 3,
        "tier": "GOOD",
        "category": "Stage 2 ship",
        "row_class": "cat-stage2",
        "note": "Only GOOD-tier Stage 2 ship cell (v2_3shot_tp_2fp).",
    },
    {
        "id": "phase2_minimum",
        "label": "Phase 2 MINIMUM · Qwen3.5-9B fs3 (CoT)",
        "base": _SAST / "runs/phase2",
        "profile": "qwen3_5_9b_bnb",
        "thinking": "on",
        "fewshot": 3,
        "tier": "MINIMUM",
        "category": "Few-shot (CoT)",
        "row_class": "cat-few-cot",
        "note": "Phase 2 matrix cell — same profile/fs3; no Stage 2 ship cell reaches MINIMUM.",
    },
    {
        "id": "phase3a_lora",
        "label": "Phase 3A LoRA",
        "base": PHASE3_EVAL,
        "profile": "qwen3_5_9b_bnb",
        "thinking": "on",
        "fewshot": 3,
        "tier": "FAIL",
        "category": "Phase 3 LoRA",
        "row_class": "cat-phase3",
        "note": "Qwen3.5-9B + LoRA SFT (gold-label supervision, thinking off in train).",
    },
)


def _fmt3(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{float(x):.3f}"


def _display_model(profile: str, thinking: str, fewshot: int) -> str:
    base = PROFILE_DISPLAY.get(profile, profile)
    if thinking == "off" and fewshot == 0:
        return f"{base} Zero-shot"
    if thinking == "off" and fewshot == 3:
        return f"{base} Few-shot 3"
    if thinking == "on" and fewshot == 0:
        return f"{base} Zero-shot (CoT)"
    return f"{base} Few-shot 3 (CoT)"


def _is_200_case_model(m: dict) -> bool:
    """Include full 200-case cells; allow ≤3 missing labels per track (gaps on disk)."""
    fp = m.get("fp_track") or {}
    tp = m.get("tp_track") or {}
    min_eval = TARGET - 3
    return (
        int(fp.get("evaluated", 0)) >= min_eval
        and int(tp.get("evaluated", 0)) >= min_eval
    )


def _critical(tp_track: dict) -> int:
    """Gold-TP cases misclassified as FP (missed vulnerabilities)."""
    tp_dist = tp_track.get("distribution") or {}
    return int(tp_dist.get("FP", 0))


def _critical_limit(row: dict) -> int:
    """PoC hard gate: >3 CRITICAL on n=27 total test cases; scale by test-set size."""
    if row.get("is_baseline"):
        test_n = POC_TEST_N
    else:
        test_n = int(row.get("test_n") or PHASE2_TEST_N)
    return (POC_CRITICAL_LIMIT * test_n) // POC_TEST_N


def _assign_tier(row: dict) -> str:
    vdr = float(row["vdr"])
    fprr = float(row["fprr"])
    macro_f1 = float(row.get("macro_f1") or 0.0)
    srs = float(row["srs"])
    critical = int(row["critical"])
    if vdr < 0.85 or srs < 0.78 or critical > _critical_limit(row):
        return "FAIL"
    for name, t_vdr, t_fprr, t_f1, t_srs in POC_TIERS:
        if vdr >= t_vdr and fprr >= t_fprr and macro_f1 >= t_f1 and srs >= t_srs:
            return name
    return "FAIL"


def _finalize_row(row: dict) -> dict:
    row["tier"] = _assign_tier(row)
    return row


def _accuracy(fp_track: dict, tp_track: dict) -> float:
    correct = int(fp_track.get("correct", 0)) + int(tp_track.get("correct", 0))
    denom = int(fp_track.get("evaluated", 0)) + int(tp_track.get("evaluated", 0))
    return correct / denom if denom else 0.0


def _macro_f1(m: dict) -> float | None:
    if m.get("macro_f1") is not None:
        return float(m["macro_f1"])
    if m.get("f1_fp_tp") is not None:
        return float(m["f1_fp_tp"])
    if m.get("f1") is not None:
        return float(m["f1"])
    return None


def _load_baseline_rows() -> list[dict]:
    """Reference PoC baselines from publication screenshot (n=27, not re-run here)."""
    band_order, category, row_class = BASELINE_BAND
    rows: list[dict] = []
    for b in SCREENSHOT_BASELINES:
        rows.append(
            _finalize_row(
                {
                    "model": b["model"],
                    "profile": None,
                    "category": category,
                    "row_class": row_class,
                    "band_order": band_order,
                    "thinking": None,
                    "fewshot": None,
                    "source": b["source"],
                    "phase": "Baseline (PoC n=27)",
                    "vdr": b["vdr"],
                    "fprr": b["fprr"],
                    "macro_f1": b["macro_f1"],
                    "srs": b["srs"],
                    "critical": b["critical"],
                    "accuracy": b["accuracy"],
                    "test_n": POC_TEST_N,
                    "is_baseline": True,
                }
            )
        )
    return rows


def _row_from_matrix(
    profile: str,
    m: dict,
    thinking: str,
    fewshot: int,
    *,
    source: str,
    bl_track: dict | None = None,
) -> dict | None:
    if not _is_200_case_model(m):
        return None
    fp_t = m["fp_track"]
    tp_t = m["tp_track"]
    bl = bl_track or m.get("bl_track")
    srs = compute_srs(fp_t, tp_t, bl, test_n=PHASE2_TEST_N)
    if srs is None:
        srs = float(m["srs"])
    band_order, category, row_class = CATEGORY_BAND[(thinking, fewshot)]
    row = {
        "model": _display_model(profile, thinking, fewshot),
        "profile": profile,
        "category": category,
        "row_class": row_class,
        "band_order": band_order,
        "thinking": thinking,
        "fewshot": fewshot,
        "source": source,
        "phase": "Phase 2",
        "vdr": float(m["vdr"]),
        "fprr": float(m["fprr"]),
        "macro_f1": _macro_f1(m),
        "srs": srs,
        "critical": _critical(tp_t),
        "accuracy": _accuracy(fp_t, tp_t),
        "test_n": PHASE2_TEST_N,
    }
    return _finalize_row(row)


def _load_phase2_matrix_rows() -> list[dict]:
    """Phase 2 stageless matrix: all 6 profiles × 4 configs (200 FP + 200 TP each)."""
    rows: list[dict] = []
    for thinking, fewshot in CONFIGS:
        path = PHASE2_SUM / f"phase2_matrix_thinking_{thinking}_fewshot_{fewshot}.json"
        if not path.is_file():
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        for profile, m in (doc.get("models") or {}).items():
            bl_t = (doc.get("borderline") or {}).get(profile)
            row = _row_from_matrix(
                profile,
                m,
                thinking,
                fewshot,
                source=str(path.relative_to(_SAST)),
                bl_track=bl_t,
            )
            if row:
                rows.append(row)
    return rows


def _load_stage2_ship_rows() -> list[dict]:
    manifest = json.loads(STAGE2_MANIFEST.read_text(encoding="utf-8"))
    rows: list[dict] = []
    band_order, category, row_class = STAGE2_BAND
    for cell in manifest.get("cells") or []:
        profile = cell["profile"]
        fewshot = int(cell["fewshot"])
        thinking = "on" if cell.get("thinking") else "off"
        cell_id = cell.get("id", profile)
        fp_path = STAGE2_SUM / f"comparison_fp_think_{thinking}_fs{fewshot}.json"
        tp_path = STAGE2_SUM / f"comparison_tp_think_{thinking}_fs{fewshot}.json"
        bl_path = STAGE2_SUM / f"comparison_bl_think_{thinking}_fs{fewshot}.json"
        if not fp_path.is_file() or not tp_path.is_file():
            continue
        fp_rows = json.loads(fp_path.read_text(encoding="utf-8"))
        tp_rows = json.loads(tp_path.read_text(encoding="utf-8"))
        bl_rows = json.loads(bl_path.read_text(encoding="utf-8")) if bl_path.is_file() else {}
        matrix = _merge_matrix(fp_rows, tp_rows, bl_rows, [profile], thinking, fewshot)
        m = matrix.get("models", {}).get(profile)
        if not m or not _is_200_case_model(m):
            continue
        fp_t = m["fp_track"]
        tp_t = m["tp_track"]
        bl_t = bl_rows.get(f"SLM ({profile})")
        srs = compute_srs(fp_t, tp_t, bl_t, test_n=PHASE2_TEST_N)
        if srs is None:
            srs = float(m["srs"])
        fs_cfg = cell.get("few_shot_config") or "zeroshot"
        base = PROFILE_DISPLAY.get(profile, profile)
        row = {
            "model": f"{base} · {cell_id}",
            "profile": profile,
            "category": category,
            "row_class": row_class,
            "band_order": band_order,
            "thinking": thinking,
            "fewshot": fewshot,
            "source": f"stage2/{cell_id}",
            "phase": "Phase 2 Stage 2",
            "vdr": float(m["vdr"]),
            "fprr": float(m["fprr"]),
            "macro_f1": _macro_f1(m),
            "srs": float(srs),
            "critical": _critical(tp_t),
            "accuracy": _accuracy(fp_t, tp_t),
            "test_n": PHASE2_TEST_N,
            "few_shot_config": fs_cfg,
        }
        rows.append(_finalize_row(row))
    return rows


def _sort_experiments(rows: list[dict]) -> list[dict]:
    baseline_order = ["Rule-based SAST", "CodeQL", "Combined (R+CQL)"]

    def _key(r: dict) -> tuple:
        if r.get("is_baseline"):
            try:
                sub = baseline_order.index(r["model"])
            except ValueError:
                sub = 99
            return (r["band_order"], sub, 0.0, "")
        return (r["band_order"], 0, -r["srs"], r["model"])

    return sorted(rows, key=_key)


def _srs_tiers_notes() -> str:
    srs_def = (
        "<b>VDR</b> (vulnerability detection rate) — TP-track recall: fraction of gold-TP cases labeled TP. "
        "<b>FPRR</b> (false-positive removal rate) — FP-track recall: fraction of gold-FP cases labeled FP. "
        "<b>SRS</b> (security review score) = 1 − (Σ penalty) / (N × 3.0) over all 600 test cases "
        "(200 FP + 200 TP + 200 BL gold tracks). Penalties: "
        "<b>TP→FP</b> 3.0× CRITICAL · <b>BL→FP</b> 1.5× HIGH · <b>TP→BL</b> 1.0× MODERATE · "
        "<b>FP→TP/BL</b> 1.0× ACCEPTABLE · correct label 0× · unlisted transitions 0×. "
        "Missing predictions count as 3.0×."
    )
    return f"""<dt>VDR, FPRR, SRS &amp; PoC success tiers</dt>
<dd>{srs_def}<br/><br/>
<b>PoC success tiers</b> — all four thresholds (VDR, FPRR, Macro-F1, SRS) must pass simultaneously:
<b>EXCELLENT</b> VDR≥0.95 · FPRR≥0.75 · Macro-F1≥0.75 · SRS≥0.93 ·
<b>GOOD</b> VDR≥0.90 · FPRR≥0.65 · Macro-F1≥0.55 · SRS≥0.80 ·
<b>MINIMUM</b> VDR≥0.85 · FPRR≥0.50 · Macro-F1≥0.50 · SRS≥0.75.
Hard gates → <b>FAIL</b>: VDR&lt;0.85, SRS&lt;0.78, or CRITICAL above limit (&gt;3 on n=27 baselines; scaled to total test size on Phase 2 rows — limit = floor(3×n/27), e.g. &gt;66 when n=600).</dd>"""


def _cell_from_timing_path(path: Path) -> dict | None:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if int(doc.get("n_cases", 0)) != TARGET:
        return None
    cases = []
    for c in doc.get("cases") or []:
        row = {"case_id": c.get("case_id")}
        for key in ("elapsed_sec", "inference_sec", "input_tokens", "output_tokens", "total_tokens"):
            if c.get(key) is not None:
                row[key] = c[key]
        if row.get("elapsed_sec") is not None:
            row["wall_sec"] = row["elapsed_sec"]
        cases.append(row)
    if len(cases) < TARGET:
        return None
    return {
        "profile": doc.get("profile", path.parent.name),
        "n_cases": len(cases),
        "cases": cases,
        "aggregate": doc.get("aggregate") or {},
        "elapsed_sec": doc.get("elapsed_sec"),
    }


def _infer_track_from_path(path: Path) -> str:
    parts = path.parts
    for i, p in enumerate(parts):
        if p in ("fp", "tp", "bl") and i + 1 < len(parts):
            return p.upper()
    return "?"


def _infer_config_from_path(path: Path) -> tuple[str, str, int]:
    parts = path.parts
    thinking = "?"
    fewshot = -1
    scope = "phase2"
    if "stage2" in parts:
        scope = "stage2"
    for p in parts:
        if p.startswith("thinking_"):
            thinking = p.replace("thinking_", "")
        if p.startswith("fewshot_"):
            fewshot = int(p.replace("fewshot_", ""))
    return scope, thinking, fewshot


def _load_ops_rows() -> list[dict]:
    roots = [_SAST / "runs/phase2", _SAST / "runs/phase2/stage2"]
    seen: set[str] = set()
    rows: list[dict] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("cell_timing.json")):
            rel = str(path.relative_to(_SAST))
            if rel in seen:
                continue
            cell = _cell_from_timing_path(path)
            if not cell:
                continue
            seen.add(rel)
            t = _timing_row(cell)
            scope, thinking, fewshot = _infer_config_from_path(path)
            track = _infer_track_from_path(path)
            prof = cell["profile"]
            display = PROFILE_DISPLAY.get(prof, prof)
            rows.append(
                {
                    "path": rel,
                    "scope": scope,
                    "track": track,
                    "thinking": thinking,
                    "fewshot": fewshot,
                    "model": prof,
                    "model_display": _display_model(prof, thinking, fewshot),
                    "n_cases": cell["n_cases"],
                    **t,
                }
            )
    return rows


def _training_status() -> dict:
    log_path = _SAST / "runs/phase3/stage3a/logs/train.log"
    lora_latest = _SAST / "runs/phase3/stage3a/lora/latest"
    status: dict = {
        "checked_at": utc_now_iso(),
        "run_unsloth_lora_running": False,
        "pgrep_matches": [],
        "train_log_path": str(log_path.relative_to(_SAST)),
        "train_log_tail": [],
        "lora_latest_exists": lora_latest.is_dir() or lora_latest.is_symlink(),
        "adapter_ready": False,
        "gpu": {},
    }
    try:
        proc = subprocess.run(
            ["pgrep", "-af", "run_unsloth_lora"],
            capture_output=True,
            text=True,
            check=False,
        )
        matches = [
            ln for ln in proc.stdout.splitlines()
            if "run_unsloth_lora" in ln and "pgrep" not in ln
        ]
        status["pgrep_matches"] = matches
        status["run_unsloth_lora_running"] = bool(matches)
    except OSError:
        pass
    if lora_latest.exists():
        target = lora_latest.resolve() if lora_latest.is_symlink() else lora_latest
        status["lora_latest"] = str(target.relative_to(_SAST)) if target.is_relative_to(_SAST) else str(target)
        status["adapter_ready"] = (
            (target / "adapter_config.json").is_file()
            or (target / "adapter_model.safetensors").is_file()
        )
    if log_path.is_file():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        status["train_log_tail"] = lines[-8:]
    try:
        smi = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total,utilization.gpu",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        status["gpu"]["query"] = smi.stdout.strip()
    except OSError:
        status["gpu"]["query"] = ""
    return status


def _load_confusion_comparisons() -> list[dict]:
    rows: list[dict] = []
    for cfg in CONFUSION_COMPARISONS:
        outcomes = collect_outcomes(
            cfg["base"],
            cfg["profile"],
            thinking=cfg["thinking"],
            fewshot=int(cfg["fewshot"]),
        )
        if len(outcomes) < TARGET * 2:
            continue
        cm = confusion_for_run(
            cfg["base"],
            cfg["profile"],
            thinking=cfg["thinking"],
            fewshot=int(cfg["fewshot"]),
        )
        fp_t = track_metrics_from_matrix(cm, "FP")
        tp_t = track_metrics_from_matrix(cm, "TP")
        bl_t = track_metrics_from_matrix(cm, "BL")
        fp_eval = int(fp_t["evaluated"])
        tp_eval = int(tp_t["evaluated"])
        fprr = fp_t["correct"] / fp_eval if fp_eval else 0.0
        vdr = tp_t["correct"] / tp_eval if tp_eval else 0.0
        srs = compute_srs(fp_t, tp_t, bl_t, test_n=PHASE2_TEST_N)
        row = {k: v for k, v in cfg.items() if k != "base"}
        row.update(
            **cm,
            fprr=fprr,
            vdr=vdr,
            srs=float(srs) if srs is not None else None,
        )
        rows.append(row)
    return rows


def _load_phase3b_rows() -> list[dict]:
    from benchmark.phases.phase3.phase3b_benchmark import experiment_row_from_cell, load_all_test_cells

    rows: list[dict] = []
    for cell in load_all_test_cells():
        row = experiment_row_from_cell(cell)
        _, category, row_class = PHASE3B_BAND
        row["category"] = cell.get("category") or category
        row["row_class"] = row_class
        row["band_order"] = PHASE3B_BAND[0]
        rows.append(_finalize_row(row))
    return rows


def _load_phase3b_confusion_rows() -> list[dict]:
    from benchmark.phases.phase3.phase3b_benchmark import load_all_test_cells

    rows: list[dict] = []
    for cell in load_all_test_cells():
        cm = cell["confusion"]
        row = {
            "id": cell["id"],
            "label": cell["label"],
            "tier": _assign_tier(
                {
                    "vdr": cell["vdr"],
                    "fprr": cell["fprr"],
                    "macro_f1": cell["macro_f1"],
                    "srs": cell["srs"],
                    "critical": cell["critical_tp_fp"],
                    "test_n": PHASE2_TEST_N,
                }
            ),
            "category": cell.get("category", "Phase 3B LoRA"),
            "row_class": "cat-phase3b",
            "note": cell.get("note", ""),
            **cm,
            "fprr": cell["fprr"],
            "vdr": cell["vdr"],
            "srs": cell["srs"],
        }
        rows.append(row)
    return rows


def _load_phase3c_rows() -> list[dict]:
    from benchmark.phases.phase3.phase3c_benchmark import experiment_row_from_cell, load_all_test_cells

    rows: list[dict] = []
    for cell in load_all_test_cells():
        row = experiment_row_from_cell(cell)
        _, category, row_class = PHASE3C_BAND
        row["category"] = cell.get("category") or category
        row["row_class"] = row_class
        row["band_order"] = PHASE3C_BAND[0]
        rows.append(_finalize_row(row))
    return rows


def _load_phase3c_confusion_rows() -> list[dict]:
    from benchmark.phases.phase3.phase3c_benchmark import load_all_test_cells

    rows: list[dict] = []
    for cell in load_all_test_cells():
        cm = cell["confusion"]
        row = {
            "id": cell["id"],
            "label": cell["label"],
            "tier": _assign_tier(
                {
                    "vdr": cell["vdr"],
                    "fprr": cell["fprr"],
                    "macro_f1": cell["macro_f1"],
                    "srs": cell["srs"],
                    "critical": cell["critical_tp_fp"],
                    "test_n": PHASE2_TEST_N,
                }
            ),
            "category": cell.get("category", "Phase 3C LoRA"),
            "row_class": "cat-phase3c",
            "note": cell.get("note", ""),
            **cm,
            "fprr": cell["fprr"],
            "vdr": cell["vdr"],
            "srs": cell["srs"],
        }
        rows.append(row)
    return rows


def _load_phase3a_row() -> dict | None:
    profile = "qwen3_5_9b_bnb"
    row_key = f"SLM ({profile})"
    fp_path = PHASE3_SUM / "comparison_fp_phase3a.json"
    tp_path = PHASE3_SUM / "comparison_tp_phase3a.json"
    bl_path = PHASE3_SUM / "comparison_bl_phase3a.json"
    if not fp_path.is_file() or not tp_path.is_file():
        return None
    fp_rows = json.loads(fp_path.read_text(encoding="utf-8"))
    tp_rows = json.loads(tp_path.read_text(encoding="utf-8"))
    bl_rows = (
        json.loads(bl_path.read_text(encoding="utf-8")) if bl_path.is_file() else {}
    )
    matrix = _merge_matrix(fp_rows, tp_rows, bl_rows, [profile], "on", 3)
    m = matrix.get("models", {}).get(profile)
    if not m:
        return None
    fp_t = m["fp_track"]
    tp_t = m["tp_track"]
    if int(fp_t.get("evaluated", 0)) < TARGET - 10 or int(tp_t.get("evaluated", 0)) < TARGET - 10:
        return None
    bl_t = bl_rows.get(row_key)
    srs = compute_srs(fp_t, tp_t, bl_t, test_n=PHASE2_TEST_N)
    if srs is None:
        srs = float(m["srs"])
    band_order, category, row_class = PHASE3_BAND
    return _finalize_row(
        {
            "model": "Qwen3.5-9B · Phase 3A LoRA",
            "profile": profile,
            "category": category,
            "row_class": row_class,
            "band_order": band_order,
            "thinking": "on",
            "fewshot": 3,
            "source": "phase3/stage3a",
            "phase": "Phase 3A",
            "vdr": float(m["vdr"]),
            "fprr": float(m["fprr"]),
            "macro_f1": _macro_f1(m),
            "srs": float(srs),
            "critical": _critical(tp_t),
            "accuracy": _accuracy(fp_t, tp_t),
            "test_n": PHASE2_TEST_N,
            "few_shot_config": "v2_3shot_tp_2fp",
        }
    )


def _confusion_matrix_html(cm: dict) -> str:
    matrix = cm.get("matrix") or {}
    missing = cm.get("missing_by_gold") or {}
    labels = ("TP", "FP", "BL")
    header = (
        "<tr><th>Gold \\ Pred</th>"
        + "".join(f"<th>→ {html.escape(p)}</th>" for p in labels)
        + "<th>miss</th><th>Σ</th></tr>"
    )
    body_rows = []
    for gold in labels:
        row = matrix.get(gold) or {}
        miss = int(missing.get(gold, 0))
        total = sum(int(row.get(p, 0)) for p in labels) + miss
        cells = [f"<th>{html.escape(gold)}</th>"]
        for pred in labels:
            val = int(row.get(pred, 0))
            cls = "cm-diag" if gold == pred and val else ""
            if gold == "TP" and pred == "FP" and val:
                cls = "cm-critical"
            elif gold == "BL" and pred == "FP" and val:
                cls = "cm-high"
            elif gold == "FP" and pred == "TP" and val:
                cls = "cm-warn"
            cells.append(
                f'<td class="{cls}">{val}</td>' if cls else f"<td>{val}</td>"
            )
        cells.append(f"<td>{miss}</td><td>{total}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table class=\"cm\"><thead>{header}</thead><tbody>{''.join(body_rows)}</tbody></table>"


def _build_confusion_section(comparisons: list[dict]) -> str:
    if not comparisons:
        return ""

    from benchmark.phases.phase3.phase3b_benchmark import load_best_epoch, load_fs0_off_rerank
    from benchmark.phases.phase3.phase3c_benchmark import load_rerank_best

    train_ep = load_best_epoch().get("epoch", 6)
    ship_ep = load_fs0_off_rerank().get("epoch", 4)
    phase3c_ep = load_rerank_best().get("epoch", 6)

    summary_cols = [
        "Model",
        "Tier",
        "FPRR",
        "VDR",
        "SRS",
        "TP→FP",
        "BL→FP",
        "FP→TP",
        "miss",
        "TP diag",
        "FP diag",
        "BL diag",
    ]
    summary_head = "".join(f"<th>{c}</th>" for c in summary_cols)
    summary_rows = []
    matrix_blocks = []
    for cm in comparisons:
        diag = cm.get("diagonal") or {}
        cells = [
            cm["label"],
            cm.get("tier", "—"),
            _fmt3(cm.get("fprr")),
            _fmt3(cm.get("vdr")),
            _fmt3(cm.get("srs")),
            str(cm.get("critical_tp_fp", 0)),
            str(cm.get("high_bl_fp", 0)),
            str(cm.get("fp_tp", 0)),
            str(cm.get("missing", 0)),
            str(diag.get("TP", 0)),
            str(diag.get("FP", 0)),
            str(diag.get("BL", 0)),
        ]
        tds = "".join(f"<td>{html.escape(c)}</td>" for c in cells)
        summary_rows.append(f'<tr class="{cm.get("row_class", "")}">{tds}</tr>')
        note = cm.get("note", "")
        matrix_blocks.append(
            f'<div class="cm-block"><h3>{html.escape(cm["label"])}</h3>'
            f'<p class="cm-note">{html.escape(note)}</p>'
            f"{_confusion_matrix_html(cm)}</div>"
        )

    return f"""<section>
<h2>Confusion matrices — Stage 2 GOOD · Phase 2 MINIMUM · Phase 3A · Phase 3B · Phase 3C</h2>
<p class="subtitle">Full 3×3 gold × predicted over 600 cases (200 FP + 200 TP + 200 BL). Phase 3B rows span teacher-matched (ep{train_ep}) and ship fs0_off (ep{ship_ep} rerank). Phase 3C: ship-aligned distill (ep{phase3c_ep}, fs0_off). Diagonal = correct; shaded cells = high-penalty misclassifications. <b>BL-gold:</b> ship models rarely predict BL — BL→TP is SRS-free; BL→FP is penalized.</p>
<table>
<thead><tr>{summary_head}</tr></thead>
<tbody>{"".join(summary_rows)}</tbody>
</table>
<div class="cm-grid">{"".join(matrix_blocks)}</div>
</section>"""


def _build_html(experiments: list[dict], ops: list[dict], comparisons: list[dict]) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    exp_cols = [
        "#",
        "Model",
        "Category",
        "VDR",
        "FPRR",
        "Macro-F1",
        "SRS",
        "CRITICAL",
        "Accuracy",
        "Tier",
    ]
    exp_thead = "".join(f"<th>{c}</th>" for c in exp_cols)
    exp_trs = []
    for i, r in enumerate(experiments):
        tier = r.get("tier", "FAIL")
        cells = [
            str(i),
            r["model"],
            r["category"],
            _fmt3(r["vdr"]),
            _fmt3(r["fprr"]),
            _fmt3(r.get("macro_f1")),
            _fmt3(r["srs"]),
            str(r["critical"]),
            _fmt3(r["accuracy"]),
        ]
        tds = "".join(f"<td>{html.escape(c)}</td>" for c in cells)
        tds += f'<td class="tier-{html.escape(tier)}">{html.escape(tier)}</td>'
        exp_trs.append(f'<tr class="{r["row_class"]}">{tds}</tr>')

    ops_cols = [
        "Model / Config",
        "Track",
        "Scope",
        "N",
        "Wall",
        "Mean case",
        "Median",
        "Mean infer",
        "Mean tok",
    ]
    ops_thead = "".join(f"<th>{c}</th>" for c in ops_cols)
    ops_sorted = sorted(ops, key=lambda r: (r["scope"], r["model"], r["track"]))
    ops_trs = []
    for r in ops_sorted:
        cells = [
            r["model_display"],
            r["track"],
            r["scope"],
            str(r["n_cases"]),
            r["wall"],
            r["mean_case"],
            r["median_case"],
            r["mean_infer"],
            r["mean_tok"],
        ]
        tds = "".join(f"<td>{html.escape(c)}</td>" for c in cells)
        ops_trs.append(f"<tr>{tds}</tr>")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Phase 2 Benchmark Results</title>
<style>
body {{ font-family: system-ui, -apple-system, sans-serif; margin: 24px; color: #1a1a2e; }}
h1 {{ color: #1e3a5f; font-size: 1.35rem; margin-bottom: 0.25rem; }}
h2 {{ color: #1e3a5f; font-size: 1.1rem; margin-top: 2rem; }}
.subtitle {{ color: #666; font-size: 0.9rem; margin-top: 0; margin-bottom: 1rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; margin: 1rem 0 2rem; }}
th {{ background: #1e3a5f; color: #fff; padding: 8px 10px; text-align: right; font-weight: 600; }}
th:first-child, th:nth-child(2), th:nth-child(3) {{ text-align: left; }}
th:last-child {{ text-align: center; }}
td {{ padding: 6px 10px; border-bottom: 1px solid #e8e8e8; text-align: right; }}
td:first-child, td:nth-child(2), td:nth-child(3) {{ text-align: left; }}
td.tier-FAIL {{ background: #e53935; color: #fff; font-weight: 600; text-align: center; }}
td.tier-MINIMUM {{ background: #fb8c00; color: #fff; font-weight: 600; text-align: center; }}
td.tier-GOOD {{ background: #1e88e5; color: #fff; font-weight: 600; text-align: center; }}
td.tier-EXCELLENT {{ background: #43a047; color: #fff; font-weight: 600; text-align: center; }}
tr.cat-baseline {{ background: #ffffff; }}
tr.cat-zero {{ background: #e6f7ff; }}
tr.cat-few {{ background: #f6ffed; }}
tr.cat-zero-cot {{ background: #eef4fb; }}
tr.cat-few-cot {{ background: #f0fff4; }}
tr.cat-stage2 {{ background: #fffbe6; }}
tr.cat-phase3 {{ background: #fce4ec; }}
tr.cat-phase3b {{ background: #f3e5f5; }}
tr.cat-phase3c {{ background: #e8eaf6; }}
.note {{ background: #fff8e1; padding: 8px 12px; border-radius: 4px; margin-bottom: 1rem; }}
.cm-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.25rem; margin-top: 1rem; }}
.cm-block h3 {{ font-size: 0.95rem; margin: 0 0 0.25rem; color: #1e3a5f; }}
.cm-note {{ font-size: 0.8rem; color: #666; margin: 0 0 0.5rem; }}
table.cm {{ font-size: 0.8rem; margin: 0; }}
table.cm th, table.cm td {{ text-align: right; }}
table.cm th:first-child, table.cm td:first-child {{ text-align: left; }}
td.cm-diag {{ background: #e8f5e9; font-weight: 600; }}
td.cm-critical {{ background: #ffcdd2; font-weight: 600; }}
td.cm-high {{ background: #ffe0b2; }}
td.cm-warn {{ background: #fff9c4; }}
.infra {{ margin-top: 2rem; }}
.infra ul {{ line-height: 1.75; }}
.notes {{ margin-top: 2rem; font-size: 0.9rem; line-height: 1.65; color: #333; }}
.notes dt {{ font-weight: 600; margin-top: 0.75rem; color: #1e3a5f; }}
.notes dd {{ margin: 0.25rem 0 0 0; padding-left: 0; }}
.status {{ font-size: 0.85rem; color: #444; margin-bottom: 1rem; }}
</style>
</head>
<body>
<p class="status">Generated {generated} · <code>benchmark/phases/phase2/build_results_tables.py</code></p>

<section>
<h1>Phase 2 Benchmark Results — All Models &amp; Approaches</h1>
<p class="subtitle">Test set · baselines n=27 (PoC reference) · LLM rows 600-case Phase 2 test (200 FP + 200 TP + 200 BL) · Baseline → Zero-shot → Few-shot → Few-shot (CoT) → Stage 2 ship → Phase 3A/3B/3C LoRA · Tier = PoC success gates (four metrics + hard gates; CRITICAL limit scales with total test size)</p>
<table>
<thead><tr>{exp_thead}</tr></thead>
<tbody>{"".join(exp_trs)}</tbody>
</table>
</section>

{_build_confusion_section(comparisons)}

<section>
<h2>Operational Stats — Timing &amp; Tokens</h2>
<p class="subtitle">Per-cell aggregates from cell_timing.json (200-case runs). Phase 1 Stage 2 (904/1373) excluded.</p>
<table>
<thead><tr>{ops_thead}</tr></thead>
<tbody>{"".join(ops_trs)}</tbody>
</table>
</section>

<section class="infra">
<h2>Infrastructure</h2>
<ul>
<li><b>Host:</b> AWS EC2 (Amazon Linux 2023), x86_64</li>
<li><b>GPU:</b> NVIDIA L40S (45 GB VRAM)</li>
<li><b>Stack:</b> Python 3.12 · uv · Unsloth 4-bit · PyTorch 2.10 · Transformers 5.5</li>
<li><b>Models:</b> Local Unsloth/HF (Qwen3 / Qwen3.5); Qwen3-Coder-30B via Bedrock when configured</li>
<li><b>Benchmark:</b> OWASP BenchmarkJava · CodeQL · SAST-Benchmark-Dataset (200 FP + 200 TP + 200 BL held-out test)</li>
<li><b>Cost:</b> Self-hosted EC2; Bedrock billed per token (not aggregated in repo)</li>
</ul>
</section>

<section class="notes">
<h2>Notes &amp; definitions</h2>
<dl>
<dt>Baseline rows (top of table)</dt>
<dd>Fixed reference values from the PoC publication screenshot (<b>n=27</b>). Not re-run on Phase 2 corpora: <b>Rule-based SAST</b>, <b>CodeQL</b>, <b>Combined (R+CQL)</b>.</dd>

{_srs_tiers_notes()}

<dt>Zero-shot</dt>
<dd>Thinking off · few-shot 0 (<code>fs0</code>). Model sees the v7-balanced prompt only — no in-prompt exemplars.</dd>

<dt>Few-shot</dt>
<dd>Thinking off · few-shot 3 (<code>fs3</code>). Three train-split exemplars (TP→FP→BL) appended after the policy block.</dd>

<dt>Zero-shot (CoT) / Few-shot (CoT)</dt>
<dd>Same as above with <b>thinking on</b> — chain-of-thought before JSON. Qwen3.5 runs use an 8192-token decode cap.</dd>

<dt>Stage 2 ship</dt>
<dd>Phase 2 Stage 2 production cells (v7-balanced prompt, thinking on). Each row is a tuned profile×config from <code>stage2/MANIFEST.json</code>, e.g. <code>5.9b_fs3_legacy</code> = Qwen3.5-9B · fs3 · legacy 3-shot pack (<code>v2_3shot_tp_2fp</code>).</dd>

<dt><code>fs3_legacy</code> / few-shot config tags</dt>
<dd><code>v2_3shot_tp_2fp</code> — 3 exemplars (1 TP multi-alert + 2 structural FP). <code>zeroshot</code> — no exemplars (<code>8b_fs0_zeroshot</code>). <code>coder30b_fs3_recall</code> — same fs3 pack, recall-oriented comparison arm.</dd>

<dt>Macro-F1</dt>
<dd>Mean of per-track F1 (FP track F1 with positive class FP, TP track F1 with positive class TP). Borderline track excluded from this table.</dd>

<dt>CRITICAL</dt>
<dd>Count of gold-<b>TP</b> cases misclassified as <b>FP</b> (missed vulnerabilities on the TP track only). Hard-gate limit: &gt;3 on PoC n=27 total test cases; on the 600-case Phase 2 test, same rate → limit = (3×600)//27 = 66 (fail if CRITICAL&gt;66).</dd>

<dt>Accuracy</dt>
<dd>Strict correct labels on FP + TP tracks combined: (correct FP-track + correct TP-track) / 400.</dd>

<dt>Confusion matrices</dt>
<dd>Full 3×3 tables (gold TP / FP / BL × predicted TP / FP / BL) over all 600 test cases. Compared cells: Stage 2 GOOD ship cell, Phase 2 MINIMUM-tier matrix cell (same profile/fs3), and Phase 3A LoRA eval. <b>Diagonal</b> counts are gold-correct per track. <b>TP→FP</b> = CRITICAL missed vulns; <b>BL→FP</b> = HIGH over-dismiss; <b>FP→TP</b> = noise kept. Neither Stage 2 GOOD nor Phase 2 MINIMUM predicts BL on BL-gold cases (0/200 diagonal).</dd>

<dt>Phase 3A LoRA</dt>
<dd>Qwen3.5-9B fine-tuned with LoRA on 1500 gold-label SFT examples (train split). Eval uses same v7-balanced prompt, thinking on, fs3 as Stage 2. Included in main table when eval summaries exist.</dd>

<dt>Phase 3B LoRA</dt>
<dd>Teacher distillation on 1500 train cases · LoRA r=32 · training CSS pick epoch 6 (fs3+CoT val) · ship rerank epoch 4 (fs0_off val). Test rows: <b>fs3 CoT</b>, <b>fs0 direct</b>, and <b>fs0 ship (rerank)</b>. Reports: <code>reports/phase3b/</code> · HTML: <code>runs/phase3/stage3b/benchmark/PHASE3B_BENCHMARK.html</code>.</dd>

<dt>Phase 3C LoRA</dt>
<dd>Ship-aligned retrain: json_only targets · fs0_off train prompts · fs0_off val CSS · v7-ship · epoch 6 pick · test SRS 89.9% (gap-fill). Reports: <code>reports/phase3c/</code> · BL analysis: <code>PHASE3C_BL_ANALYSIS.md</code>.</dd>

<dt>CSS (Phase 3B checkpoint selection)</dt>
<dd><code>CSS = 0.35·SRS + 0.35·VDR + 0.20·FPRR + 0.10·Macro-F1</code> on validation; disqualified if VDR &lt; 0.75. Used for epoch pick only — not the final ship gate (test SRS is).</dd>

<dt>Test scope</dt>
<dd>Phase 2 stageless matrix (6 profiles × 4 configs = 24 cells) plus 4 Stage 2 ship cells plus Phase 3A/3B/3C LoRA when eval completes. Phase 1 Stage 2 (904/1373) excluded.</dd>
</dl>
</section>
</body>
</html>
"""


def main() -> None:
    baselines = _load_baseline_rows()
    phase3_row = _load_phase3a_row()
    phase3b_rows = _load_phase3b_rows()
    phase3c_rows = _load_phase3c_rows()
    experiment_parts = baselines + _load_phase2_matrix_rows() + _load_stage2_ship_rows()
    if phase3_row:
        experiment_parts.append(phase3_row)
    experiment_parts.extend(phase3b_rows)
    experiment_parts.extend(phase3c_rows)
    experiments = _sort_experiments(experiment_parts)
    comparisons = (
        _load_confusion_comparisons()
        + _load_phase3b_confusion_rows()
        + _load_phase3c_confusion_rows()
    )
    ops = _load_ops_rows()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    exp_doc = {
        "generated_at": utc_now_iso(),
        "n_rows": len(experiments),
        "target_cases_per_track": TARGET,
        "note": (
            "3 baselines + Phase 2 stageless matrix (24 cells) + Stage 2 ship (4 cells)"
            + (" + Phase 3A LoRA" if phase3_row else "")
            + (f" + Phase 3B LoRA ({len(phase3b_rows)} cells)" if phase3b_rows else "")
            + (f" + Phase 3C LoRA ({len(phase3c_rows)} cells)" if phase3c_rows else "")
            + "."
        ),
        "baselines": baselines,
        "experiments": experiments,
        "confusion_comparisons": comparisons,
        "rankings": {
            "top5_srs": sorted(experiments, key=lambda r: -r["srs"])[:5],
            "bottom5_srs": sorted(experiments, key=lambda r: r["srs"])[:5],
        },
    }
    ops_doc = {
        "generated_at": utc_now_iso(),
        "n_rows": len(ops),
        "ops": ops,
    }
    meta = {
        "generated_at": utc_now_iso(),
        "html": str(HTML_OUT.relative_to(_SAST)),
        "phase2_matrix_rows": len(_load_phase2_matrix_rows()),
        "stage2_ship_rows": len(_load_stage2_ship_rows()),
        "phase3a_row": phase3_row is not None,
        "phase3b_rows": len(phase3b_rows),
        "phase3c_rows": len(phase3c_rows),
        "confusion_comparisons": len(comparisons),
    }

    EXP_JSON.write_text(json.dumps(exp_doc, indent=2), encoding="utf-8")
    OPS_JSON.write_text(json.dumps(ops_doc, indent=2), encoding="utf-8")
    META_JSON.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    CONFUSION_JSON.write_text(json.dumps(comparisons, indent=2), encoding="utf-8")
    HTML_OUT.write_text(_build_html(experiments, ops, comparisons), encoding="utf-8")

    from collections import Counter
    tiers = Counter(r["tier"] for r in experiments)
    print(f"Wrote {HTML_OUT}")
    print(f"Experiment rows: {len(experiments)} ({len(baselines)} baseline + matrix + stage2 ship"
          f"{'' if not phase3_row else ' + phase3a'}"
          f"{'' if not phase3b_rows else f' + phase3b×{len(phase3b_rows)}'}"
          f"{'' if not phase3c_rows else f' + phase3c×{len(phase3c_rows)}'})")
    print(f"Confusion comparisons: {len(comparisons)}")
    print(f"Tiers: {dict(sorted(tiers.items()))}")
    print(f"Ops rows: {len(ops)}")


if __name__ == "__main__":
    main()
