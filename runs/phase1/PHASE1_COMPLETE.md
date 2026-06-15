# Phase 1 — Complete Record and Closure

**Status:** Closed  
**Closure date:** June 2026  
**Runbook (Stage 1 + Stage 2 ops):** [benchmark/PHASE1.md](../../benchmark/PHASE1.md)  
**Next phase:** Prompting ablation and scale-up — see [Phase 2 closure](../phase2/PHASE2_COMPLETE.md)

This document closes Phase 1: vanilla zero-shot SLM triage on OWASP BenchmarkJava CodeQL alerts at slice scale (Stage 1) and full-corpus scale with a borderline track (Stage 2). Operational details remain in the runbook and README; this file is the single narrative record from planning through results and handoff to Phase 2.

---

## 1. Phase 1 timeline

| Stage | Goal | Corpus | Models | Thinking | Labels |
|-------|------|--------|--------|----------|--------|
| **Stage 1** | Baseline SLM triage matrix | **50 FP + 50 TP** (seed 42) | 4B, 8B, 14B, GPT-OSS, Coder-30B* | off + on | **3-label** (track-specific prompts: TP \| FP \| UNKNOWN) |
| **Stage 2** | Scale to full CodeQL corpora + borderline | **904 FP + 1,373 TP + 200 BL** | 4B, 8B, 14B only | **off only** | **4-label** unified (`make_task.py`: TP \| FP \| BL \| UNKNOWN) |

\* Coder-30B skipped on this host (`phase1_logs/phase1_skip_coder.txt`); 0% coverage in Stage 1 summaries.

---

## 2. Task and metrics

### 2.1 Research questions (Phase 1)

From [docs/EXPERIMENT_PLAN.md](../../docs/EXPERIMENT_PLAN.md):

- **RQ-FP:** Can SLMs dismiss CodeQL false positives?
- **RQ-TP:** Do SLMs suppress true vulnerabilities when asked to retain them?
- **RQ-Scale / RQ-Prompt:** Initial probes at 4B–14B, zero-shot, thinking off vs on.

Phase 1 did **not** include few-shot exemplars, multi-alert unified prompting (v7), or fine-tuning.

### 2.2 Metrics

| Metric | Definition |
|--------|------------|
| **FPRR** | On FP-gold cases: fraction predicted **FP** |
| **VDR** | On TP-gold cases: fraction predicted **TP** |
| **SRS** | 0.5 × FPRR + 0.5 × VDR |
| **F1** | 0.5 × F1-FP-track + 0.5 × F1-TP-track |
| **Coverage** | Valid JSON / N |

**Borderline track (Stage 2 only):** label distribution, lenient accuracy (TP or FP acceptable), benchmark agreement, ambiguity index — see Stage 2 §4.

### 2.3 Important label/schema caveats

| Stage | Prompt | Do not mix with |
|-------|--------|-----------------|
| Stage 1 | Separate FP-track and TP-track prompts; **no BL label** | Stage 2+ 4-label metrics |
| Stage 2 | Unified `make_task.py`; model may output **BL** | Stage 1 3-label runs |

Artifacts under `FP-runs/phase1_n50/` and `TP-runs/phase1_n50/` are **frozen**; Phase 2+ uses `runs/phase2/` and the `SAST-Benchmark-Dataset` held-out test split.

---

## 3. Stage 1 — N=50 baseline matrix

### 3.1 Design

| Dimension | Value |
|-----------|--------|
| Cases | 50 FP + 50 TP (CWE-balanced, seed **42**) |
| Profiles | `qwen3_4b_bnb`, `qwen3_8b_bnb`, `qwen3_14b_bnb`, `gpt_oss_20b`, `qwen3_coder_30b_bnb` |
| Few-shot | 0 (zero-shot) |
| Thinking | off and on |
| Excluded | `google_gemma_3_12b_it` (too slow on L40S) |

Manifest: `benchmark/phase1_manifest.json`  
Orchestrator: `benchmark/run_phase1_matrix.sh`

### 3.2 Results — thinking **off** (reference)

Source: `benchmark/phase1_combined_summary.json` (non-coder profiles with valid runs)

| Profile | FPRR | VDR | SRS | F1 | Notes |
|---------|------|-----|-----|-----|-------|
| qwen3_8b_bnb | **100%** | **100%** | **100%** | **100%** | Best on N=50 slice |
| qwen3_14b_bnb | 100% | 80% | 90% | 90% | Strong FPRR; moderate VDR |
| qwen3_4b_bnb | 100% | 62% | 81% | 81% | High FPRR; VDR gap |
| gpt_oss_20b | 58% | 92% | 75% | 75% | Recall-biased; weak FP removal |
| qwen3_coder_30b_bnb | — | — | — | — | Not run (skipped) |

### 3.3 Results — thinking **on** (selected)

