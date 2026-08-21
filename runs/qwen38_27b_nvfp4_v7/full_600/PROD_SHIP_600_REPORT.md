# Prod ship 600-case test report

**Profile:** `qwen3_8_27b_nvfp4`

## Merged metrics

| Metric | Value |
|--------|------:|
| **SRS** | **87.0%** |
| FPRR (FP track) | 77.3% |
| VDR (TP track) | 81.9% |
| BL rate (BL-gold track) | 16.0% |
| BL lenient accuracy | 16.0% |
| Macro-F1 | 58.4% |

## Per-track distribution

| Track | Gold | Evaluated | TP | FP | BL | UNKNOWN | Missing |
|-------|------|----------:|---:|---:|---:|--------:|--------:|
| FP | FP | 198 | 44 | 153 | 0 | 1 | 2 |
| TP | TP | 199 | 163 | 35 | 0 | 1 | 1 |
| BL | BL | 200 | 111 | 51 | 32 | 6 | 0 |

JSON: `runs/qwen38_27b_nvfp4_v7/full_600/summaries/merged_600.json`
