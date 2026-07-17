#!/usr/bin/env python3
"""Score v8 Phase 1 hard-slice runs and pick smoke-pass cells."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

SLICE = Path(__file__).resolve().parent / "smoke_slice_cases.json"
MANIFEST = Path(__file__).resolve().parent / "v8_phase1" / "MANIFEST.json"
PROFILE = "qwen3_5_9b_bnb"


def _score_cell(eval_root: Path, slice_data: dict) -> dict:
    sub = eval_root / PROFILE / "llm"
    tp_ok = fp_ok = unk = miss = 0
    tp_misses: list[str] = []
    fp_misses: list[str] = []
    for cid in slice_data["tp"]:
        p = sub / cid / "agent-llm-triage-result.json"
        if not p.is_file():
            miss += 1
            tp_misses.append(cid)
            continue
        lbl = str(json.loads(p.read_text()).get("label", "")).upper()
        if lbl == "TP":
            tp_ok += 1
        elif lbl == "UNKNOWN":
            unk += 1
        else:
            tp_misses.append(f"{cid}:{lbl}")
    for cid in slice_data["fp"]:
        p = sub / cid / "agent-llm-triage-result.json"
        if not p.is_file():
            miss += 1
            fp_misses.append(cid)
            continue
        lbl = str(json.loads(p.read_text()).get("label", "")).upper()
        if lbl == "FP":
            fp_ok += 1
        elif lbl == "UNKNOWN":
            unk += 1
        else:
            fp_misses.append(f"{cid}:{lbl}")
    n_tp = len(slice_data["tp"])
    n_fp = len(slice_data["fp"])
    return {
        "vdr": tp_ok,
        "vdr_pct": tp_ok / n_tp if n_tp else 0.0,
        "fprr": fp_ok,
        "fprr_pct": fp_ok / n_fp if n_fp else 0.0,
        "total": tp_ok + fp_ok,
        "unknown": unk,
        "missing": miss,
        "tp_errors": tp_misses,
        "fp_errors": fp_misses,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--eval-root", type=Path, default=_sast / "runs" / "phase2" / "v8_phase1")
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument("--md-out", type=Path, default=None)
    args = ap.parse_args()

    eval_root = args.eval_root.expanduser().resolve()
    sast_root = _sast.resolve()

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    slice_data = json.loads(SLICE.read_text(encoding="utf-8"))
    gates = manifest.get("smoke_gates") or {}
    vdr_min = int(gates.get("vdr_min", 9))
    fprr_min = int(gates.get("fprr_min", 7))
    total_min = int(gates.get("total_min", 17))
    baseline = manifest.get("baseline_600") or {}

    rows: list[dict] = []
    for cell in manifest.get("cells") or []:
        cell_root = (eval_root / cell["id"] / "hard_slice").resolve()
        sc = _score_cell(cell_root, slice_data)
        smoke_pass = (
            sc["vdr"] >= vdr_min
            and sc["fprr"] >= fprr_min
            and sc["total"] >= total_min
            and sc["missing"] == 0
        )
        try:
            rel_root = str(cell_root.relative_to(sast_root))
        except ValueError:
            rel_root = str(cell_root)
        rows.append(
            {
                **cell,
                **sc,
                "smoke_pass": smoke_pass,
                "eval_root": rel_root,
            }
        )

    rows.sort(key=lambda r: (-r["total"], -r["vdr"], -r["fprr"]))
    passed = [r for r in rows if r["smoke_pass"]]
    doc = {
        "slice": str(SLICE.relative_to(_sast)),
        "smoke_gates": gates,
        "baseline_600": baseline,
        "scores": rows,
        "passed_ids": [r["id"] for r in passed],
        "best_id": rows[0]["id"] if rows else None,
    }

    out_json = args.json_out or (eval_root / "PHASE1_SMOKE_SUMMARY.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    lines = [
        "# v8 Phase 1 — hard slice smoke",
        "",
        f"Slice: 10 TP + 10 FP · gates: VDR≥{vdr_min}/10 · FPRR≥{fprr_min}/10 · total≥{total_min}/20",
        "",
        f"600-case baseline (v8-ship-bl): VDR {100 * float(baseline.get('vdr', 0)):.1f}% · "
        f"FPRR {100 * float(baseline.get('fprr', 0)):.1f}% · SRS {100 * float(baseline.get('srs', 0)):.1f}% · "
        f"TP→FP {baseline.get('tp_as_fp', '?')}",
        "",
        "| Cell | VDR | FPRR | Total | Pass | Notes |",
        "|------|----:|-----:|------:|:----:|-------|",
    ]
    for r in rows:
        lines.append(
            f"| **{r['id']}** | {r['vdr']}/10 | {r['fprr']}/10 | **{r['total']}/20** | "
            f"{'✓' if r['smoke_pass'] else '✗'} | {r.get('note', '')} |"
        )
    if passed:
        lines.extend(
            [
                "",
                f"**Smoke pass:** {', '.join(r['id'] for r in passed)}",
                "",
                "Next: run 600-case eval on best passer (`PHASE1_FULL=1 PHASE1_CELL=<id> bash run_v8_phase1.sh`).",
            ]
        )
    else:
        lines.extend(["", "**No cell passed smoke gates.** Review tp_errors in JSON."])
    for r in rows:
        if r.get("tp_errors"):
            lines.append(f"\n### {r['id']} TP misses\n- " + "\n- ".join(r["tp_errors"]))
    lines.append(f"\nJSON: `{out_json.relative_to(_sast)}`")

    out_md = args.md_out or (eval_root / "PHASE1_SMOKE_REPORT.md")
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"passed": doc["passed_ids"], "best": doc["best_id"]}, indent=2))
    print(f"Wrote {out_json}")
    print(f"Wrote {out_md}")


if __name__ == "__main__":
    main()
