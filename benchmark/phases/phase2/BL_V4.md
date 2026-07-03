# Borderline v4 — Phase 2 eval

Dataset spec and rebuild: `SAST-Benchmark-Dataset/docs/BORDERLINE_V4_SPEC.md`.

## Prompt + few-shot (recommended)

| Setting | Value |
|---------|-------|
| Prompt | `v7-ship-bl` (language-agnostic + BL calibration) |
| Few-shot | `v2_3shot_tp_fp_bl` (3-shot: TP + FP + BL exemplar) |
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

Full test (200, stratified v4 mix): **18.5% BL** — gates fail; model still collapses to TP/FP on many synthetic deployment/dns cases. See `runs/bl_v4_eval/review_ship_bl.json`.

## Run outputs

| Path | Contents |
|------|----------|
| `runs/bl_v4_pilot/` | Pilot reviews (`PILOT_REVIEW_*.html`, `pilot_review_*.json`) |
| `runs/bl_v4_eval/` | Full eval review (`REVIEW_SHIP_BL.html`, `review_ship_bl.json`) |

Per-case LLM outputs under `stage2_*/` are gitignored (regenerate with scripts above).
