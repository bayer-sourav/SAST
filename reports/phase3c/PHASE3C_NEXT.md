# Phase 3C — Next course of action

## Is BL the problem?

**Full analysis:** `PHASE3C_BL_ANALYSIS.md`

**Short answer:** BL is not the SRS bottleneck in the way you might expect — but **BL-train supervision may be confusing the TP/FP boundary**.

| Fact | Detail |
| --- | --- |
| Ship eval | `acceptable_labels` on BL test = **TP or FP only** — BL output is not valid |
| Stage 2 / 3C | **0% predict BL** on BL-gold test; **100% lenient accuracy** (TP or FP both OK) |
| SRS on BL | BL→TP = **free**; BL→FP = 1.5 penalty — predicting TP is optimal under current metrics |
| Main SRS gap | **TP→FP** on TP-gold (27 vs 14 Stage 2), not missing BL predictions |

**Training confusion (your hypothesis):** On BL-gold **train**, Stage 2 teacher labels **85% TP / 14% FP / 0.5% BL** — yet all 500 are benchmark-safe. The model learns contradictory TP vs FP targets on the hardest ambiguous cases (362 export rows). Teacher agrees with gold track label BL only **0.5%** (vs 72% FP, 93% TP on their tracks).

## Would removing BL from fine-tuning help?

**Worth an ablation — revised view.** Removing BL is unlikely to make the model “predict BL” (that requires schema + metric changes). It **might** sharpen VDR/FPRR on clear TP/FP if boundary noise is hurting — or **hurt** if you lose useful ambiguity signal.

| Approach | Tradeoff |
| --- | --- |
| **3D-a: drop BL from train** | ~921 FP+TP records; test if TP→FP drops |
| **Fix teacher on BL** | Consistent policy (e.g. FP when safe) before distilling |
| **BL auxiliary loss** | Keep BL cases separate with soft/multi-label targets |
| **Change ship to emit BL** | New prompt, metrics, and teacher — large scope |

**Recommendation:** Run **3D-a as ablation**, not as the main bet. Primary 3D should still target **TP→FP** with hard-negative mining + VDR-weighted CSS.

## Recommended next steps (priority order)

### 1. Phase 3D — VDR-focused correction (highest leverage)

Target the **27 TP→FP** errors (not BL removal):

- **Hard-negative mining:** oversample train cases matching 3C TP→FP confusion (same rule families / code patterns from error analysis)
- **CSS reweight:** add TP→FP penalty to val CSS or use constrained pick (VDR floor 0.90 + max FPRR) instead of pure CSS
- **Rank 64** json_only with same ship config — more capacity for subtle TP recall

### 2. Recover training data (cheap win)

- Export dropped **217** cases (99 missing teacher, 97 unparseable, 21 too long) — re-run teacher JSON repair or raise seq cap selectively
- Full 1500 distillation may stabilize VDR without changing architecture

### 3. Pareto ensemble / dual adapter (no retrain)

- 3C epoch 6 = high FPRR; 3B ship ep4 = high VDR — evaluate **val-weighted blend** or route by rule class if error analysis clusters

### 4. Preference tuning (3E)

- DPO/KTO on pairs from Stage 2 vs 3C delta: TP→FP (reject), FP→TP (reject), BL→FP (reject) using Stage 2 as preferred

### 5. Inference robustness

- Six test cases fail JSON parse — add stricter json_only retry at serve time (does not affect SRS much but affects coverage)

## Success criteria for 3D

| Gate | Target |
| --- | --- |
| SRS | ≥ 92.5% (Stage 2) |
| VDR | ≥ 90% |
| FPRR | ≥ 73.5% (maintain 3C gain vs 3B) |
| TP→FP | ≤ 17 |

## Not recommended

- Removing BL from train/val/test splits (changes benchmark)
- Returning to fs3+CoT train (reintroduces train/serve mismatch)
- Gold-label SFT (3A showed VDR collapse)
