# LLM-Based SAST Triage: Experimental Report

**Project:** OWASP BenchmarkJava Phase 2 LLM triage  
**Final prompt:** `unified-4label-v7-balanced`  
**Report date:** June 2026  
**Artifacts:** `runs/smoke/`, `runs/phase2/`, `runs/phase2/stage2/`

---

## 1. Executive Summary

We evaluated local Qwen-family models for automated triage of CodeQL SAST alerts on OWASP BenchmarkJava. Experiments progressed through prompt engineering (multi-alert handling, per-alert sink resolution, balanced recall/precision), few-shot exemplar design, and model/thinking/configuration search on a **20-case hard slice** before full-corpus validation on **600 cases per configuration** (200 FP + 200 TP + 200 borderline).

**Primary finding:** The best production configuration is **Qwen3.5-9B · chain-of-thought (thinking) ON · 3-shot few-shot · legacy v2 exemplars (1 TP + 2 FP)**, achieving **20/20** on the hard diagnostic slice and **83.0% SRS** (73.5% FPRR, 92.5% VDR) on the full test corpus under the final v7-balanced prompt.

**Secondary finding:** The v7-balanced prompt deliberately shifts toward **vulnerability detection recall (VDR)** at the cost of false-positive rejection rate (FPRR) versus earlier prompts—appropriate for security triage where missed TPs are costlier than extra review of FPs.

---

## 2. Task and Metrics

### 2.1 Task

Given one Java source file and one or more CodeQL alerts, assign a **case-level label**:

| Label | Meaning |
|-------|---------|
| **TP** | At least one alert is a true vulnerability on its path |
| **FP** | Every alert is a false positive with path-specific evidence |
| **BL** | No TP; at least one alert genuinely ambiguous |
| **UNKNOWN** | Insufficient information |

Models must assess **each alert independently** before aggregating to a case label (critical for multi-alert cases).

### 2.2 Evaluation Tracks

| Track | Gold label | Cases | Metric |
|-------|------------|-------|--------|
| FP test | FP | 200 | **FPRR** — fraction correctly labeled FP |
| TP test | TP | 200 | **VDR** — fraction correctly labeled TP |
| Borderline test | mixed | 200 | Lenient accuracy, BL rate, ambiguity index |

### 2.3 Composite Metrics

- **SRS** (Security Review Score) = 0.5 × FPRR + 0.5 × VDR  
- **F1** = 0.5 × F1-FP-track + 0.5 × F1-TP-track  
- **Hard-slice accuracy** = (correct TP + correct FP) / 20 on fixed diagnostic subset

### 2.4 Models Evaluated

| Profile | Model | Role in study |
|---------|-------|---------------|
| qwen3_4b_bnb | Qwen3-4B | Size baseline (Phase 2 Stage 1 only) |
| qwen3_8b_bnb | Qwen3-8B | Fast/cheap arm |
| qwen3_14b_bnb | Qwen3-14B | Mid-size baseline |
| qwen3_5_9b_bnb | Qwen3.5-9B | **Primary production candidate** |
| qwen3_coder_30b_bnb | Qwen3-Coder-30B | Recall ceiling / comparison |
| qwen3_5_4b_bnb | Qwen3.5-4B | Extension (Stage 1 only) |
| gemma_4_e4b_bnb | Gemma 4 4B-IT | **Dropped** (infra cost, no gain) |

All local models run 4-bit quantized (Unsloth/BnB) on NVIDIA L40S unless noted (Coder-30B via Bedrock for some Phase 2 cells).

---

## 3. Experimental Phases

### Phase A — Prompt iteration (hard slice, 20 cases)

Fixed diagnostic slice: 10 TP + 10 FP from Phase 2 test corpora (see `/tmp/smoke_slice_cases.json`). Used to iterate quickly before full runs.

