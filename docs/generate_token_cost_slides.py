#!/usr/bin/env python3
"""Generate PowerPoint: comparison table + bar-chart graphics for SAST triage $/M costs."""

from __future__ import annotations

import tempfile
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

IN_TOK = 7154
OUT_TOK = 1041
TOTAL = IN_TOK + OUT_TOK
INFER_SEC = 13.5
EC2_OD = 1.861
EC2_SPOT = 0.426
SM_G6E = 2.605
CMU_RATE = 0.05718
BEDROCK_OVERHEAD = 1.1

# category, segment, vendor, model, in_m, out_m, note — in/out None => derived self-host
# segment distinguishes managed-API rows: "Bedrock FM" vs "Frontier" (OpenAI/Anthropic/Google)
ROWS: list[tuple[str, str, str, str, float | None, float | None, str]] = [
    ("Managed API", "Bedrock FM", "Bedrock", "Qwen3.5-9B* (hypothetical)", 0.18, 0.18, "Not listed on Bedrock"),
    ("Managed API", "Bedrock FM", "Bedrock", "Ministral 8B", 0.15, 0.15, "Listed per-token FM"),
    ("Managed API", "Bedrock FM", "Bedrock", "Qwen3 32B", 0.1545, 0.618, "Nearest listed Qwen"),
    ("Self-host", "", "AWS VPC", "EC2 g6e spot + vLLM + LoRA", None, None, "GPU $/hr"),
    ("Self-host", "", "AWS VPC", "EC2 g6e on-demand + vLLM + LoRA", None, None, "GPU $/hr"),
    ("Self-host", "", "AWS VPC", "SageMaker ml.g6e BYOC + LoRA", None, None, "VPC endpoint"),
    ("Self-host", "", "Bedrock CMI", "Bedrock Custom Model Import · 1 CMU", None, None, "Merged LoRA import"),
    ("Self-host", "", "Bedrock CMI", "Bedrock Custom Model Import · 2 CMU", None, None, "Typical 8B CMU"),
    ("Managed API", "Frontier", "Google", "Gemini 2.5 Pro", 1.25, 10.00, ""),
    ("Managed API", "Frontier", "Google", "Gemini 3.5 Flash", 1.50, 9.00, ""),
    ("Managed API", "Frontier", "OpenAI", "GPT-5.4", 2.50, 15.00, ""),
    ("Managed API", "Frontier", "OpenAI", "GPT-5.5", 5.00, 30.00, ""),
    ("Managed API", "Frontier", "Anthropic", "Claude Haiku 4.5", 1.00, 5.00, ""),
    ("Managed API", "Frontier", "Anthropic", "Claude Sonnet 5 (intro)", 2.00, 10.00, ""),
    ("Managed API", "Frontier", "Anthropic", "Claude Opus 4.8", 5.00, 25.00, ""),
]

CAT_COLORS = {
    "Managed API": "#2d8a5e",
    "Self-host": "#3b6ea8",
}
SEGMENT_COLORS = {
    "Bedrock FM": "#2d8a5e",
    "Frontier": "#5cb88a",
    "": "#3b6ea8",
}


def per_triage(in_m: float, out_m: float) -> float:
    return (IN_TOK / 1e6) * in_m + (OUT_TOK / 1e6) * out_m


def blended(pt: float) -> float:
    return pt / (TOTAL / 1e6)


def gpu_pt(hourly: float) -> float:
    return (INFER_SEC / 3600) * hourly


def cmi_pt(cmus: int) -> float:
    hrs = (INFER_SEC / 3600) * BEDROCK_OVERHEAD
    return cmus * CMU_RATE * 60 * hrs


def self_host_pt(model: str) -> float:
    if "spot" in model:
        return gpu_pt(EC2_SPOT)
    if "SageMaker" in model:
        return gpu_pt(SM_G6E)
    if "1 CMU" in model:
        return cmi_pt(1)
    if "2 CMU" in model:
        return cmi_pt(2)
    return gpu_pt(EC2_OD)


def build() -> list[dict]:
    out: list[dict] = []
    for cat, segment, vendor, model, in_m, out_m, note in ROWS:
        if in_m is None:
            pt = self_host_pt(model)
            in_s = out_s = "derived*"
        else:
            pt = per_triage(in_m, out_m)
            in_s = fmt_m(in_m)
            out_s = fmt_m(out_m)
        out.append(
            {
                "category": cat,
                "segment": segment,
                "vendor": vendor,
                "model": model,
                "in_s": in_s,
                "out_s": out_s,
                "blended": blended(pt),
                "per_triage": pt,
                "note": note,
            }
        )
    return sorted(out, key=lambda r: r["blended"])


def fmt_m(v: float) -> str:
    if v >= 10:
        return f"${v:.1f}"
    if v >= 1:
        return f"${v:.2f}"
    return f"${v:.3f}"


def fmt_triage(v: float) -> str:
    return f"${v:.5f}" if v < 0.01 else f"${v:.4f}"


def add_title(slide, title: str, subtitle: str) -> None:
    box = slide.shapes.add_textbox(Inches(0.45), Inches(0.25), Inches(9.1), Inches(1.0))
    tf = box.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.text = title
    p.font.size = Pt(26)
    p.font.bold = True
    p2 = tf.add_paragraph()
    p2.text = subtitle
    p2.font.size = Pt(11)
    p2.font.color.rgb = RGBColor(0x55, 0x55, 0x55)


def add_table(slide, headers: list[str], rows: list[list[str]], *, top: float, height: float) -> None:
    table = slide.shapes.add_table(
        len(rows) + 1, len(headers), Inches(0.35), Inches(top), Inches(9.3), Inches(height)
    ).table
    for j, h in enumerate(headers):
        c = table.cell(0, j)
        c.text = h
        for p in c.text_frame.paragraphs:
            p.font.bold = True
            p.font.size = Pt(8)
    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row):
            c = table.cell(i, j)
            c.text = val
            for p in c.text_frame.paragraphs:
                p.font.size = Pt(7)
                if j >= 4:
                    p.alignment = PP_ALIGN.RIGHT


