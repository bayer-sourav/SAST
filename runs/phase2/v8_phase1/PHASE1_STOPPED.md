# v8 Phase 1 — stopped (July 2026)

**Decision:** Stop further Phase 1 prompt/few-shot ablations. Do **not** treat further gains on the 600-case held-out set as ship decisions.

## Why stop

Smoke (1A) and the single 600-case commit (1B) already used the **same held-out Phase 2 test tracks** (hard-slice ⊂ 600-case FP/TP). Continuing ablations (`8B-vdr-fs3` full, 8D/8E, ensembles) would optimize hyperparameters on the test set and inflate reported VDR/FPRR/SRS.

**Ship config remains:** `v8-ship-bl` · fs4 `v2_4shot_tp_fp_bl2` · **thinking ON** (unchanged prod ship from BL v4 calibration). The `8C-think-off` 600-case run is an **exploratory measurement only**, not a new ship candidate.

## What was run

### 1A — Hard-slice smoke (20 cases)

| Cell | VDR | FPRR | Total | Smoke pass |
|------|----:|-----:|------:|:----------:|
| 8C-think-off | 9/10 | 7/10 | 16/20 | no |
| 8B-vdr-fs3 | 8/10 | 8/10 | 16/20 | no |
| 8B-bl-fs3 | 8/10 | 6/10 | 14/20 | no |
| 8A-baseline | 8/10 | 5/10 | 13/20 | no |

Report: `PHASE1_SMOKE_REPORT.md`

### 1B — 600-case exploratory (`8C-think-off` only)

| Metric | Gate | 8C think-off | v8 ship (think-on) |
|--------|------|-------------:|-------------------:|
| VDR | ≥85% | 79.4% | 74.6% |
| FPRR | ≥70% | 66.8% | 67.5% |
| SRS | ≥88% | 87.4% | 86.1% |
| BL rate | ≥35% | 41.5% | 41.5% |
| TP→FP | ≤25 | 35 | 43 |

Gates **not met**. Think-off looks slightly better on VDR/SRS in this single measurement; **not** promoted.

Report: `8C-think-off/full_600/PROD_SHIP_600_REPORT.md`

## Process note (for any future work)

- Use a **dev/val** slice for prompt/few-shot/thinking choices; freeze config; evaluate **once** on the 600-case test.
- Prefer integration/Bayer E2E or train/val preference tuning over more test-set cells.
- Deferred 1C / further 600-case cells: **cancelled** under this stop.

## Artifact index

| Artifact | Path |
|----------|------|
| Plan (stopped) | `benchmark/phases/phase2/v8_phase1/PLAN.md` |
| Smoke summary | `runs/phase2/v8_phase1/PHASE1_SMOKE_SUMMARY.json` |
| 8C 600 merged | `runs/phase2/v8_phase1/8C-think-off/full_600/summaries/merged_600.json` |
| BL calibration context | `benchmark/phases/phase2/BL_V4.md` |
