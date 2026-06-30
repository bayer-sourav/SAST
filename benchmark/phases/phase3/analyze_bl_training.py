#!/usr/bin/env python3
"""Analyze borderline (BL) cases: train teacher labels, test predictions, vs TP/FP tracks."""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.build_phase2_corpora import _dataset_root  # noqa: E402
from benchmark.phases.phase3.eval_val_for_css import _valid_triage_result  # noqa: E402

OUT = _sast / "runs/phase3/stage3c/summaries" / "PHASE3C_BL_ANALYSIS.md"
TEACHER = _sast / "runs/phase3/stage3b/teacher/train"
EXPORT = _sast / "runs/phase3/stage3c/data/distill_train.jsonl"


def _teacher_label(track: str, case_id: str) -> str | None:
    rp = (
        TEACHER
        / track
        / "thinking_on/fewshot_3/qwen3_5_9b_bnb/llm"
        / case_id
        / "agent-llm-triage-result.json"
    )
    if not rp.is_file():
        return None
    return str(json.loads(rp.read_text(encoding="utf-8")).get("label", "")).strip().upper()


def _test_preds(eval_base: Path, thinking: str, fewshot: int) -> dict[str, tuple[Counter[str], int]]:
    out: dict[str, tuple[Counter[str], int]] = {}
    for track in ("fp", "tp", "bl"):
        corpus = _sast / (
            f"benchmark/corpora/phase2_{track}_test"
            if track != "bl"
            else "benchmark/corpora/phase2_bl_test"
        )
        root = eval_base / track / f"thinking_{thinking}/fewshot_{fewshot}/qwen3_5_9b_bnb/llm"
        dist: Counter[str] = Counter()
        miss = 0
        for p in sorted(corpus.glob("*.json")):
            cid = str(json.loads(p.read_text(encoding="utf-8")).get("case_id") or p.stem)
            rp = root / cid / "agent-llm-triage-result.json"
            if not _valid_triage_result(rp):
                miss += 1
                continue
            dist[json.loads(rp.read_text(encoding="utf-8"))["label"].upper()] += 1
        out[track] = (dist, miss)
    return out


def _train_teacher_stats(dataset: Path) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for track, gold in (("fp", "FP"), ("tp", "TP"), ("borderline", "BL")):
        mpath = dataset / track / "manifest.json"
        entries = [
            r
            for r in json.loads(mpath.read_text(encoding="utf-8"))["cases"]
            if "/train/" in str(r.get("bundle", "")).replace("\\", "/")
        ]
        teacher = Counter()
        bench_lbl = Counter()
        for row in entries:
            bundle = (dataset / row["bundle"]).resolve()
            case = json.loads((bundle / "case.json").read_text(encoding="utf-8"))
            tl = _teacher_label(track, row["case_id"])
            if tl:
                teacher[tl] += 1
            bl = "TP" if case.get("benchmark_real_vuln") else "FP"
            bench_lbl[bl] += 1
        n = sum(teacher.values())
        stats[track] = {
            "gold": gold,
            "n_manifest": len(entries),
            "n_teacher": n,
            "teacher": dict(teacher),
            "teacher_agrees_gold": teacher.get(gold, 0) / n if n else 0.0,
            "benchmark_label": dict(bench_lbl),
        }
    return stats


def _export_teacher_by_gold() -> dict[str, Counter[str]]:
    out: dict[str, Counter[str]] = {}
    if not EXPORT.is_file():
        return out
    for line in EXPORT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        gl = str(r.get("gold_label") or "")
        tl = str(r.get("teacher_label") or "")
        out.setdefault(gl, Counter())[tl] += 1
    return out


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return lines


