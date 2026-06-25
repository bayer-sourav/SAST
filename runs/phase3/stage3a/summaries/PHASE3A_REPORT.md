# Phase 3A eval report
Profile: `qwen3_5_9b_bnb` + LoRA adapter (`SAST_LORA_ADAPTER`)
Baseline (Phase 2 Stage 2 GOOD): SRS **92.5%** (VDR 92.5%, FPRR 73.5%)

## Headline metrics

| Metric | Phase 3A | Stage 2 baseline | Delta |
| --- | --- | --- | --- |
| FPRR | 59.4% | 73.5% | -14.1pp |
| VDR | 34.5% | 92.5% | -58.0pp |
| SRS | 70.0% | 92.5% | -22.5pp |

**Verdict:** NOT YET — SRS < Stage 2 baseline.

## Confusion matrix — Phase 3A LoRA (600 cases)

| Gold \ Pred | → TP | → FP | → BL | miss |
| --- | ---: | ---: | ---: | ---: |
| **TP** | 67 | 83 | 44 | 6 |
| **FP** | 25 | 117 | 55 | 3 |
| **BL** | 55 | 87 | 55 | 3 |

- **TP track diagonal:** 67/200 (33.5%) — TP→FP critical: **83**
- **FP track diagonal:** 117/200 (58.5%)
- **BL track diagonal:** 55/200 (27.5%)
- **Missing predictions:** 12

## Confusion matrix — Stage 2 GOOD baseline (5.9b_fs3_legacy)

| Gold \ Pred | → TP | → FP | → BL | miss |
| --- | ---: | ---: | ---: | ---: |
| **TP** | 185 | 14 | 1 | 0 |
| **FP** | 53 | 147 | 0 | 0 |
| **BL** | 174 | 26 | 0 | 0 |

- **TP track diagonal:** 185/200 (92.5%) — TP→FP critical: **14**
- **FP track diagonal:** 147/200 (73.5%)
- **BL track diagonal:** 0/200 (0.0%)

## Critical misclassifications vs Stage 2 GOOD

| Transition | Stage 2 GOOD | Phase 3A | Δ |
| --- | ---: | ---: | ---: |
| TP→FP (missed vuln) | 14 | 83 | +69 |
| BL→FP (over-dismiss) | 26 | 87 | +61 |
| FP→TP (noise kept) | 53 | 25 | -28 |

Full three-way comparison (Stage 2 GOOD · Phase 2 MINIMUM · Phase 3A) is in `runs/phase2/phase2_benchmark_tables/BENCHMARK_RESULTS.html` and `runs/phase2/phase2_benchmark_tables/benchmark_confusion_comparison.json`.