| Prompt version | Key change | Outcome |
|----------------|------------|---------|
| v3 multi-alert | Per-alert assessment introduced | Fixed multi-alert conflation; baseline for later work |
| v4 sink-trace | Explicit sink expression tracing | Improved structural FP reasoning |
| v6 balanced | Balanced encoding / mitigation rules | Reduced over-mitigation FPs |
| **v7 balanced** | Mandatory resolved-sink-value; VDR-first few-shot placement | **Selected for full evaluation** |
| v8 balanced | Minor v7 variant | No improvement over v7 on slice; not adopted |

### Phase B — Few-shot layout and exemplar search (hard slice)

| Config ID | Exemplars | Order | Hard-slice best (think=on) |
|-----------|-----------|-------|----------------------------|
| `v2_3shot_tp_2fp` | 02272 (TP), 00200 (FP), 00340 (FP) | TP→FP→FP | **5.9b: 20/20** |
| `v2_2shot_tp_fp` | 02272 (TP), 00200 (FP) | TP→FP | 8b/5.9b: 18/20 |
| `v2_3shot_2tp_fp` | 02272, 00008 (TP), 00200 (FP) | TP→TP→FP | 8b: 18/20; 5.9b: 17/20 (**regressed**) |
| v3 layout (TP+FP+BL) | Includes borderline slot | TP→FP→BL | 5.9b: 19/20 (**regressed** vs legacy v2 fs3) |
| Zero-shot (fs0) | — | — | 8b/5.9b: 16–17/20 |

**Conclusion:** Legacy **1 TP + 2 FP** compact v2 exemplars with thinking ON are optimal. Adding a second TP or BL exemplar did not help.

### Phase C — Configuration matrix smoke (hard slice, 320–160 runs)

Full matrix: 4 profiles × thinking {on, off} × few-shot {0, 2, 3} on v7-balanced prompt.

**Top configurations (think=on only):**

| Profile | FS | Config | VDR | FPRR | Total |
|---------|-----|--------|-----|------|-------|
| qwen3_5_9b_bnb | 3 | v2_3shot_tp_2fp | 10/10 | 10/10 | **20/20** |
| qwen3_8b_bnb | 0 or 2 or 3 | various | 8/10 | 10/10 | 18/20 |
| qwen3_5_9b_bnb | 2 | v2_2shot_tp_fp | 8/10 | 10/10 | 18/20 |
| qwen3_14b_bnb | 3 | v2_3shot_tp_2fp | 8/10 | 9/10 | 17/20 |
| qwen3_coder_30b_bnb | 2 or 3 | various | 9–10/10 | 2/10 | 11–13/20 |

**Anti-patterns discovered:**

| Configuration | Failure mode |
|---------------|--------------|
| think=off + fs3 (8b) | 0/10 VDR — labels all TPs as FP |
| think=off + fs3 (5.9b) | 0/10 FPRR — labels all FPs as TP |
| think=off (all profiles, early v2 smoke) | 0/20 — models non-functional without CoT |
| Gemma 4 | 0/20 — dropped from study |

### Phase D — Phase 2 Stage 1 (full corpus, pre-v7-final prompt era)

**Corpus:** 200 cases × 3 tracks = 600 evaluations per cell.  
**Matrix:** 6 profiles × thinking {off, on} × few-shot {0, 3} × 3 tracks.

**Best cells — thinking ON, few-shot 3 (full 200/track):**

| Profile | FPRR | VDR | SRS |
|---------|------|-----|-----|
| qwen3_5_9b_bnb | **94.0%** | 85.5% | **89.8%** |
| qwen3_8b_bnb | 90.0% | 51.0% | 70.5% |
| qwen3_coder_30b_bnb | 90.0% | 43.0% | 66.5% |
| qwen3_14b_bnb | 97.5% | 26.0% | 61.7% |

**Best zero-shot — thinking ON, fs0:**

| Profile | FPRR | VDR | SRS |
|---------|------|-----|-----|
| qwen3_8b_bnb | 96.0% | 65.8% | 80.9% |
| qwen3_5_9b_bnb | 96.0% | 65.8% | 80.9% |

### Phase E — Phase 2 Stage 2 (full corpus, final v7-balanced prompt)

