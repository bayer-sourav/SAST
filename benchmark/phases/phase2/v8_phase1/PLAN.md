# v8-ship-bl roadmap — lang-agnostic + BL + holistic metrics

**Goal:** Improve **VDR, FPRR, and SRS** without sacrificing **TP retention (TPRR)**, while **emitting BL** on ambiguous cases and staying **language-agnostic** for multi-language codebases.

**Status:** Phase 1 **STOPPED** (July 2026) — no further test-set prompt ablations.

**Why:** 1A/1B already peeked at held-out Phase 2 tracks. More cells would overfit the 600-case test. Ship stays **`v8-ship-bl` fs4 thinking ON**. Closure write-up: [`runs/phase2/v8_phase1/PHASE1_STOPPED.md`](../../../runs/phase2/v8_phase1/PHASE1_STOPPED.md).

**Smoke (1A):** No cell passed gates. Best: **8C-think-off** 16/20. See `PHASE1_SMOKE_REPORT.md`.

**1B exploratory only (`8C-think-off`):** VDR **79.4%** · FPRR **66.8%** · SRS **87.4%** · BL **41.5%** · TP→FP **35**. Gates not met; **not shipped**.

---

## Where we are today

| Config | Scope | VDR | FPRR | SRS* | BL rate (BL-gold) | TP→FP |
|--------|------:|----:|-----:|-----:|------------------:|------:|
| Stage 2 · `v7-balanced` fs3 (Java) | 600 | **92.5%** | **73.5%** | 92.5% | 0% | 14 |
| `v7-balanced-langagnostic` fs3 | 600 | 72.4% | 67.0% | 84.4% | 4% | 46 |
| **`v8-ship-bl` fs4 (current ship)** | 600 | 74.6% | 67.5% | **86.1%** | **41.5%** | 43 |
| 8C-think-off (exploratory; not ship) | 600 | 79.4% | 66.8% | 87.4% | 41.5% | 35 |
| Phase 3C LoRA (v7-ship train) | 600 | 86.3% | 78.3% | 89.9% | 0% | 27 |

\*600-case asymmetric SRS (`benchmark/srs.py`).

**Binding constraint:** v8 buys BL (+41.5pp) and beats lang-agnostic v7 on all metrics, but **VDR is −17.9pp vs Stage 2** (43 TP→FP vs 14). Phase 1 prompt work is **stopped** (test-set leak); ship stays v8 think-on until a proper train/val protocol exists.

**References:**

- BL calibration eval: [`../BL_V4.md`](../BL_V4.md)
- HTML leaderboard: `runs/phase2/phase2_benchmark_tables/BENCHMARK_RESULTS.html`
- Phase 3 analysis: `reports/phase3c/PHASE3C_NEXT.md`

---

## Phase 1 — Prompt ablations (no training)

**Objective:** Recover **VDR ≥ 85%** and **FPRR ≥ 70%** on 600-case test while keeping **BL rate ≥ 35%** on the 200-case BL track.

**Base stack:** `qwen3_5_9b_bnb` · vLLM · `v8-ship-bl` prompt · thinking ON (unless cell says off).

### 1A — Hard-slice smoke (20 cases: 10 TP + 10 FP)

Fast regression before committing to 600-case runs (~1–2 h for all cells).

| Cell ID | Few-shot | Config | Thinking | Hypothesis |
|---------|----------|--------|----------|------------|
| **8A-baseline** | 4 | `v2_4shot_tp_fp_bl2` | on | Current prod ship (BL calibration + BL exemplars) |
| **8B-vdr-fs3** | 3 | `v2_3shot_tp_2fp` | on | Stage 2 VDR-first layout under v8 BL text |
| **8B-bl-fs3** | 3 | `v2_3shot_tp_fp_bl` | on | Fewer shots, one BL exemplar |
| **8C-think-off** | 4 | `v2_4shot_tp_fp_bl2` | off | CoT may hurt VDR when BL rules add structure |

**Smoke gates** (`MANIFEST.json`): VDR ≥ 9/10 · FPRR ≥ 7/10 · total ≥ 17/20 · missing = 0.

```bash
# All smoke cells
bash benchmark/phases/phase2/run_v8_phase1.sh

# One cell only
PHASE1_CELL=8B-vdr-fs3 bash benchmark/phases/phase2/run_v8_phase1.sh

# Force re-run
PHASE1_FORCE=1 bash benchmark/phases/phase2/run_v8_phase1.sh
```

