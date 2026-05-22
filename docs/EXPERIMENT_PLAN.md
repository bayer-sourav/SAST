# Experiment plan: SLM-based SAST triage (OWASP BenchmarkJava)

This plan turns the README “next steps” into a runnable study: **vanilla LLM triage** (primary), optional agents deprioritized, **CodeQL-only** inputs, **OWASP BenchmarkJava** gold labels, and the metrics **FPRR**, **VDR**, **SRS**, **F1**.

**Infrastructure already in place:** `benchmark/rq1_codeql_only/` (gold **FP**), `benchmark/tp_codeql_only/` (gold **TP**), `run_llm_local.py`, `run_batch.py`, `summarize_triage.py`, `run_comparison.sh`. Run on **GPU** (e.g. AWS `g6e` + Unsloth 4-bit); Mac dev is for smoke tests only (HF/MPS fallback).

---

## 1. Research questions

| ID | Question |
|----|----------|
| **RQ-FP** | How well do SLMs **remove false positives** from CodeQL alerts on OWASP Benchmark (RQ1-style corpus)? |
| **RQ-TP** | How much do SLMs **suppress true positives** when asked to retain vulnerabilities (TP-retention corpus)? |
| **RQ-Scale** | Do gains scale with model size (4B → 8B → 14B → 32B) and family (Qwen vs Gemma vs coder-specialized)? |
| **RQ-Prompt** | Do **few-shot** examples and **thinking** (chain-of-thought before JSON) change FPRR/VDR trade-offs? |
| **RQ-FT** | Does **fine-tuning** (no thinking in training) beat prompting alone at matched compute? |

**Out of scope for Phase 1:** OpenHands / multi-step agents (exploratory only in Phase 4).

---

## 2. Dataset and inputs

| Corpus | Path | Gold label | CodeQL | N (approx.) | Role |
|--------|------|------------|--------|-------------|------|
| **FP filter** | `benchmark/rq1_codeql_only/` | FP | Only `raw_output.CodeQL` | ~904 | Measure noise reduction |
| **TP retention** | `benchmark/tp_codeql_only/` | TP | CodeQL only | ~1373 | Measure over-suppression |

- **Source repo:** sibling `BenchmarkJava/` (auto-detected) or `--repo`.
- **SAST input:** CodeQL SARIF-derived case JSONs (not Semgrep/Joern/Sonar).
- **Slices for development:** fixed seeds, **N ∈ {45, 100, full}** per corpus; report all three when feasible.

**Stratified analysis (recommended):** join `case_id` → CWE via `SAST_paper_artifacts/Evaluation Framework/owasp_benchmark_cwe_mapping.json` for per-CWE tables (injection vs crypto vs cookie flags, per paper).

---

## 3. Systems under test

### 3.1 Baselines (required)

| System ID | Description | Implementation |
|-----------|-------------|----------------|
| **S0 – CodeQL** | No LLM filter; treat alert as kept (**TP** for metrics) | `summarize_triage.py` CodeQL row |
| **S1 – Vanilla SLM** | Single-shot triage, JSON output | `run_llm_local.py` + `--gold FP\|TP` |

### 3.2 Model matrix (Phase 2+)

| Family | Profiles / checkpoints | Sizes | Priority |
|--------|------------------------|-------|----------|
| **Qwen3** | `qwen3_4b_bnb`, `qwen3_8b_bnb`, `qwen3_14b_bnb` (+ 32B if VRAM allows) | 4B, 8B, 14B, 32B | P0 (in repo) |
| **Gemma** | `google_gemma_3_12b_it`, `google_gemma_2_9b_it`, `google_gemma_2_2b_it` | 2B–12B | P1 |
| **Qwen Coder** | Qwen2.5-Coder-7B / 14B (HF/Unsloth ids TBD) | 7B, 14B | P1 |
| **DeepSeek Coder** | DeepSeek-Coder-V2-Lite-Instruct (16B) | 16B | P2 |

**Rule:** one loaded model per GPU job; batch profiles sequentially (`run_comparison.sh` pattern).

### 3.3 Prompt / training factors (orthogonal)

| Factor | Levels | Notes |
|--------|--------|-------|
| **Few-shot** | 0, 1, 3, 5, 10 | Balanced **TP + FP** exemplars in system prompt; same JSON schema |
| **Thinking** | off, on | off = JSON only; on = allow reasoning then final JSON (or separate “thinking” field stripped before parse) |
| **Fine-tuning** | none, LoRA-SFT | Train on (CodeQL snippet + code + label); **no thinking tokens** in training targets |

