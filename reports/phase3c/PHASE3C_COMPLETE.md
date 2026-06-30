# Phase 3C — Complete Record

**Status:** Complete (ship-aligned distillation)  
**Ship adapter:** `runs/phase3/stage3c/lora/best` (epoch 6, full-val CSS)  
**Infer:** fs0 · thinking off · v7-ship

## Val pick (full 600-case rerank)

| Epoch | Full val CSS | SRS | VDR | FPRR |
| ---: | ---: | ---: | ---: | ---: |
| 6 | 0.8441 | 85.7% | 89.9% | 85.6% |

## Test results (after gap-fill, 6 missing)

See `PHASE3C_TEST_REPORT.md` for full confusion matrix and vs 3B ship.

| Metric | 3C test | 3B ship | Stage 2 |
| --- | ---: | ---: | ---: |
| SRS | 89.9% | 89.9% | 92.5% |
| FPRR | 78.3% | 66.2% | 73.5% |
| VDR | 86.3% | 90.3% | 92.5% |

**Hypothesis:** train/serve alignment closed FPRR gap vs 3B; VDR regression kept aggregate SRS flat. See `PHASE3C_NEXT.md` for 3D plan.

## Key artifacts

| Path | Role |
| --- | --- |
| `runs/phase3/stage3c/lora/best` | Global best LoRA (epoch 6) |
| `runs/phase3/stage3c/data/distill_train.jsonl` | 1283 json_only records |
| `benchmark/phases/phase3/stage3c/PLAN.md` | Design doc |
| `benchmark/phases/phase3/rescore_test_eval.py` | Test gap-fill |
