# SAST false-positive filtering — experiment summary (tabular)

**Project:** Use small language models (SLMs) to triage CodeQL alerts — reduce review noise without dropping real vulnerabilities.

**Reference:** [arxiv:2601.22952](https://arxiv.org/pdf/2601.22952v1) · **Technical plan:** [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md) · **How to run:** [benchmark/README.md](../benchmark/README.md)

**Word (for managers):** [EXPERIMENT_PLAN_SUMMARY.docx](EXPERIMENT_PLAN_SUMMARY.docx) — regenerate with `python docs/build_experiment_docx.py`

---

## Overview

| Field | Value |
|-------|--------|
| **Problem** | CodeQL produces many false positives; manual triage is costly |
| **Solution** | Local SLM reads alert + code → **keep (TP)** or **dismiss (FP)** |
| **Benchmark** | OWASP BenchmarkJava |
| **SAST input** | CodeQL only |
| **Phase 1 models** | Qwen3 4B, 8B (GPU) |
| **Phase 1 scope** | Vanilla prompting; **no** agent frameworks |
| **Infrastructure** | AWS GPU (e.g. L40S); scripts in `benchmark/` |

---

## Evaluation tracks

| Track | Corpus | Gold label | What “good” means |
|-------|--------|------------|-------------------|
| **False-positive removal** | `benchmark/rq1_codeql_only` | Alert is **not** a real bug | Model labels **FP** (dismiss) |
| **True-positive retention** | `benchmark/tp_codeql_only` | Alert **is** a real bug | Model labels **TP** (keep) |

---

## Metrics

| Metric | Definition (plain) | Measured on |
|--------|-------------------|-------------|
| **FPRR** | % of false alerts correctly dismissed | FP track |
| **VDR** | % of real vulnerabilities still kept after triage | TP track |
| **F1** | Balance of correct keep/dismiss vs mistakes | Both tracks |
| **SRS** | Combined score (FPRR + VDR, equal weight) | Both tracks |

| Baseline / target | FPRR (FP track) | VDR (TP track) |
|-------------------|-----------------|---------------|
| **CodeQL (no AI)** | 0% | 100% |
| **Draft target** | ≥ 70% | ≥ 90% |

---

## Phased plan

| Phase | Timing | Models / methods | Dataset size (per track) | Outcome |
|-------|--------|------------------|--------------------------|---------|
| **1 — Baseline** | Now | Qwen3 4B, 8B; zero-shot | ~100 → full | CodeQL vs SLM tables |
| **2 — Scale** | Next | +14B/32B, Gemma, Qwen/DeepSeek Coder | ~100+ | Size & family comparison |
| **3 — Prompting** | Next | Few-shot (1, 3, 5, 10); thinking on/off | ~100 | Best prompt recipe |
| **4 — Training** | Later | LoRA fine-tune (no thinking in train) | Hold-out 10% | vs prompting-only |

---

## Phase 1 run matrix (minimum)

| Run ID | Corpus | Model | Few-shot | Thinking | Cases (target) |
|--------|--------|-------|----------|----------|----------------|
| R1 | FP | Qwen3-4B | 0 | Off | 100 |
| R2 | FP | Qwen3-8B | 0 | Off | 100 |
| R3 | TP | Qwen3-4B | 0 | Off | 100 |
| R4 | TP | Qwen3-8B | 0 | Off | 100 |
| — | Both | CodeQL | — | — | Same N (baseline) |

---

## Systems compared (results table template)

| System | FPRR (FP track) | VDR (TP track) | F1 (FP) | F1 (TP) | SRS | Notes |
|--------|-----------------|----------------|---------|---------|-----|-------|
| CodeQL (no filter) | 0% | 100% | — | — | — | Baseline |
| Qwen3-4B | *TBD* | *TBD* | *TBD* | *TBD* | *TBD* | Phase 1 |
| Qwen3-8B | *TBD* | *TBD* | *TBD* | *TBD* | *TBD* | Phase 1 |

---

## Out of scope (phase 1)

| Item | Status |
|------|--------|
| OpenHands / multi-step agents | Optional later |
| Semgrep, Joern, SonarQube inputs | Excluded |
| Real Bayer repos / Node.js prod data | Future phase |
