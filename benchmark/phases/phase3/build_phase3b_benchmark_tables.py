#!/usr/bin/env python3
"""Build Phase 3B benchmark report (CSS, confusion matrices, val vs test)."""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

_SAST = Path(__file__).resolve().parents[3]
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

from benchmark.css import W_FPRR, W_MACRO_F1, W_SRS, W_VDR, VDR_DISQUALIFY, css_from_metrics_pack  # noqa: E402
from benchmark.phases.phase3.phase3b_benchmark import (  # noqa: E402
    PHASE2_TEST_N,
    load_all_test_cells,
    load_best_epoch,
    load_fs0_off_rerank,
)
from benchmark.srs import compute_srs  # noqa: E402
from timing import utc_now_iso  # noqa: E402

OUT_DIR = _SAST / "runs/phase3/stage3b/benchmark"
HTML_OUT = OUT_DIR / "PHASE3B_BENCHMARK.html"
SUMMARY_JSON = OUT_DIR / "phase3b_benchmark_summary.json"
CONFUSION_JSON = OUT_DIR / "phase3b_confusion_comparison.json"
STAGE2_BASE = {"srs": 0.925, "vdr": 0.925, "fprr": 0.735}


def _fmt(x: float | None) -> str:
    return f"{float(x):.3f}" if x is not None else "—"