def render_chart(rows: list[dict], path: Path) -> None:
    """Grouped horizontal bar: $/M blended by option, colored by category."""
    labels = [r["model"].replace(" + vLLM + LoRA", "").replace("Custom Model Import · ", "CMI ") for r in rows]
    values = [r["blended"] for r in rows]
    colors = [
        SEGMENT_COLORS.get(r["segment"], CAT_COLORS[r["category"]]) for r in rows
    ]

    fig, ax = plt.subplots(figsize=(10, 6.5))
    y = range(len(labels))
    ax.barh(list(y), values, color=colors, height=0.72)
    ax.set_yticks(list(y))
    ax.set_yticklabels(labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlabel("$/M blended (in+out at triage workload)", fontsize=10)
    ax.set_title(
        f"SAST triage token cost — {IN_TOK:,} in + {OUT_TOK:,} out / case · Jun 2026 pricing",
        fontsize=11,
        fontweight="bold",
    )
    ax.axvline(blended(per_triage(0.18, 0.18)), color="#2d8a5e", linestyle="--", linewidth=1, alpha=0.7)
    ax.text(blended(per_triage(0.18, 0.18)) + 0.02, 0.5, "Managed 9B*", fontsize=7, color="#2d8a5e")
    from matplotlib.patches import Patch

    ax.legend(
        handles=[
            Patch(facecolor=SEGMENT_COLORS["Bedrock FM"], label="Managed API — Bedrock FM"),
            Patch(facecolor=SEGMENT_COLORS["Frontier"], label="Managed API — Frontier"),
            Patch(facecolor=CAT_COLORS["Self-host"], label="Self-host (BYOM)"),
        ],
        loc="upper right",
        fontsize=8,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def render_self_host_chart(path: Path) -> None:
    """Self-host only: show derived vs blended."""
    sh = [r for r in build() if r["category"] == "Self-host"]
    labels = [r["model"].replace(" + vLLM + LoRA", "") for r in sh]
    blended_v = [r["blended"] for r in sh]
    pt_v = [r["per_triage"] * 1000 for r in sh]  # m$/triage for scale

    fig, ax1 = plt.subplots(figsize=(9, 4))
    x = range(len(labels))
    ax1.bar([i - 0.2 for i in x], blended_v, width=0.4, color="#3b6ea8", label="$/M blended")
    ax1.set_ylabel("$/M blended", color="#3b6ea8")
    ax1.set_xticks(list(x))
    ax1.set_xticklabels(labels, rotation=15, ha="right", fontsize=8)
    ax2 = ax1.twinx()
    ax2.bar([i + 0.2 for i in x], pt_v, width=0.4, color="#7aa6d8", label="m$/triage (×1000)")
    ax2.set_ylabel("$/triage × 1000", color="#7aa6d8")
    ax1.set_title("Self-host paths — derived $/M from GPU/CMU time (not vendor token rates)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    root = Path(__file__).resolve().parent
    out_path = root / "token-cost-slides.pptx"
    rows = build()

    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)

    # Slide 1 — full comparison table
    s1 = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(
        s1,
        "SAST Triage — $/M Token Cost Comparison",
        f"Workload: {IN_TOK:,} in + {OUT_TOK:,} out tokens/triage · Phase 3C ship · Jun 2026",
    )
    add_table(
        s1,
        ["Category", "Segment", "Vendor", "Model", "$/M in", "$/M out", "$/M blended", "$/triage"],
        [
            [
                r["category"],
                r["segment"] or "—",
                r["vendor"],
                r["model"],
                r["in_s"],
                r["out_s"],
                fmt_m(r["blended"]),
                fmt_triage(r["per_triage"]),
            ]
            for r in rows
        ],
        top=1.15,
        height=5.8,
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        chart_all = tmp_path / "all.png"
        chart_sh = tmp_path / "selfhost.png"
        render_chart(rows, chart_all)
        render_self_host_chart(chart_sh)

        # Slide 2 — bar chart all categories
        s2 = prs.slides.add_slide(prs.slide_layouts[6])
        add_title(
            s2,
            "Graphic — $/M blended by deployment option",
            "Green = Managed API (Bedrock FM + Frontier) · Blue = Self-host BYOM with custom LoRA",
        )
        s2.shapes.add_picture(str(chart_all), Inches(0.35), Inches(1.1), width=Inches(9.3))

        # Slide 3 — self-host methodology graphic
        s3 = prs.slides.add_slide(prs.slide_layouts[6])
        add_title(
            s3,
            "Graphic — Self-host derived rates",
            "* $/M in/out are derived from GPU $/hr or CMU $/min ÷ token throughput — see formula below",
        )
        s3.shapes.add_picture(str(chart_sh), Inches(0.35), Inches(1.05), width=Inches(9.0))
        box = s3.shapes.add_textbox(Inches(0.45), Inches(5.35), Inches(9.0), Inches(1.8))
        tf = box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = (
            "VPC: $/triage = (13.5s ÷ 3600) × GPU_$/hr  →  $/M blended = $/triage ÷ (8,195 ÷ 1M)\n"
            "Bedrock CMI: $/triage = CMUs × $0.05718/min × 60 × active_hrs  →  same blended formula\n"
            "Derived $/M_in = $/triage ÷ (7,154 ÷ 1M)   ·   Derived $/M_out = $/triage ÷ (1,041 ÷ 1M)"
        )
        p.font.size = Pt(10)

    prs.save(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
