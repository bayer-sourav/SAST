#!/usr/bin/env python3
"""Phase 2 status report: execution timing, merged metrics, borderline — writes PHASE2_REPORT.md."""

from __future__ import annotations

import json
from collections import Counter
import re
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

_BENCH = Path(__file__).resolve().parents[2]
_SAST = Path(__file__).resolve().parents[3]
if str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

from merge_phase1_summary import _slm_row  # noqa: E402
from timing import (  # noqa: E402
    aggregate_seconds,
    aggregate_tokens,
    case_elapsed_sec,
    format_duration,
    read_run_meta,
    tokens_from_meta,
    utc_now_iso,
    write_json,
)
from benchmark.triage_labels import VALID_LABELS  # noqa: E402
from benchmark.srs import compute_srs  # noqa: E402
from benchmark.summarize_triage import (  # noqa: E402
    _f1_for_positive_class,
    _metrics_for_cases,
    macro_f1_from_track_f1s,
)

MANIFEST_PATH = _BENCH / "phases" / "phase2" / "MANIFEST.json"

CORE_PROFILES = (
    "qwen3_4b_bnb",
    "qwen3_8b_bnb",
    "qwen3_14b_bnb",
    "qwen3_coder_30b_bnb",
)
EXTENSION_PROFILES = ("qwen3_5_4b_bnb", "qwen3_5_9b_bnb")
ALL_PROFILES = CORE_PROFILES + EXTENSION_PROFILES
TARGET = 200
TRACKS = {
    "fp": ("FP", _SAST / "runs/phase2/fp"),
    "tp": ("TP", _SAST / "runs/phase2/tp"),
    "bl": ("BL", _SAST / "runs/phase2/bl"),
}
CONFIGS = tuple((t, f) for t in ("off", "on") for f in (0, 3))
CELL_RE = re.compile(
    r"^comparison_(fp|tp|bl)_test_thinking_(off|on)_fewshot_(\d+)\.json$"
)
_GAPS_RE = re.compile(r"Missing valid results:\s*(\d+)")


def _pct(x: float) -> str:
    return f"{100 * float(x):.1f}%"


def _dash() -> str:
    return "—"

def _fmt_num(n: float | int) -> str:
    return str(int(round(float(n))))


def _md_table(columns: list[str], rows: list[list[str]]) -> list[str]:
    n = len(columns)
    if any(len(row) != n for row in rows):
        raise ValueError(f"row width must match {n} columns")
    header = "| " + " | ".join(columns) + " |"
    sep = "| " + " | ".join(["---"] * n) + " |"
    return [header, sep] + ["| " + " | ".join(row) + " |" for row in rows]


def _config_title(thinking: str, fewshot: int) -> str:
    think_label = "Thinking on" if thinking == "on" else "Thinking off"
    return f"{think_label} · Few-shot {fewshot}"



def _stdev(vals: list[float]) -> float:
    return statistics.stdev(vals) if len(vals) >= 2 else 0.0


def _mean(vals: list[float]) -> float:
    return sum(vals) / len(vals) if vals else 0.0


def _gaps_skipped_count(logs_dir: Path) -> int:
    path = logs_dir / "gaps_skipped.txt"
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8")
    m = _GAPS_RE.search(text)
    if m:
        return int(m.group(1))
    return sum(
        1
        for line in text.splitlines()
        if line.strip() and not line.startswith(("skipped_at", "reason=", "---", "Missing "))
    )


def _count_valid(runs_root: Path, profile: str, thinking: str, fewshot: int) -> int:
    d = runs_root / f"thinking_{thinking}" / f"fewshot_{fewshot}" / profile / "llm"
    if not d.is_dir():
        return 0
    n = 0
    for p in d.iterdir():
        rp = p / "agent-llm-triage-result.json"
        if not rp.is_file():
            continue
        try:
            lbl = str(json.loads(rp.read_text(encoding="utf-8")).get("label", "")).strip().upper()
        except json.JSONDecodeError:
            continue
        if lbl in VALID_LABELS:
            n += 1
    return n


def _enrich_case_tokens(cell_path: Path, cases: list[dict]) -> list[dict]:
    out = []
    for c in cases:
        row = dict(c)
        if row.get("total_tokens") is not None:
            out.append(row)
            continue
        run_dir = cell_path / str(row.get("case_id", ""))
        if run_dir.is_dir():
            row.update(tokens_from_meta(read_run_meta(run_dir)))
        out.append(row)
    return out


