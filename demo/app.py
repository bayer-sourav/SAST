#!/usr/bin/env python3
"""
Live SAST triage demo — Git → CodeQL → AI triage → metrics.

Run: ./demo/run_demo.sh
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pandas as pd

from demo.bootstrap import ensure_import_paths

ensure_import_paths()

import streamlit as st

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
    codeql_alert_count,
    codeql_rules,
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


def _init_state() -> None:
    defaults = {
        "outcomes": [],
        "compare_rows": [],
        "commit_sha": "a1b2c3d",
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
    progress = st.progress(0, text="Starting…")
    rows: list[dict] = []

    if use_cached:
        cached = load_cached_outcomes(
            entries, profile=profile, prompt_version=prompt_version, fewshot=fewshot
        )
        rows = cached
        progress.progress(1.0, text="Loaded from cache")
    else:
        configure_backend(profile)
        for i, entry in enumerate(entries):
            cid = entry["case_id"]
            progress.progress(i / len(entries), text=f"{profile}: {cid} ({i + 1}/{len(entries)})")
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
        progress.progress(1.0, text="Done")

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


def _render_pipeline(model_label: str, backend: str) -> None:
    sha = st.session_state.commit_sha[:7]
    st.markdown("### Pipeline")
    cols = st.columns(4)
    steps = [
        ("1 · Git push", f"main @ {sha}"),
        ("2 · CodeQL", "GitHub CodeQL Action → SARIF"),
        ("3 · AI triage", f"{model_label} ({backend})"),
        ("4 · Metrics", "VDR · FPRR · gates"),
    ]
    for col, (title, body) in zip(cols, steps):
        with col:
            st.markdown(f"**{title}**")
            st.caption(body)


def _render_codeql_table(entries: list[dict]) -> None:
    rows = []
    for e in entries:
        try:
            _, case = load_case_entry(e)
            rel = case.get("file", "?")
            rows.append(
                {
                    "Finding": e["case_id"],
                    "File": rel.split("/")[-1] if rel else "?",
                    "Rule": ", ".join(codeql_rules(case)[:2]),
                    "Alerts": codeql_alert_count(case),
                    "Truth": e["gold"],
                    "Summary": e.get("title", ""),
                }
            )
        except FileNotFoundError:
            rows.append({"Finding": e["case_id"], "File": "?", "Rule": "?", "Alerts": 0, "Truth": e["gold"], "Summary": "missing"})
    st.dataframe(rows, use_container_width=True, hide_index=True)


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

    st.markdown(f"### Results · {profile_label}")
    strict = f"**{tracks['correct']}/{tracks['evaluated']}** strict (TP/FP exact match)"
    if bl_tr["n"]:
        strict += f" · **{tracks['lenient_correct']}/{tracks['evaluated']}** lenient (incl. acceptable borderline)"
    if m["gates_pass"]:
        st.success(f"{strict} — passes VDR/FPRR gates on TP+FP tracks")
    else:
        st.warning(f"{strict} — below VDR/FPRR gates on TP+FP tracks")

    c1, c2, c3 = st.columns(3)
    with c1:
        _score_bar("Threat detection (VDR)", m["vdr"], vdr_t, tp_tr["hits"], tp_tr["n"])
    with c2:
        _score_bar("Noise reduction (FPRR)", m["fprr"], fprr_t, fp_tr["hits"], fp_tr["n"])
    with c3:
        if bl_tr["n"]:
            st.markdown(
                f"**Borderline handling** — {format_fraction(bl_tr['acceptable'], bl_tr['n'])} acceptable "
                f"({bl_tr['escalated']} escalated as BL)"
            )
            if m.get("bl_handling") is not None:
                st.progress(m["bl_handling"])
                st.markdown(f"### {format_pct(m['bl_handling'])}")
            st.caption("TP or FP defensible, or explicit BL — models often disagree")
        else:
            st.caption("No borderline cases in this pack")

    st.markdown("#### Per-finding results")
    st.dataframe(outcomes_table_rows(outcomes), use_container_width=True, hide_index=True)

    st.markdown("#### AI vs CodeQL-only")
    comp = {
        "System": ["CodeQL (no filter)", profile_label],
        "VDR": [format_pct(cb["vdr"]), format_pct(m["vdr"])],
        "FPRR": [format_pct(cb["fprr"]), format_pct(m["fprr"])],
        "SRS": [format_pct(cb["srs"]), format_pct(m["srs"])],
    }
    chart_df = pd.DataFrame(
        {
            "CodeQL": [cb["vdr"] or 0, cb["fprr"] or 0],
            "AI triage": [m["vdr"] or 0, m["fprr"] or 0],
        },
        index=["VDR", "FPRR"],
    )
    st.bar_chart(chart_df)
    st.dataframe(comp, use_container_width=True, hide_index=True)
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

    st.markdown("#### Reasoning & source")
    for o in outcomes:
        status, _ = outcome_status(o.gold, o.predicted, acceptable_labels=o.acceptable_labels)
        with st.expander(f"{status} · {o.case_id} → {o.predicted or '?'} (truth {o.gold})"):
            st.write(o.title)
            if o.borderline_rationale:
                st.info(o.borderline_rationale)
            if o.reason:
                st.write(o.reason)
            try:
                entry = next(e for e in st.session_state.get("_last_entries", []) if e["case_id"] == o.case_id)
                case_path, case = load_case_entry(entry)
                repo = st.session_state.get("_last_repo")
                st.code(
                    (resolve_repo(case_path, case, repo) / case["file"]).read_text(encoding="utf-8", errors="replace")[:2500],
                    language="java",
                )
            except Exception:
                pass


def _render_compare(compare_rows: list[dict]) -> None:
    st.markdown("### Model comparison (cached)")
    st.caption("Side-by-side on the same CodeQL findings — highlights FPRR gap on Coder-30B vs 5.9B.")
    st.dataframe(compare_rows, use_container_width=True, hide_index=True)
    if compare_rows:
        chart_data = {
            row["Model"]: {
                "VDR": float(row["VDR"].rstrip("%")) / 100 if row["VDR"] != "—" else 0,
                "FPRR": float(row["FPRR"].rstrip("%")) / 100 if row["FPRR"] != "—" else 0,
            }
            for row in compare_rows
        }
        st.bar_chart(chart_data)


def main() -> None:
    _init_state()
    manifest = load_manifest()
    models = list_models()
    model_ids = [m["id"] for m in models]
    default_profile = manifest.get("default_profile", model_ids[0])

    st.title("AI-Assisted SAST Triage")
    st.markdown(
        "CodeQL findings from a **git commit** are reviewed by an **LLM** before they reach "
        "your security team — with **VDR** (keep real vulns) and **FPRR** (drop noise) tracked explicitly."
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
            help="Compare shows why 5.9B beats Coder-30B on FPs. Live uses Bedrock for Coder-30B, GPU for others.",
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
        vdr_t, fprr_t = _targets()
        st.markdown("---")
        st.markdown(f"**Production gates:** VDR > {format_pct(vdr_t)}, FPRR ≥ {format_pct(fprr_t)}")

    entries = _load_pack_cases(pack)
    repo = Path(repo_str).expanduser() if repo_str.strip() else None
    model_label = meta.get("label", profile)
    backend = meta.get("backend", "local")

    _render_pipeline(model_label if run_mode != "Compare all models (cached)" else "All models", backend)

    st.markdown("---")
    st.markdown("### CodeQL findings (from commit scan)")
    _render_codeql_table(entries)

    st.markdown("---")
    b1, b2, _ = st.columns([1, 1, 3])
    run_clicked = b1.button("Run", type="primary", use_container_width=True)
    if b2.button("Clear", use_container_width=True):
        st.session_state.outcomes = []
        st.session_state.compare_rows = []
        st.rerun()

    if run_clicked:
        st.session_state._last_entries = entries
        st.session_state._last_repo = repo
        fewshot = manifest["default_fewshot"]
        fs_config = manifest["default_few_shot_config"]
        with st.spinner("Running…"):
            if run_mode == "Compare all models (cached)":
                st.session_state.compare_rows = _run_compare(
                    entries, models=models, prompt_version=prompt_version, fewshot=fewshot
                )
                st.session_state.outcomes = []
            else:
                st.session_state.outcomes = _run_single(
                    entries,
                    profile=profile,
                    prompt_version=prompt_version,
                    fewshot=fewshot,
                    fs_config=fs_config,
                    thinking=thinking,
                    use_cached=(run_mode == "Single model · cached"),
                    repo=repo,
                )
                st.session_state.compare_rows = []

    if st.session_state.compare_rows:
        st.markdown("---")
        _render_compare(st.session_state.compare_rows)

    if st.session_state.outcomes:
        st.markdown("---")
        _render_metrics(st.session_state.outcomes, profile_label=model_label)


if __name__ == "__main__":
    main()
