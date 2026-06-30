# Phase 3C test eval report

**Adapter:** epoch **6** (`runs/phase3/stage3c/lora/best`) · full-val CSS pick  
**Infer:** fs0 · thinking off · v7-ship (language-agnostic)  
**Train:** json_only targets · fs0_off user prompts · 1283 records · r=32

Baseline (Stage 2 GOOD): SRS **92.5%** (VDR 92.5%, FPRR 73.5%)  
Reference (3B ship ep4): SRS **89.9%** (VDR 90.3%, FPRR 66.2%)

## Headline metrics (594/600 evaluated after gap-fill)

| Metric | Phase 3C | 3B ship | Stage 2 | Δ vs S2 |
| --- | --- | --- | --- | --- |
| SRS | 89.9% | 89.9% | 92.5% | -2.6pp |
| FPRR | 78.3% | 66.2% | 73.5% | +4.8pp |
| VDR | 86.3% | 90.3% | 92.5% | -6.2pp |

## Coverage

| Track | Coverage | Missing |
| --- | ---: | ---: |
| FP | 99.0% | 2 |
| TP | 98.5% | 3 |
| BL | 99.5% | 1 |
| **Total** | | **6** |

Gap-fill (`rescore_test_eval.py`, 5 rounds) recovered 59/65 missing cases. Six cases still fail JSON parse at inference (CoT without JSON tail).

**Verdict:** NOT YET — SRS < Stage 2 baseline.

## SRS penalty breakdown (600-case denominator)

| Track | Evaluated | Missing | Penalty | Main driver |
| --- | ---: | ---: | ---: | --- |
| FP | 198 | 2 | 49.0 | FP→TP (1.0 each) |
| TP | 197 | 3 | 90.0 | TP→FP (3.0 each, CRITICAL) |
| BL | 199 | 1 | 43.5 | BL→FP (1.5 each); BL→TP is free |
| **Total** | | | **182.5** | SRS = 1 − penalty / (600×3) = **89.9%** |

## Confusion matrix — Phase 3C (fs0_off)

| Gold \ Pred | → TP | → FP | → BL | miss |
| --- | ---: | ---: | ---: | ---: |
| **TP** | 170 | 27 | 0 | 3 |
| **FP** | 42 | 155 | 1 | 2 |
| **BL** | 172 | 27 | 0 | 1 |

- **TP→FP (CRITICAL):** 27 (3B ship: 17 · Stage 2: 14)
- **BL→FP (HIGH):** 27 (3B ship: 16 · Stage 2: 26)
- **FP→TP:** 42 (3B ship: 63 · Stage 2: 53)
- **BL→TP (zero penalty):** 172/200
- **Predicted BL on any gold:** 1 (ship never emits BL — expected)

## vs Phase 3B ship (same SRS, different error mix)

3C matches 3B ship on **SRS (~89.9%)** but trades **+12pp FPRR** for **−4pp VDR**:

- **Win:** fewer false alarms kept (FP→TP 42 vs 63) — FPRR 78.3% vs 66.2%
- **Loss:** more missed vulns (TP→FP 27 vs 17) — VDR 86.3% vs 90.3%
- **Train/serve alignment validated:** val CSS pick epoch 6 = full-val rerank best (no post-hoc fs0 rerank needed, unlike 3B)

## Artifacts

- `runs/phase3/stage3c/summaries/css_rerank_best.json` — val pick epoch 6
- `runs/phase3/stage3c/logs/test_rescore.log` — gap-fill log
- `benchmark/phases/phase3/rescore_test_eval.py` — gap-fill tool
