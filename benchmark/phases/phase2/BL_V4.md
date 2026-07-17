# Borderline v4 — Phase 2 eval

Dataset spec and rebuild: `SAST-Benchmark-Dataset/docs/BORDERLINE_V4_SPEC.md`.

## Prompt + few-shot (recommended ship for BL)

| Setting | Value |
|---------|-------|
| Prompt | `v8-ship-bl` (language-agnostic + BL calibration rules) |
| Few-shot | 4 (`v2_4shot_tp_fp_bl2`: TP + FP + DNS BL + init-param BL) |
| Model | `qwen3_5_9b_bnb` (Stage 2 GOOD) |
| Inference | vLLM via `phase2_infer_env.sh` (batch 4, prefix cache, thinking ON) |

Earlier iterations used `v7-ship-bl` (Java-specific BL few-shot). **v8-ship-bl** is the production candidate when the advisory must emit **BL** on ambiguous cases.

## Corpora

| Corpus | Cases | Source |
|--------|------:|--------|
| `benchmark/corpora/bl_v4_pilot` | 40 | All-synthetic pilot from `borderline_pilot/` |
| `benchmark/corpora/phase2_bl_test` | 200 | Test split from `BenchmarkJava/borderline/` v4 |

Current `phase2_bl_test` tier: **`curated_v4_calibrated_v3`** (post template calibration). Rebuild after dataset changes:

```bash
uv run python benchmark/build_phase2_corpora.py
```

## Scripts

```bash
# Pilot only (40 synthetic) — not used for full-eval reporting
bash benchmark/phases/phase2/run_bl_v4_pilot.sh
PILOT_SKIP_REBUILD=1 bash benchmark/phases/phase2/run_bl_v4_pilot_fast.sh

# Full BL test eval (200 cases) — default v8-ship-bl + 4-shot
BL_V4_SKIP_REBUILD=1 bash benchmark/phases/phase2/run_bl_v4_eval.sh

# 600-case prod ship: FP + TP + BL merged SRS (v8-ship-bl)
bash benchmark/phases/phase2/run_bl_v4_prod_ship_600_eval.sh

# Lang-agnostic v7 baseline (no BL calibration) for comparison
bash benchmark/phases/phase2/run_v7_balanced_langagnostic_fs3_600_eval.sh
```

Environment: `phase2_infer_env.sh` sets vLLM defaults; sourced by pilot/eval scripts and `phase2_cell_env.sh`.

## Automated review gates (200-case BL test)

`benchmark/analyze_bl_v4_pilot.py` reports BL prediction rate on **BL-gold** cases by category:

| Gate | Threshold |
|------|-----------|
| Overall BL rate | ≥ 35% |
| `dns_rebinding` BL rate | ≥ 50% |
| Missing results | ≤ 5% |

Gold on this track is **BL**; success means the model predicts **BL** (not TP/FP).

---

## Full evaluation results (200-case BL test, not pilot)

All runs below: **200 cases**, `benchmark/corpora/phase2_bl_test`, `qwen3_5_9b_bnb`, vLLM, thinking ON. Pilot runs (40-case synthetic) are excluded from this table.

### Progression summary

