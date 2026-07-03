#!/usr/bin/env python3
"""Review BL v4 pilot inference — BL prediction rate by category + HTML report."""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

_sast = Path(__file__).resolve().parent.parent
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.triage_labels import VALID_LABELS  # noqa: E402


def _load_pred(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def analyze(*, corpus_dir: Path, runs_root: Path, profile: str) -> dict:
    model_dir = profile.replace("/", "_")
    case_files = sorted(p for p in corpus_dir.glob("*.json") if p.name != "slice_manifest.json")
    rows: list[dict] = []
    by_cat: dict[str, Counter[str]] = defaultdict(Counter)
    overall = Counter()
    missing = 0

    for cf in case_files:
        case = json.loads(cf.read_text(encoding="utf-8"))
        cid = str(case.get("case_id") or cf.stem)
        cat = case.get("borderline_category") or "unknown"
        result_path = runs_root / model_dir / "llm" / cid / "agent-llm-triage-result.json"
        pred_obj = _load_pred(result_path)
        if pred_obj is None:
            missing += 1
            label = "(missing)"
        else:
            label = str(pred_obj.get("label", "")).upper()
            if label not in VALID_LABELS:
                label = "UNKNOWN"
        correct = label == "BL"
        overall[label] += 1
        by_cat[cat][label] += 1
        rows.append(
            {
                "case_id": cid,
                "borderline_category": cat,
                "predicted": label,
                "correct_bl": correct,
                "confidence": pred_obj.get("confidence") if pred_obj else None,
                "reason": (pred_obj or {}).get("reason", "")[:400],
                "bl_context_questions": case.get("bl_context_questions") or [],
                "borderline_rationale": case.get("borderline_rationale") or "",
            }
        )

    evaluated = len(case_files) - missing
    bl_hits = overall.get("BL", 0)
    bl_rate = bl_hits / evaluated if evaluated else 0.0

    cat_bl_rate = {}
    for cat, ctr in by_cat.items():
        n = sum(ctr.values()) - ctr.get("(missing)", 0)
        cat_bl_rate[cat] = ctr.get("BL", 0) / n if n else 0.0

    # Pilot pass gates (automated)
    gates = {
        "overall_bl_rate_ge_35pct": bl_rate >= 0.35,
        "dns_rebinding_bl_rate_ge_50pct": cat_bl_rate.get("dns_rebinding", 0) >= 0.50,
        "missing_le_5pct": missing / len(case_files) <= 0.05 if case_files else False,
    }
    pilot_pass = all(gates.values())

    return {
        "n_cases": len(case_files),
        "evaluated": evaluated,
        "missing": missing,
        "bl_rate": round(bl_rate, 4),
        "distribution": dict(overall),
        "by_category_bl_rate": {k: round(v, 4) for k, v in sorted(cat_bl_rate.items())},
        "by_category_distribution": {k: dict(v) for k, v in sorted(by_cat.items())},
        "gates": gates,
        "pilot_pass": pilot_pass,
        "rows": rows,
    }


def write_html(report: dict, path: Path) -> None:
    rows_html = []
    for r in report["rows"]:
        cls = "pass" if r["correct_bl"] else "fail"
        rows_html.append(
            f"<tr class='{cls}'><td>{html.escape(r['case_id'])}</td>"
            f"<td>{html.escape(r['borderline_category'])}</td>"
            f"<td><b>{html.escape(r['predicted'])}</b></td>"
            f"<td>{html.escape(str(r.get('confidence') or ''))}</td>"
            f"<td>{html.escape(r.get('borderline_rationale') or '')}</td>"
            f"<td>{html.escape(r.get('reason') or '')}</td></tr>"
        )
    gates = report["gates"]
    gate_lines = "".join(
        f"<li>{'✓' if v else '✗'} {html.escape(k)}</li>" for k, v in gates.items()
    )
    doc = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>BL v4 Pilot Review</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 1.5rem; }}
.pass {{ background: #ecfdf5; }} .fail {{ background: #fef2f2; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
th, td {{ border: 1px solid #ddd; padding: 6px 8px; vertical-align: top; }}
th {{ background: #f3f4f6; }}
</style></head><body>
<h1>BL v4 Pilot — Stage 2 GOOD inference review</h1>
<p><b>Pilot pass:</b> {'YES' if report['pilot_pass'] else 'NO'} ·
<b>BL rate:</b> {report['bl_rate']*100:.1f}% ({report['distribution'].get('BL',0)}/{report['evaluated']}) ·
<b>Missing:</b> {report['missing']}</p>
<h2>Automated gates</h2><ul>{gate_lines}</ul>
<h2>BL rate by category</h2>
<pre>{html.escape(json.dumps(report['by_category_bl_rate'], indent=2))}</pre>
<table><thead><tr><th>Case</th><th>Category</th><th>Pred</th><th>Conf</th><th>Rationale</th><th>Model reason</th></tr></thead>
<tbody>{''.join(rows_html)}</tbody></table>
</body></html>"""
    path.write_text(doc, encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--corpus", type=Path, default=_sast / "benchmark" / "corpora" / "bl_v4_pilot")
    ap.add_argument("--runs", type=Path, default=_sast / "runs" / "bl_v4_pilot")
    ap.add_argument("--profile", default="qwen3_5_9b_bnb")
    ap.add_argument("--json-out", type=Path, default=_sast / "runs" / "bl_v4_pilot" / "pilot_review.json")
    ap.add_argument("--html-out", type=Path, default=_sast / "runs" / "bl_v4_pilot" / "PILOT_REVIEW.html")
    args = ap.parse_args()

    report = analyze(
        corpus_dir=args.corpus.expanduser().resolve(),
        runs_root=args.runs.expanduser().resolve(),
        profile=args.profile,
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_html(report, args.html_out.expanduser().resolve())
    summary = {
        "pilot_pass": report["pilot_pass"],
        "bl_rate": report["bl_rate"],
        "by_category_bl_rate": report["by_category_bl_rate"],
        "gates": report["gates"],
        "html": str(args.html_out.resolve()),
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
