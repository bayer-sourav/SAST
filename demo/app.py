#!/usr/bin/env python3
"""
Live SAST triage demo — Git → CodeQL → AI triage → metrics.

Run: ./demo/run_demo.sh
"""

from __future__ import annotations

import html
import json
import time
from pathlib import Path

import pandas as pd

from demo.bootstrap import ensure_import_paths

ensure_import_paths()

import streamlit as st

from demo.findings import (
    CATEGORY_STYLES,
    VULN_CATEGORIES,
    build_finding_views,
    gold_badge,
    label_badge,
    snippet_html,
)
from demo.metrics import (
    CaseOutcome,
    compute_metrics,
    format_fraction,
    format_pct,
    outcome_status,
    outcomes_table_rows,
)
from demo.pipeline import (
    case_meta,
    configure_backend,
    list_models,
    load_cached_outcomes,
    load_case_entry,
    load_manifest,
    model_by_id,
    resolve_repo,
    run_live_triage,
)

st.set_page_config(
    page_title="SAST AI Triage Demo",
    layout="wide",
    initial_sidebar_state="expanded",
)

TARGET_VDR = 0.95
TARGET_FPRR = 0.90

DEMO_CSS = """
<style>
.pipeline { display: flex; gap: 0.5rem; margin: 1rem 0 1.5rem; flex-wrap: wrap; }
.step {
  flex: 1; min-width: 140px; padding: 0.75rem 1rem; border-radius: 8px;
  border: 1px solid #dde3ea; background: #f8fafc; text-align: center;
}
.step.active { border-color: #1e88e5; background: #e3f2fd; }
.step.done { border-color: #43a047; background: #e8f5e9; }
.step-num { font-size: 0.75rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.04em; }
.step-title { font-weight: 600; color: #1e3a5f; margin-top: 0.15rem; }
.step-body { font-size: 0.8rem; color: #64748b; margin-top: 0.2rem; }

.finding-card {
  border: 1px solid #e2e8f0; border-radius: 10px; padding: 1rem 1.25rem;
  margin-bottom: 1rem; background: #fff;
}
.finding-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; flex-wrap: wrap; }
.finding-title { font-size: 1.05rem; font-weight: 600; color: #1e3a5f; margin: 0; }
.finding-meta { font-size: 0.85rem; color: #64748b; margin-top: 0.35rem; }
.rule-pill {
  display: inline-block; padding: 0.15rem 0.55rem; border-radius: 999px;
  background: #eef2ff; color: #3730a3; font-size: 0.78rem; font-family: monospace;
}
.cat-pill {
  display: inline-block; padding: 0.2rem 0.6rem; border-radius: 6px;
  font-size: 0.75rem; font-weight: 700; letter-spacing: 0.02em;
}
.cat-ssrf { background: #fce4ec; color: #ad1457; }
.cat-pssrf { background: #ede7f6; color: #4527a0; }
.cat-typeconf { background: #e0f2f1; color: #00695c; }
.msg-box {
  margin: 0.75rem 0; padding: 0.65rem 0.85rem; border-left: 3px solid #1e88e5;
  background: #f0f7ff; font-size: 0.9rem; color: #1e293b;
}
.flow-trail {
  font-size: 0.82rem; color: #475569; margin: 0.5rem 0 0.75rem;
  font-family: ui-monospace, monospace;
}
.verdict-row {
  display: flex; gap: 0.75rem; flex-wrap: wrap; align-items: center;
  margin-top: 0.85rem; padding-top: 0.85rem; border-top: 1px dashed #e2e8f0;
}
.badge, .label-badge {
  display: inline-block; padding: 0.25rem 0.65rem; border-radius: 6px;
  font-size: 0.78rem; font-weight: 600;
}
.badge-tp { background: #ffebee; color: #c62828; }
.badge-fp { background: #e8f5e9; color: #2e7d32; }
.badge-bl { background: #fff8e1; color: #f57f17; }
.badge-unknown { background: #eceff1; color: #546e7a; }
.badge-pending { background: #f1f5f9; color: #94a3b8; }
.label-tp { background: #c62828; color: #fff; }
.label-fp { background: #2e7d32; color: #fff; }
.label-bl { background: #f57f17; color: #fff; }
.label-unknown { background: #78909c; color: #fff; }
.status-ok { color: #2e7d32; font-weight: 600; }
.status-bad { color: #c62828; font-weight: 600; }
.status-warn { color: #ef6c00; font-weight: 600; }

.code-block {
  background: #0f172a; color: #e2e8f0; border-radius: 8px; padding: 0.5rem 0;
  overflow-x: auto; font-size: 0.78rem; line-height: 1.5; margin: 0;
}
.code-line { display: flex; white-space: pre; align-items: stretch; }
.code-line.hot { background: rgba(251, 191, 36, 0.1); }
.code-line .ln {
  color: #64748b; min-width: 3.5rem; text-align: right; padding: 0 0.75rem;
  user-select: none; border-right: 1px solid #334155; margin-right: 0.5rem;
}
.code-line .ln-hot { color: #fbbf24; font-weight: 700; }
.code-line code { flex: 1; padding: 0.05rem 0.75rem 0.05rem 0; }
.code-line mark { border-radius: 2px; padding: 0 1px; }
mark.hl-sink { background: #f59e0b; color: #0f172a; font-weight: 600; }
mark.hl-flow { background: rgba(56, 189, 248, 0.35); color: #e0f2fe; }
.code-empty { color: #94a3b8; font-style: italic; padding: 0.75rem; }
</style>
"""