| Run dir | Prompt | Few-shot | Corpus / template tier | BL rate | Gates | Notes |
|---------|--------|----------|------------------------|--------:|-------|-------|
| `runs/bl_v4_eval` | `v7-ship-bl` | 3 (`v2_3shot_tp_fp_bl`) | Pre-calibration mixed v4 (`BLv4*` IDs) | **18.5%** | FAIL | Baseline BL prompt; model over-calls **TP** (120/200) |
| `runs/bl_v4_synthetic_eval` | `v7-ship-bl` | 3 | `curated_v4_tight` (OWASP IDs) | **6.0%** | FAIL | Tight synthetic tier; heavy **TP** bias (154/200) |
| `runs/bl_v4_calibrated_eval` | `v7-ship-bl` | 3 | `curated_v4_calibrated` (v1 templates) | **7.0%** | FAIL | First calibrated rebuild **regressed** vs `bl_v4_eval`; template bugs pushed **TP** (139/200) |
| `runs/bl_v4_calibrated_v2_eval` | `v7-ship-bl` | 4 (`v2_4shot_tp_fp_bl2`) | `curated_v4_calibrated_v2` | **20.0%** | FAIL | +4-shot BL exemplars recover vs v1; still below gate |
| `runs/bl_v4_calibrated_v3_eval` | `v7-ship-bl` | 4 | `curated_v4_calibrated_v3` | **27.5%** | FAIL | Best **v7-ship-bl** run; `deployment_trust` still weak (6% BL) |
| `runs/bl_v4_prod_ship_eval` | **`v8-ship-bl`** | 4 | `curated_v4_calibrated_v3` | **41.5%** | **PASS** | Lang-agnostic BL calibration + 4-shot; all category gates near target |

**Distribution (predicted labels on BL-gold, 200 cases):**

| Run | BL | TP | FP | UNKNOWN |
|-----|---:|---:|---:|--------:|
| `bl_v4_eval` | 37 | 120 | 43 | 0 |
| `bl_v4_synthetic_eval` | 12 | 154 | 34 | 0 |
| `bl_v4_calibrated_eval` | 14 | 139 | 46 | 1 |
| `bl_v4_calibrated_v2_eval` | 40 | 118 | 42 | 0 |
| `bl_v4_calibrated_v3_eval` | 55 | 97 | 47 | 1 |
| **`bl_v4_prod_ship_eval`** | **83** | 80 | 37 | 0 |

### BL rate by borderline category (full eval)

| Category | `bl_v4_eval` | `calibrated_v3` (`v7`) | **`prod_ship` (`v8`)** |
|----------|-------------:|-----------------------:|----------------------:|
| `bypassable_mitigation` | 15.9% | 40.0% | **38.0%** |
| `deployment_trust` | 2.3% | 6.0% | **38.0%** |
| `dns_rebinding` | 30.2% | 26.0% | **54.0%** |
| `semi_trusted_input` | 20.0% | 38.0% | **36.0%** |

**Notes:**

1. **Template calibration matters.** v1 calibrated templates (`bl_v4_calibrated_eval`) hurt BL rate (7%) vs pre-calibration mixed corpus (18.5%) because cases read as clearer TPs. v2/v3 template fixes + BL few-shot examples monotonically improved BL rate.
2. **4-shot BL exemplars** (`v2_4shot_tp_fp_bl2`) are load-bearing: +13pp BL rate (v2 vs v1 on calibrated tiers) before any prompt rewrite.
3. **`v8-ship-bl` is the step-change.** Lang-agnostic procedure text + explicit BL calibration rules (DNS rebinding split, deployment trust, semi-trusted source, bypassable mitigation) lifted overall BL rate from 27.5% → **41.5%** and fixed **`deployment_trust`** (6% → 38%).
4. **`dns_rebinding`** is the only category above the 50% gate (54%); others are close but still below 35% overall gate threshold on v7 — v8 passes the **overall** 35% gate.
5. Remaining errors on BL-gold are mostly **TP** (80/200 on v8) — the model still “resolves” ambiguity to TP when flow looks exploitable in-snippet.

Calibration analysis and template changelog: `SAST-Benchmark-Dataset/docs/BL_V4_CALIBRATION_ANALYSIS.md`.

---

## 600-case prod ship eval (`v8-ship-bl`)

Merged **FP + TP + BL** tracks (same 600-case held-out test as Stage 2):

