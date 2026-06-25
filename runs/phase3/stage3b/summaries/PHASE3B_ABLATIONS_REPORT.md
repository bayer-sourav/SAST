# Phase 3B inference ablations

Fine-tuned LoRA (rank 32, teacher distillation) on 600-case Phase 2 test holdout.
Phase 2 Stage 2 baseline: SRS **92.5%** (VDR 92.5%, FPRR 73.5%)

**Ship pick:** epoch **4** adapter (`lora/best_fs0_off`) after val rerank under fs0_off infer.
Training-time fs3+CoT CSS pick was epoch **6** — train/serve mismatch hurts FPRR.

**Rationale:** Distillation bakes triage policy into weights. Zero-shot drops few-shot tokens (shorter prompts, less truncation). Thinking-off avoids long CoT and should improve JSON reliability vs thinking-on.

## Cell comparison

| Cell | SRS | FPRR | VDR | Missing | TP→FP |
| --- | ---: | ---: | ---: | ---: | ---: |
| Ship (teacher-matched) · ep6 (`fs3_on`) | 84.1% | 71.5% | 83.2% | 36 | 32 |
| Zero-shot · thinking off · ep6 (`fs0_off`) | 88.7% | 58.7% | 89.2% | 12 | 17 |
| Zero-shot · thinking off · ep4 (rerank) (`fs0_off_best`) | 89.9% | 66.2% | 90.3% | 13 | 17 |

**Best cell so far:** `fs0_off_best` (SRS 89.9%)
**Vs Stage 2 baseline:** -2.6pp SRS

