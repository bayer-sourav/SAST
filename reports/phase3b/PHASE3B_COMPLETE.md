# Phase 3B — Complete Record

**Status:** Primary path complete (distilled LoRA r=32)  
**Ship adapter:** `runs/phase3/stage3b/lora/best_fs0_off` (epoch 4, val rerank)  
**Next:** Phase 3C — fs0-aligned retrain to close FPRR gap vs Stage 2

## Headline test results (600-case holdout)

| Config | Epoch | SRS | FPRR | VDR | Missing | TP→FP |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fs3 + CoT (teacher-matched) | 6 | 84.1% | 71.5% | 83.2% | 36 | 32 |
| fs0 direct (ep6 adapter) | 6 | 88.7% | 58.7% | 89.2% | 12 | 17 |
| fs0 ship (rerank pick) | 4 | 89.9% | 66.2% | 90.3% | 13 | 17 |

**Stage 2 baseline:** SRS 92.5% · **Best ship:** SRS 89.9% (-2.6pp) · main gap is **FPRR** (66.2% vs 73.5%)

## Checkpoint selection

- **Training CSS (fs3+CoT val):** epoch 6 · CSS 0.851
- **Ship rerank (fs0_off val):** epoch 4 · val SRS 90.8%

## Artifacts in this folder

| File | Description |
| --- | --- |
| `PHASE3B_COMPLETE.md` | This document |
| `PHASE3B_BENCHMARK.html` | CSS + confusion matrices |
| `PHASE3B_ABLATIONS_REPORT.md` | Inference ablation table |
| `PHASE3B_TEST_REPORT.md` | fs3-on primary test report |
| `PHASE3B_FS0_OFF_BEST_TEST.md` | Ship config test summary |
| `css_fs0_off_rerank.json` | Val rerank per epoch |
| `comparison_*_phase3a*.json` | Track-level test metrics |

## Regenerate

```bash
cd /path/to/SAST
./benchmark/phases/phase3/rebuild_benchmarks.sh
```
