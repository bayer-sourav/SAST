# Prod ship 600-case test report

**Profile:** `qwen3_5_9b_bnb`

## Merged metrics

| Metric | Value |
|--------|------:|
| **SRS** | **86.1%** |
| FPRR (FP track) | 67.5% |
| VDR (TP track) | 74.6% |
| BL rate (BL-gold track) | 41.5% |
| BL lenient accuracy | 41.5% |
| Macro-F1 | 61.2% |

## Per-track distribution

| Track | Gold | Evaluated | TP | FP | BL | UNKNOWN | Missing |
|-------|------|----------:|---:|---:|---:|--------:|--------:|
| FP | FP | 200 | 53 | 135 | 2 | 10 | 0 |
| TP | TP | 197 | 147 | 43 | 2 | 5 | 3 |
| BL | BL | 200 | 80 | 37 | 83 | 0 | 0 |

JSON: `runs/bl_v4_prod_ship_eval/summaries/merged_600.json`