| Profile | FPRR | VDR | SRS | Δ vs off |
|---------|------|-----|-----|----------|
| qwen3_8b_bnb | 72% | 80% | **76%** | **−24 pp SRS** |
| qwen3_4b_bnb | 100% | 62% | 81% | unchanged |
| qwen3_14b_bnb | 100% | 80% | 90% | unchanged |
| gpt_oss_20b | 58% | 92% | 75% | unchanged (thinking_on synced from off; GPT-OSS does not use Qwen CoT) |

### 3.4 Stage 1 findings

1. **Qwen3-8B + thinking off** looked optimal on the small slice (100% SRS) — later shown **not to generalize** at full corpus scale (Stage 2).
2. **Thinking on hurt 8B** on the slice (100% → 76% SRS): over-reasoning shifted labels toward conservative dismissal/retention errors.
3. **Initial default:** thinking **off** for cost and stability on zero-shot triage.
4. **GPT-OSS:** opposite bias to Qwen — good VDR, poor FPRR; not carried forward.
5. **Coder-30B:** deferred due to GPU/load issues on 44GB L40S.
6. **N=50 is a development slice only** — high variance; Phase 2 introduced a separate 20-case hard slice and 600-case held-out test.

---

## 4. Stage 2 — full corpora + borderline

### 4.1 Design

| Dimension | Value |
|-----------|--------|
| FP track | 904 cases — `benchmark/corpora/fp_codeql/` |
| TP track | 1,373 cases — `benchmark/corpora/tp_codeql/` |
| Borderline | 200 cases — `benchmark/corpora/borderline_n200_seed42/` (strict heuristic, seed 42) |
| Models | 4B, 8B, 14B only |
| Excluded | GPT-OSS (poor FPRR on slice), Coder-30B (deferred) |
| Thinking | **off only** (Option A from plan — half GPU cost vs off+on) |
| Prompt | Unified zero-shot via `make_task.py` (4-label schema) |

Manifest: `benchmark/phases/phase1/stage2/MANIFEST.json`  
Plan: `benchmark/phases/phase1/stage2/PLAN.md`  
Orchestrator: `benchmark/phases/phase1/stage2/run_phase1_stage2.sh`  
Outputs: `runs/phase1/stage2/{fp,tp,bl}/thinking_off/<profile>/llm/<case_id>/`

**Case runs:** 2,477 per model × 3 models ≈ **7,431** total (thinking off).

### 4.2 FP / TP results — thinking off

Source: `runs/phase1/stage2/summaries/phase1_stage2_matrix_thinking_off.json`

| Profile | FPRR | VDR | SRS | FP cov | TP cov |
|---------|------|-----|-----|--------|--------|
| qwen3_4b_bnb | 90.9% | **41.7%** | **66.3%** | 100% | 100% |
| qwen3_8b_bnb | 94.5% | 25.0% | 59.7% | 99.8% | 99.7% |
| qwen3_14b_bnb | **98.8%** | 23.0% | 60.9% | 100% | 100% |

**Pattern:** All profiles are **FPRR-heavy and VDR-poor** at full scale — the opposite of the CodeQL baseline (0% FPRR, 100% VDR). Models aggressively label alerts FP, including most gold-TP cases. Larger models on this setup increase FPRR slightly but **do not** fix TP retention.

**Slice vs scale (8B):** N=50 thinking off → **100% SRS**; full corpus → **59.7% SRS** — the main motivation for Phase 2's larger held-out test and prompt work.

### 4.3 Borderline track (N=200)

| Profile | Pred TP% | Pred FP% | Pred BL% | Lenient acc | Benchmark agree |
|---------|----------|----------|----------|-------------|-----------------|
| qwen3_4b_bnb | 58% | 42% | 0% | 100% | 78.5% |
| qwen3_8b_bnb | 25% | 73% | 2% | 98% | 58.0% |
| qwen3_14b_bnb | 28.5% | 71.5% | 0% | 100% | 65.0% |

Models **rarely assign BL** (0–2% on borderline gold). They collapse ambiguous cases toward TP or FP — same pattern observed later in Phase 2 Stage 2.

### 4.4 Gaps and data quality

Some cases missing valid JSON (mostly 8B FP/TP, scattered 4B TP). Log: `runs/phase1/stage2/logs/missing_cases.json`.  
Remediation scripts: `finish_gaps.py`, `repair_llm_results.py`, `rerun_bad_cases.py`.

Metrics above use **evaluated cases only** (standard `summarize_triage.py` behavior).

---

## 5. Excluded and deferred work

