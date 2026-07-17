# Latency budget ablation (thinking ON)

## Why

Single-case wall time is dominated by CoT length (~2–4k tokens). vLLM batch logs showing ~60–130 tok/s are **aggregate** scheduler estimates; per-stream decode on L40S is ~35–40 tok/s, and Integration single-case path does not micro-batch.

## Cells

| Cell | Prompt | Few-shot |
|------|--------|----------|
| `5.9b_fs3_legacy` | `v7-balanced` | fs3 `v2_3shot_tp_2fp` |
| `langagnostic_fs3` | `v7-balanced-langagnostic` | same |

## Arms

| Arm | `PHASE2_ON_MAX_NEW_TOKENS_THINKING` | `SAST_SHORT_THINKING` |
|-----|-------------------------------------|------------------------|
| baseline | 4096 | off |
| t2048 | 2048 | off |
| t2048_short | 2048 | on |
| t1536_short | 1536 | on |

## Corpus

Hard diagnostic slice (10 TP + 10 FP) — same as Phase 2 smokes. Not a 600-case ship decision; pick the best arm then confirm once on 600 if smoke holds (≥17/20, prefer ≥19/20 with recovered≪baseline).

## Run

```bash
cd /home/ec2-user/Projects/SAST
WAIT_FOR_GPU=1 nohup bash benchmark/phases/phase2/run_latency_budget_ablation.sh \
  >> runs/phase2/latency_budget_ablation/nohup.log 2>&1 &
```

Summary: `runs/phase2/latency_budget_ablation/ABLATION_SUMMARY.md`
