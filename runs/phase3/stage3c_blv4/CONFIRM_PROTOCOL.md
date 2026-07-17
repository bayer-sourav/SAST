# Phase 3C confirmatory re-run (BL v4 synthetic)

**Status:** complete (gates NOT met)  
**Date:** 2026-07-14 → test finished 2026-07-16  
**Report:** `runs/phase3/stage3c_blv4/summaries/PHASE3C_BLV4_TEST_REPORT.md`

## Purpose

Re-train the **frozen** Phase 3C recipe on the **current** borderline train split (`curated_v4_calibrated_v3`, `BenchmarkTest28xxx`) and evaluate **once** on the held-out 600-case test.

Original `runs/phase3/stage3c` distill (Jun 2026) used retired **`BLSynthetic*`** IDs that are no longer on disk. This run asks: do 3C numbers still hold after the BL corpus refresh?

## Frozen recipe (no search)

| Knob | Value |
|------|--------|
| Prompt | `v7-ship` · fs0 · thinking off |
| Supervision | Stage 2 teacher distill · `json_only` |
| LoRA | r=32 · α=32 · lr 5e-5 · max 10 epochs · CSS early stop |
| Checkpoint pick | CSS on **validation** only |
| Test | **Single** eval of `lora/best` on 600-case Phase 2 test |

No hyperparameter sweeps, no additional prompt cells, no re-picking checkpoints from test.

## Compare against

| | SRS | VDR | FPRR | TP→FP |
|--|----:|----:|-----:|------:|
| Original 3C | 89.9% | 86.3% | 78.3% | 27 |
| Stage 2 | 92.5% | 92.5% | 73.5% | 14 |

## Commands

```bash
cd /home/ec2-user/Projects/SAST
export PHASE3_MANIFEST=benchmark/phases/phase3/stage3c_blv4/MANIFEST.json
export PHASE3C_ROOT=runs/phase3/stage3c_blv4
PHASE3C_SKIP_TEACHER=0 bash benchmark/phases/phase3/run_phase3c.sh
```

Monitor: `tail -f runs/phase3/stage3c_blv4/logs/phase3c.log`

## Outputs

| Artifact | Path |
|----------|------|
| Manifest | `benchmark/phases/phase3/stage3c_blv4/MANIFEST.json` |
| Distill | `runs/phase3/stage3c_blv4/data/distill_train.jsonl` |
| Adapter | `runs/phase3/stage3c_blv4/lora/best` |
| Test eval | `runs/phase3/stage3c_blv4/eval/` · `summaries/` |