**Outputs:** `runs/phase2/v8_phase1/PHASE1_SMOKE_REPORT.md` · `PHASE1_SMOKE_SUMMARY.json`

### 1B — 600-case commit (best smoke passer)

Only run when at least one cell passes smoke gates.

```bash
PHASE1_FULL=1 PHASE1_CELL=8B-vdr-fs3 bash benchmark/phases/phase2/run_v8_phase1.sh
# or omit PHASE1_CELL to auto-pick first passer from smoke summary
```

**600-case success gates:**

| Gate | Target |
|------|--------|
| VDR | ≥ **85%** (stretch: 90%) |
| FPRR | ≥ **70%** |
| BL rate (200 BL test) | ≥ **35%** |
| TP → FP | ≤ **25** (from 43) |
| SRS (600) | ≥ **88%** (stretch: beat 89.9% Phase 3C) |

### 1C — Cancelled (test-set stop)

Further cells (8D, 8E, ensemble, additional 600-case commits) **cancelled**. Any future tuning must use a **dev/val** split and a single frozen eval on the 600-case test.

---

## Phase 2 — Integration & real-world validation

**Objective:** Validate chosen Phase 1 config on **production path** before more research spend.

| Step | Action |
|------|--------|
| 2.1 | Update **SAST-Integration** `MANIFEST.json` → winning `v8-ship-bl` cell (prompt, fs, thinking) |
| 2.2 | E2E test: Bayer SARIF → ALB → worker → JSON (TP / FP / **BL**) |
| 2.3 | Compare vs Stage 2 v7 on same SARIF sample (qualitative + error taxonomy) |
| 2.4 | Confirm advisory schema/UI accepts **BL** label end-to-end |

**Gate:** Real cases do not show worse TP retention than benchmark delta suggests; BL labels are actionable for reviewers.

---

## Phase 3 — Training (only after Phase 1 plateaus)

**Objective:** Beat **Stage 2 TP/FP** and **Phase 3C LoRA** while preserving **BL emission**.

| Item | Choice |
|------|--------|
| Train/serve prompt | **`v8-ship-bl`** (not v7-ship) |
| Teacher | v8-ship-bl or hybrid (v7 teacher on clear TP/FP only) |
| First bet | **Phase 3E preference tuning** (DPO/KTO) on v8 error pairs |
| Control | **3D-a** — train FP+TP only, no BL (does BL train blur TP/FP?) |
| Avoid | Full SFT on BL-gold with contradictory Stage 2 teacher |

**Preference pairs (examples):**

- BL-gold → model said **TP** → reject
- TP-gold → model said **FP** → reject
- BL-gold → model said **FP** → reject (over-dismiss)

**Success gates:** Same as Phase 1B 600-case table; **TP→FP ≤ 17** (Stage 2 parity).

---

## Phase 4 — Multi-language validation

**Objective:** Confirm lang-agnostic prompt generalizes beyond Java CodeQL benchmark.

| Step | Action |
|------|--------|
| 4.1 | Add Node/Python (or Bayer) CodeQL slices when corpora exist |
| 4.2 | 50-case smoke per language with frozen Phase 1/2 ship config |
| 4.3 | Phase 3B-style translation augmentation only if prompt-only gap remains |

---

## Decision log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-07 | Ship research on **`v8-ship-bl`**, not v7 lang-agnostic | v8 dominates BL + SRS vs lang-agnostic v7 |
| 2026-07 | Phase 1 before LoRA | 3C plateau at 89.9% SRS; VDR gap is prompt-level on v8 |
| 2026-07 | No “stage3e SFT on v4 BL data” | Teacher contradicts BL-gold; ship eval was TP/FP-only in 3C |
| 2026-07-14 | **Stop Phase 1 ablations** | Optimizing on held-out 600/smoke leaks test signal; ship stays think-on v8 |

---

## Artifact index

| Artifact | Path |
|----------|------|
| This plan | `benchmark/phases/phase2/v8_phase1/PLAN.md` |
| Stop / results | `runs/phase2/v8_phase1/PHASE1_STOPPED.md` |
| Phase 1 manifest | `benchmark/phases/phase2/v8_phase1/MANIFEST.json` |
| Phase 1 runner | `benchmark/phases/phase2/run_v8_phase1.sh` |
| Smoke scorer | `benchmark/phases/phase2/summarize_v8_phase1.py` |
| Hard slice cases | `benchmark/phases/phase2/smoke_slice_cases.json` |
| Phase 1 runs | `runs/phase2/v8_phase1/` |