def _init_state() -> None:
    defaults = {
        "outcomes": [],
        "compare_rows": [],
        "commit_sha": "a1b2c3d",
        "demo_phase": "codeql",
        "finding_views": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def _load_pack_cases(pack_key: str) -> list[dict]:
    manifest = load_manifest()
    pack = manifest["packs"][pack_key]
    if "cases" in pack:
        return pack["cases"]
    slice_path = Path(pack["slice_file"])
    data = json.loads(slice_path.read_text())
    cases = []
    for cid in data.get("tp", []):
        cases.append(
            {
                "case_id": cid,
                "gold": "TP",
                "corpus": "phase2_tp_test",
                "title": f"TP track · {cid}",
                "rule": "mixed",
            }
        )
    for cid in data.get("fp", []):
        cases.append(
            {
                "case_id": cid,
                "gold": "FP",
                "corpus": "phase2_fp_test",
                "title": f"FP track · {cid}",
                "rule": "mixed",
            }
        )
    return cases


def _targets() -> tuple[float, float]:
    manifest = load_manifest()
    t = manifest.get("targets", {})
    return float(t.get("vdr_min", TARGET_VDR)), float(t.get("fprr_min", TARGET_FPRR))


def _outcome_map(outcomes: list[CaseOutcome]) -> dict[str, CaseOutcome]:
    return {o.case_id: o for o in outcomes}


def _outcomes_from_entries(
    entries: list[dict],
    rows: list[dict],
    profile: str,
) -> list[CaseOutcome]:
    by_id = {r["case_id"]: r for r in rows}
    outcomes: list[CaseOutcome] = []
    for entry in entries:
        r = by_id.get(entry["case_id"], {})
        try:
            _, case = load_case_entry(entry)
            meta = case_meta(entry, case)
        except FileNotFoundError:
            meta = {"acceptable_labels": [], "borderline_rationale": ""}
        outcomes.append(
            CaseOutcome(
                case_id=entry["case_id"],
                gold=entry["gold"],
                predicted=r.get("predicted"),
                title=entry.get("title", ""),
                rule=entry.get("rule", ""),
                reason=r.get("reason", ""),
                confidence=r.get("confidence", ""),
                elapsed_sec=r.get("elapsed_sec"),
                source=r.get("source", "live"),
                profile=profile,
                acceptable_labels=meta.get("acceptable_labels") or [],
                borderline_rationale=meta.get("borderline_rationale") or "",
            )
        )
    return outcomes


def _run_single(
    entries: list[dict],
    *,
    profile: str,
    prompt_version: str,
    fewshot: int,
    fs_config: str,
    thinking: bool,
    use_cached: bool,
    repo: Path | None,
) -> list[CaseOutcome]:
    sast = Path(__file__).resolve().parent.parent
    run_base = sast / "runs" / "demo" / "live"
    progress = st.progress(0, text="Starting AI triage…")
    rows: list[dict] = []

    if use_cached:
        cached = load_cached_outcomes(
            entries, profile=profile, prompt_version=prompt_version, fewshot=fewshot
        )
        rows = cached
        progress.progress(1.0, text="Loaded cached triage results")
        time.sleep(0.3)
    else:
        configure_backend(profile)
        for i, entry in enumerate(entries):
            cid = entry["case_id"]
            progress.progress(
                (i + 0.1) / len(entries),
                text=f"AI triage: {cid} ({i + 1}/{len(entries)})",
            )
            case_path, case = load_case_entry(entry)
            run_dir = run_base / profile / prompt_version / cid
            out = run_live_triage(
                case_path=case_path,
                case=case,
                gold=entry["gold"],
                profile=profile,
                prompt_version=prompt_version,
                fewshot=fewshot,
                few_shot_config=fs_config,
                thinking=thinking,
                run_dir=run_dir,
                repo=repo,
            )
            result = out.get("result") or {}
            meta = out.get("meta") or {}
            rows.append(
                {
                    "case_id": cid,
                    "predicted": result.get("label"),
                    "reason": result.get("reason", ""),
                    "confidence": result.get("confidence", ""),
                    "elapsed_sec": meta.get("elapsed_sec"),
                    "source": "live",
                }
            )
        progress.progress(1.0, text="AI triage complete")

    return _outcomes_from_entries(entries, rows, profile)


def _run_compare(
    entries: list[dict],
    *,
    models: list[dict],
    prompt_version: str,
    fewshot: int,
) -> list[dict]:
    compare: list[dict] = []
    vdr_t, fprr_t = _targets()
    for model in models:
        profile = model["id"]
        outcomes = _outcomes_from_entries(
            entries,
            load_cached_outcomes(
                entries, profile=profile, prompt_version=prompt_version, fewshot=fewshot
            ),
            profile,
        )
        m = compute_metrics(outcomes, vdr_target=vdr_t, fprr_target=fprr_t)
        tp = m["tracks"]["tp_track"]
        fp = m["tracks"]["fp_track"]
        bl_tr = m["tracks"]["bl_track"]
        missing = sum(1 for o in outcomes if o.predicted is None)
        compare.append(
            {
                "Model": model["label"],
                "Profile": profile,
                "Backend": model.get("backend", "?"),
                "VDR": format_pct(m["vdr"]),
                "FPRR": format_pct(m["fprr"]),
                "SRS": format_pct(m["srs"]),
                "Borderline": format_fraction(bl_tr["acceptable"], bl_tr["n"]),
                "Threats": format_fraction(tp["hits"], tp["n"]),
                "Noise": format_fraction(fp["hits"], fp["n"]),
                "Pass": "Yes" if m["gates_pass"] else ("Partial" if missing else "No"),
            }
        )
    return compare


def _render_pipeline(*, phase: str, sha: str, model_label: str, backend: str) -> None:
    steps = [
        ("1", "Git push", f"main @ {sha[:7]}", phase in ("codeql", "triaging", "done", "compare")),
        ("2", "CodeQL", "SARIF findings", phase in ("codeql", "triaging", "done", "compare")),
        ("3", "AI triage", f"{model_label} ({backend})", phase in ("triaging", "done")),
        ("4", "Metrics", "VDR · FPRR · SRS", phase == "done" or phase == "compare"),
    ]
    parts = ['<div class="pipeline">']
    for num, title, body, done in steps:
        active = (
            (phase == "codeql" and num == "2")
            or (phase == "triaging" and num == "3")
            or (phase == "done" and num == "4")
            or (phase == "compare" and num == "4")
        )
        cls = "step done" if done else ("step active" if active else "step")
        parts.append(
            f'<div class="{cls}">'
            f'<div class="step-num">Step {num}</div>'
            f'<div class="step-title">{html.escape(title)}</div>'
            f'<div class="step-body">{html.escape(body)}</div>'
            f"</div>"
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _status_class(status: str) -> str:
    if status in ("Correct", "Acceptable", "Escalated"):
        return "status-ok"
    if status in ("Missed vuln", "False alarm", "Overconfident"):
        return "status-bad"
    return "status-warn"


def _render_finding_card(
    view,
    outcome: CaseOutcome | None,
    *,
    show_eval_truth: bool,
) -> None:
    featured = view.featured or (view.alerts[0] if view.alerts else None)
    rule = featured.rule_id if featured else view.rule
    message = featured.message if featured else view.title
    sink = f"{view.file_name} {featured.sink_lines}" if featured else view.file_name
    cat_cls = CATEGORY_STYLES.get(view.vuln_category, "cat-ssrf")
    cat_desc = VULN_CATEGORIES.get(view.vuln_category, "")

    header = (
        f'<div class="finding-header">'
        f'<div><p class="finding-title">{html.escape(view.case_id)} '
        f'<span class="cat-pill {cat_cls}">{html.escape(view.vuln_category)}</span></p>'
        f'<div class="finding-meta">{html.escape(view.title)}</div>'
        f'<div class="finding-meta" style="font-size:0.78rem">{html.escape(cat_desc)}</div></div>'
        f'<span class="rule-pill">{html.escape(rule)}</span>'
        f"</div>"
    )
    if message:
        header += f'<div class="msg-box">{html.escape(message)}</div>'
    header += (
        f'<div class="finding-meta">'
        f"<b>File</b> {html.escape(view.file_path)} · "
        f"<b>Sink</b> {html.escape(sink)} · "
        f"<b>{view.alert_count}</b> alert{'s' if view.alert_count != 1 else ''}"
        f"</div>"
    )
    if featured and featured.flow_steps:
        flow = " → ".join(featured.flow_steps[:8])
        if len(featured.flow_steps) > 8:
            flow += " → …"
        header += f'<div class="flow-trail"><b>Dataflow</b> {html.escape(flow)}</div>'

    with st.container(border=True):
        st.markdown(f'<div class="finding-card" style="border:none;padding:0;margin:0">{header}</div>', unsafe_allow_html=True)

        sink_label = featured.sink_lines if featured else "?"
        with st.expander(f"Source snippet · {view.file_name} · sink {sink_label}", expanded=True):
            st.markdown(
                snippet_html(
                    view.snippet,
                    view.snippet_start_line,
                    view.highlight_lines,
                    view.highlight_spans,
                ),
                unsafe_allow_html=True,
            )
            st.caption("Line numbers on the left · **amber** = sink token · **blue** = dataflow step")

        if outcome is not None:
            label_text, label_cls = label_badge(outcome.predicted)
            status, detail = outcome_status(
                outcome.gold, outcome.predicted, acceptable_labels=outcome.acceptable_labels
            )
            st_cls = _status_class(status)
            conf = f" · {outcome.confidence}" if outcome.confidence else ""
            gold_text, gold_cls = gold_badge(view.gold)
            verdict = (
                f'<div class="verdict-row">'
                f'<span class="label-badge {label_cls}">AI: {html.escape(label_text)}{html.escape(conf)}</span>'
                f'<span class="{st_cls}">{html.escape(status)}</span>'
                f'<span class="finding-meta">{html.escape(detail)}</span>'
            )
            if show_eval_truth:
                verdict += f'<span class="badge {gold_cls}">Eval truth: {html.escape(gold_text)}</span>'
            verdict += "</div>"
            st.markdown(verdict, unsafe_allow_html=True)
            if outcome.reason:
                st.markdown(f"**Reasoning** — {outcome.reason}")
            if outcome.borderline_rationale:
                st.info(outcome.borderline_rationale)
        else:
            st.markdown(
                '<div class="verdict-row"><span class="badge badge-pending">Awaiting AI triage</span></div>',
                unsafe_allow_html=True,
            )

    st.markdown("<div style='margin-bottom:0.75rem'></div>", unsafe_allow_html=True)


def _score_bar(label: str, value: float | None, target: float, hits: int, n: int) -> None:
    st.markdown(f"**{label}** — {format_fraction(hits, n)} correct · gate ≥ {format_pct(target)}")
    if value is not None:
        pct = min(value / target, 1.0) if target else value
        st.progress(pct)
        st.markdown(f"### {format_pct(value)}")
    else:
        st.caption("No results")


def _render_metrics(outcomes: list[CaseOutcome], *, profile_label: str) -> None:
    vdr_t, fprr_t = _targets()
    m = compute_metrics(outcomes, vdr_target=vdr_t, fprr_target=fprr_t)
    cb = m["codeql_baseline"]
    tracks = m["tracks"]
    tp_tr = tracks["tp_track"]
    fp_tr = tracks["fp_track"]
    bl_tr = tracks.get("bl_track", {"acceptable": 0, "n": 0, "escalated": 0})

    st.markdown("### Aggregate metrics")
    strict = f"**{tracks['correct']}/{tracks['evaluated']}** strict (TP/FP exact match)"
    if bl_tr["n"]:
        strict += f" · **{tracks['lenient_correct']}/{tracks['evaluated']}** lenient (incl. borderline)"
    if m["gates_pass"]:
        st.success(f"{strict} — passes VDR/FPRR gates on TP+FP tracks")
    else:
        st.warning(f"{strict} — below VDR/FPRR gates on TP+FP tracks")

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        _score_bar("Threat detection (VDR)", m["vdr"], vdr_t, tp_tr["hits"], tp_tr["n"])
    with c2:
        _score_bar("Noise reduction (FPRR)", m["fprr"], fprr_t, fp_tr["hits"], fp_tr["n"])
    with c3:
        st.markdown("**Security score (SRS)**")
        if m["srs"] is not None:
            st.progress(min(m["srs"], 1.0))
            st.markdown(f"### {format_pct(m['srs'])}")
        else:
            st.caption("—")
    with c4:
        if bl_tr["n"]:
            st.markdown(
                f"**Borderline** — {format_fraction(bl_tr['acceptable'], bl_tr['n'])} acceptable"
            )
            if m.get("bl_handling") is not None:
                st.progress(m["bl_handling"])
                st.markdown(f"### {format_pct(m['bl_handling'])}")
        else:
            st.caption("No borderline cases")

    st.markdown("#### Summary table")
    st.dataframe(outcomes_table_rows(outcomes), use_container_width=True, hide_index=True)

    st.markdown("#### AI vs CodeQL-only")
    chart_df = pd.DataFrame(
        {
            "CodeQL": [cb["vdr"] or 0, cb["fprr"] or 0, cb["srs"] or 0],
            "AI triage": [m["vdr"] or 0, m["fprr"] or 0, m["srs"] or 0],
        },
        index=["VDR", "FPRR", "SRS"],
    )
    st.bar_chart(chart_df)
    st.caption(cb["note"])

    with st.expander("Technical metrics (TPR, FPR, precision, confusion matrix)"):
        t1, t2, t3, t4 = st.columns(4)
        t1.metric("TPR (recall)", format_pct(m["tpr"]))
        t2.metric("FPR", format_pct(m["fpr"]))
        t3.metric("Precision", format_pct(m["precision"]))
        t4.metric("TNR (specificity)", format_pct(m["tnr"]))
        cm = m["confusion"]
        st.markdown(
            f"""
|  | AI: Vuln (TP) | AI: Safe (FP) | Review |
| --- | ---: | ---: | ---: |
| **Actual vuln** | {cm['tp']} | {cm['fn']} | {cm['review_vuln']} |
| **Actual safe** | {cm['fp']} | {cm['tn']} | {cm['review_safe']} |
"""
        )


def _render_compare(compare_rows: list[dict]) -> None:
    st.markdown("### Model comparison (cached)")
    st.caption("Same CodeQL findings — side-by-side VDR/FPRR/SRS across models.")
    st.dataframe(compare_rows, use_container_width=True, hide_index=True)
    if compare_rows:
        chart_data = {
            row["Model"]: {
                "VDR": float(row["VDR"].rstrip("%")) / 100 if row["VDR"] != "—" else 0,
                "FPRR": float(row["FPRR"].rstrip("%")) / 100 if row["FPRR"] != "—" else 0,
                "SRS": float(row["SRS"].rstrip("%")) / 100 if row["SRS"] != "—" else 0,
            }
            for row in compare_rows
        }
        st.bar_chart(chart_data)


def main() -> None:
    _init_state()
    st.markdown(DEMO_CSS, unsafe_allow_html=True)

    manifest = load_manifest()
    models = list_models()
    model_ids = [m["id"] for m in models]
    default_profile = manifest.get("default_profile", model_ids[0])

    st.title("AI-Assisted SAST Triage")
    st.markdown(
        "Simulated **CI pipeline**: a git push triggers **CodeQL**, findings appear with "
        "source context, then an **LLM triage agent** labels each as **TP** (vuln), **FP** (noise), "
        "or **BL** (human review) — with **VDR**, **FPRR**, and **SRS** tracked on the pack."
    )

    with st.sidebar:
        st.header("Settings")
        st.session_state.commit_sha = st.text_input("Commit SHA", st.session_state.commit_sha)
        pack = st.selectbox(
            "Finding pack",
            options=list(manifest["packs"].keys()),
            format_func=lambda k: manifest["packs"][k]["label"],
        )
        run_mode = st.radio(
            "Run mode",
            ["Compare all models (cached)", "Single model · cached", "Single model · live"],
            help="Compare shows why 5.9B beats Coder-30B on FPs. Live uses Bedrock for Coder-30B.",
        )
        profile = st.selectbox(
            "Model",
            model_ids,
            index=model_ids.index(default_profile) if default_profile in model_ids else 0,
            format_func=lambda pid: next(m["label"] for m in models if m["id"] == pid),
            disabled=(run_mode == "Compare all models (cached)"),
        )
        meta = model_by_id(profile) or {}
        if meta.get("note"):
            st.caption(meta["note"])

        best = manifest.get("best_smoke_config", {})
        use_best_prompt = st.checkbox(
            "Best smoke prompt (recommended)",
            value=True,
            help=best.get("label", "v7-balanced + fs3"),
        )
        if use_best_prompt:
            prompt_version = best.get("prompt_version", "v7-balanced")
            fewshot = int(best.get("fewshot", manifest["default_fewshot"]))
            fs_config = best.get("few_shot_config", manifest["default_few_shot_config"])
            thinking = bool(best.get("thinking", True))
            st.caption(f"**{best.get('label', prompt_version)}**")
            if best.get("note"):
                st.caption(best["note"])
        else:
            prompt_version = st.selectbox("Prompt", ["v7-balanced", "v8-dual-gate", "v9-fprr-first"])
            fewshot = manifest["default_fewshot"]
            fs_config = manifest["default_few_shot_config"]
            thinking = st.checkbox("Chain-of-thought", value=True)

        repo_str = st.text_input(
            "BenchmarkJava path",
            value=str(Path(__file__).resolve().parent.parent.parent / "BenchmarkJava"),
        )
        show_eval_truth = st.checkbox(
            "Show eval ground truth",
            value=True,
            help="Reveal TP/FP/BL gold labels after triage (for benchmark demos).",
        )
        vdr_t, fprr_t = _targets()
        st.markdown("---")
        st.markdown(f"**Production gates:** VDR > {format_pct(vdr_t)}, FPRR ≥ {format_pct(fprr_t)}")

    entries = _load_pack_cases(pack)
    repo = Path(repo_str).expanduser() if repo_str.strip() else None
    model_label = meta.get("label", profile) if run_mode != "Compare all models (cached)" else "All models"
    backend = meta.get("backend", "local") if run_mode != "Compare all models (cached)" else "cached"

    phase = st.session_state.demo_phase
    if run_mode == "Compare all models (cached)" and st.session_state.compare_rows:
        phase = "compare"
    elif st.session_state.outcomes:
        phase = "done"

    _render_pipeline(
        phase=phase,
        sha=st.session_state.commit_sha,
        model_label=model_label,
        backend=backend,
    )

    views = build_finding_views(entries, repo)
    st.session_state.finding_views = views

    st.markdown("### CodeQL findings")
    categories = sorted({v.vuln_category for v in views})
    st.caption(
        f"**{len(views)}** findings from commit `{st.session_state.commit_sha[:7]}` — "
        f"categories: {', '.join(categories)}. Each card shows the featured CodeQL alert, "
        "dataflow, and a collapsible highlighted snippet."
    )

    outcomes_by_id = _outcome_map(st.session_state.outcomes)

    for view in views:
        _render_finding_card(
            view,
            outcomes_by_id.get(view.case_id),
            show_eval_truth=show_eval_truth and view.case_id in outcomes_by_id,
        )

    st.markdown("---")
    b1, b2, _ = st.columns([1, 1, 3])
    run_clicked = b1.button("Run AI triage", type="primary", use_container_width=True)
    if b2.button("Reset", use_container_width=True):
        st.session_state.outcomes = []
        st.session_state.compare_rows = []
        st.session_state.demo_phase = "codeql"
        st.rerun()

    if run_clicked:
        st.session_state._last_entries = entries
        st.session_state._last_repo = repo
        st.session_state.demo_phase = "triaging"
        fewshot_run = fewshot if use_best_prompt else manifest["default_fewshot"]
        fs_config_run = fs_config if use_best_prompt else manifest["default_few_shot_config"]
        with st.spinner("Running AI triage on CodeQL findings…"):
            if run_mode == "Compare all models (cached)":
                st.session_state.compare_rows = _run_compare(
                    entries, models=models, prompt_version=prompt_version, fewshot=fewshot_run
                )
                st.session_state.outcomes = []
                st.session_state.demo_phase = "compare"
            else:
                st.session_state.outcomes = _run_single(
                    entries,
                    profile=profile,
                    prompt_version=prompt_version,
                    fewshot=fewshot_run,
                    fs_config=fs_config_run,
                    thinking=thinking,
                    use_cached=(run_mode == "Single model · cached"),
                    repo=repo,
                )
                st.session_state.compare_rows = []
                st.session_state.demo_phase = "done"
        st.rerun()

    if st.session_state.compare_rows:
        st.markdown("---")
        _render_compare(st.session_state.compare_rows)

    if st.session_state.outcomes:
        st.markdown("---")
        _render_metrics(st.session_state.outcomes, profile_label=model_label)


if __name__ == "__main__":
    main()
