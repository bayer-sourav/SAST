#!/usr/bin/env python3
"""Build Phase 2 COMPARISON_TABLE.md from per-cell comparison JSON files."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

_SAST = Path(__file__).resolve().parents[3]
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

from benchmark.triage_labels import VALID_LABELS  # noqa: E402

CORE_PROFILES = (
    "qwen3_4b_bnb",
    "qwen3_8b_bnb",
    "qwen3_14b_bnb",
    "qwen3_coder_30b_bnb",
)
QWEN35_PROFILES = ("qwen3_5_4b_bnb", "qwen3_5_9b_bnb")
CONFIGS = tuple((t, f) for t in ("off", "on") for f in (0, 3))
TARGET = 200
TRACKS = {
    "fp": _SAST / "runs/phase2/fp",
    "tp": _SAST / "runs/phase2/tp",
    "bl": _SAST / "runs/phase2/bl",
}
CELL_RE = re.compile(
    r"^comparison_(fp|tp|bl)_test_thinking_(off|on)_fewshot_(\d+)\.json$"
)

LEGEND = [
    "## Legend",
    "",
    "- **Thinking**: `off` = no chain-of-thought; `on` = CoT before JSON",
    "- **Few-shot**: `0` = zero-shot; `3` = 3 exemplars in task.md",
    "- **Coverage**: % of 200 test cases with valid triage label",
    "- **FP FPRR**: false-positive removal rate (higher = better at calling FP)",
    "- **TP VDR**: vulnerability detection rate (higher = better at calling TP)",
    "- **BL Lenient acc**: correct if label matches gold OR acceptable neighbor",
    "- **BL Bench agree**: agreement with benchmark borderline framing",
    "",
]


def _pct(x: float) -> str:
    return f"{100 * float(x):.1f}%"


def _dash() -> str:
    return "—"


def _slm(data: dict, profile: str) -> dict | None:
    return data.get(f"SLM ({profile})")


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


def _load_cells(summaries_dir: Path) -> dict[tuple[str, str, int], dict]:
    cells: dict[tuple[str, str, int], dict] = {}
    for path in sorted(summaries_dir.glob("comparison_*_test_thinking_*_fewshot_*.json")):
        m = CELL_RE.match(path.name)
        if not m:
            continue
        track, thinking, fewshot = m.group(1), m.group(2), int(m.group(3))
        cells[(track, thinking, fewshot)] = json.loads(path.read_text(encoding="utf-8"))
    return cells


def _base_cells(m: dict | None) -> list[str]:
    if not m:
        return [_dash()] * 5
    return [
        str(int(m.get("evaluated", 0))),
        str(int(m.get("missing", 0))),
        _pct(m.get("coverage", 0.0)),
    ]


def _track_rows_fp(cells: dict[tuple[str, str, int], dict]) -> list[str]:
    header = (
        "| Model | Thinking | Few-shot | Evaluated | Missing | Coverage | Accuracy | FPRR |"
    )
    sep = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    lines = [header, sep]
    for profile in CORE_PROFILES:
        for thinking, fewshot in CONFIGS:
            data = cells.get(("fp", thinking, fewshot), {})
            m = _slm(data, profile) if data else None
            if m:
                cells_vals = _base_cells(m) + [
                    _pct(m.get("accuracy", 0.0)),
                    _pct(m.get("fprr", m.get("fp_removal_rate", 0.0))),
                ]
            else:
                cells_vals = [_dash()] * 7
            lines.append(
                "| "
                + " | ".join([profile, thinking, str(fewshot), *cells_vals])
                + " |"
            )
    return lines


def _track_rows_tp(cells: dict[tuple[str, str, int], dict]) -> list[str]:
    header = (
        "| Model | Thinking | Few-shot | Evaluated | Missing | Coverage | Accuracy | VDR |"
    )
    sep = "| --- | --- | --- | --- | --- | --- | --- | --- |"
    lines = [header, sep]
    for profile in CORE_PROFILES:
        for thinking, fewshot in CONFIGS:
            data = cells.get(("tp", thinking, fewshot), {})
            m = _slm(data, profile) if data else None
            if m:
                cells_vals = _base_cells(m) + [
                    _pct(m.get("accuracy", 0.0)),
                    _pct(m.get("vdr", m.get("tp_rate", 0.0))),
                ]
            else:
                cells_vals = [_dash()] * 7
            lines.append(
                "| "
                + " | ".join([profile, thinking, str(fewshot), *cells_vals])
                + " |"
            )
    return lines


def _track_rows_bl(cells: dict[tuple[str, str, int], dict]) -> list[str]:
    header = (
        "| Model | Thinking | Few-shot | Evaluated | Missing | Coverage | "
        "Lenient acc | Bench agree | BL rate |"
    )
    sep = "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"
    lines = [header, sep]
    for profile in CORE_PROFILES:
        for thinking, fewshot in CONFIGS:
            data = cells.get(("bl", thinking, fewshot), {})
            m = _slm(data, profile) if data else None
            if m:
                cells_vals = _base_cells(m) + [
                    _pct(m.get("lenient_accuracy", 0.0)),
                    _pct(m.get("benchmark_agreement", 0.0)),
                    _pct(m.get("bl_rate", 0.0)),
                ]
            else:
                cells_vals = [_dash()] * 8
            lines.append(
                "| "
                + " | ".join([profile, thinking, str(fewshot), *cells_vals])
                + " |"
            )
    return lines


def _qwen35_progress_lines() -> list[str]:
    header = "| Track | Model | Thinking | Few-shot | Completed | Target |"
    sep = "| --- | --- | --- | --- | --- | --- |"
    lines = [header, sep]
    for track_key, root in TRACKS.items():
        track_label = track_key.upper()
        for profile in QWEN35_PROFILES:
            for thinking, fewshot in CONFIGS:
                completed = _count_valid(root, profile, thinking, fewshot)
                lines.append(
                    "| "
                    + " | ".join(
                        [
                            track_label,
                            profile,
                            thinking,
                            str(fewshot),
                            str(completed),
                            str(TARGET),
                        ]
                    )
                    + " |"
                )
    return lines


def _load_gaps(logs_dir: Path) -> dict[str, list[str]]:
    path = logs_dir / "missing_core.json"
    by_profile: dict[str, list[str]] = defaultdict(list)
    if path.is_file():
        for item in json.loads(path.read_text(encoding="utf-8")):
            by_profile[item["profile"]].append(item["case_id"])
    return {p: ids for p, ids in sorted(by_profile.items())}


def main() -> None:
    summaries_dir = _SAST / "runs/phase2/summaries"
    out_path = summaries_dir / "COMPARISON_TABLE.md"
    cells = _load_cells(summaries_dir)

    lines: list[str] = [
        "# Phase 2 comparison table (core Qwen3 profiles)",
        "",
        "Source: `comparison_*_test_*.json` in `runs/phase2/summaries/`.",
        "One row per model × thinking × few-shot configuration (16 rows per track table).",
        "",
        *LEGEND,
        "## Table A — FP track (gold label = FP)",
        "",
        *_track_rows_fp(cells),
        "",
        "## Table B — TP track (gold = TP)",
        "",
        *_track_rows_tp(cells),
        "",
        "## Table C — BL track (gold = BL)",
        "",
        *_track_rows_bl(cells),
        "",
        "## Table D — Qwen3.5 progress (live disk counts)",
        "",
        "Valid labels on disk (`agent-llm-triage-result.json`).",
        "",
        *_qwen35_progress_lines(),
    ]

    gaps = _load_gaps(_SAST / "runs/phase2/logs")
    n_gaps = sum(len(v) for v in gaps.values())
    lines.extend(
        [
            "",
            f"## Skipped core gaps ({n_gaps})",
            "",
            "Unfixable missing valid results; case IDs only, grouped by profile.",
            "",
        ]
    )
    for profile, case_ids in gaps.items():
        lines.append(f"### `{profile}`")
        lines.append("")
        for cid in case_ids:
            lines.append(f"- {cid}")
        lines.append("")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    print(out_path)
    text = out_path.read_text(encoding="utf-8").splitlines()
    for line in text[:80]:
        print(line)


if __name__ == "__main__":
    main()