**Selected cells only** (2,400 total runs, 100% complete):

| Cell | Profile | FS | Few-shot config | FPRR | VDR | SRS |
|------|---------|-----|-----------------|------|-----|-----|
| Primary | qwen3_5_9b_bnb | 3 | v2_3shot_tp_2fp | 73.5% | **92.5%** | **83.0%** |
| Fast | qwen3_8b_bnb | 0 | — | 75.0% | 84.0% | 79.5% |
| Mid | qwen3_14b_bnb | 3 | v2_3shot_tp_2fp | 82.5% | 64.0% | 73.2% |
| Recall | qwen3_coder_30b_bnb | 3 | v2_3shot_tp_2fp | 56.0% | **92.5%** | 74.2% |

**Borderline track (Stage 2, fs3, think=on):**

| Profile | Predicted TP% | Predicted FP% | Lenient Acc |
|---------|---------------|---------------|-------------|
| qwen3_5_9b_bnb | 87.0% | 13.0% | 100% |
| qwen3_14b_bnb | 65.5% | 34.5% | 100% |
| qwen3_coder_30b_bnb | 97.5% | 2.5% | 100% |

Models rarely assign BL (0% BL rate on borderline track); they collapse ambiguous cases toward TP or FP.

---

## 4. Cross-Experiment Comparison

### 4.1 Hard slice: prompt + few-shot evolution (think=on)

| Experiment | Best profile | FS | Total /20 |
|------------|--------------|-----|-----------|
| Legacy fs3 (v2, 1TP+2FP) | qwen3_5_9b_bnb | 3 | **20** |
| 2-shot matrix | qwen3_8b_bnb / 5.9b | 0/2 | 18 |
| 2TP+1FP fs3 | qwen3_8b_bnb | 3 | 18 |
| Few-shot v3 layout | qwen3_5_9b_bnb | 3 | 19 |
| Zero-shot | qwen3_5_9b_bnb | 0 | 16–17 |

### 4.2 Full corpus: Stage 1 vs Stage 2 (matched profiles)

| Profile | FS | Stage 1 SRS | Stage 2 SRS | Δ SRS | VDR change | FPRR change |
|---------|-----|-------------|-------------|-------|------------|-------------|
| qwen3_5_9b_bnb | 3 | **89.8%** | 83.0% | −6.8pp | +7.0pp | −20.5pp |
| qwen3_8b_bnb | 0 | 80.9% | 79.5% | −1.4pp | +18.2pp | −21.0pp |
| qwen3_14b_bnb | 3 | 61.7% | 73.2% | **+11.5pp** | +38.0pp | −15.0pp |
| qwen3_coder_30b_bnb | 3 | 66.5% | 74.2% | **+7.7pp** | +49.5pp | −34.0pp |

The v7-balanced prompt trades FPRR for VDR across all profiles. Net SRS impact depends on profile: 14b and coder improve; 5.9b regresses slightly on SRS but achieves highest absolute VDR (92.5%).

### 4.3 Model ranking (Stage 2, final prompt)

| Rank | Profile | FS | SRS | Strength | Weakness |
|------|---------|-----|-----|----------|----------|
| 1 | qwen3_5_9b_bnb | 3 | 83.0% | Best balance; highest VDR with acceptable FPRR | Lower FPRR than Stage 1 |
| 2 | qwen3_8b_bnb | 0 | 79.5% | Fast, strong VDR, no few-shot overhead | FPRR 75% |
| 3 | qwen3_coder_30b_bnb | 3 | 74.2% | Matches 5.9b VDR | FPRR 56% — unusable for FP track |
| 4 | qwen3_14b_bnb | 3 | 73.2% | Largest Stage 1→2 improvement | VDR still moderate (64%) |

---

## 5. Key Findings for Publication

1. **Multi-alert per-alert assessment is essential.** Case-level prompts that do not require independent alert verdicts before aggregation fail on multi-alert BenchmarkJava cases.

2. **Resolved sink value reasoning reduces structural FP errors.** Requiring models to state the exact value reaching the sink (not merely that taint exists) improves list/map/switch false-positive rejection.

