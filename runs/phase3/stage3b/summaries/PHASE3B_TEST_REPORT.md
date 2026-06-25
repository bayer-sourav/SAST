# Phase 3B test eval report
Profile: `qwen3_5_9b_bnb` + LoRA (`runs/phase3/stage3b/lora/best`)
Baseline (Phase 2 Stage 2 GOOD): SRS **92.5%** (VDR 92.5%, FPRR 73.5%)

## Headline metrics

| Metric | Phase 3B test | Stage 2 baseline | Delta |
| --- | --- | --- | --- |
| FPRR | 71.5% | 73.5% | -2.0pp |
| VDR | 83.2% | 92.5% | -9.3pp |
| SRS | 84.1% | 92.5% | -8.4pp |

## Coverage

| Track | Coverage | Missing |
| --- | ---: | ---: |
| FP | 93.0% | 14 |
| TP | 95.0% | 10 |
| BL | 94.0% | 12 |

**Verdict:** NOT YET — SRS < Stage 2 baseline.

## Confusion matrix — Phase 3B LoRA (600 cases)

| Gold \ Pred | → TP | → FP | → BL | miss |
| --- | ---: | ---: | ---: | ---: |
| **TP** | 158 | 32 | 0 | 10 |
| **FP** | 50 | 133 | 3 | 14 |
| **BL** | 168 | 20 | 0 | 12 |

- **TP track diagonal:** 158/200 (79.0%) — TP→FP critical: **32**
- **FP track diagonal:** 133/200 (66.5%)
- **BL track diagonal:** 0/200 (0.0%)
- **Missing predictions:** 36

## Confusion matrix — Stage 2 GOOD baseline

| Gold \ Pred | → TP | → FP | → BL | miss |
| --- | ---: | ---: | ---: | ---: |
| **TP** | 185 | 14 | 1 | 0 |
| **FP** | 53 | 147 | 0 | 0 |
| **BL** | 174 | 26 | 0 | 0 |

- **TP track diagonal:** 185/200 (92.5%) — TP→FP critical: **14**
- **FP track diagonal:** 147/200 (73.5%)
- **BL track diagonal:** 0/200 (0.0%)

## Critical misclassifications vs Stage 2 GOOD

| Transition | Stage 2 GOOD | Phase 3B | Δ |
| --- | ---: | ---: | ---: |
| TP→FP (missed vuln) | 14 | 32 | +18 |
| BL→FP (over-dismiss) | 26 | 20 | +-6 |
| FP→TP (noise kept) | 53 | 50 | -3 |
