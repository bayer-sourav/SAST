# Phase 3C — Borderline (BL) track analysis

Gold track **BL** = ambiguous cases in BenchmarkJava. This doc compares BL to TP/FP in **training supervision**, **test scoring**, and **model predictions**.

## 1. What BL means in this benchmark

| Split | `benchmark_real_vuln` | `acceptable_labels` | SRS scoring |
| --- | --- | --- | --- |
| BL **train** (500) | 100% safe (`false`) | `('FP', 'TP')` only | — |
| BL **test** (200) | 100% safe (`false`) | `('FP', 'TP')` only | BL→TP free; BL→FP penalized |

**BL is not an acceptable prediction label on test.** Lenient accuracy counts TP or FP as correct. Stage 2 and 3C both achieve **100% lenient accuracy** on BL test — every prediction is TP or FP.

**Ship inference never targets BL output** (0% BL predictions on BL-gold for Stage 2 and 3C).

## 2. Stage 2 teacher labels on BL-gold **train** (distillation source)

| Gold track | N (teacher) | Teacher label | Count | % |
| --- | --- | --- | --- | --- |
| BL (borderline) | 371 | TP | 316 | 85.2% |
|  |  | FP | 53 | 14.3% |
|  |  | BL | 2 | 0.5% |

Teacher agrees with gold track label **BL**: **0.5%** (vs FP track **71.8%**, TP track **92.6%**).

All BL-train cases are benchmark-safe (`benchmark_real_vuln=false` → bench label **FP**), but teacher says **TP on 316** of them — **contradictory supervision**.

## 3. Phase 3C export (what the model actually learns)

| teacher_label (BL-gold export) | Count | % |
| --- | --- | --- |
| TP | 308 | 85.1% |
| FP | 52 | 14.4% |
| BL | 2 | 0.6% |

Total BL-gold export records: **362** (of 1283 total).

## 4. Test predictions by gold track (fs0_off)

| Model | Gold | N | →TP | →FP | →BL | miss |
| --- | --- | --- | --- | --- | --- | --- |
| Phase 3C | FP | 198 | 42 (21%) | 155 (78%) | 1 (1%) | 2 |
| Phase 3C | TP | 197 | 170 (86%) | 27 (14%) | 0 (0%) | 3 |
| Phase 3C | BL | 199 | 172 (86%) | 27 (14%) | 0 (0%) | 1 |
| Stage 2 GOOD | FP | 200 | 53 (26%) | 147 (74%) | 0 (0%) | 0 |
| Stage 2 GOOD | TP | 200 | 185 (92%) | 14 (7%) | 1 (0%) | 0 |
| Stage 2 GOOD | BL | 200 | 174 (87%) | 26 (13%) | 0 (0%) | 0 |
| 3B ship | FP | 195 | 63 (32%) | 129 (66%) | 3 (2%) | 5 |
| 3B ship | TP | 195 | 176 (90%) | 17 (9%) | 2 (1%) | 5 |
| 3B ship | BL | 197 | 180 (91%) | 16 (8%) | 1 (1%) | 3 |

## 5. Is BL confusing the model?

**Partially yes — but not because the model should output BL.**

| Mechanism | Evidence |
| --- | --- |
| **Contradictory BL supervision** | 85% of BL-train teacher labels are **TP** on cases benchmark marks as safe/ambiguous |
| **Low teacher–gold agreement on BL track** | 0.5% teacher says BL; 72–93% on FP/TP tracks |
| **Boundary blur** | 362 BL export rows teach TP/FP split on hardest cases — may widen TP/FP confusion on clear tracks |
| **Not a BL-output problem** | Predicting BL is not scored as success; Stage 2 also uses 0% BL on BL test |

### What hurts SRS on BL test

- **BL→FP** (27 in 3C vs 16 in 3B ship): over-dismiss ambiguous findings — 1.5× penalty each
- **BL→TP** (172 in 3C): **zero penalty** — this is the SRS-optimal direction

Wanting "mostly BL" on BL cases **conflicts with ship eval design** unless you change:

1. Prompt/schema to emit BL at inference
2. `acceptable_labels` and SRS penalty table
3. Teacher to label BL on ambiguous cases (Stage 2 currently does not)

## 6. Implications for 3D (refined)

| Approach | Rationale |
| --- | --- |
| **Drop BL from train** | Removes contradictory TP/FP supervision on ambiguous cases — may sharpen VDR/FPRR on clear tracks, but loses boundary signal |
| **Keep BL, fix teacher** | Re-label BL train with consistent policy (e.g. always FP when safe, or true BL with new ship schema) |
| **BL-only auxiliary loss** | Train clear TP/FP on 821 cases; use BL separately with soft/multi-label targets |
| **Primary 3D focus** | Still **TP→FP** on TP-gold (27 vs 14 Stage 2) — independent of BL output class |

**Recommendation:** Before dropping BL, run **3D-ablation** (FP+TP train only) *and* measure TP→FP on TP-gold separately. If VDR rises without FPRR collapse, BL boundary noise was hurting. If VDR stays flat, BL wasn't the bottleneck.
