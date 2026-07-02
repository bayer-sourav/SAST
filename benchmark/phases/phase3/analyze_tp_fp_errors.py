#!/usr/bin/env python3
"""Mine Phase 3C TP→FP test errors; map to train hard-negatives by rule family."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.build_phase2_corpora import _dataset_root  # noqa: E402
from benchmark.confusion_matrix import collect_outcomes, load_label  # noqa: E402
from benchmark.phases.phase3.export_sft_dataset import _split_entries  # noqa: E402

PROFILE = "qwen3_5_9b_bnb"
_TRACK_KEYS = ("fp", "tp", "borderline")


def _rule_id(case: dict[str, Any]) -> str:
    raw = case.get("raw_output") or {}
    for tool_alerts in raw.values():
        if not isinstance(tool_alerts, list):
            continue
        for alert in tool_alerts:
            if not isinstance(alert, dict):
                continue
            rid = alert.get("ruleId")
            if rid:
                return str(rid)
            rule = alert.get("rule") or {}
            if rule.get("id"):
                return str(rule["id"])
    # fallback: filename heuristic
    fpath = str(case.get("file") or "")
    if "BenchmarkTest" in fpath:
        return "unknown"
    return "unknown"


def _short_rule(rule_id: str) -> str:
    """java/xss → xss for ship-aligned grouping."""
    if "/" in rule_id:
        return rule_id.split("/", 1)[-1]
    return rule_id


def _load_case(dataset: Path, bundle_rel: str) -> dict[str, Any]:
    bundle = (dataset / bundle_rel).resolve()
    return json.loads((bundle / "case.json").read_text(encoding="utf-8"))


def _case_index(dataset: Path, split: str) -> dict[str, dict[str, Any]]:
    """case_id -> {track, bundle, rule_id, short_rule, gold}."""
    idx: dict[str, dict[str, Any]] = {}
    gold_map = {"fp": "FP", "tp": "TP", "borderline": "BL"}
    for track in _TRACK_KEYS:
        mpath = dataset / track / "manifest.json"
        entries = _split_entries(json.loads(mpath.read_text(encoding="utf-8")), split)
        for row in entries:
            case = _load_case(dataset, row["bundle"])
            rid = _rule_id(case)
            idx[row["case_id"]] = {
                "case_id": row["case_id"],
                "track": track,
                "bundle": row["bundle"],
                "rule_id": rid,
                "short_rule": _short_rule(rid),
                "gold": gold_map[track],
            }
    return idx


def _pred_label(eval_root: Path, track: str, case_id: str, *, thinking: str, fewshot: int) -> str | None:
    p = (
        eval_root
        / track
        / f"thinking_{thinking}"
        / f"fewshot_{fewshot}"
        / PROFILE
        / "llm"
        / case_id
        / "agent-llm-triage-result.json"
    )
    return load_label(p)


def _teacher_label(teacher_root: Path, track: str, case_id: str) -> str | None:
    p = (
        teacher_root
        / track
        / "thinking_on/fewshot_3/qwen3_5_9b_bnb/llm"
        / case_id
        / "agent-llm-triage-result.json"
    )
    return load_label(p)


def analyze(
    *,
    eval_root: Path,
    stage2_eval: Path | None,
    teacher_root: Path,
    out_json: Path,
    out_md: Path,
    max_neighbors_per_error: int,
    max_total_oversample: int,
) -> dict[str, Any]:
    dataset = _dataset_root(None)
    test_idx = _case_index(dataset, "test")
    train_idx = _case_index(dataset, "train")

    outcomes = collect_outcomes(eval_root, PROFILE, thinking="off", fewshot=0)
    tp_fp = [o for o in outcomes if o["gold"] == "TP" and o["predicted"] == "FP"]

    # Enrich errors
    errors: list[dict[str, Any]] = []
    rule_counter: Counter[str] = Counter()
    short_rule_counter: Counter[str] = Counter()
    for row in tp_fp:
        cid = str(row["case_id"])
        meta = test_idx.get(cid, {})
        rid = meta.get("rule_id", "unknown")
        sr = meta.get("short_rule", "unknown")
        rule_counter[rid] += 1
        short_rule_counter[sr] += 1
        s2_pred = None
        if stage2_eval and stage2_eval.is_dir():
            s2_pred = _pred_label(stage2_eval, "tp", cid, thinking="on", fewshot=3)
        errors.append(
            {
                "case_id": cid,
                "gold": "TP",
                "predicted": "FP",
                "rule_id": rid,
                "short_rule": sr,
                "stage2_pred": s2_pred,
                "stage2_correct": s2_pred == "TP",
            }
        )

    # Train index by short_rule
    train_by_rule: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rec in train_idx.values():
        train_by_rule[rec["short_rule"]].append(rec)

    oversample_ids: list[str] = []
    oversample_detail: list[dict[str, Any]] = []
    seen: set[str] = set()

    for err in errors:
        sr = err["short_rule"]
        candidates = [
            c
            for c in train_by_rule.get(sr, [])
            if c["gold"] == "TP"
        ]
        # Prefer TP-gold train with teacher TP; include teacher-FP as hard boundary
        scored: list[tuple[int, str, dict[str, Any]]] = []
        for c in candidates:
            tl = _teacher_label(teacher_root, c["track"], c["case_id"])
            priority = 0
            if tl == "TP":
                priority = 2
            elif tl == "FP":
                priority = 1
            scored.append((priority, c["case_id"], c))
        scored.sort(key=lambda x: (-x[0], x[1]))
        picked = 0
        for _, _, c in scored:
            if c["case_id"] in seen:
                continue
            if picked >= max_neighbors_per_error:
                break
            if len(oversample_ids) >= max_total_oversample:
                break
            seen.add(c["case_id"])
            oversample_ids.append(c["case_id"])
            tl = _teacher_label(teacher_root, c["track"], c["case_id"])
            oversample_detail.append(
                {
                    "train_case_id": c["case_id"],
                    "train_gold": c["gold"],
                    "teacher_label": tl,
                    "rule_id": c["rule_id"],
                    "short_rule": sr,
                    "matched_error": err["case_id"],
                }
            )
            picked += 1

    s2_correct = sum(1 for e in errors if e.get("stage2_correct"))
    result = {
        "source_eval": str(eval_root.resolve()),
        "n_tp_fp_errors": len(errors),
        "errors": errors,
        "rule_counts": dict(rule_counter.most_common()),
        "short_rule_counts": dict(short_rule_counter.most_common()),
        "stage2_tp_correct_on_errors": s2_correct,
        "stage2_tp_correct_rate": s2_correct / len(errors) if errors else 0.0,
        "oversample_train_case_ids": oversample_ids,
        "oversample_detail": oversample_detail,
        "n_oversample": len(oversample_ids),
        "max_neighbors_per_error": max_neighbors_per_error,
        "max_total_oversample": max_total_oversample,
    }

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")

    out_md.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Phase 3D TP→FP error analysis",
        "",
        f"**Source eval:** `{eval_root}`  ",
        f"**Errors:** {len(errors)} TP-gold → predicted FP  ",
        f"**Stage 2 recall on same cases:** {s2_correct}/{len(errors)} "
        f"({100 * result['stage2_tp_correct_rate']:.1f}%)",
        "",
        "## Rule family breakdown (short_rule)",
        "",
        "| Rule | Count |",
        "| --- | ---: |",
    ]
    for rule, n in short_rule_counter.most_common():
        lines.append(f"| `{rule}` | {n} |")

    lines.extend(
        [
            "",
            "## Hard-negative train oversample",
            "",
            f"Mined **{len(oversample_ids)}** train case IDs "
            f"(max {max_neighbors_per_error}/error, cap {max_total_oversample}).",
            "",
            "| Train case | rule | teacher | matched test error |",
            "| --- | --- | --- | --- |",
        ]
    )
    for d in oversample_detail[:40]:
        lines.append(
            f"| `{d['train_case_id']}` | `{d['short_rule']}` | "
            f"{d.get('teacher_label') or '—'} | `{d['matched_error']}` |"
        )
    if len(oversample_detail) > 40:
        lines.append(f"| … | | | ({len(oversample_detail) - 40} more) |")

    lines.extend(
        [
            "",
            "## Sample errors (first 15)",
            "",
            "| case_id | rule | Stage 2 pred |",
            "| --- | --- | --- |",
        ]
    )
    for e in errors[:15]:
        lines.append(
            f"| `{e['case_id']}` | `{e['short_rule']}` | {e.get('stage2_pred') or '—'} |"
        )

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--eval-root",
        type=Path,
        default=_sast / "runs/phase3/stage3c/eval",
    )
    ap.add_argument(
        "--stage2-eval",
        type=Path,
        default=_sast / "runs/phase2/stage2",
    )
    ap.add_argument(
        "--teacher-root",
        type=Path,
        default=_sast / "runs/phase3/stage3b/teacher/train",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=_sast / "runs/phase3/stage3d/data/hard_negatives.json",
    )
    ap.add_argument(
        "--report",
        type=Path,
        default=_sast / "runs/phase3/stage3d/summaries/PHASE3D_TP_FP_ANALYSIS.md",
    )
    ap.add_argument("--max-neighbors", type=int, default=3)
    ap.add_argument("--max-total", type=int, default=120)
    args = ap.parse_args()

    stage2 = args.stage2_eval if args.stage2_eval.is_dir() else None
    result = analyze(
        eval_root=args.eval_root,
        stage2_eval=stage2,
        teacher_root=args.teacher_root,
        out_json=args.out,
        out_md=args.report,
        max_neighbors_per_error=args.max_neighbors,
        max_total_oversample=args.max_total,
    )
    print(
        f"[tp_fp] {result['n_tp_fp_errors']} errors -> "
        f"{result['n_oversample']} train oversample ids -> {args.out}"
    )


if __name__ == "__main__":
    main()
