#!/usr/bin/env python3
"""Generate PowerPoint: summary table + simple business bar chart for SAST triage costs."""

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

CHART_COLOR = "#2563eb"

# category, segment, vendor, model, in_m, out_m, note — in/out None => derived self-host
ROWS: list[tuple[str, str, str, str, float | None, float | None, str]] = [
    # ("Managed API", "Bedrock FM", "Bedrock", "Qwen3.5-9B* (hypothetical)", 0.18, 0.18, "Not listed on Bedrock"),
    # ("Managed API", "Bedrock FM", "Bedrock", "Ministral 8B", 0.15, 0.15, "Listed per-token FM"),
    # ("Managed API", "Bedrock FM", "Bedrock", "Qwen3 32B", 0.1545, 0.618, "Nearest listed Qwen"),
    ("Self-host", "", "AWS VPC", "EC2 g6e spot + vLLM + LoRA", None, None, "GPU $/hr"),
    ("Self-host", "", "AWS VPC", "EC2 g6e on-demand + vLLM + LoRA", None, None, "GPU $/hr"),
    ("Self-host", "", "AWS VPC", "SageMaker ml.g6e BYOC + LoRA", None, None, "VPC endpoint"),
    ("Self-host", "", "Bedrock CMI", "Bedrock Custom Model Import · 1 CMU", None, None, "Merged LoRA import"),
    # ("Self-host", "", "Bedrock CMI", "Bedrock Custom Model Import · 2 CMU", None, None, "Typical 8B CMU"),
    ("Managed API", "Frontier", "Google", "Gemini 2.5 Pro", 1.25, 10.00, ""),
    ("Managed API", "Frontier", "Google", "Gemini 3.5 Flash", 1.50, 9.00, ""),
    ("Managed API", "Frontier", "OpenAI", "GPT-5.4", 2.50, 15.00, ""),
    ("Managed API", "Frontier", "OpenAI", "GPT-5.5", 5.00, 30.00, ""),
    ("Managed API", "Frontier", "Anthropic", "Claude Haiku 4.5", 1.00, 5.00, ""),
    ("Managed API", "Frontier", "Anthropic", "Claude Sonnet 5 (intro)", 2.00, 10.00, ""),
    ("Managed API", "Frontier", "Anthropic", "Claude Opus 4.8", 5.00, 25.00, ""),
]


def business_label(model: str, category: str) -> str:
    """Plain-language labels for executives."""
    if category == "Self-host":
        if "spot" in model:
            return "Qwen3.5-9B self-host (spot)"
        if "on-demand" in model:
            return "Qwen3.5-9B self-host (on-demand)"
        if "SageMaker" in model:
            return "Qwen3.5-9B self-host (managed)"
        if "1 CMU" in model:
            return "Qwen3.5-9B on Bedrock"
        if "2 CMU" in model:
            return "Qwen3.5-9B on Bedrock"
        return "Qwen3.5-9B self-host"
    if "hypothetical" in model:
        return "Qwen3.5-9B pay-per-use*"
    if "Ministral" in model:
        return "Ministral 8B pay-per-use"
    if "Qwen3 32B" in model:
        return "Qwen3-32B pay-per-use"
    return model.replace(" (intro)", "")


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
            in_s = out_s = "—"
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
                "label": business_label(model, cat),
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
    return f"${v:.4f}" if v >= 0.01 else f"${v:.5f}"


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
            p.font.size = Pt(9)
    for i, row in enumerate(rows, start=1):
        for j, val in enumerate(row):
            c = table.cell(i, j)
            c.text = val
            for p in c.text_frame.paragraphs:
                p.font.size = Pt(8)
                if j >= 1:
                    p.alignment = PP_ALIGN.RIGHT


def render_chart(rows: list[dict], path: Path) -> None:
    """Simple vertical bar chart — one color, business labels."""
    labels = [r["label"] for r in rows]
    values = [r["blended"] for r in rows]

    fig, ax = plt.subplots(figsize=(10, 6.2))
    x = range(len(labels))
    bars = ax.bar(list(x), values, color=CHART_COLOR, width=0.62, edgecolor="white", linewidth=0.6)

    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=55, ha="right", fontsize=9)
    ax.set_ylabel("Cost per million tokens ($)", fontsize=11)
    # ax.set_title("Cost by deployment option", fontsize=14, fontweight="bold", pad=14)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", linestyle=":", alpha=0.35)
    ax.set_axisbelow(True)

    for bar, val in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            bar.get_height() + max(values) * 0.012,
            fmt_m(val),
            ha="center",
            va="bottom",
            fontsize=7,
            color="#333333",
        )

    # fig.text(
    #     0.5,
    #     0.02,
    #     f"Typical security alert (~{TOTAL:,} tokens). Lower is better.  ·  Pricing as of Jun 2026",
    #     ha="center",
    #     fontsize=9,
    #     color="#666666",
    # )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    root = Path(__file__).resolve().parent
    out_path = root / "token-cost-slides.pptx"
    rows = build()

    prs = Presentation()
    prs.slide_width = Inches(10)
    prs.slide_height = Inches(7.5)

    # Slide 1 — summary table (plain language)
    s1 = prs.slides.add_slide(prs.slide_layouts[6])
    add_title(
        s1,
        "SAST Triage — Cost Comparison",
        "What it costs to review one security alert with each option",
    )
    add_table(
        s1,
        ["Option", "$/M tokens", "$/alert"],
        [
            [
                r["label"],
                fmt_m(r["blended"]),
                fmt_triage(r["per_triage"]),
            ]
            for r in rows
        ],
        top=1.15,
        height=5.8,
    )

    with tempfile.TemporaryDirectory() as tmp:
        chart_all = Path(tmp) / "cost_chart.png"
        render_chart(rows, chart_all)

        # Slide 2 — simple bar chart
        s2 = prs.slides.add_slide(prs.slide_layouts[6])
        add_title(
            s2,
            "Cost by deployment options",
            "$/M tokens — self-host vs pay-per-use vs frontier models",
        )
        s2.shapes.add_picture(str(chart_all), Inches(0.35), Inches(1.05), width=Inches(9.3))

    prs.save(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
