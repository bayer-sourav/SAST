# Prod ship 600-case test report

**Profile:** `qwen3_5_9b_bnb`

## Merged metrics

| Metric | Value |
|--------|------:|
| **SRS** | **84.4%** |
| FPRR (FP track) | 67.0% |
| VDR (TP track) | 72.4% |
| BL rate (BL-gold track) | 4.0% |
| BL lenient accuracy | 4.0% |
| Macro-F1 | 47.8% |

## Per-track distribution

| Track | Gold | Evaluated | TP | FP | BL | UNKNOWN | Missing |
|-------|------|----------:|---:|---:|---:|--------:|--------:|
| FP | FP | 200 | 49 | 134 | 1 | 16 | 0 |
| TP | TP | 199 | 144 | 46 | 0 | 9 | 1 |
| BL | BL | 200 | 129 | 60 | 8 | 3 | 0 |

JSON: `runs/v7_balanced_langagnostic_fs3_eval/summaries/merged_600.json`