def _confusion_html(cm: dict) -> str:
    matrix = cm.get("matrix") or {}
    missing = cm.get("missing_by_gold") or {}
    labels = ("TP", "FP", "BL")
    header = (
        "<tr><th>Gold \\ Pred</th>"
        + "".join(f"<th>→ {html.escape(p)}</th>" for p in labels)
        + "<th>miss</th></tr>"
    )
    body = []
    for gold in labels:
        row = matrix.get(gold) or {}
        miss = int(missing.get(gold, 0))
        cells = [f"<th>{html.escape(gold)}</th>"]
        for pred in labels:
            val = int(row.get(pred, 0))
            cls = ""
            if gold == pred and val:
                cls = "cm-diag"
            elif gold == "TP" and pred == "FP" and val:
                cls = "cm-critical"
            elif gold == "BL" and pred == "FP" and val:
                cls = "cm-high"
            cells.append(f'<td class="{cls}">{val}</td>' if cls else f"<td>{val}</td>")
        cells.append(f"<td>{miss}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<table class="cm"><thead>{header}</thead><tbody>{"".join(body)}</tbody></table>'


def _css_section(best: dict) -> str:
    val = best.get("metrics") or {}
    pack = css_from_metrics_pack(val)
    comps = pack.get("components") or {}
    weights = pack.get("weights") or {}
    return f"""<section>
<h2>Checkpoint selection (validation CSS)</h2>
<p>Best LoRA checkpoint by CSS on 600-case validation split (teacher distillation, rank 32).</p>
<table>
<thead><tr><th>Epoch</th><th>CSS</th><th>SRS</th><th>VDR</th><th>FPRR</th><th>Macro-F1</th><th>Eligible</th></tr></thead>
<tbody>
<tr>
  <td><b>{best.get('epoch', '—')}</b></td>
  <td>{_fmt(best.get('css'))}</td>
  <td>{_fmt(val.get('srs'))}</td>
  <td>{_fmt(val.get('vdr'))}</td>
  <td>{_fmt(val.get('fprr'))}</td>
  <td>{_fmt(val.get('macro_f1'))}</td>
  <td>{'yes' if not pack.get('disqualified') else 'no (VDR gate)'}</td>
</tr>
</tbody>
</table>
<h3>CSS formula</h3>
<p><code>CSS = {W_SRS}·SRS + {W_VDR}·VDR + {W_FPRR}·FPRR + {W_MACRO_F1}·Macro-F1</code></p>
<p>Hard disqualifier: VDR &lt; {VDR_DISQUALIFY} on validation → CSS = 0. Used for checkpoint pick only; final ship metric is test SRS.</p>
<dl>
<dt>Components (epoch {best.get('epoch')})</dt>
<dd>SRS {_fmt(comps.get('srs'))} × {weights.get('srs', W_SRS)} +
    VDR {_fmt(comps.get('vdr'))} × {weights.get('vdr', W_VDR)} +
    FPRR {_fmt(comps.get('fprr'))} × {weights.get('fprr', W_FPRR)} +
    Macro-F1 {_fmt(comps.get('macro_f1'))} × {weights.get('macro_f1', W_MACRO_F1)}
    = <b>{_fmt(pack.get('css'))}</b></dd>
</dl>
</section>"""


def _fs0_rerank_section(rerank: dict) -> str:
    epochs = rerank.get("epochs") or []
    if not epochs:
        return ""
    head = (
        "<tr><th>Epoch</th><th>Val SRS</th><th>Val VDR</th><th>Val FPRR</th>"
        "<th>Val CSS</th><th>fs3 CSS (ref)</th></tr>"
    )
    best_ep = rerank.get("epoch")
    rows = []
    for e in epochs:
        ep = e.get("epoch")
        pick = " <b>(ship pick)</b>" if ep == best_ep else ""
        rows.append(
            f"<tr><td>{ep}{pick}</td>"
            f"<td>{_fmt(e.get('val_srs'))}</td>"
            f"<td>{_fmt(e.get('val_vdr'))}</td>"
            f"<td>{_fmt(e.get('val_fprr'))}</td>"
            f"<td>{_fmt(e.get('val_css'))}</td>"
            f"<td>{_fmt(e.get('fs3_css'))}</td></tr>"
        )
    cfg = rerank.get("infer_config") or {}
    return f"""<section>
<h2>Ship checkpoint rerank (validation · fs0_off)</h2>
<p>Re-scored all CSS-eligible epochs on full 600-case validation under ship inference
(thinking={cfg.get('thinking', 'off')}, fewshot={cfg.get('fewshot', 0)}, prompt={cfg.get('prompt', 'v7-ship')}).
Pick by val SRS → epoch <b>{best_ep}</b> (adapter <code>lora/best_fs0_off</code>).</p>
<table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table>
<p>Training-time fs3+CoT CSS pick was epoch {load_best_epoch().get('epoch')} — train/serve mismatch explains FPRR gap vs Stage 2.</p>
</section>"""


def _test_section(cells: list[dict]) -> str:
    if not cells:
        return "<p><i>No test eval summaries found.</i></p>"

    head = (
        "<tr><th>Config</th><th>Epoch</th><th>SRS</th><th>VDR</th><th>FPRR</th><th>Macro-F1</th>"
        "<th>Missing</th><th>TP→FP</th><th>Δ SRS vs S2</th></tr>"
    )
    rows = []
    for c in cells:
        delta = (c["srs"] - STAGE2_BASE["srs"]) * 100
        sign = "+" if delta >= 0 else ""
        rows.append(
            f"<tr><td>{html.escape(c['label'])}</td>"
            f"<td>{c['epoch']}</td>"
            f"<td>{_fmt(c['srs'])}</td><td>{_fmt(c['vdr'])}</td>"
            f"<td>{_fmt(c['fprr'])}</td><td>{_fmt(c['macro_f1'])}</td>"
            f"<td>{c['missing']}</td><td>{c['critical_tp_fp']}</td>"
            f"<td>{sign}{delta:.1f}pp</td></tr>"
        )

    cm_blocks = []
    for c in cells:
        cm_blocks.append(
            f'<div class="cm-block"><h3>{html.escape(c["label"])}</h3>'
            f'<p class="note">{html.escape(c.get("note", ""))}</p>'
            f"{_confusion_html(c['confusion'])}</div>"
        )

    ship = next((c for c in cells if c["id"] == "phase3b_fs0_off_best"), cells[-1] if cells else None)
    ship_note = (
        f"Recommended ship row: epoch {ship['epoch']} · SRS {_fmt(ship['srs'])}."
        if ship
        else ""
    )

    return f"""<section>
<h2>Test eval (600-case Phase 2 holdout)</h2>
<p>Profile <code>qwen3_5_9b_bnb</code> · Stage 2 GOOD baseline SRS {_fmt(STAGE2_BASE['srs'])}.
{ship_note}</p>
<table><thead>{head}</thead><tbody>{''.join(rows)}</tbody></table>
<div class="cm-grid">{''.join(cm_blocks)}</div>
</section>"""


def _srs_notes() -> str:
    return """<section class="notes">
<h2>Metric definitions</h2>
<dl>
<dt>SRS (Security Review Score)</dt>
<dd>1 − (Σ penalty) / (N × 3.0) over 600 test cases. Penalties: TP→FP 3.0× · BL→FP 1.5× · TP→BL 1.0× · FP→TP/BL 1.0× · missing 3.0×.</dd>
<dt>VDR / FPRR</dt>
<dd>TP-track recall and FP-track recall respectively.</dd>
<dt>CSS</dt>
<dd>Composite Selection Score for validation checkpoint ranking during LoRA training — not the final ship gate.</dd>
</dl>
</section>"""


def build_html(cells: list[dict], best: dict, rerank: dict) -> str:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ship_ep = rerank.get("epoch") or best.get("epoch")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>Phase 3B Benchmark — LoRA ship epoch {ship_ep}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; color: #1a1a2e; }}
h1 {{ color: #4a148c; font-size: 1.35rem; }}
h2 {{ color: #4a148c; font-size: 1.05rem; margin-top: 2rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; margin: 1rem 0; }}
th {{ background: #4a148c; color: #fff; padding: 8px 10px; text-align: right; }}
th:first-child {{ text-align: left; }}
td {{ padding: 6px 10px; border-bottom: 1px solid #e8e8e8; text-align: right; }}
td:first-child {{ text-align: left; }}
.cm-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.25rem; }}
.cm-block h3 {{ font-size: 0.95rem; margin: 0 0 0.25rem; }}
.note {{ color: #666; font-size: 0.85rem; }}
td.cm-diag {{ background: #e8f5e9; font-weight: 600; }}
td.cm-critical {{ background: #ffcdd2; font-weight: 600; }}
td.cm-high {{ background: #ffe0b2; }}
.status {{ font-size: 0.85rem; color: #444; }}
</style>
</head>
<body>
<p class="status">Generated {generated} · <code>build_phase3b_benchmark_tables.py</code></p>
<h1>Phase 3B Benchmark — Distilled LoRA (r=32)</h1>
<p>Teacher: Phase 2 Stage 2 · Qwen3.5-9B · train distill 1500 cases · CSS early stop @ epoch {best.get('epoch')} (fs3 val).</p>
{_css_section(best)}
{_fs0_rerank_section(rerank)}
{_test_section(cells)}
{_srs_notes()}
</body>
</html>"""


def main() -> None:
    best = load_best_epoch()
    rerank = load_fs0_off_rerank()
    cells = load_all_test_cells()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    summary = {
        "generated_at": utc_now_iso(),
        "train_pick_epoch": best.get("epoch"),
        "ship_pick_epoch": rerank.get("epoch"),
        "val_css_fs3": best,
        "val_rerank_fs0_off": rerank,
        "test_cells": [
            {
                "id": c["id"],
                "label": c["label"],
                "epoch": c["epoch"],
                "thinking": c["thinking"],
                "fewshot": c["fewshot"],
                "srs": c["srs"],
                "vdr": c["vdr"],
                "fprr": c["fprr"],
                "macro_f1": c["macro_f1"],
                "missing": c["missing"],
                "critical_tp_fp": c["critical_tp_fp"],
            }
            for c in cells
        ],
        "stage2_baseline": STAGE2_BASE,
    }
    comparisons = [
        {k: v for k, v in c["confusion"].items()}
        | {
            "id": c["id"],
            "label": c["label"],
            "srs": c["srs"],
            "vdr": c["vdr"],
            "fprr": c["fprr"],
            "note": c.get("note", ""),
            "row_class": "cat-phase3b",
        }
        for c in cells
    ]

    SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    CONFUSION_JSON.write_text(json.dumps(comparisons, indent=2), encoding="utf-8")
    HTML_OUT.write_text(build_html(cells, best, rerank), encoding="utf-8")
    print(f"Wrote {HTML_OUT}")
    for c in cells:
        print(f"  {c['id']:16s} SRS={c['srs']:.4f} missing={c['missing']}")


if __name__ == "__main__":
    main()
