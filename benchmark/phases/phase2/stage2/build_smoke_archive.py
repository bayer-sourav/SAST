#!/usr/bin/env python3
"""Build smoke-test archive + Phase 2 Stage 1 comparison for safekeeping."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path

SAST = Path(__file__).resolve().parents[4]
OUT = SAST / "runs/phase2/stage2/SMOKE_ARCHIVE.md"


def _load_json(p: Path) -> dict | list | None:
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _aggregate_results(results: list[dict]) -> list[dict]:
    agg: dict[tuple, dict] = {}
    for r in results:
        think = "on" if r.get("thinking") in (True, "on") else "off"
        key = (r["profile"], think, r.get("fewshot", 0))
        if key not in agg:
            agg[key] = {"profile": r["profile"], "thinking": think, "fewshot": r.get("fewshot", 0), "vdr": 0, "fprr": 0, "total": 0, "missing": 0}
        row = agg[key]
        if r.get("label") in ("ERROR", "?"):
            row["missing"] += 1
            continue
        gold, lbl = r.get("gold"), r.get("label")
        if gold == "TP" and lbl == "TP":
            row["vdr"] += 1
        if gold == "FP" and lbl == "FP":
            row["fprr"] += 1
        if r.get("ok"):
            row["total"] += 1
    return list(agg.values())


def _scores_from_summary(path: Path) -> list[dict]:
    d = _load_json(path)
    if not d:
        return []
    if "scores" in d and d["scores"]:
        return d["scores"]
    if "results" in d:
        return _aggregate_results(d["results"])
    return []


def _md_table(rows: list[dict], cols: list[tuple[str, str]]) -> str:
    if not rows:
        return "_No data_\n"
    hdr = "| " + " | ".join(c[0] for c in cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    lines = [hdr, sep]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(k, "")) for _, k in cols) + " |")
    return "\n".join(lines) + "\n"


def main() -> None:
    smoke_runs = [
        ("v7_3shot_2tp_fp (2TP+1FP fs3)", "runs/smoke/v7_3shot_2tp_fp/summary.json", "v2-3shot-2tp-fp"),
        ("v7_final_2shot (fs0+fs2)", "runs/smoke/v7_final_2shot/summary.json", "v2-2shot"),
        ("v7_thinking_on_fs3 (legacy 1TP+2FP)", "runs/smoke/v7_thinking_on_fs3/summary.json", "v2 fs3"),
        ("v7_thinking_on_fs0", "runs/smoke/v7_thinking_on_fs0/summary.json", "zero-shot"),
        ("v7_fewshot_v3 (TP+FP+BL)", "runs/smoke/v7_fewshot_v3_best_profiles/summary.json", "v3 fs3"),
        ("v7_fewshot_v2 all profiles", "runs/smoke/v7_fewshot_v2_all_profiles/summary.json", "v2 fs3"),
        ("v7_balanced all profiles", "runs/smoke/v7_balanced_all_profiles/summary.json", "v7-balanced"),
    ]

    sections: list[str] = []
    sections.append("# Smoke test archive + Phase 2 comparison\n")
    sections.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}\n")
    sections.append("Hard slice: 20 cases (10 TP + 10 FP). Metrics: VDR / FPRR / Total correct.\n")

    sections.append("## Hard-slice smoke results (chronological)\n")
    for name, rel, tag in smoke_runs:
        scores = _scores_from_summary(SAST / rel)
        if not scores:
            sections.append(f"### {name}\n\n_No summary at `{rel}`_\n")
            continue
        rows = []
        for s in sorted(scores, key=lambda x: (-x.get("total", 0), -x.get("vdr", 0), -x.get("fprr", 0))):
            rows.append(
                {
                    "Profile": s.get("profile", "?"),
                    "Think": s.get("thinking", "?"),
                    "FS": s.get("fewshot", "?"),
                    "VDR": f"{s.get('vdr', 0)}/10",
                    "FPRR": f"{s.get('fprr', 0)}/10",
                    "Total": f"{s.get('total', 0)}/20",
                    "Miss": s.get("missing", 0),
                }
            )
        sections.append(f"### {name} (`{tag}`)\n")
        sections.append(
            _md_table(
                rows,
                [("Profile", "Profile"), ("Think", "Think"), ("FS", "FS"), ("VDR", "VDR"), ("FPRR", "FPRR"), ("Total", "Total"), ("Miss", "Miss")],
            )
        )

    sections.append("## Key smoke conclusions\n")
    sections.append(
        "- **Best hard-slice score:** legacy fs3 (`v2_3shot_tp_2fp`) · qwen3_5_9b · think=on → **20/20**\n"
        "- **2TP+1FP fs3 (`v2_3shot_2tp_fp`) regressed** vs legacy on 5.9b (17/20) and 14b (15/20); not adopted\n"
        "- **8b think=on fs0 or fs3** both hit 18/20 with perfect FPRR; fs0 chosen for Stage 2 (shorter prompts)\n"
        "- **8b think=off + fs3** → 0/10 VDR; **5.9b think=off + fs3** → 0/10 FPRR — avoid think=off with few-shot\n"
        "- **Coder-30b** — recall-first (10/10 VDR think=on) but FPRR ~3/10; kept in Stage 2 for comparison only\n"
        "- **Gemma 4** dropped (transformers/compatibility cost vs benefit)\n"
    )

    sections.append("## Phase 2 Stage 1 (full 200×3 corpus, prior prompt era)\n")
    sections.append("Source: `runs/phase2/summaries/PHASE2_TABLES.md` (Jun 2026).\n")
    sections.append("### Thinking ON · Few-shot 3 (full corpus, 200 cases/track)\n")
    p2_rows = [
        {"Profile": "qwen3_5_9b_bnb", "FPRR": "94.0%", "VDR": "85.5%", "SRS": "89.8%", "Note": "Best overall Stage 1"},
        {"Profile": "qwen3_8b_bnb", "FPRR": "90.0%", "VDR": "51.0%", "SRS": "70.5%", "Note": "Balanced mid-tier"},
        {"Profile": "qwen3_coder_30b_bnb", "FPRR": "90.0%", "VDR": "43.0%", "SRS": "66.5%", "Note": "High FP track FPRR, moderate VDR"},
        {"Profile": "qwen3_14b_bnb", "FPRR": "97.5%", "VDR": "26.0%", "SRS": "61.7%", "Note": "FPRR-heavy, low recall"},
        {"Profile": "qwen3_4b_bnb", "FPRR": "100.0%", "VDR": "9.5%", "SRS": "54.8%", "Note": "Not in Stage 2"},
    ]
    sections.append(_md_table(p2_rows, [("Profile", "Profile"), ("FPRR", "FPRR"), ("VDR", "VDR"), ("SRS", "SRS"), ("Note", "Note")]))

    sections.append("### Thinking ON · Few-shot 0 (8b zero-shot baseline, full corpus)\n")
    p2_fs0 = [
        {"Profile": "qwen3_8b_bnb", "FPRR": "96.0%", "VDR": "65.8%", "SRS": "80.9%", "Note": "Stage 1 fs0 reference"},
        {"Profile": "qwen3_5_9b_bnb", "FPRR": "96.0%", "VDR": "65.8%", "SRS": "80.9%", "Note": "5.9b fs0"},
    ]
    sections.append(_md_table(p2_fs0, [("Profile", "Profile"), ("FPRR", "FPRR"), ("VDR", "VDR"), ("SRS", "SRS"), ("Note", "Note")]))

    sections.append("## Phase 2 Stage 2 plan (this run)\n")
    stage2 = _load_json(SAST / "benchmark/phases/phase2/stage2/MANIFEST.json") or {}
    s2_rows = []
    for c in stage2.get("cells", []):
        s2_rows.append(
            {
                "Cell": c.get("id", "?"),
                "Profile": c.get("profile", "?"),
                "Think": "on",
                "FS": c.get("fewshot", "?"),
                "Config": c.get("few_shot_config") or "—",
                "Note": c.get("note", ""),
            }
        )
    sections.append(_md_table(s2_rows, [("Cell", "Cell"), ("Profile", "Profile"), ("Think", "Think"), ("FS", "FS"), ("Config", "Config"), ("Note", "Note")]))
    sections.append("\nOutput: `runs/phase2/stage2/{fp,tp,bl}/thinking_on/fewshot_{0,3}/`\n")
    sections.append("Prompt: `unified-4label-v7-balanced` + versioned few-shot configs in `benchmark/few_shot_configs/`.\n")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("".join(sections), encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