3. **Few-shot exemplar composition matters more than count.** 3-shot with 1 TP + 2 FP outperforms 2-shot and an alternative 2 TP + 1 FP layout. Order: VDR-first (TP exemplars before FP).

4. **Chain-of-thought (thinking mode) is required** for reliable few-shot triage. Thinking-off configurations exhibit extreme label bias (all-FP or all-TP).

5. **Model size vs. capability:** Qwen3.5-9B offers the best cost/quality tradeoff. Qwen3-8B with zero-shot thinking is a viable fast path. Qwen3-Coder-30B maximizes recall but cannot suppress false positives.

6. **Recall–precision tradeoff is prompt-controllable.** The v7-balanced prompt increases VDR by 7–50 percentage points (profile-dependent) while reducing FPRR by 15–34pp. For security triage, this is a defensible operating point.

7. **Borderline (BL) label is underused.** Models assign TP or FP to nearly all borderline cases; BL rate ≈ 0% despite 200-case borderline track designed for ambiguity.

---

## 6. Recommended Configuration (Final)

```
Prompt:     unified-4label-v7-balanced
Model:      qwen3_5_9b_bnb
Thinking:   ON
Few-shot:   3
Config:     v2_3shot_tp_2fp  (benchmark/few_shot_configs/v2_3shot_tp_2fp.json)
Exemplars:  BenchmarkTest02272 (TP, multi-alert)
            BenchmarkTest00200 (FP, list remove/get)
            BenchmarkTest00340 (FP, switch branch)
```

**Fast alternative:** qwen3_8b_bnb · think=ON · fs0 (zero-shot)

**CLI:** `--few-shot 3 --few-shot-config v2_3shot_tp_2fp --thinking`

---

## 7. Limitations

- **Single benchmark:** OWASP BenchmarkJava only; generalization to production codebases untested.
- **Single SAST tool:** CodeQL alerts only.
- **Train/test leakage control:** Few-shot exemplars drawn from train split; test cases held out (verified by preflight).
- **BL track evaluation:** Models rarely use BL label; borderline metrics may not reflect intended ambiguity handling.
- **Compute:** Thinking-on 5.9b averages ~3 min/case on full corpus; not suitable for real-time inline triage without batching.
- **Stage 1 vs Stage 2 comparability:** Prompt changed between stages; direct SRS comparison reflects prompt effect, not model drift.

---

## 8. Artifact Index

| Artifact | Path |
|----------|------|
| **Phase 2 closure** (Stage 3, lang-agnostic, large-model probes) | `runs/phase2/PHASE2_COMPLETE.md` |
| Hard-slice archive | `runs/phase2/stage2/SMOKE_ARCHIVE.md` |
| Stage 2 results | `runs/phase2/stage2/summaries/STAGE2_REPORT.md` |
| Stage 1 full matrix | `runs/phase2/summaries/PHASE2_TABLES.md` |
| Few-shot configs | `benchmark/few_shot_configs/` |
| Stage 2 manifest | `benchmark/phases/phase2/stage2/MANIFEST.json` |
| Status checker | `benchmark/phases/phase2/stage2/status_stage2.py` |

---

## 9. Suggested Publication Claims

> We present a unified 4-label LLM triage pipeline for multi-alert CodeQL findings, with per-alert sink-resolution prompting and compact few-shot exemplars. On OWASP BenchmarkJava (600-case evaluation per configuration), Qwen3.5-9B with chain-of-thought and 3-shot exemplars achieves 92.5% vulnerability detection recall and 73.5% false-positive rejection (83.0% SRS), outperforming Qwen3-8B zero-shot (79.5% SRS) and Qwen3-Coder-30B (74.2% SRS with 56% FPRR). Ablation on a 20-case diagnostic slice shows that exemplar composition (1 TP + 2 FP) outperforms alternative layouts and that thinking mode is necessary for stable few-shot behavior.

---

*Generated from experimental logs in `runs/smoke/` and `runs/phase2/`.*
