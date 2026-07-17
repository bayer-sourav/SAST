# v8-ship-bl fs4 vs Stage 2 baseline

**Profile:** `qwen3_5_9b_bnb` · **600 cases** (200 FP + 200 TP + 200 BL)

## Headline comparison

| Metric | Stage 2 v7-balanced fs3 | v8-ship-bl fs4 (lang-agnostic) | Δ |
|--------|------:|------:|----:|
| **SRS** | 92.5% | 86.1% | **-6.4pp** |
| **FPRR** | 73.5% | 67.5% | **-6.0pp** |
| **VDR** | 92.5% | 74.6% | **-17.9pp** |
| **BL rate (BL-gold)** | 0.0% | 41.5% | **+41.5pp** |
| **Macro-F1** | 55.3% | 61.2% | **+5.9pp** |

## Critical confusion (lower is better)

| Error | Stage 2 | v8-ship-bl | Δ |
|-------|--------:|--------------:|----:|
| TP → FP (missed vulns) | 14 | 43 | +29 |
| FP → TP (false alarms kept) | 53 | 53 | +0 |

JSON: `runs/bl_v4_prod_ship_eval/summaries/compare_vs_stage2.json`