def _valid_label_in_run(case_dir: Path) -> bool:
    rp = case_dir / "agent-llm-triage-result.json"
    if not rp.is_file():
        return False
    try:
        lbl = str(json.loads(rp.read_text(encoding="utf-8")).get("label", "")).strip().upper()
    except json.JSONDecodeError:
        return False
    return lbl in VALID_LABELS


def _scan_cell(
    track_root: Path, thinking: str, fewshot: int, profile: str
) -> dict | None:
    runs_root = track_root / f"thinking_{thinking}" / f"fewshot_{fewshot}"
    cell_path = runs_root / profile / "llm"
    if not cell_path.is_dir():
        return None

    timing_by_id: dict[str, dict] = {}
    cell_timing_path = runs_root / profile / "cell_timing.json"
    if cell_timing_path.is_file():
        try:
            timing_doc = json.loads(cell_timing_path.read_text(encoding="utf-8"))
            for c in timing_doc.get("cases", []):
                cid = str(c.get("case_id", "")).strip()
                if cid:
                    timing_by_id[cid] = c
        except json.JSONDecodeError:
            pass

    cases: list[dict] = []
    for case_dir in sorted(cell_path.iterdir()):
        if not case_dir.is_dir():
            continue
        if not _valid_label_in_run(case_dir):
            continue
        cid = case_dir.name
        sup = timing_by_id.get(cid, {})
        meta = read_run_meta(case_dir)
        elapsed = case_elapsed_sec(case_dir)
        if elapsed is None and sup.get("elapsed_sec") is not None:
            elapsed = float(sup["elapsed_sec"])
        tok = tokens_from_meta(meta)
        for key in ("input_tokens", "output_tokens", "total_tokens"):
            if tok.get(key) is None and sup.get(key) is not None:
                tok[key] = sup[key]
        row: dict = {"case_id": cid, **tok}
        if elapsed is not None:
            row["elapsed_sec"] = round(elapsed, 3)
            row["wall_sec"] = round(elapsed, 3)
        if meta.get("inference_sec") is not None:
            row["inference_sec"] = meta.get("inference_sec")
        elif sup.get("inference_sec") is not None:
            row["inference_sec"] = sup.get("inference_sec")
        cases.append(row)

    if not cases:
        return None

    elapsed_vals = [float(c["elapsed_sec"]) for c in cases if c.get("elapsed_sec") is not None]
    infer_vals = [
        float(c["inference_sec"]) for c in cases if c.get("inference_sec") is not None
    ]
    wall_sec = sum(elapsed_vals) if elapsed_vals else None
    return {
        "profile": profile,
        "n_cases": len(cases),
        "cases": cases,
        "aggregate": {
            "wall_clock_sec": wall_sec,
            "per_case": aggregate_seconds(elapsed_vals),
            "inference": aggregate_seconds(infer_vals),
            "tokens": {
                "input": aggregate_tokens(cases, "input_tokens"),
                "output": aggregate_tokens(cases, "output_tokens"),
                "total": aggregate_tokens(cases, "total_tokens"),
            },
        },
    }