def main() -> None:
    dataset = _dataset_root(None)
    train = _train_teacher_stats(dataset)
    export = _export_teacher_by_gold()

    lines = [
        "# Phase 3C — Borderline (BL) track analysis",
        "",
        "Gold track **BL** = ambiguous cases in BenchmarkJava. This doc compares BL to TP/FP "
        "in **training supervision**, **test scoring**, and **model predictions**.",
        "",
        "## 1. What BL means in this benchmark",
        "",
        "| Split | `benchmark_real_vuln` | `acceptable_labels` | SRS scoring |",
        "| --- | --- | --- | --- |",
        "| BL **train** (500) | 100% safe (`false`) | `('FP', 'TP')` only | — |",
        "| BL **test** (200) | 100% safe (`false`) | `('FP', 'TP')` only | BL→TP free; BL→FP penalized |",
        "",
        "**BL is not an acceptable prediction label on test.** Lenient accuracy counts TP or FP as correct. "
        "Stage 2 and 3C both achieve **100% lenient accuracy** on BL test — every prediction is TP or FP.",
        "",
        "**Ship inference never targets BL output** (0% BL predictions on BL-gold for Stage 2 and 3C).",
        "",
        "## 2. Stage 2 teacher labels on BL-gold **train** (distillation source)",
        "",
    ]

    bl = train["borderline"]
    rows = [
        ["BL (borderline)", str(bl["n_teacher"]), "TP", str(bl["teacher"].get("TP", 0)), f"{bl['teacher'].get('TP', 0)/max(bl['n_teacher'],1)*100:.1f}%"],
        ["", "", "FP", str(bl["teacher"].get("FP", 0)), f"{bl['teacher'].get('FP', 0)/max(bl['n_teacher'],1)*100:.1f}%"],
        ["", "", "BL", str(bl["teacher"].get("BL", 0)), f"{bl['teacher'].get('BL', 0)/max(bl['n_teacher'],1)*100:.1f}%"],
    ]
    lines.extend(_md_table(["Gold track", "N (teacher)", "Teacher label", "Count", "%"], rows))
    lines.extend(
        [
            "",
            f"Teacher agrees with gold track label **BL**: **{bl['teacher_agrees_gold']*100:.1f}%** "
            f"(vs FP track **{train['fp']['teacher_agrees_gold']*100:.1f}%**, "
            f"TP track **{train['tp']['teacher_agrees_gold']*100:.1f}%**).",
            "",
            "All BL-train cases are benchmark-safe (`benchmark_real_vuln=false` → bench label **FP**), "
            f"but teacher says **TP on {bl['teacher'].get('TP', 0)}** of them — **contradictory supervision**.",
            "",
            "## 3. Phase 3C export (what the model actually learns)",
            "",
        ]
    )
    if export:
        rows = []
        for tl, n in sorted(export.get("BL", Counter()).items(), key=lambda x: -x[1]):
            total = sum(export["BL"].values())
            rows.append([tl or "(empty)", str(n), f"{n/total*100:.1f}%"])
        lines.extend(_md_table(["teacher_label (BL-gold export)", "Count", "%"], rows))
        lines.append(f"\nTotal BL-gold export records: **{sum(export['BL'].values())}** (of 1283 total).")

    lines.extend(["", "## 4. Test predictions by gold track (fs0_off)", ""])
    configs = [
        ("Phase 3C", _sast / "runs/phase3/stage3c/eval", "off", 0),
        ("Stage 2 GOOD", _sast / "runs/phase2/stage2", "on", 3),
        (
            "3B ship",
            _sast / "runs/phase3/stage3b/eval_ablation/fs0_off_best",
            "off",
            0,
        ),
    ]
    rows = []
    for name, base, think, fs in configs:
        if not base.is_dir():
            continue
        preds = _test_preds(base, think, fs)
        for track in ("fp", "tp", "bl"):
            dist, miss = preds[track]
            n = sum(dist.values())
            if n == 0:
                continue
            rows.append(
                [
                    name,
                    track.upper(),
                    str(n),
                    f"{dist.get('TP', 0)} ({dist.get('TP', 0)/n*100:.0f}%)",
                    f"{dist.get('FP', 0)} ({dist.get('FP', 0)/n*100:.0f}%)",
                    f"{dist.get('BL', 0)} ({dist.get('BL', 0)/n*100:.0f}%)",
                    str(miss),
                ]
            )
    lines.extend(
        _md_table(
            ["Model", "Gold", "N", "→TP", "→FP", "→BL", "miss"],
            rows,
        )
    )

    lines.extend(
        [
            "",
            "## 5. Is BL confusing the model?",
            "",
            "**Partially yes — but not because the model should output BL.**",
            "",
            "| Mechanism | Evidence |",
            "| --- | --- |",
            "| **Contradictory BL supervision** | 85% of BL-train teacher labels are **TP** on cases benchmark marks as safe/ambiguous |",
            "| **Low teacher–gold agreement on BL track** | 0.5% teacher says BL; 72–93% on FP/TP tracks |",
            "| **Boundary blur** | 362 BL export rows teach TP/FP split on hardest cases — may widen TP/FP confusion on clear tracks |",
            "| **Not a BL-output problem** | Predicting BL is not scored as success; Stage 2 also uses 0% BL on BL test |",
            "",
            "### What hurts SRS on BL test",
            "",
            "- **BL→FP** (27 in 3C vs 16 in 3B ship): over-dismiss ambiguous findings — 1.5× penalty each",
            "- **BL→TP** (172 in 3C): **zero penalty** — this is the SRS-optimal direction",
            "",
            "Wanting \"mostly BL\" on BL cases **conflicts with ship eval design** unless you change:",
            "",
            "1. Prompt/schema to emit BL at inference",
            "2. `acceptable_labels` and SRS penalty table",
            "3. Teacher to label BL on ambiguous cases (Stage 2 currently does not)",
            "",
            "## 6. Implications for 3D (refined)",
            "",
            "| Approach | Rationale |",
            "| --- | --- |",
            "| **Drop BL from train** | Removes contradictory TP/FP supervision on ambiguous cases — may sharpen VDR/FPRR on clear tracks, but loses boundary signal |",
            "| **Keep BL, fix teacher** | Re-label BL train with consistent policy (e.g. always FP when safe, or true BL with new ship schema) |",
            "| **BL-only auxiliary loss** | Train clear TP/FP on 821 cases; use BL separately with soft/multi-label targets |",
            "| **Primary 3D focus** | Still **TP→FP** on TP-gold (27 vs 14 Stage 2) — independent of BL output class |",
            "",
            "**Recommendation:** Before dropping BL, run **3D-ablation** (FP+TP train only) *and* measure TP→FP on TP-gold separately. "
            "If VDR rises without FPRR collapse, BL boundary noise was hurting. If VDR stays flat, BL wasn't the bottleneck.",
        ]
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