| Item | Reason | Phase 1 outcome |
|------|--------|-----------------|
| `google_gemma_3_12b_it` | ~25+ min/case on L40S | Never in matrix |
| `qwen3_coder_30b_bnb` | GPU / load on 44GB | Skipped Stage 1; excluded Stage 2 |
| `gpt_oss_20b` | 58% FPRR on slice | Excluded from Stage 2 full run |
| Thinking **on** at full scale | Cost (~2× cells); hurt 8B on slice | Deferred; revisited in Phase 2 |
| Few-shot / CoT prompting | Out of Phase 1 scope | Phase 2 |
| LoRA fine-tuning | Out of Phase 1 scope | Phase 3 |

---

## 6. Phase 1 conclusions

1. **Vanilla zero-shot SLM triage works for FP removal** (≈91–99% FPRR on full FP corpus) but **fails TP retention** (≈23–42% VDR) with the Phase 1 unified prompt — unusable as a security filter without recall improvements.
2. **Small slices mislead:** 8B at 100% SRS (N=50) dropped to 60% SRS at full scale; always validate on held-out full or near-full corpora.
3. **Thinking off was the Phase 1 default**, but Phase 2 later showed **thinking on is required** once few-shot and v7 multi-alert prompting were introduced (different prompt regime — not a contradiction).
4. **Borderline track and BL label** were added in Stage 2; models under-use BL — metric and prompt design carried into Phase 2.
5. **Repo structure established:** `benchmark/corpora/`, `benchmark/phases/`, `runs/phase1/stage2/` layout reused in Phase 2.
6. **Phase 2 was the natural next step:** Qwen3.5 models, few-shot exemplars, chain-of-thought, multi-alert prompt engineering, and `SAST-Benchmark-Dataset` train/test discipline.

---

## 7. Handoff to Phase 2

Phase 2 addressed Phase 1 gaps deliberately:

| Phase 1 limitation | Phase 2 response |
|--------------------|------------------|
| Zero-shot only | Few-shot configs (`v2_3shot_tp_2fp`, etc.) |
| Weak VDR at scale | v3→v7 prompts, per-alert assessment, resolved-sink reasoning |
| Thinking off default | Thinking **on** for production config (with fs3) |
| Ad hoc full corpora (904/1373) | **SAST-Benchmark-Dataset** 200+200+200 **test** split + train exemplars |
| 4B–14B only | + Qwen3.5-4B/9B, Coder-30B (Bedrock), Gemma probe |
| No publication closure | Phase 2 → [PHASE2_COMPLETE.md](../phase2/PHASE2_COMPLETE.md), [PUBLICATION_REPORT.md](../phase2/stage2/PUBLICATION_REPORT.md) |

**Phase 2 ship config** (baseline for Phase 3 SFT): Qwen3.5-9B · v7-balanced · think ON · fs3 → **83.0% SRS** (92.5% VDR, 73.5% FPRR) on 600-case test.

---

## 8. Artifact index

| Artifact | Path |
|----------|------|
| **This closure doc** | `runs/phase1/PHASE1_COMPLETE.md` |
| Stage 1 runbook | `benchmark/PHASE1.md` |
| Stage 1 manifest | `benchmark/phase1_manifest.json` |
| Stage 1 combined metrics | `benchmark/phase1_combined_summary.json` |
| Stage 1 timing | `benchmark/phase1_timing_report.json` |
| Stage 1 per-case runs (FP) | `FP-runs/phase1_n50/thinking_{off,on}/<profile>/llm/` |
| Stage 1 per-case runs (TP) | `TP-runs/phase1_n50/thinking_{off,on}/<profile>/llm/` |
| Stage 1 matrix JSON | `FP-runs/phase1_n50/phase1_matrix_thinking_{off,on}.json` |
| Stage 2 plan | `benchmark/phases/phase1/stage2/PLAN.md` |
| Stage 2 manifest | `benchmark/phases/phase1/stage2/MANIFEST.json` |
| Stage 2 matrix summary | `runs/phase1/stage2/summaries/phase1_stage2_matrix_thinking_off.json` |
| Stage 2 per-track JSON | `runs/phase1/stage2/summaries/comparison_{fp,tp,bl}_*.json` |
| Stage 2 timing | `benchmark/phase1_stage2_timing_report.json` |
| Stage 2 missing cases | `runs/phase1/stage2/logs/missing_cases.json` |
| Borderline corpus manifest | `benchmark/corpora/borderline_n200_seed42_manifest.json` |
| Metrics explanation + Stage 1 table | `benchmark/README.md` (Phase 1 section) |
| Original study plan | `docs/EXPERIMENT_PLAN.md`, `docs/EXPERIMENT_PLAN_SUMMARY.md` |
| Phase 2 closure | `runs/phase2/PHASE2_COMPLETE.md` |

---

*Phase 1 closed after Stage 2 full-corpus runs. Raw outputs under `FP-runs/phase1_n50/`, `TP-runs/phase1_n50/`, and `runs/phase1/stage2/`.*
