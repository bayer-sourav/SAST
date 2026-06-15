# Phase 2 — Complete Record and Closure

**Status:** Closed (prompting-only path exhausted)  
**Closure date:** June 2026  
**Primary report:** [stage2/PUBLICATION_REPORT.md](stage2/PUBLICATION_REPORT.md)  
**Next phase:** LoRA SFT on Qwen3.5-9B (see [Phase 3 plan](#phase-3-handoff) below)

This document closes Phase 2 by recording everything after Stage 2 full-corpus validation: Stage 3 prompt sweeps, lang-agnostic probing, and large-model smokes. Stage 1–2 design, smoke tuning, and publication-ready analysis remain in the linked reports.

---

## 1. Phase 2 timeline

| Stage | Goal | Corpus | Outcome |
|-------|------|--------|---------|
| **Smoke / tuning** | Prompt (v3→v7), few-shot layout, think on/off | 20-case hard slice | Ship config selected — see [SMOKE_ARCHIVE.md](stage2/SMOKE_ARCHIVE.md) |
| **Stage 1** | Full model × think × fs matrix | 600/cell (200 FP + 200 TP + 200 BL) | Best fs3 5.9b: **89.8% SRS** (pre-v7-final era) — [PHASE2_REPORT.md](summaries/PHASE2_REPORT.md) |
| **Stage 2** | Validate v7-balanced on best cells | 600/cell | **Ship config: 83.0% SRS** — [PUBLICATION_REPORT.md](stage2/PUBLICATION_REPORT.md) |
| **Stage 3** | Push VDR ≥ 95% and FPRR ≥ 90% via v8/v9 prompts | Hard slice smoke only | **No cell beat Stage 2; full corpus skipped** |
| **Post-Stage-2 probes** | Lang-agnostic v7; larger Qwen models | Hard slice smoke only | **Rejected** — 5.9B + Java v7 remains baseline |

---

## 2. Ship configuration (Phase 2 baseline to beat)

| Setting | Value |
|---------|--------|
| Model | `qwen3_5_9b_bnb` (`unsloth/Qwen3.5-9B`, 4-bit) |
| Prompt | `v7-balanced` → tag `unified-4label-v7-balanced` |
| Thinking | ON |
| Few-shot | 3, config `v2_3shot_tp_2fp` |
| Exemplars (train split) | `BenchmarkTest02272` (TP), `BenchmarkTest00200` (FP), `BenchmarkTest00340` (FP) |

**Full test corpus (Stage 2, 600 cases):**

| Metric | Value |
|--------|-------|
| FPRR (FP track) | **73.5%** |
| VDR (TP track) | **92.5%** |
| SRS | **83.0%** |

**Hard slice (20 cases: 10 TP + 10 FP, `/tmp/smoke_slice_cases.json`):**

- Tuning era (Jun 2026): **20/20** with this config — see smoke archive.
- Later re-runs (Stage 3 smoke, large-model smokes): **18–19/20** on the same slice; recurring TP misses include **`BenchmarkTest00071`** and, on some runs, **`BenchmarkTest00029`**. FPRR stayed **10/10** in all post-Stage-2 smokes. Treat the slice as a **regression gate**, not a frozen leaderboard — full-corpus Stage 2 numbers are the authoritative evaluation.

**Fast alternative (Stage 2):** `qwen3_8b_bnb` · think ON · fs0 → 79.5% SRS, 18/20 hard slice.

---

## 3. Stage 3 — prompt variant sweep

### 3.1 Motivation

Stage 2 ship config reached **92.5% VDR** and **73.5% FPRR** — below aspirational gates of **VDR ≥ 95%** and **FPRR ≥ 90%**. Stage 3 tested two new prompt procedures on top of the frozen Stage 2 inference stack (think ON, fs3, `v2_3shot_tp_2fp`).

| Prompt ID | Tag | Intent |
|-----------|-----|--------|
| `v7-balanced` | `unified-4label-v7-balanced` | Stage 2 baseline (Java/CodeQL-specific) |
| `v8-dual-gate` | `unified-4label-v8-dual-gate` | Symmetric TP/FP gates before case label |
| `v9-fprr-first` | `unified-4label-v9-fprr-first` | Structural-FP-first ordering; target coder over-TP bias |

Manifest: `benchmark/phases/phase2/stage3/MANIFEST.json`  
Runner: `benchmark/phases/phase2/stage3/run_stage3_smoke.py`  
Registry: `benchmark/prompt_versions.py`

### 3.2 Hard-slice smoke results (120 runs, 6 cells × 20 cases)

Source: `runs/phase2/stage3/smoke/smoke_summary.json`  
Smoke gates: VDR ≥ 9/10 **and** FPRR ≥ 9/10.

| Cell | Profile | Prompt | VDR | FPRR | Total | Pass |
|------|---------|--------|-----|------|-------|------|
| 59b_v7 | qwen3_5_9b_bnb | v7-balanced | 9/10 | 10/10 | 19/20 | **Yes** |
| 59b_v8 | qwen3_5_9b_bnb | v8-dual-gate | 7/10 | 10/10 | 17/20 | No |
| 59b_v9 | qwen3_5_9b_bnb | v9-fprr-first | 8/10 | 10/10 | 18/20 | No |
| coder_v7 | qwen3_coder_30b_bnb | v7-balanced | 9/10 | 2/10 | 11/20 | No |
| coder_v8 | qwen3_coder_30b_bnb | v8-dual-gate | 8/10 | 3/10 | 11/20 | No |
| coder_v9 | qwen3_coder_30b_bnb | v9-fprr-first | 0/10 | 10/10 | 10/20 | No |

### 3.3 Stage 3 verdict

- **v8** and **v9** hurt VDR on 5.9B without improving FPRR on the hard slice; they do not justify a 600-case run.
- **Coder-30B** remains recall-heavy: high VDR, unusable FPRR (~2/10). v9 on coder collapses VDR to 0/10 (all-TP bias eliminated → all FPs missed on TP track).
- Only **59b_v7** passed smoke; it matches Stage 2 and does not close the 95/90 gap.
- **Decision:** Skip Stage 3 full corpus. **Retain v7-balanced as the production prompt.**

---

## 4. Lang-agnostic v7 experiment (rejected)

### 4.1 Motivation

Rewrite v7 procedure text in language-neutral terms (no Java-specific sink examples) to support future Python/Node corpora without prompt forks.

Implementation: temporary tag `unified-4label-v7-balanced-langagnostic` in `benchmark/prompt_versions.py` (later **reverted**; registry restored to Java-specific v7 for Stage 2 parity).

### 4.2 Results

| Run | Profile(s) | VDR | FPRR | Total | Pass |
|-----|------------|-----|------|-------|------|
| 59b only | qwen3_5_9b_bnb | 8/10 | 10/10 | 18/20 | No |
| Large models | qwen3_next_80b_bnb, qwen3_6_27b_bnb | 8/10 each | 10/10 | 18/20 | No |

Sources:

- `runs/phase2/stage3/smoke/smoke_summary_59b_v7_langagnostic.json`
- `runs/smoke/large_qwen_v7_langagnostic/smoke_summary.json`

### 4.3 Verdict

Lang-agnostic v7 **regressed VDR** vs Java-specific v7 on the same slice (8/10 vs 9–10/10) while FPRR unchanged. Java/CodeQL-specific guidance (sink patterns, list/map/switch examples) appears load-bearing for hard TP cases.

**Decision:** Do **not** promote lang-agnostic v7. Keep Java-specific v7 for BenchmarkJava; revisit language-neutral prompts when non-Java corpora enter scope (Phase 3B or later).

---

## 5. Large-model smoke (post-Stage-2)

### 5.1 Motivation

Test whether scaling model size beats the 5.9B ship config on the hard slice with **unchanged** Stage 2 stack (Java v7, fs3, think ON).

Runner: `benchmark/phases/smoke/run_large_qwen_smoke.py`  
Profiles added: `qwen3_next_80b_bnb` (Bedrock), `qwen3_6_27b_bnb` (local 4-bit), `qwen3_6_35b_a3b_bnb` (attempted).

### 5.2 Feasibility

| Profile | Backend | Result |
|---------|---------|--------|
| qwen3_next_80b_bnb | Bedrock (Qwen3-Next-80B-A3B) | OK |
| qwen3_6_27b_bnb | Local Unsloth 4-bit (~18 GB VRAM) | OK |
| qwen3_6_35b_a3b_bnb | Local Unsloth 4-bit | **Failed** — Unsloth `Params4bit._is_hf_initialized` + disk; not evaluated |

### 5.3 Hard-slice results (Java v7)

Source: `runs/smoke/large_qwen_stage2_v7/smoke_summary.json`

| Profile | VDR | FPRR | Total | vs 5.9B Stage 3 smoke |
|---------|-----|------|-------|------------------------|
| qwen3_next_80b_bnb | 8/10 | 10/10 | 18/20 | Worse VDR |
| qwen3_6_27b_bnb | 8/10 | 10/10 | 18/20 | Worse VDR |
| qwen3_5_9b_bnb (reference) | 9/10 | 10/10 | 19/20 | Best among evaluated |

Shared TP misses on large-model runs: **`BenchmarkTest00071`**, **`BenchmarkTest00029`**.

### 5.4 Verdict

Larger models did **not** improve hard-slice VDR under the Stage 2 prompt stack. **Qwen3.5-9B remains the cost/quality choice** for Phase 2 baseline and Phase 3 SFT base model.

---

## 6. Summary of rejected paths

| Experiment | Result | Decision |
|------------|--------|----------|
| v8-dual-gate prompt | 7/10 VDR on 5.9B hard slice | Reject — keep v7 |
| v9-fprr-first prompt | 8/10 VDR on 5.9B; 0/10 VDR on coder | Reject — keep v7 |
| Stage 3 full corpus (600 × 6 cells) | Not run | Skip — smoke did not justify cost |
| Lang-agnostic v7 | 8/10 VDR (59b, 80b, 27b) | Reject — revert to Java v7 |
| Qwen3-Next-80B (Bedrock) | 8/10 VDR | No scale-up benefit on slice |
| Qwen3.6-27B local | 8/10 VDR | No scale-up benefit on slice |
| Qwen3.6-35B-A3B local | Infra failure | Not evaluated |
| Gemma 4 (Stage 1/2 era) | 0/20 hard slice | Dropped earlier |

---

## 7. Phase 2 conclusions

1. **Production config is frozen:** Qwen3.5-9B · v7-balanced · think ON · fs3 · `v2_3shot_tp_2fp` · **83.0% SRS** on 600-case held-out test.
2. **Prompt-only improvements are exhausted** for the 95/90 gates; v8/v9 and lang-agnostic rewrites hurt or flat VDR on the diagnostic slice.
3. **Model scale (80B, 27B) did not beat 5.9B** on the same prompt stack; bigger models are not the next lever.
4. **Hard slice is useful for fast regression** but can drift slightly (19/20 vs 20/20); full corpus Stage 2 metrics remain primary.
5. **Phase 3 (training)** is the agreed next step: LoRA SFT on `unsloth/Qwen3.5-9B` using BenchmarkJava **train** split labels, holding Phase 2 **test** (600 cases) out, inference stack unchanged except adapter weights.

---

## 8. Phase 3 handoff

Detailed implementation plan: **`benchmark/phases/phase3/PLAN.md`** (to be written at Phase 3 kickoff).

Agreed direction (from Phase 2 closure discussion):

| Item | Choice |
|------|--------|
| Base model | `unsloth/Qwen3.5-9B` 4-bit + LoRA (Unsloth) |
| Phase 3A data | Java train split only (~1,500 SFT examples: fp/tp/borderline) |
| Train labels | Gold TP/FP/**BL** on borderline train (adjust if TP/FP hurt) |
| Inference at eval | Same as ship config; **no thinking tokens in SFT targets** |
| Held out | Phase 2 test corpora (600); few-shot exemplars already from train |
| Phase 3B (later) | Cross-language translation augmentation for Python/Node |

Success criterion for Phase 3A: beat Stage 2 ship config on held-out 600-case test (primary: VDR and SRS; monitor FPRR).

---

## 9. Artifact index

| Artifact | Path |
|----------|------|
| **This closure doc** | `runs/phase2/PHASE2_COMPLETE.md` |
| Publication report (Stage 1–2) | `runs/phase2/stage2/PUBLICATION_REPORT.md` |
| Smoke tuning archive | `runs/phase2/stage2/SMOKE_ARCHIVE.md` |
| Stage 1 full matrix | `runs/phase2/summaries/PHASE2_REPORT.md` |
| Stage 2 metrics table | `runs/phase2/stage2/summaries/STAGE2_REPORT.md` |
| Stage 2 manifest | `benchmark/phases/phase2/stage2/MANIFEST.json` |
| Stage 3 manifest | `benchmark/phases/phase2/stage3/MANIFEST.json` |
| Stage 3 smoke summary | `runs/phase2/stage3/smoke/smoke_summary.json` |
| Lang-agnostic 59b smoke | `runs/phase2/stage3/smoke/smoke_summary_59b_v7_langagnostic.json` |
| Large model smoke (Java v7) | `runs/smoke/large_qwen_stage2_v7/smoke_summary.json` |
| Large model smoke (lang-agnostic) | `runs/smoke/large_qwen_v7_langagnostic/smoke_summary.json` |
| Prompt version registry | `benchmark/prompt_versions.py` |
| Few-shot configs | `benchmark/few_shot_configs/` |
| Phase 2 matrix plan (Stage 1) | `benchmark/phases/phase2/PLAN.md` |
| Original study plan | `docs/EXPERIMENT_PLAN.md` |
| **Phase 1 closure** | `runs/phase1/PHASE1_COMPLETE.md` |
| Demo (uses Stage 3 smoke cache) | `demo/README.md` |

---

*Phase 2 closed after Stage 3 and post-Stage-2 probes. All raw run outputs under `runs/phase2/` and `runs/smoke/`.*
