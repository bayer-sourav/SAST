#!/usr/bin/env python3
"""Phase 2 tabular report (execution, results, borderline) — writes PHASE2_TABLES.md."""

from __future__ import annotations

import importlib.util
import json
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

# Load sibling module without package install
_spec = importlib.util.spec_from_file_location(
    "report_phase2_status",
    _HERE / "report_phase2_status.py",
)
_rps = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_rps)

CONFIGS = _rps.CONFIGS
TARGET = _rps.TARGET
TRACKS = _rps.TRACKS
ALL_PROFILES = _rps.ALL_PROFILES
_load_comparison_cells = _rps._load_comparison_cells
_merge_matrix = _rps._merge_matrix
_profiles_for_config = _rps._profiles_for_config
_scan_cell = _rps._scan_cell
_timing_row = _rps._timing_row
_slm_row = _rps._slm_row
_evaluated_count = _rps._evaluated_count
_gaps_skipped_count = _rps._gaps_skipped_count
_md_table = _rps._md_table
_pct = _rps._pct
_dash = _rps._dash
_fmt_num = _rps._fmt_num


def _status_str(evaluated: int, missing: int) -> str:
    if evaluated >= TARGET and missing == 0:
        return "Done"
    return f"{evaluated} / {TARGET}"


def _profiles_union(
    summaries_dir: Path, thinking: str, fewshot: int
) -> list[str]:
    found: list[str] = []
    for track_key, (_, track_root) in TRACKS.items():
        for p in _profiles_for_config(
            summaries_dir, track_root, thinking, fewshot, track_key
        ):
            if p not in found:
                found.append(p)
    ordered: list[str] = []
    for p in ALL_PROFILES:
        if p in found:
            ordered.append(p)
    return ordered