---

## 4. Metrics (definitions)

Predictions: model `label ∈ {TP, FP, UNKNOWN}`. Gold: corpus gold **FP** or **TP**. Map **UNKNOWN** / missing JSON as **wrong** for “strict” and exclude for “coverage-adjusted” (match current `summarize_triage.py`).

### 4.1 On FP corpus (gold = FP)

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| **FPRR** (False Positive Removal Rate) | (# predicted **FP**) / (total cases with valid prediction) | Higher = more noise removed |
| **Over-call TP rate** | (# predicted **TP**) / total evaluated | Lower = fewer FPs mistaken as real vulns |
| **Precision (FP task)** | TP predictions that are wrong / all TP predictions | Same as error rate on FP corpus |
| **Coverage** | (# valid JSON) / N | Parse reliability |
| **F1 (FP task)** | Treat **FP** as positive class: P = correct FP labels / pred FP, R = correct FP / gold FP | Single scalar for FP-filtering quality |

### 4.2 On TP corpus (gold = TP)

| Metric | Formula | Interpretation |
|--------|---------|----------------|
| **VDR** (Vulnerability Detection / retention Rate) | (# predicted **TP**) / (total TP gold cases, valid pred) | **Your README definition:** correct TP / total TP; higher = less harm to real vulns |
| **False dismiss rate** | (# predicted **FP**) / total evaluated | Lower = safer for security |
| **F1 (TP task)** | Treat **TP** as positive class | Harmonic mean of precision/recall for retention |

### 4.3 Combined / operational

| Metric | Definition | Use |
|--------|------------|-----|
| **SRS** (SAST Reduction Score) | Weighted composite, e.g. `SRS = w·FPRR|_FP + (1−w)·VDR|_TP` with **w = 0.5** (report w) | One number for slides; **not** a replacement for separate FP/TP tables |
| **Cost** | wall-clock × GPU $/hr, or tokens/case | Compare 4B vs 8B vs agent (Phase 4) |

**Reporting:** always show **FP corpus and TP corpus separately**, then SRS. CodeQL baseline: **0% FPRR** on FP corpus, **100% VDR** on TP corpus.

---

## 5. Experimental design (phases)

### Phase 0 — Repro & smoke (1 week)

- [ ] Confirm corpora built (`build_codeql_cases.py`, `build_tp_codeql_cases.py`).
- [ ] Smoke: 1 FP + 1 TP case per profile on GPU.
- [ ] Pilot **N=45** per corpus × `qwen3_4b_bnb`, `qwen3_8b_bnb` → `run_comparison.sh` / `summarize_triage.py`.
- [ ] Deliverable: `runs/comparison_fp_45.json`, `runs/tp_retention/comparison_tp_45.json`.

### Phase 1 — Core SLM benchmark (2–3 weeks)

**Goal:** Answer RQ-FP and RQ-TP for vanilla Qwen without agents.

| Run | Corpus | Models | Prompt | N |
|-----|--------|--------|--------|---|
| 1.1 | FP | 4B, 8B | zero-shot, no thinking | 45 → 100 → full |
| 1.2 | TP | 4B, 8B | zero-shot, no thinking | 45 → 100 → full |

- [ ] Per-CWE breakdown script (join mapping JSON).
- [ ] Table: FPRR, VDR, F1, coverage, SRS (w=0.5).
- [ ] Error analysis: 20 misclassified cases per model (qualitative tags).

### Phase 2 — Model scale & families (2–3 weeks)

- [ ] Add **14B** (and **32B** only if 48GB+ VRAM stable).
- [ ] Add **Gemma** + **Qwen Coder** + **DeepSeek Coder** at matched “best effort” sizes.
- [ ] Same corpora, **N=100** minimum for cross-model comparison.
- [ ] Hypothesis: FPRR rises with size on FP corpus; VDR non-decreasing on TP corpus; coder models ↑ FPRR on injection CWEs.

### Phase 3 — Prompting ablations (2 weeks)

Fixed model: **best cost/perf from Phase 1** (likely 8B) + runner-up 4B.

| Run | Few-shot k | Thinking |
|-----|------------|----------|
| 3.1 | 0 | off |
| 3.2 | 1, 3, 5, 10 | off |
| 3.3 | 0 | on |
| 3.4 | best k from 3.2 | on |

- [ ] Few-shot pool: frozen set of exemplars (document case IDs in `benchmark/few_shot_examples.json`).
- [ ] Measure **latency + token length** vs FPRR/VDR.

### Phase 4 — Fine-tuning (3–4 weeks, optional)

- [ ] Train LoRA on mixed FP+TP CodeQL cases (chat template, **JSON label only**, no thinking).
- [ ] Hold-out: 10% case IDs stratified by CWE.
- [ ] Compare **S1 zero-shot 8B** vs **S1-FT** on full hold-out; same metrics.
- [ ] Agents (OpenHands + local server): **≤20 cases** only if vanilla plateaus and stakeholder needs tool-use narrative.

---

## 6. Run matrix (minimal publishable set)

If time is limited, run **only** these cells:

| # | Corpus | Model | Few-shot | Thinking | N |
|---|--------|-------|----------|----------|---|
| A | FP | Qwen3-4B | 0 | off | 100 |
| B | FP | Qwen3-8B | 0 | off | 100 |
| C | TP | Qwen3-4B | 0 | off | 100 |
| D | TP | Qwen3-8B | 0 | off | 100 |
| E | FP | Qwen3-8B | 5 | off | 100 |
| F | TP | Qwen3-8B | 5 | off | 100 |
| G | FP | Qwen3-8B | 5 | on | 100 |
| H | TP | Qwen3-8B | 5 | on | 100 |

Full scale + extra families = Phase 2 extension.

---

## 7. Execution checklist (commands)

From `SAST` root on GPU host:

```bash
uv sync

# Corpora
uv run python benchmark/build_codeql_cases.py
uv run python benchmark/build_tp_codeql_cases.py

# Example: FP corpus, 45 cases, both Qwen sizes
./benchmark/run_comparison.sh 45 benchmark/rq1_codeql_only FP runs

# TP corpus
./benchmark/run_comparison.sh 45 benchmark/tp_codeql_only TP runs/tp_retention

# Metrics JSON
uv run python benchmark/summarize_triage.py \
  --case-dir benchmark/rq1_codeql_only --max-cases 45 --gold FP --runs runs \
  --json-out runs/comparison_fp_45.json
```

**Record per run:** git commit, `profile`, `AGENT_*` env, GPU type, date, `comparison_*.json`.

---

## 8. Outputs & success criteria

| Deliverable | Content |
|-------------|---------|
| **Results tables** | FPRR (FP), VDR (TP), F1, coverage, SRS; rows = system × model |
| **CWE heatmaps** | FPRR/VDR by CWE category |
| **Case study doc** | 5 FP successes, 5 FP failures, 5 TP false dismissals |
| **Recommendation** | Minimum model size for “acceptable” VDR (e.g. VDR ≥ 90%) while FPRR ≥ X% |

**Suggested acceptance (tune with stakeholders):**

- On **FP** corpus: FPRR ≥ 70% at VDR ≥ 90% on TP corpus (8B zero-shot).
- Beat **4B** with **8B** on FPRR without VDR drop > 5 points.
- Few-shot **+5–10 pt** FPRR at ≤2 pt VDR drop vs zero-shot.

---

## 9. Risks & mitigations

| Risk | Mitigation |
|------|------------|
| JSON parse failures | `repair_llm_results.py`; raise `AGENT_MAX_NEW_TOKENS` |
| TP corpus over-suppression | TP-specific prompt (`--gold TP`); report VDR prominently |
| Mac / no CUDA | EC2 g6e for all scored runs |
| Full 904+1373 runtime | Staged N; tmux; `--retry-missing` |
| Metric confusion | Never merge FP and TP corpora into one accuracy number |

---

## 10. Timeline (indicative)

| Phase | Duration | Milestone |
|-------|----------|-----------|
| 0 | Week 1 | N=45 tables reproducible |
| 1 | Weeks 2–4 | 4B/8B full metrics + CWE breakdown |
| 2 | Weeks 5–7 | Multi-family comparison |
| 3 | Weeks 8–9 | Few-shot + thinking ablation |
| 4 | Weeks 10–13 | Fine-tuning + optional agent pilot |

---

## 11. Not yet implemented (backlog)

- [ ] `benchmark/few_shot_examples.json` + `--few-shot k` in `run_llm_local.py`
- [ ] `--thinking` prompt flag
- [ ] `summarize_triage.py`: explicit **FPRR**, **VDR**, **SRS**, **F1** column names (aliases for current Acc/TP/FP)
- [ ] Per-CWE aggregation script
- [ ] Fine-tuning pipeline (LoRA dataset export from case JSONs)

Link this plan from the root README “next steps” section when stable.