def _timing_row(cell: dict | None) -> dict[str, str]:
    empty = {k: _dash() for k in (
        "wall", "mean_case", "stdev_case", "median_case",
        "mean_infer", "stdev_infer", "mean_tok", "stdev_tok",
        "mean_in", "stdev_in", "mean_out", "stdev_out",
    )}
    if not cell:
        return empty
    cases = cell.get("cases", [])
    if not cases:
        return empty

    agg = cell.get("aggregate", {})
    wall_sec = agg.get("wall_clock_sec")
    if wall_sec is None:
        wall_sec = cell.get("elapsed_sec")
    if wall_sec is None:
        elapsed_vals = [
            float(c["elapsed_sec"]) for c in cases if c.get("elapsed_sec") is not None
        ]
        wall_sec = sum(elapsed_vals) if elapsed_vals else 0.0

    case_secs = [
        float(c.get("wall_sec") or c["elapsed_sec"])
        for c in cases
        if c.get("elapsed_sec") is not None
    ]
    infer_secs = [
        float(c["inference_sec"]) for c in cases if c.get("inference_sec") is not None
    ]
    in_tok = [float(c["input_tokens"]) for c in cases if c.get("input_tokens") is not None]
    out_tok = [float(c["output_tokens"]) for c in cases if c.get("output_tokens") is not None]
    tot_tok = [float(c["total_tokens"]) for c in cases if c.get("total_tokens") is not None]

    def fmt_time(mean_v: float, st_v: float) -> tuple[str, str]:
        return format_duration(mean_v), format_duration(st_v)

    mc, sc = _mean(case_secs), _stdev(case_secs)
    mi, si = _mean(infer_secs), _stdev(infer_secs)
    mt, st = _mean(tot_tok), _stdev(tot_tok)
    mn_i, sd_i = _mean(in_tok), _stdev(in_tok)
    mn_o, sd_o = _mean(out_tok), _stdev(out_tok)
    med = statistics.median(case_secs) if case_secs else 0.0

    m_case, s_case = fmt_time(mc, sc)
    m_inf, s_inf = fmt_time(mi, si)

    return {
        "wall": format_duration(float(wall_sec)),
        "mean_case": m_case if case_secs else format_duration(0.0),
        "stdev_case": s_case if case_secs else format_duration(0.0),
        "median_case": format_duration(med) if case_secs else format_duration(0.0),
        "mean_infer": m_inf if infer_secs else format_duration(0.0),
        "stdev_infer": s_inf if infer_secs else format_duration(0.0),
        "mean_tok": _fmt_num(mt),
        "stdev_tok": f"{st:.1f}",
        "mean_in": _fmt_num(mn_i),
        "stdev_in": f"{sd_i:.1f}",
        "mean_out": _fmt_num(mn_o),
        "stdev_out": f"{sd_o:.1f}",
    }


