# Phase 3D — VDR recovery + constrained checkpoint selection

**Status:** Planned  
**Prior:** Phase 3C complete — test SRS **89.9%** (epoch 6, `lora/best`) vs Stage 2 **92.5%**  
**Frozen references:**
- Stage 2 GOOD · `5.9b_fs3_legacy` — SRS 92.5% · VDR 92.5% · FPRR 73.5% · TP→FP 14
- Phase 3C ship · epoch 6 — SRS 89.9% · VDR 86.3% · FPRR 78.3% · TP→FP 27
- Phase 3B ship · epoch 4 — SRS 89.9% · VDR 90.3% · FPRR 66.2% · TP→FP 17

---

## Problem statement (from 3C)

Phase 3C fixed train/serve alignment and **closed the FPRR gap vs 3B ship** (+12pp), but **VDR regressed** (−4pp vs 3B ship). Net SRS unchanged at 89.9% — still **2.6pp below Stage 2**.

| Error type | 3C | 3B ship | Stage 2 | SRS weight |
|------------|-----|---------|-----------|------------|
| **TP→FP** (missed vuln) | **27** | 17 | 14 | CRITICAL ×3 |
| BL→FP (over-dismiss) | 27 | 16 | 26 | HIGH ×1.5 |
| FP→TP (noise kept) | 42 | 63 | 53 | ×1 |

**Root cause hypothesis:** Pure CSS (0.35·SRS + 0.35·VDR + 0.20·FPRR + …) selected epoch 6 for a **high-FPRR / lower-VDR** tradeoff. The model improved false-positive dismissal at the cost of recall on true positives.

**Secondary hypothesis (BL training):** 362 BL-gold export rows carry **contradictory teacher labels** (85% TP / 14% FP on benchmark-safe cases). This may blur the TP/FP boundary — see `reports/phase3c/PHASE3C_BL_ANALYSIS.md`. BL output class is **not** the issue (ship never emits BL; test `acceptable_labels` = TP|FP only).

---

## Goals

| Priority | Metric | Target | vs 3C |
|----------|--------|--------|-------|
| **Primary** | Test SRS | ≥ **92.5%** | +2.6pp |
| **Co-primary** | VDR | ≥ **90%** | +3.7pp |
| **Constraint** | FPRR | ≥ **73.5%** | maintain 3C gain vs 3B |
| **Hard gate** | TP→FP | ≤ **17** | −10 |
| Secondary | Missing test preds | ≤ 3 | gap-fill pipeline |

**Non-goals for 3D:**
- Changing BL test scoring or requiring BL output at ship (→ Phase 3E if ever)
- fs3+CoT train (reintroduces train/serve mismatch)
- Gold-label SFT (3A VDR collapse)

---

## Experiment matrix

Run in order; stop early if primary track hits gates on test.

| ID | Name | Train data | CSS / selection | LoRA | Hypothesis |
|----|------|------------|-----------------|------|------------|
| **3D-001** | **VDR-primary** | 3C export + hard-neg oversample | **VDR-constrained CSS** | r=32 | Directly fix TP→FP; keep 3C FPRR |
| **3D-002** | Capacity | same as 001 | VDR-constrained CSS | **r=64** | More headroom for subtle TP recall |
| **3D-a** | **BL ablation** | **FP+TP only** (~921 rows) | VDR-constrained CSS | r=32 | Test if BL boundary noise hurts VDR |
| **3D-data** | Full export | recover toward 1500 rows | VDR-constrained CSS | r=32 | More data stabilizes recall |

### 3D-001 — VDR-primary (main bet)

**Hard-negative mining on 3C TP→FP errors:**

1. Run confusion analysis on `runs/phase3/stage3c/eval/` (TP-gold → predicted FP).
2. Cluster by rule family / CWE / file pattern (from case metadata + teacher `reason`).
3. Find **train cases** with similar features (same rule, similar flow).
4. Export distill JSONL with **2× or 3× duplication** of mined hard-negatives + matched TP neighbors.
5. Cap total train rows ≤ 1500 equivalent tokens budget (avoid runaway oversampling).

**VDR-constrained checkpoint selection:**

Replace unconstrained CSS max with **feasible set + lexicographic pick**:

```
Eligible if: VDR ≥ 0.90 AND FPRR ≥ 0.735 AND VDR_disqualify (≥ 0.75)
Pick: max SRS among eligible
Tie-break: max VDR, then max FPRR
```

Implement as `benchmark/phases/phase3/css_constrained.py` + manifest flag `checkpoint_selection.pick_by: constrained_srs`.

**Training:** Same as 3C — fs0_off prompts, json_only targets, reuse 3B teacher cache, `v7-ship`, 10 epochs max, fast val every 2 epochs.

### 3D-002 — Rank 64

Only if 3D-001 improves VDR but plateaus below 90%. Same data and selection as 001; sweep `lora_r ∈ {64}`.

### 3D-a — BL train ablation

**Purpose:** Test user hypothesis that BL-train confuses the model — **not** to emit BL at inference.

| | 3C | 3D-a |
|---|-----|------|
| Train tracks | FP + TP + BL (1283 rows) | **FP + TP only** (~921 rows after drops) |
| Val / test | unchanged (600 + 600) | unchanged |
| Teacher | reuse 3B cache | same |
| Target | json_only | json_only |

Export flag: `--tracks fp,tp` or manifest `supervision.train_tracks: ["fp", "tp"]`.

**Success criterion for ablation:** TP→FP ↓ vs 3C **without** FPRR ↓ below 73.5%. If VDR flat and FPRR drops, BL boundary signal was helping.

### 3D-data — Export recovery (parallel cheap win)

Address 217 dropped 3C export cases:

