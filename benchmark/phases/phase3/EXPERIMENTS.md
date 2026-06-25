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

## Phase 3B — teacher distillation + CSS + rank sweep (planned)

| Field | Value |
|-------|-------|
| **Run ID** | `3b-001` (placeholder) |
| **Status** | Not started |
| **Manifest** | `stage3b/MANIFEST.json` |
| **Hypothesis** | Distill Stage 2 on **train**; CSS on **val** picks checkpoint; sweep ranks **16/32/64** (L40S) |

### Data & teacher (confirmed)

| Split | N | Teacher? | Role |
|-------|---|------------|------|
| Train | 1,500 | **Yes** | SFT distillation targets (CoT + JSON from Stage 2) |
| Validation | 600 | No | CSS checkpoint scoring vs **gold** labels |
| Test | 600 | No | Final metrics (same suite as val) — **once**, best checkpoint only |

### LoRA rank sweep

| Rank | Status | Best val CSS | Notes |
|------|--------|--------------|-------|
| 16 | — | — | 3A capacity; ablation |
| 32 | — | — | Primary candidate |
| 64 | — | — | CoT headroom |
| ~~128~~ | excluded | — | Overfit risk; no VRAM win on L40S |

### Checkpoint workflow

**Epochs:** CSS early stop (patience 3 val evals); no fixed low budget — hard cap **≤10** per rank. Best checkpoint may be any epoch, not the last.

1. **During training** (per rank): save checkpoints each epoch → **fast val (150 stratified)** → SRS/VDR/FPRR/macro-F1/CSS → log eligible (VDR ≥ 0.75); stop when CSS plateaus or cap hit.
2. **After all ranks**: re-eval **every CSS-eligible** checkpoint on **full val (600)** (confirmation).
3. **Pick global best** by CSS on val across all ranks.
4. **Test eval once** on that adapter; report same metrics + confusion matrix.

### CSS definition

```
CSS = 0.35*SRS + 0.35*VDR + 0.20*FPRR + 0.10*Macro-F1
Disqualify if VDR < 0.75 -> CSS = 0
```

Code: `benchmark/css.py`

### Results (fill after run)

| Checkpoint | Rank | Val CSS | Val SRS | Val VDR | Test SRS | Test VDR | Selected |
|------------|------|---------|---------|---------|----------|----------|----------|
| — | — | — | — | — | — | — | |

### Run checklist

- [ ] Teacher on **train** only (1500)
- [ ] `export_distill_dataset.py` → train JSONL
- [ ] Preflight (no test leakage)
- [ ] Train ranks **16, 32, 64** with CSS val eval each epoch
- [ ] `rerank_val_checkpoints.py` on all CSS-eligible weights
- [ ] Pick global best; **test eval once**
- [ ] Update this table + `summaries/PHASE3B_REPORT.md`

---

## Phase 3C — ship-aligned distillation (in progress)

| Field | Value |
|-------|-------|
| **Run ID** | `3c-001` |
| **Status** | Training |
| **Manifest** | `stage3c/MANIFEST.json` |
| **Plan** | `stage3c/PLAN.md` |
| **Hypothesis** | Train fs0_off + JSON-only targets; CSS val under ship config closes FPRR gap |

### vs 3B ship

| Metric | 3B ship (ep4) | Stage 2 | 3C target |
|--------|---------------|---------|-----------|
| SRS | 89.9% | 92.5% | ≥ 92.5% |
| FPRR | 66.2% | 73.5% | ≥ 73.5% |
| VDR | 90.3% | 92.5% | ≥ 90% |

### Train export (first run)

- **Records:** 1148 / 1500 (json_only, **v7-ship language-agnostic** user prompts)
- **Reuse teacher:** `runs/phase3/stage3b/teacher/train`
- **LoRA:** r=32 · CSS early stop · val fs0_off
- **Ship prompts:** dedicated `_procedure_v7_ship` (no Java/CodeQL policy text); alert headers use "SAST tool", rule IDs strip `java/` prefix

### Run checklist

- [x] Plan + manifest
- [x] Export ship-aligned distill JSONL
- [x] Preflight
- [ ] CSS training loop (running)
- [ ] Full val rerank → `lora/best`
- [ ] fs0_off test eval
- [ ] Update summaries + reports

---

## Decision log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2025-06 | Abandon sklearn unified metrics | Shifted tiers/SRS; reverted to penalty SRS |
| 2025-06 | 3B: distill Stage 2, not gold SFT | 3A VDR collapse; teacher has target behavior |
| 2025-06 | CSS for early stopping, not loss | Loss ~0.03 in 3A while VDR failed |
| 2025-06 | CoT + fs3 in training | Match eval ship config |
| 2025-06 | LoRA rank sweep 16/32/64 (L40S) | 32 primary; 64 CoT; skip 128 |
| 2025-06 | Re-eval all CSS-eligible on val before test | Confirm best checkpoint; test run once only |