def _execution_section(
    thinking: str,
    fewshot: int,
    profiles: list[str],
    cells_comp: dict,
) -> list[str]:
    timing_cols = [
        "Category",
        "Model",
        "Status",
        "Wall",
        "Mean/Case",
        "σ",
        "Median",
        "Mean infer",
        "σ infer",
    ]
    token_cols = [
        "Category",
        "Model",
        "Status",
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
            missing = int(comp_row.get("missing", 0)) if comp_row else max(
                0, TARGET - evaluated
            )
            if evaluated <= 0 and missing >= TARGET:
                continue
            status = _status_str(evaluated, missing)
            cell = _scan_cell(track_root, thinking, fewshot, profile)
            t = _timing_row(cell)
            cat = f"{cat_label} ({TARGET})"
            timing_rows.append(
                [
                    cat,
                    profile,
                    status,
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
                    cat,
                    profile,
                    status,
                    t["mean_tok"] if t["mean_tok"] != _dash() else _dash(),
                    t["stdev_tok"] if t["stdev_tok"] != _dash() else _dash(),
                    t["mean_in"] if t["mean_in"] != _dash() else _dash(),
                    t["stdev_in"] if t["stdev_in"] != _dash() else _dash(),
                    t["mean_out"] if t["mean_out"] != _dash() else _dash(),
                    t["stdev_out"] if t["stdev_out"] != _dash() else _dash(),
                ]
            )

    lines = ["#### Execution Summary", ""]
    lines.append("**Timing**")
    lines.append("")
    if timing_rows:
        lines.extend(_md_table(timing_cols, timing_rows))
    else:
        lines.append("_No timing data._")
    lines.extend(["", "**Tokens**", ""])
    if token_rows:
        lines.extend(_md_table(token_cols, token_rows))
    else:
        lines.append("_No token data._")
    return lines


def _results_table(matrix: dict) -> list[str]:
    cols = [
        "Profile",
        "FPRR",
        "VDR",
        "SRS",
        "F1",
        "F1-FP",
        "F1-TP",
        "Cov-FP",
        "Cov-TP",
    ]
    rows: list[list[str]] = []
    for profile, m in matrix.get("models", {}).items():
        fp = m.get("fp_track", {})
        tp = m.get("tp_track", {})
        rows.append(
            [
                profile,
                _pct(m["fprr"]),
                _pct(m["vdr"]),
                _pct(m["srs"]),
                _pct(m.get("f1", m.get("f1_fp_tp", 0))),
                _pct(m.get("f1_fp_track", 0)),
                _pct(m.get("f1_tp_track", 0)),
                _pct(fp.get("coverage", 0)),
                _pct(tp.get("coverage", 0)),
            ]
        )
    if rows:
        return _md_table(cols, rows)
    return ["_No results for this configuration._"]


def _borderline_table(matrix: dict) -> list[str]:
    cols = [
        "Profile",
        "Cov",
        "TP%",
        "FP%",
        "BL%",
        "LenAcc",
        "BenchAg",
        "AmbIdx",
    ]
    rows: list[list[str]] = []
    for profile, m in matrix.get("borderline", {}).items():
        if int(m.get("evaluated", 0)) <= 0:
            continue
        amb = m.get("ambiguity_index")
        amb_s = f"{float(amb):.3f}" if amb is not None else _dash()
        rows.append(
            [
                profile,
                _pct(m.get("coverage", 0)),
                _pct(m.get("tp_rate", 0)),
                _pct(m.get("fp_rate", 0)),
                _pct(m.get("bl_rate", 0)),
                _pct(m.get("lenient_accuracy", 0)),
                _pct(m.get("benchmark_agreement", 0)),
                amb_s,
            ]
        )
    lines = ["#### Borderline Metrics", ""]
    if rows:
        lines.extend(_md_table(cols, rows))
    else:
        lines.append("_No borderline data for this configuration._")
    return lines


def _config_block(
    thinking: str,
    fewshot: int,
    summaries_dir: Path,
    cells_comp: dict,
) -> list[str]:
    profiles = _profiles_union(summaries_dir, thinking, fewshot)
    fp_rows = cells_comp.get(("fp", thinking, fewshot), {})
    tp_rows = cells_comp.get(("tp", thinking, fewshot), {})
    bl_rows = cells_comp.get(("bl", thinking, fewshot), {})
    matrix = _merge_matrix(fp_rows, tp_rows, bl_rows, profiles, thinking, fewshot)

    fs_label = f"Few-shot {fewshot}"
    think_tag = f"thinking_{thinking}"
    return [
        f"### {fs_label}",
        "",
        *_execution_section(thinking, fewshot, profiles, cells_comp),
        "",
        f"#### Results: {think_tag} · {fs_label}",
        "",
        *_results_table(matrix),
        "",
        *_borderline_table(matrix),
        "",
    ]


def build_tables_markdown(sast: Path) -> str:
    summaries_dir = sast / "runs/phase2/summaries"
    cells_comp = _load_comparison_cells(summaries_dir)
    n_gaps = _gaps_skipped_count(sast / "runs/phase2/logs")
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines: list[str] = [
        "# Phase 2 results tables",
        "",
        f"Generated: {generated}",
        "",
        f"Target: **{TARGET}** cases per track (FP / TP / BL). "
        f"**{n_gaps}** core gap cases skipped.",
        "",
        "Profiles: "
        + ", ".join(f"`{p}`" for p in ALL_PROFILES)
        + ".",
        "",
        "## Legend",
        "",
        "- **Status**: `Done` when evaluated = target and missing = 0; else `evaluated / target`.",
        "- **SRS** = 1 − (Σ penalty) / (N × 3.0) over FP + TP + BL tracks (penalties: TP→FP 3.0×, "
        "BL→FP 1.5×, TP→BL 1.0×, FP→TP/BL 1.0×, correct 0×; missing = 3.0×). **F1** = 0.5×F1-FP + 0.5×F1-TP.",
        "- **LenAcc**: borderline lenient accuracy. **BenchAg**: benchmark agreement. "
        "**AmbIdx**: ambiguity index.",
        "",
    ]

    for thinking in ("off", "on"):
        title = "Thinking ON" if thinking == "on" else "Thinking OFF"
        lines.extend([f"## {title}", ""])
        for fewshot in (0, 3):
            lines.extend(_config_block(thinking, fewshot, summaries_dir, cells_comp))

    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    sast = _SAST
    out = sast / "runs/phase2/summaries" / "PHASE2_TABLES.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = build_tables_markdown(sast)
    out.write_text(text, encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
