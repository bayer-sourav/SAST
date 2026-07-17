# Phase 3C blv4 test eval report

**Adapter:** epoch **10** (`runs/phase3/stage3c_blv4/lora/best`) · full-val CSS=0.8475833333333334  
**Infer:** fs0 · thinking off · v7-ship  
**Train:** confirmatory 3C on BL v4 synthetics (`BenchmarkTest28xxx`) · json_only · r=32

**Coverage:** 600/600 evaluated · **missing=0**

## Headline metrics

| Metric | blv4 | Original 3C | 3B ship | Stage 2 | Δ vs S2 |
| --- | ---: | ---: | ---: | ---: | ---: |
| SRS | 88.1% | 89.9% | 89.9% | 92.5% | -4.4pp |
| VDR | 72.5% | 86.3% | 90.3% | 92.5% | -20.0pp |
| FPRR | 76.5% | 78.3% | 66.2% | 73.5% | +3.0pp |

## Success gates

| Gate | Target | Result |
| --- | --- | --- |
| Beat Stage 2 SRS | > 92.5% | FAIL (88.1%) |
| FPRR target | ≥ 73.5% | PASS (76.5%) |
| VDR floor | ≥ 90.0% | FAIL (72.5%) |

**Verdict:** NOT YET — does not beat Stage 2 / miss gates

## Coverage by track

| Track | Evaluated | Missing |
| --- | ---: | ---: |
| FP | 200 | 0 |
| TP | 200 | 0 |
| BL | 200 | 0 |

## SRS penalty breakdown

| Track | Penalty | Main driver |
| --- | ---: | --- |
| FP | 39.0 | FP→TP |
| TP | 122.0 | TP→FP (×3) |
| BL | 54.0 | BL→FP (×1.5) |
| **Total** | **215.0** | SRS = 1 − total/(600×3) |

## Confusion matrix — blv4 (fs0_off)

| Gold \ Pred | → TP | → FP | → BL | miss |
| --- | ---: | ---: | ---: | ---: |
| **TP** | 145 | 40 | 2 | 0 |
| **FP** | 39 | 153 | 0 | 0 |
| **BL** | 162 | 36 | 2 | 0 |

## Confusion matrix — Stage 2 GOOD (think-on fs3)

| Gold \ Pred | → TP | → FP | → BL | miss |
| --- | ---: | ---: | ---: | ---: |
| **TP** | 185 | 14 | 1 | 0 |
| **FP** | 53 | 147 | 0 | 0 |
| **BL** | 174 | 26 | 0 | 0 |

## Interpretation

- **vs original 3C:** same recipe on refreshed BL train; compare FPRR/VDR tradeoff.
- **vs 3B ship:** 3B = higher VDR; 3C-family = higher FPRR when it works.
- **vs Stage 2:** Stage 2 remains the quality bar (think-on fs3, slower).
- **Integration:** only consider blv4 if gates pass; otherwise keep Stage 2 recipe or 3B ep4 as interim latency path.

## Artifacts

- Summaries: `runs/phase3/stage3c_blv4/summaries/`
- Eval: `runs/phase3/stage3c_blv4/eval/`
- Gap-fill log: `runs/phase3/stage3c_blv4/logs/test_rescore.log`