def _profiles_for_config(
    summaries_dir: Path,
    track_root: Path,
    thinking: str,
    fewshot: int,
    track_key: str,
) -> list[str]:
    found: list[str] = []
    comp = summaries_dir / f"comparison_{track_key}_test_thinking_{thinking}_fewshot_{fewshot}.json"
    comp_data: dict = {}
    if comp.is_file():
        try:
            comp_data = json.loads(comp.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            comp_data = {}

    for profile in ALL_PROFILES:
        if _slm_row(comp_data, profile) is not None:
            found.append(profile)
            continue
        runs_root = track_root / f"thinking_{thinking}" / f"fewshot_{fewshot}"
        if (runs_root / profile / "cell_timing.json").is_file():
            found.append(profile)
            continue
        if _count_valid(track_root, profile, thinking, fewshot) > 0:
            found.append(profile)
    # preserve order, dedupe
    seen: set[str] = set()
    ordered: list[str] = []
    for p in ALL_PROFILES:
        if p in found and p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def _status(
    track_root: Path,
    profile: str,
    thinking: str,
    fewshot: int,
    comp_row: dict | None,
) -> str:
    evaluated = None
    if comp_row is not None:
        evaluated = int(comp_row.get("evaluated", 0))
    if evaluated is None:
        evaluated = _count_valid(track_root, profile, thinking, fewshot)
    return f"{evaluated} eval"


def _load_label(result_path: Path) -> str | None:
    if not result_path.is_file():
        return None
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    lbl = str(data.get("label", "")).strip().upper()
    return lbl if lbl in VALID_LABELS else None


def _manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        return {}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _manifest_track_key(track_key: str) -> str:
    return "borderline" if track_key == "bl" else track_key


def _case_json_path(corpus_dir: Path, cid: str) -> Path | None:
    for name in (f"OWASP_{cid}.json", f"{cid}.json"):
        path = corpus_dir / name
        if path.is_file():
            return path
    return None


def _benchmark_gold_label(case: dict) -> str:
    return "TP" if case.get("benchmark_real_vuln") else "FP"


def _predictions_for_cell(
    track_root: Path,
    thinking: str,
    fewshot: int,
    profile: str,
    case_ids: list[str],
) -> dict[str, str | None]:
    llm_root = (
        track_root / f"thinking_{thinking}" / f"fewshot_{fewshot}" / profile / "llm"
    )
    predicted: dict[str, str | None] = {}
    for cid in case_ids:
        predicted[cid] = _load_label(
            llm_root / cid / "agent-llm-triage-result.json"
        )
    return predicted


def _borderline_row_from_disk(
    track_root: Path,
    thinking: str,
    fewshot: int,
    profile: str,
    corpus_dir: Path,
    case_ids: list[str],
) -> dict | None:
    llm_root = (
        track_root / f"thinking_{thinking}" / f"fewshot_{fewshot}" / profile / "llm"
    )
    if not llm_root.is_dir():
        return None
    dist: Counter[str] = Counter()
    missing = 0
    lenient_correct = 0
    bench_agree = 0
    bl_label = 0
    evaluated = 0
    n = len(case_ids)
    for cid in case_ids:
        case_path = _case_json_path(corpus_dir, cid)
        if case_path is None:
            missing += 1
            dist["(missing)"] += 1
            continue
        try:
            case = json.loads(case_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            missing += 1
            dist["(missing)"] += 1
            continue
        bench_lbl = _benchmark_gold_label(case)
        acceptable = set(case.get("acceptable_labels") or ["TP", "FP", "BL"])
        pred = _load_label(llm_root / cid / "agent-llm-triage-result.json")
        if pred is None:
            missing += 1
            dist["(missing)"] += 1
            continue
        evaluated += 1
        dist[pred] += 1
        if pred in acceptable:
            lenient_correct += 1
        if pred == bench_lbl:
            bench_agree += 1
        if pred == "BL":
            bl_label += 1
    if evaluated <= 0:
        return None
    tp_rate = dist.get("TP", 0) / evaluated
    fp_rate = dist.get("FP", 0) / evaluated
    bl_rate = bl_label / evaluated
    return {
        "profile": profile,
        "n_cases": n,
        "evaluated": evaluated,
        "missing": missing,
        "coverage": evaluated / n if n else 0.0,
        "distribution": dict(dist),
        "tp_rate": tp_rate,
        "fp_rate": fp_rate,
        "bl_rate": bl_rate,
        "lenient_accuracy": lenient_correct / evaluated,
        "benchmark_agreement": bench_agree / evaluated,
        "ambiguity_index": 1.0 - abs(tp_rate - 0.5) * 2,
        "f1_bl": _f1_for_positive_class("BL", dist, evaluated=evaluated),
    }


def _triage_row_from_disk(
    track_key: str,
    track_root: Path,
    thinking: str,
    fewshot: int,
    profile: str,
    case_ids: list[str],
    gold: str,
) -> dict | None:
    predicted = _predictions_for_cell(
        track_root, thinking, fewshot, profile, case_ids
    )
    if not any(v is not None for v in predicted.values()):
        return None
    row = _metrics_for_cases(case_ids, gold=gold, predicted=predicted)
    if int(row.get("evaluated", 0)) <= 0:
        return None
    row["profile"] = profile
    return row


def _comparison_cell_from_disk(
    track_key: str,
    track_root: Path,
    thinking: str,
    fewshot: int,
) -> dict:
    manifest = _manifest()
    track_info = (manifest.get("tracks") or {}).get(_manifest_track_key(track_key)) or {}
    case_ids = [str(c) for c in track_info.get("case_ids") or []]
    if not case_ids:
        return {}
    gold = str(track_info.get("gold", track_key.upper())).upper()
    corpus_dir = Path(str(track_info.get("corpus_dir", "")))
    out: dict = {}
    for profile in ALL_PROFILES:
        if track_key == "bl":
            row = _borderline_row_from_disk(
                track_root, thinking, fewshot, profile, corpus_dir, case_ids
            )
        else:
            row = _triage_row_from_disk(
                track_key, track_root, thinking, fewshot, profile, case_ids, gold
            )
        if row:
            out[f"SLM ({profile})"] = row
    return out


def _load_comparison_cells(summaries_dir: Path) -> dict[tuple[str, str, int], dict]:
    cells: dict[tuple[str, str, int], dict] = {}
    for path in sorted(summaries_dir.glob("comparison_*_test_thinking_*_fewshot_*.json")):
        m = CELL_RE.match(path.name)
        if not m:
            continue
        track, thinking, fewshot = m.group(1), m.group(2), int(m.group(3))
        try:
            cells[(track, thinking, fewshot)] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue

    for track_key, (_, track_root) in TRACKS.items():
        for thinking, fewshot in CONFIGS:
            key = (track_key, thinking, fewshot)
            disk = _comparison_cell_from_disk(
                track_key, track_root, thinking, fewshot
            )
            if not disk:
                continue
            merged = dict(cells.get(key, {}))
            for row_key, row in disk.items():
                if int(row.get("evaluated", 0)) > 0:
                    merged[row_key] = row
            cells[key] = merged
    return cells


def _f1_bl_from_row(bl_m: dict | None) -> float | None:
    if not bl_m:
        return None
    if bl_m.get("f1_bl") is not None:
        return float(bl_m["f1_bl"])
    evaluated = int(bl_m.get("evaluated", 0))
    if evaluated <= 0:
        return None
    dist = Counter(bl_m.get("distribution") or {})
    return _f1_for_positive_class("BL", dist, evaluated=evaluated)


def _merge_matrix(
    fp_rows: dict,
    tp_rows: dict,
    bl_rows: dict,
    profiles: list[str],
    thinking: str,
    fewshot: int,
) -> dict:
    out: dict = {
        "_meta": {
            "stage": "phase2",
            "thinking": thinking,
            "fewshot": fewshot,
            "profiles": profiles,
        },
        "models": {},
        "borderline": {},
    }
    for profile in profiles:
        fp_m = _slm_row(fp_rows, profile)
        tp_m = _slm_row(tp_rows, profile)
        bl_m = bl_rows.get(f"SLM ({profile})")
        if not fp_m or not tp_m:
            continue
        if int(fp_m.get("evaluated", 0)) <= 0 or int(tp_m.get("evaluated", 0)) <= 0:
            continue
        fprr = float(fp_m.get("fprr", fp_m.get("fp_removal_rate", 0.0)))
        vdr = float(tp_m.get("vdr", tp_m.get("tp_rate", 0.0)))
        f1_fp = float(fp_m.get("f1", 0.0))
        f1_tp = float(tp_m.get("f1", 0.0))
        len_acc = None
        bench_ag = None
        amb_idx = None
        cov_bl = None
        f1_bl = _f1_bl_from_row(bl_m)
        f1_pack = macro_f1_from_track_f1s(f1_fp, f1_tp, f1_bl)
        srs3 = None
        if bl_m and int(bl_m.get("evaluated", 0)) > 0:
            len_acc = float(bl_m.get("lenient_accuracy", 0.0))
            bench_ag = float(bl_m.get("benchmark_agreement", 0.0))
            amb_idx = float(bl_m.get("ambiguity_index", 0.0))
            cov_bl = float(bl_m.get("coverage", 0.0))
            srs3 = (fprr + vdr + len_acc) / 3.0
        srs = compute_srs(fp_m, tp_m, bl_m)
        if srs is None:
            srs = 0.5 * fprr + 0.5 * vdr
        out["models"][profile] = {
            "fprr": fprr,
            "vdr": vdr,
            "srs": srs,
            "srs3": srs3,
            "f1_fp_track": f1_fp,
            "f1_tp_track": f1_tp,
            "f1": f1_pack["f1_fp_tp"],
            "f1_fp_tp": f1_pack["f1_fp_tp"],
            "macro_f1": f1_pack["macro_f1"],
            "f1_bl": f1_bl,
            "lenient_accuracy": len_acc,
            "benchmark_agreement": bench_ag,
            "ambiguity_index": amb_idx,
            "cov_bl": cov_bl,
            "fp_track": fp_m,
            "tp_track": tp_m,
        }
        if bl_m:
            out["borderline"][profile] = bl_m

    for profile in profiles:
        if profile in out["borderline"]:
            continue
        bl_m = bl_rows.get(f"SLM ({profile})")
        if bl_m and int(bl_m.get("evaluated", 0)) > 0:
            out["borderline"][profile] = bl_m
    return out


def _evaluated_count(
    track_root: Path,
    profile: str,
    thinking: str,
    fewshot: int,
    comp_row: dict | None,
) -> int:
    if comp_row is not None:
        return int(comp_row.get("evaluated", 0))
    return _count_valid(track_root, profile, thinking, fewshot)


def _execution_summary_section(
    thinking: str, fewshot: int, profiles: list[str], cells_comp: dict
) -> list[str]:
    timing_cols = [
        "Category",
        "Model",
        "N eval",
        "Wall",
        "Mean",
        "σ",
        "Median",
        "Mean infer",
        "σ infer",
    ]
    token_cols = [
        "Category",
        "Model",
        "N eval",
        "Mean total",
        "σ",
        "Mean in",
        "σ",
        "Mean out",
        "σ",
    ]
    timing_rows: list[list[str]] = []
    token_rows: list[list[str]] = []
    for track_key, (cat_label, track_root) in TRACKS.items():
        comp = cells_comp.get((track_key, thinking, fewshot), {})
        for profile in profiles:
            comp_row = _slm_row(comp, profile) if comp else None
            evaluated = _evaluated_count(
                track_root, profile, thinking, fewshot, comp_row
            )
            if evaluated <= 0:
                continue
            cell = _scan_cell(track_root, thinking, fewshot, profile)
            n_eval = _fmt_num(evaluated)
            t = _timing_row(cell)
            timing_rows.append(
                [
                    f"{cat_label} ({TARGET})",
                    profile,
                    n_eval,
                    t["wall"],
                    t["mean_case"],
                    t["stdev_case"],
                    t["median_case"],
                    t["mean_infer"],
                    t["stdev_infer"],
                ]
            )
            token_rows.append(
                [
                    f"{cat_label} ({TARGET})",
                    profile,
                    n_eval,
                    t["mean_tok"],
                    t["stdev_tok"],
                    t["mean_in"],
                    t["stdev_in"],
                    t["mean_out"],
                    t["stdev_out"],
                ]
            )

    lines = ["### Execution Summary", ""]
    lines.append("**Timing**")
    lines.append("")
    if timing_rows:
        lines.extend(_md_table(timing_cols, timing_rows))
    else:
        lines.append("_No timing data for this configuration._")
    lines.extend(["", "**Tokens**", ""])
    if token_rows:
        lines.extend(_md_table(token_cols, token_rows))
    else:
        lines.append("_No token data for this configuration._")
    return lines


def _pct_or_dash(x: float | None) -> str:
    return _pct(x) if x is not None else _dash()


def _results_section(matrix: dict) -> list[str]:
    summary_cols = [
        "Profile",
        "FPRR",
        "VDR",
        "SRS",
        "Macro F1",
        "LenAcc",
        "SRS3",
    ]
    detail_cols = [
        "Profile",
        "F1₂",
        "F1-FP",
        "F1-TP",
        "F1-BL",
        "Cov-FP",
        "Cov-TP",
        "Cov-BL",
        "BenchAg",
        "AmbIdx",
    ]
    summary_rows: list[list[str]] = []
    detail_rows: list[list[str]] = []
    for profile, m in matrix.get("models", {}).items():
        fp = m.get("fp_track", {})
        tp = m.get("tp_track", {})
        amb = m.get("ambiguity_index")
        amb_s = f"{float(amb):.3f}" if amb is not None else _dash()
        summary_rows.append(
            [
                profile,
                _pct(m["fprr"]),
                _pct(m["vdr"]),
                _pct(m["srs"]),
                _pct_or_dash(m.get("macro_f1")),
                _pct_or_dash(m.get("lenient_accuracy")),
                _pct_or_dash(m.get("srs3")),
            ]
        )
        detail_rows.append(
            [
                profile,
                _pct(m.get("f1", 0)),
                _pct(m.get("f1_fp_track", 0)),
                _pct(m.get("f1_tp_track", 0)),
                _pct_or_dash(m.get("f1_bl")),
                _pct(fp.get("coverage", 0)),
                _pct(tp.get("coverage", 0)),
                _pct_or_dash(m.get("cov_bl")),
                _pct_or_dash(m.get("benchmark_agreement")),
                amb_s,
            ]
        )

    lines = ["**Summary**", ""]
    if summary_rows:
        lines.extend(_md_table(summary_cols, summary_rows))
    else:
        lines.append("_No results for this configuration._")
    lines.extend(["", "**Detail**", ""])
    if detail_rows:
        lines.extend(_md_table(detail_cols, detail_rows))
    else:
        lines.append("_No results for this configuration._")
    return lines


def _borderline_dist_note(m: dict) -> str:
    tp = float(m.get("tp_rate", 0))
    fp = float(m.get("fp_rate", 0))
    bl = float(m.get("bl_rate", 0))
    top = max((("TP", tp), ("FP", fp), ("BL", bl)), key=lambda x: x[1])
    if top[1] >= 0.5:
        return f"{top[0]}-dominant"
    return "mixed"


def _borderline_section(matrix: dict) -> list[str]:
    cols = ["Profile", "TP%", "FP%", "BL%", "distribution note"]
    rows: list[list[str]] = []
    bl = matrix.get("borderline", {})
    for profile, m in bl.items():
        if int(m.get("evaluated", 0)) <= 0:
            continue
        rows.append(
            [
                profile,
                _pct(m.get("tp_rate", 0)),
                _pct(m.get("fp_rate", 0)),
                _pct(m.get("bl_rate", 0)),
                _borderline_dist_note(m),
            ]
        )
    lines = ["### Borderline label distribution", ""]
    if rows:
        lines.extend(_md_table(cols, rows))
    else:
        lines.append("_No borderline data for this configuration._")
    return lines


def _legend_section() -> list[str]:
    return [
        "## Legend",
        "",
        "- All rates (FPRR, VDR, LenAcc, F1, coverage, label %) use **evaluated cases only**; "
        "missing or skipped cases are excluded from denominators.",
        "- **VDR** is often low on the TP track because gold labels are TP while models frequently "
        "predict FP or BL — low recall on the TP slice reflects conservative triage bias, not "
        "random error.",
        "- **SRS** = 0.5×FPRR + 0.5×VDR (FP + TP tracks). **SRS₃** adds borderline **LenAcc**: "
        "(FPRR + VDR + LenAcc) / 3 when borderline data exists for the profile.",
        "- **Macro F1** = mean(F1-FP, F1-TP, F1-BL) when borderline F1 is available; otherwise "
        "mean(F1-FP, F1-TP). **F1₂** = 0.5×F1-FP + 0.5×F1-TP (Phase 1 compatible; JSON field `f1`).",
        "- High FPRR with low VDR yields a moderate **SRS** (~50–65%): strong FP removal alongside "
        "weak TP retention.",
        "",
    ]


def _qwen35_partial_note() -> str | None:
    incomplete: list[str] = []
    for profile in EXTENSION_PROFILES:
        for track_key, (_, track_root) in TRACKS.items():
            for thinking, fewshot in CONFIGS:
                c = _count_valid(track_root, profile, thinking, fewshot)
                if 0 < c < TARGET:
                    incomplete.append(f"{profile} {track_key} think={thinking} fs={fewshot}: {c}/{TARGET}")
                elif c == 0:
                    incomplete.append(f"{profile} {track_key} think={thinking} fs={fewshot}: no data")
    if not incomplete:
        # any extension profile with partial coverage across matrix
        for profile in EXTENSION_PROFILES:
            total = sum(
                _count_valid(root, profile, t, f)
                for _, root in TRACKS.values()
                for t, f in CONFIGS
            )
            full = TARGET * len(TRACKS) * len(CONFIGS)
            if 0 < total < full:
                return (
                    f"**Qwen3.5 extension ({', '.join(EXTENSION_PROFILES)})**: "
                    f"partial matrix coverage ({total}/{full} valid case runs on disk)."
                )
        return None
    return (
        "**Qwen3.5 extension**: partial or missing cells — "
        + "; ".join(incomplete[:8])
        + (" …" if len(incomplete) > 8 else "")
    )


def _build_timing_report(sast: Path) -> dict:
    all_case: list[float] = []
    all_case_tokens: list[dict] = []
    all_cell_wall: list[float] = []
    experiments: list[dict] = []

    for track_name, (_, track_root) in TRACKS.items():
        for thinking, fewshot in CONFIGS:
            profiles = _profiles_for_config(
                sast / "runs/phase2/summaries",
                track_root,
                thinking,
                fewshot,
                track_name,
            )
            for profile in profiles:
                cell = _scan_cell(track_root, thinking, fewshot, profile)
                if not cell:
                    continue
                agg = cell.get("aggregate", {})
                per = agg.get("per_case", {})
                wall = float(
                    cell.get("elapsed_sec")
                    or agg.get("wall_clock_sec")
                    or per.get("total_sec", 0)
                )
                if wall > 0:
                    all_cell_wall.append(wall)
                tok_agg = agg.get("tokens", {})
                tot_tok = tok_agg.get("total", {})
                for c in cell.get("cases", []):
                    if c.get("elapsed_sec") is not None:
                        all_case.append(float(c["elapsed_sec"]))
                    if c.get("total_tokens") is not None:
                        all_case_tokens.append(c)
                experiments.append(
                    {
                        "track": track_name.upper(),
                        "thinking": thinking,
                        "fewshot": fewshot,
                        "profile": profile,
                        "n_cases": cell.get("n_cases", 0),
                        "n_target": TARGET,
                        "wall_clock_sec": wall,
                        "wall_clock_human": format_duration(wall) if wall else "—",
                        "mean_case_sec": per.get("mean_sec", 0),
                        "mean_case_human": format_duration(per.get("mean_sec", 0))
                        if per.get("mean_sec")
                        else "—",
                        "tokens": tok_agg,
                        "mean_total_tokens": tot_tok.get("mean", 0),
                    }
                )

    report: dict = {
        "generated_at": utc_now_iso(),
        "stage": "phase2",
        "n_cases_per_cell": TARGET,
        "experiments": experiments,
        "overall": {
            "n_experiments_with_timing": len(experiments),
            "n_case_timings": len(all_case),
            "case_timing": aggregate_seconds(all_case),
            "cell_wall_clock": aggregate_seconds(all_cell_wall),
            "tokens": {
                "input": aggregate_tokens(all_case_tokens, "input_tokens"),
                "output": aggregate_tokens(all_case_tokens, "output_tokens"),
                "total": aggregate_tokens(all_case_tokens, "total_tokens"),
            },
        },
    }
    o = report["overall"]
    if o["case_timing"].get("count"):
        o["case_timing"]["total_human"] = format_duration(o["case_timing"]["total_sec"])
        o["case_timing"]["mean_human"] = format_duration(o["case_timing"]["mean_sec"])
    return report


def main() -> None:
    sast = _SAST
    summaries_dir = sast / "runs/phase2/summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    cells_comp = _load_comparison_cells(summaries_dir)
    n_gaps = _gaps_skipped_count(sast / "runs/phase2/logs")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        "# Phase 2 benchmark report",
        "",
        f"Generated: {generated}",
        "",
        f"Note: **{n_gaps} gaps skipped** (per `runs/phase2/logs/gaps_skipped.txt`).",
        "",
        *_legend_section(),
    ]

    for thinking, fewshot in CONFIGS:
        profiles: list[str] = []
        for track_key, (_, track_root) in TRACKS.items():
            for p in _profiles_for_config(
                summaries_dir, track_root, thinking, fewshot, track_key
            ):
                if p not in profiles:
                    profiles.append(p)

        fp_rows = cells_comp.get(("fp", thinking, fewshot), {})
        tp_rows = cells_comp.get(("tp", thinking, fewshot), {})
        bl_rows = cells_comp.get(("bl", thinking, fewshot), {})
        matrix = _merge_matrix(fp_rows, tp_rows, bl_rows, profiles, thinking, fewshot)

        matrix_path = summaries_dir / f"phase2_matrix_thinking_{thinking}_fewshot_{fewshot}.json"
        matrix_path.write_text(json.dumps(matrix, indent=2), encoding="utf-8")
        print(f"Wrote {matrix_path}")

        lines.extend(
            [
                f"## {_config_title(thinking, fewshot)}",
                "",
                *_execution_summary_section(thinking, fewshot, profiles, cells_comp),
                "",
                f"### Results: {_config_title(thinking, fewshot)}",
                "",
                *_results_section(matrix),
                "",
                *_borderline_section(matrix),
                "",
            ]
        )

    q35 = _qwen35_partial_note()
    if q35:
        lines.extend(["## Extension profiles", "", q35, ""])

    report_path = summaries_dir / "PHASE2_REPORT.md"
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(f"Wrote {report_path}")

    timing_path = sast / "benchmark/phase2_timing_report.json"
    timing_report = _build_timing_report(sast)
    write_json(timing_path, timing_report)
    print(f"Wrote {timing_path}")


if __name__ == "__main__":
    main()
