# Phase 3D Test Report (600-case Phase 2 test, fs0 off)

Baseline (Phase 2 Stage 2 GOOD): SRS **92.5%** (VDR 92.5%, FPRR 73.5%)

| Metric | Phase 3D (ep6) | Stage 2 baseline | Delta |
| --- | --- | --- | --- |
| FPRR | 77.5% | 73.5% | +4.0pp |
| VDR | 75.0% | 92.5% | -17.5pp |
| SRS | 88.0% | 92.5% | -4.5pp |
| BL lenient | 94.0% | — | — |

**Coverage:** 600/600 (0 missing after compact JSON retry + prose recovery)

**Verdict:** FAIL — SRS below Stage 2; VDR below 85% gate. Val rerank picked checkpoint-850 (epoch 6); test generalization regressed on VDR vs val (90.9% → 75.0%).

See `runs/phase2/phase2_benchmark_tables/BENCHMARK_RESULTS.html` for full cross-stage comparison.
