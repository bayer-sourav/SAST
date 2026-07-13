# Borderline v4 — Phase 2 eval

Dataset spec and rebuild: `SAST-Benchmark-Dataset/docs/BORDERLINE_V4_SPEC.md`.

## Prompt + few-shot (recommended)

| Setting | Value |
|---------|-------|
| Prompt | `v8-ship-bl` (language-agnostic + BL calibration) |
| Few-shot | 4 (`v2_4shot_tp_fp_bl2`: TP + FP + DNS BL + init-param BL) |
| Model | `qwen3_5_9b_bnb` (Stage 2 GOOD) |
| Inference | vLLM via `phase2_infer_env.sh` (batch 4, prefix cache) |

Alternatives tested in pilot: `v7-balanced-bl` (Java-specific + BL few-shot).

## Corpora

| Corpus | Cases | Source |
|--------|------:|--------|
| `benchmark/corpora/bl_v4_pilot` | 40 | All-synthetic pilot from `borderline_pilot/` |
| `benchmark/corpora/phase2_bl_test` | 200 | Test split from `BenchmarkJava/borderline/` v4 |

Refresh phase2 test corpora after dataset rebuild:

```bash
uv run python benchmark/build_phase2_corpora.py
```

## Scripts

```bash
# Pilot: build dataset bundles → infer → HTML review
bash benchmark/phases/phase2/run_bl_v4_pilot.sh

# Fast feedback loop (~20–30 min, 40 cases; skip rebuild after template edits)
PILOT_SKIP_REBUILD=1 bash benchmark/phases/phase2/run_bl_v4_pilot_fast.sh

# Full test eval (200 cases)
BL_V4_SKIP_REBUILD=1 bash benchmark/phases/phase2/run_bl_v4_eval.sh

# Resume partial pilot runs (sequential GPU jobs)
bash benchmark/phases/phase2/run_bl_v4_pilot_chain.sh
```

Environment: `phase2_infer_env.sh` sets vLLM defaults; sourced by pilot/eval scripts and `phase2_cell_env.sh`.

## Automated review gates (pilot)

`benchmark/analyze_bl_v4_pilot.py` reports BL prediction rate by category:

- Overall BL rate ≥ 35%
- `dns_rebinding` BL rate ≥ 50%
- Missing results ≤ 5%

Pilot (40 synthetic, `v7-ship-bl`): **PASS** (40% BL).

| Run | Corpus tier | BL rate | Gates |
|-----|-------------|--------:|-------|
| `runs/bl_v4_eval` | mixed v4 test | 18.5% | FAIL |
| `runs/bl_v4_synthetic_eval` | `curated_v4_tight` (OWASP IDs) | 6% | FAIL |
| `runs/bl_v4_calibrated_eval` | `curated_v4_calibrated` | **7%** | FAIL |
| `runs/bl_v4_pilot_fast_v2` | `curated_v4_calibrated_v2` + 4-shot | **25%** (pilot) | FAIL |

Calibration analysis and template fixes: `SAST-Benchmark-Dataset/docs/BL_V4_CALIBRATION_ANALYSIS.md`.

Full test (200, stratified v4 mix): see `runs/bl_v4_eval/review_ship_bl.json` and calibrated re-run under `runs/bl_v4_calibrated_eval/`.

## Run outputs

| Path | Contents |
|------|----------|
| `runs/bl_v4_pilot/` | Pilot reviews (`PILOT_REVIEW_*.html`, `pilot_review_*.json`) |
| `runs/bl_v4_eval/` | Full eval review (`REVIEW_SHIP_BL.html`, `review_ship_bl.json`) |
| `runs/bl_v4_calibrated_eval/` | Post-calibration re-eval (`curated_v4_calibrated` templates) |

Per-case LLM outputs under `stage2_*/` are gitignored (regenerate with scripts above).
