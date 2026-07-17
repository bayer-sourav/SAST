# Phase 3 experiment log

Track every training/eval run here. **Authoritative test metrics** always come from the 600-case Phase 2 held-out test. **CSS** is validation-only checkpoint selection.

---

## Baseline (no LoRA)

| ID | Model | SRS | VDR | FPRR | Macro-F1 | Notes |
|----|-------|-----|-----|------|----------|-------|
| **S2-GOOD** | Stage 2 · 5.9b_fs3_legacy | 92.5% | 92.5% | 73.5% | 0.553 | Teacher + eval reference |
| P2-MIN | Phase 2 · Qwen3.5-9B fs3 CoT | 92.8% | 85.5% | 94.0% | 0.598 | High FPRR, lower VDR |

Sources: `runs/phase2/phase2_benchmark_tables/BENCHMARK_RESULTS.html`, confusion comparison JSON.

---

## Phase 3A — gold-label SFT (completed)

| Field | Value |
|-------|-------|
| **Run ID** | `3a-202506` |
| **Status** | Failed vs baseline |
| **Manifest** | `MANIFEST.json` (phase3a) |
| **Adapter** | `runs/phase3/stage3a/lora/latest` |
| **Train** | 1500 gold-label · fs0 · thinking off · 1 epoch · lr 2e-4 |
| **Eval** | fs3 · thinking on · 600 test cases |

### Test results (600-case)

| Metric | 3A | Stage 2 | Delta |
|--------|-----|---------|-------|
| SRS | 70.0% | 92.5% | -22.5pp |
| VDR | 34.5% | 92.5% | -58.0pp |
| FPRR | 59.4% | 73.5% | -14.1pp |
| TP→FP critical | 83 | 14 | +69 |

### Diagnosis

- Train/eval mismatch (thinking, few-shot).
- Generic gold reasons — no reasoning supervision.
- Loss converged but VDR collapsed; model hedges to BL.

### Artifacts

- `runs/phase3/stage3a/summaries/PHASE3A_REPORT.md`
- `runs/phase3/stage3a/summaries/confusion_matrix_comparison.json`
- `runs/phase3/stage3a/lora/latest/train_meta.json`

---

## Phase 3B — teacher distillation + CSS + rank sweep (complete)

| Field | Value |
|-------|-------|
| **Run ID** | `3b-001` |
| **Status** | Complete — ship adapter pushed (LFS) |
| **Manifest** | `stage3b/MANIFEST.json` |
| **Ship adapter** | `runs/phase3/stage3b/lora/best_fs0_off` (epoch 4, fs0 rerank) |

### Test results — ship (fs0_off best)

| Metric | 3B ship | Stage 2 | Delta |
|--------|---------|---------|-------|
| SRS | 89.9% | 92.5% | -2.6pp |
| VDR | 90.3% | 92.5% | -2.2pp |
| FPRR | 66.2% | 73.5% | -7.3pp |
| TP→FP | 17 | 14 | +3 |

### Artifacts

- `reports/phase3b/PHASE3B_TEST_REPORT.md`
- `runs/phase3/stage3b/lora/best_fs0_off/` (git LFS)

---

## Phase 3C — ship-aligned distillation (complete)

| Field | Value |
|-------|-------|
| **Run ID** | `3c-001` |
| **Status** | Complete — did not beat Stage 2 SRS |
| **Manifest** | `stage3c/MANIFEST.json` |
| **Adapter** | `runs/phase3/stage3c/lora/best` (epoch 6, full-val CSS) |
| **Plan** | `stage3c/PLAN.md` |

### Hypothesis result

Train/serve alignment **validated** (epoch 6 = val pick without fs0 rerank correction). **FPRR improved +12pp vs 3B ship** but **VDR dropped −4pp** → **same aggregate SRS** as 3B ship.

### Train export

- **Records:** 1283 / 1500 (json_only, v7-ship, fs0_off)
- **Dropped:** 99 missing teacher, 97 unparseable, 21 too long
- **Teacher:** reused `runs/phase3/stage3b/teacher/train`

### Val rerank (full 600)

| Epoch | Full CSS | SRS | VDR | FPRR | Selected |
|-------|----------|-----|-----|------|----------|
| 2 | 0.813 | 83.7% | 86.7% | 80.6% | |
| 4 | 0.824 | 83.9% | 86.7% | 85.0% | |
| **6** | **0.844** | **85.7%** | **89.9%** | **85.6%** | **yes** |
| 8 | 0.839 | 85.2% | 88.8% | 85.6% | |
| 10 | 0.833 | 84.4% | 88.8% | 84.4% | |

### Test results (594/600 after gap-fill)

| Metric | 3C | 3B ship | Stage 2 | Δ vs S2 |
|--------|-----|---------|---------|---------|
| SRS | 89.9% | 89.9% | 92.5% | -2.6pp |
| VDR | 86.3% | 90.3% | 92.5% | -6.2pp |
| FPRR | 78.3% | 66.2% | 73.5% | +4.8pp |
| TP→FP | 27 | 17 | 14 | +13 |
| BL→FP | 27 | 16 | 26 | +1 |
| Missing | 6 | 13 | 0 | |

### Diagnosis

