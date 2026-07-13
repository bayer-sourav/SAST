# Lang-agnostic v7-balanced fs3 vs Stage 2 baseline

**Profile:** `qwen3_5_9b_bnb` · **600 cases** (200 FP + 200 TP + 200 BL)

## Headline comparison

| Metric | Stage 2 Java v7-balanced fs3 | Lang-agnostic v7-balanced fs3 | Δ |
|--------|------:|------:|----:|
| **SRS** | 92.5% | 84.4% | **-8.1pp** |
| **FPRR** | 73.5% | 67.0% | **-6.5pp** |
| **VDR** | 92.5% | 72.4% | **-20.1pp** |
| **BL rate (BL-gold)** | 0.0% | 4.0% | **+4.0pp** |
| **Macro-F1** | 55.3% | 47.8% | **-7.5pp** |

## Critical confusion (lower is better)

| Error | Stage 2 | Lang-agnostic | Δ |
|-------|--------:|--------------:|----:|
| TP → FP (missed vulns) | 14 | 46 | +32 |
| FP → TP (false alarms kept) | 53 | 49 | -4 |

JSON: `runs/v7_balanced_langagnostic_fs3_eval/summaries/compare_vs_stage2.json`