| Reason | N | Action |
|--------|---|--------|
| missing_teacher | 99 | gap-fill teacher cache or skip |
| unparseable_teacher | 97 | JSON tail repair in `export_distill_dataset.py` |
| too_long | 21 | per-case seq cap or source truncate |

Target: **≥ 1400** distill rows before hard-neg duplication.

---

## What stays the same as 3C

- Base model: Qwen3.5-9B 4-bit (Unsloth)
- Teacher: `runs/phase3/stage3b/teacher/train` (no re-inference unless 3D-data gap-fill)
- Train prompt: `v7-ship` · fs0 · thinking off
- Train target: `json_only` (compact teacher JSON)
- Val CSS infer: fs0_off · 150 fast during train · 600 full rerank
- Test eval: fs0_off once on global best
- Leakage rule: Phase 2 test IDs never in train/val

---

## Workflow

```
[optional] gap-fill teacher (3D-data only)
     ↓
export_distill_dataset.py  (--tracks / --hard-neg-config from 3C error analysis)
     ↓
preflight_phase3.py --stage 3d
     ↓
run_unsloth_lora_css.py  (constrained CSS callback)
     ↓
rerank_val_checkpoints.py  (full 600 val, constrained pick)
     ↓
rescore_test_eval.py --until-complete 5  (gap-fill missing test preds)
     ↓
run_phase3_eval.sh  (fs0_off test, once)
     ↓
report_phase3d_test.py → reports/phase3d/
     ↓
build_results_tables.py  (add Phase 3D row to BENCHMARK_RESULTS.html)
```

---

## Implementation checklist (before first run)

- [ ] `stage3d/MANIFEST.json` — tracks, constrained CSS, experiment IDs
- [ ] `phase3d_env.sh` — `PHASE3_MANIFEST` → stage3d
- [ ] `export_distill_dataset.py` — `--tracks`, `--hard-neg-json`, `--oversample-factor`
- [ ] `analyze_tp_fp_errors.py` — mine 3C TP→FP → hard-neg case list
- [ ] `css_constrained.py` — VDR/FPRR floors + SRS pick
- [ ] `run_unsloth_lora_css.py` — read constrained pick from manifest
- [ ] `rerank_val_checkpoints.py` — constrained global best
- [ ] `run_phase3d.sh` — orchestration (clone of `run_phase3c.sh`)
- [ ] `report_phase3d_test.py` + `publish_phase3d_reports.py`
- [ ] Disk hygiene: prune `*-vllm-merged` after each CSS epoch (3C disk-full lesson)

---

## Success gates (test, 600-case, after gap-fill)

| Gate | Target |
|------|--------|
| **PASS** | SRS ≥ 92.5% **and** VDR ≥ 90% **and** FPRR ≥ 73.5% |
| **Partial win** | SRS ≥ 91.5% or VDR ≥ 90% with FPRR ≥ 73.5% → iterate 3D-002 |
| **Ablation readout** | 3D-a vs 3D-001 on TP→FP and FPRR — document in `PHASE3D_ABLATION.md` |

---

## Risk register

| Risk | Mitigation |
|------|------------|
| Constrained pick finds no eligible checkpoint | Relax FPRR floor to 70% for selection only; report test at 73.5% gate |
| Hard-neg oversampling overfits TP track | Cap dup factor; validate on FP-gold FPRR each epoch |
| BL ablation drops too much data | Run 3D-a only after 3D-001 baseline |
| Disk full during vLLM merge | Delete stale `*-vllm-merged`; keep `lora/best` only |
| 6+ JSON parse failures | `rescore_test_eval.py` before final SRS |

---

## Deferred (Phase 3E+)

| Idea | Why deferred |
|------|--------------|
| Ship emits **BL** label | Requires prompt schema, `acceptable_labels`, SRS penalty redesign, teacher re-label |
| DPO / KTO on Stage 2 vs 3C pairs | After 3D SFT plateaus |
| Pareto ensemble (3C FPRR + 3B VDR adapters) | No-retrain baseline; run if 3D-001/002 fail |
| Mixed supervision (80% json + 20% short rationale) | Adds serve mismatch risk |

---

## Commands (placeholder)

```bash
cd /path/to/SAST
source benchmark/phases/phase3/phase3d_env.sh

# Error analysis → hard-neg list
.venv/bin/python benchmark/phases/phase3/analyze_tp_fp_errors.py \
  --eval-root runs/phase3/stage3c/eval \
  --out runs/phase3/stage3d/data/hard_negatives.json

# Full pipeline
bash benchmark/phases/phase3/run_phase3d.sh

# Ablation only
PHASE3D_EXPERIMENT=3d-a PHASE3D_TRAIN_TRACKS=fp,tp bash benchmark/phases/phase3/run_phase3d.sh
```

---

## Artifacts (expected)

| Path | Role |
|------|------|
| `benchmark/phases/phase3/stage3d/MANIFEST.json` | Authoritative config |
| `runs/phase3/stage3d/data/distill_train.jsonl` | Train export |
| `runs/phase3/stage3d/data/hard_negatives.json` | Mined TP→FP neighbors |
| `runs/phase3/stage3d/lora/best` | Global best adapter |
| `runs/phase3/stage3d/summaries/` | Metrics + reports |
| `reports/phase3d/` | Git-friendly publish copy |

---

## References

- `reports/phase3c/PHASE3C_TEST_REPORT.md` — 3C test confusion
- `reports/phase3c/PHASE3C_BL_ANALYSIS.md` — BL train supervision analysis
- `benchmark/phases/phase3/EXPERIMENTS.md` — experiment log
- `runs/phase2/phase2_benchmark_tables/BENCHMARK_RESULTS.html` — leaderboard
