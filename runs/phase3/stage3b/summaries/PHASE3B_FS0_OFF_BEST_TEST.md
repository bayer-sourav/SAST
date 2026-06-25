# Phase 3B ship test — fs0_off rerank pick

**Adapter:** epoch **4** (`runs/phase3/stage3b/lora/best_fs0_off`)  
**Infer:** zero-shot · thinking off · v7-ship  
**Val pick:** SRS 90.8% on 600-case validation

Baseline (Phase 2 Stage 2 GOOD): SRS **92.5%** (VDR 92.5%, FPRR 73.5%)

## Headline metrics

| Metric | Phase 3B ship | Stage 2 baseline | Delta |
| --- | --- | --- | --- |
| SRS | 89.9% | 92.5% | -2.6pp |
| VDR | 90.3% | 92.5% | -2.2pp |
| FPRR | 66.2% | 73.5% | -7.3pp |

## Coverage

| Track | Coverage | Missing |
| --- | ---: | ---: |
| FP | 97.5% | 5 |
| TP | 97.5% | 5 |
| BL | 98.5% | 3 |

**Verdict:** NOT YET — ship SRS < Stage 2 baseline.

## Confusion matrix — Phase 3B ship (600 cases)

| Gold \ Pred | → TP | → FP | → BL | miss |
| --- | ---: | ---: | ---: | ---: |
| **TP** | 176 | 17 | 2 | 5 |
| **FP** | 63 | 129 | 3 | 5 |
| **BL** | 180 | 16 | 1 | 3 |

- **TP→FP critical:** 17
- **Missing predictions:** 13

## vs fs3-on test (epoch 6, teacher-matched infer)

Train/serve mismatch: model distilled with fs3+CoT but deployed fs0+direct. Reranking checkpoints under ship infer improves SRS ~6pp vs fs3-on test and ~1pp vs fs0 on ep6.