- Primary gap: **TP→FP** (VDR), not BL volume — BL→TP is zero penalty and dominates BL track
- 3C trades fewer FP→TP errors for more TP→FP vs 3B ship (same total SRS penalty)
- Six inference JSON-parse failures remain (CoT without JSON)

### Artifacts

- `reports/phase3c/PHASE3C_TEST_REPORT.md`
- `reports/phase3c/PHASE3C_NEXT.md` — recommended 3D plan
- `runs/phase3/stage3c/summaries/css_rerank_best.json`
- `benchmark/phases/phase3/rescore_test_eval.py`

### Run checklist

- [x] Plan + manifest
- [x] Export ship-aligned distill JSONL
- [x] Preflight
- [x] CSS training (10 epochs, r=32)
- [x] Full val rerank → `lora/best`
- [x] fs0_off test eval + gap-fill
- [x] Reports + EXPERIMENTS update

---

## Phase 3C blv4 — BL synthetic refresh confirm (complete — NOT ship)

| Field | Value |
|-------|-------|
| **Run ID** | `3c-blv4-001` |
| **Status** | Complete — **gates NOT met** (do not ship) |
| **Manifest** | `stage3c_blv4/MANIFEST.json` |
| **Adapter** | `runs/phase3/stage3c_blv4/lora/best` (epoch 10, CSS 0.848) |
| **Protocol** | `runs/phase3/stage3c_blv4/CONFIRM_PROTOCOL.md` |

### Hypothesis

Same frozen 3C recipe on **current** BL train (`curated_v4_calibrated_v3` / `BenchmarkTest28xxx`) should confirm original 3C metrics after retiring `BLSynthetic*`.

### Result

**Rejected.** Refreshing BL train collapsed VDR; FPRR stayed decent. Worse than original 3C and 3B ship on SRS/VDR.

| Metric | blv4 | Original 3C | 3B ship | Stage 2 | Δ vs S2 |
|--------|------|-------------|---------|---------|---------|
| SRS | **88.1%** | 89.9% | 89.9% | 92.5% | −4.4pp |
| VDR | **72.5%** | 86.3% | 90.3% | 92.5% | −20.0pp |
| FPRR | **76.5%** | 78.3% | 66.2% | 73.5% | +3.0pp |
| TP→FP | **40** | 27 | 17 | 14 | +26 |
| Missing | 0 (after gap-fill) | 6 | 13 | 0 | |

### Gates

| Gate | Target | Result |
|------|--------|--------|
| Beat Stage 2 SRS | > 92.5% | FAIL |
| FPRR ≥ Stage 2 | ≥ 73.5% | PASS |
| VDR floor | ≥ 90% | FAIL |

### Artifacts

- `runs/phase3/stage3c_blv4/summaries/PHASE3C_BLV4_TEST_REPORT.md`
- `runs/phase3/stage3c_blv4/summaries/confusion_matrix_comparison.json`
- `benchmark/phases/phase3/report_phase3c_blv4_test.py`

### Decision

Keep **original 3C** as historical ship-aligned row; use **3B ep4 fs0** for Integration latency interim; do not promote blv4.

---

## Phase 3D — VDR recovery + constrained CSS (planned)

| Field | Value |
|-------|-------|
| **Run ID** | `3d-001` (primary), `3d-a` (BL ablation) |
| **Status** | Planned — see `stage3d/PLAN.md` |
| **Hypothesis** | VDR-constrained checkpoint pick + hard-neg mining on 3C TP→FP errors closes SRS gap while keeping 3C FPRR |

### Experiments

| ID | Train | Selection | Rank |
|----|-------|-----------|------|
| 3D-001 | 3C export + hard-neg oversample | VDR≥0.90, FPRR≥0.735, max SRS | 32 |
| 3D-002 | same | constrained | 64 |
| 3D-a | FP+TP only (no BL) | constrained | 32 |
| 3D-data | recover → 1500 export | constrained | 32 |

### Targets

SRS ≥ 92.5% · VDR ≥ 90% · FPRR ≥ 73.5% · TP→FP ≤ 17

---

## Decision log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2025-06 | Abandon sklearn unified metrics | Shifted tiers/SRS; reverted to penalty SRS |
| 2025-06 | 3B: distill Stage 2, not gold SFT | 3A VDR collapse; teacher has target behavior |
| 2025-06 | CSS for early stopping, not loss | Loss ~0.03 in 3A while VDR failed |
| 2025-06 | CoT + fs3 in training | Match eval ship config |
| 2025-06 | LoRA rank sweep 16/32/64 (L40S) | 32 primary; 64 CoT; skip 128 |
| 2026-07-16 | Reject 3C blv4 confirm | VDR 72.5% / SRS 88.1% on refreshed BL; keep 3B ep4 for Integration latency |
| 2025-06 | Re-eval all CSS-eligible on val before test | Confirm best checkpoint; test run once only |
| 2025-06 | 3C: fs0_off train + json_only + ship val CSS | Close 3B FPRR gap; fix train/serve mismatch |
| 2025-06 | 3C: reuse 3B teacher cache | Avoid 1500-case re-inference |
| 2025-06 | 3C result: same SRS as 3B ship, +FPRR −VDR | CSS picks different error tradeoff; TP→FP is next target |
| 2025-06 | 3D-a: BL train ablation (not primary) | BL not valid ship output; contradictory teacher on BL-gold may blur TP/FP — test via 3D-a |