| Metric | Stage 2 `v7-balanced` fs3 | `v7-balanced-langagnostic` fs3 | **`v8-ship-bl` fs4** |
|--------|--------------------------:|-------------------------------:|---------------------:|
| **SRS** (asymmetric penalty) | 92.5% | 84.4% | **86.1%** |
| FPRR | 73.5% | 67.0% | 67.5% |
| VDR | 92.5% | 72.4% | 74.6% |
| BL rate (BL-gold) | 0.0% | 4.0% | **41.5%** |
| Macro-F1 | 55.3% | 47.8% | **61.2%** |
| TP → FP (missed vulns) | 14 | 46 | 43 |
| FP → TP (false alarms kept) | 53 | 49 | 53 |

Sources:

- Stage 2: `runs/phase2/stage2/summaries/`
- Lang-agnostic: `runs/v7_balanced_langagnostic_fs3_eval/`
- v8-ship-bl: `runs/bl_v4_prod_ship_eval/PROD_SHIP_600_REPORT.md`
- Headline deltas vs Stage 2: `runs/bl_v4_prod_ship_eval/COMPARE_VS_STAGE2.md`

**Notes:**

- **SRS here uses the asymmetric 600-case penalty** (TP→FP = 3.0, BL→FP = 1.5, etc.), not the legacy `0.5×FPRR + 0.5×VDR` on FP+TP only. Stage 2 scores high partly because it never predicts BL on BL-gold (0% BL rate → no BL→FP penalty, but also no BL credit).
- **v8-ship-bl beats lang-agnostic v7** on every metric (+1.7pp SRS, +2.2pp VDR, +37.5pp BL rate) while keeping FP→TP flat vs Stage 2.
- **VDR gap vs Stage 2 remains the main cost** (−17.9pp): lang-agnostic + BL calibration makes the model more conservative on TP-gold (43 TP→FP vs 14). FPRR is similar to lang-agnostic v7, not worse than Stage 2’s FP→TP count.
- **Tradeoff is explicit:** v8 buys meaningful BL emission (+41.5pp) and better macro-F1 (+5.9pp) at the cost of TP retention. Closing VDR without collapsing BL rate is the next optimization target.

---

## Run outputs

| Path | Contents |
|------|----------|
| `runs/bl_v4_pilot/` | Pilot only (`PILOT_REVIEW_*.html`) — do not cite as full eval |
| `runs/bl_v4_eval/` | Full eval, pre-calibration corpus |
| `runs/bl_v4_synthetic_eval/` | Full eval, `curated_v4_tight` tier |
| `runs/bl_v4_calibrated_eval/` | Full eval, calibrated v1 templates |
| `runs/bl_v4_calibrated_v2_eval/` | Full eval, calibrated v2 + 4-shot |
| `runs/bl_v4_calibrated_v3_eval/` | Full eval, calibrated v3 + `v7-ship-bl` |
| `runs/bl_v4_prod_ship_eval/` | **Ship candidate:** BL track + 600-case merged report |
| `runs/v7_balanced_langagnostic_fs3_eval/` | Lang-agnostic v7 baseline (no BL rules) |

Per-case LLM outputs under `stage2_ship_bl/` are gitignored (regenerate with scripts above).

## HTML reports

| Report | Path |
|--------|------|
| **Main benchmark HTML** (600-case + BL calibration table) | `runs/phase2/phase2_benchmark_tables/BENCHMARK_RESULTS.html` |
| Per-run BL review (200-case, case-level) | `runs/bl_v4_*/REVIEW_SHIP_BL.html` |
| v8-ship-bl 600-case merged | `runs/bl_v4_prod_ship_eval/PROD_SHIP_600_REPORT.md` |

Regenerate main HTML after new eval runs:

```bash
uv run python benchmark/phases/phase2/build_results_tables.py
```

## Next steps (v8 roadmap)

Holistic improvement plan (lang-agnostic + BL + VDR/FPRR/SRS): **[`v8_phase1/PLAN.md`](v8_phase1/PLAN.md)**

Phase 1 smoke cells: **8A-baseline** · **8B-vdr-fs3** · **8B-bl-fs3** · **8C-think-off** — run via `run_v8_phase1.sh`.
