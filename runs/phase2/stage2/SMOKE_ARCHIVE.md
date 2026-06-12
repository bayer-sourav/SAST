# Smoke test archive + Phase 2 comparison
Generated: 2026-06-11 15:07 UTC
Hard slice: 20 cases (10 TP + 10 FP). Metrics: VDR / FPRR / Total correct.
## Hard-slice smoke results (chronological)
### v7_3shot_2tp_fp (2TP+1FP fs3) (`v2-3shot-2tp-fp`)
| Profile | Think | FS | VDR | FPRR | Total | Miss |
| --- | --- | --- | --- | --- | --- | --- |
| qwen3_8b_bnb | on | 3 | 8/10 | 10/10 | 18/20 | 0 |
| qwen3_5_9b_bnb | on | 3 | 7/10 | 10/10 | 17/20 | 1 |
| qwen3_14b_bnb | on | 3 | 7/10 | 8/10 | 15/20 | 0 |
| qwen3_coder_30b_bnb | on | 3 | 10/10 | 3/10 | 13/20 | 0 |
| qwen3_14b_bnb | off | 3 | 7/10 | 6/10 | 13/20 | 0 |
| qwen3_coder_30b_bnb | off | 3 | 9/10 | 2/10 | 11/20 | 0 |
| qwen3_8b_bnb | off | 3 | 0/10 | 10/10 | 10/20 | 0 |
| qwen3_5_9b_bnb | off | 3 | 9/10 | 0/10 | 9/20 | 0 |
### v7_final_2shot (fs0+fs2) (`v2-2shot`)
| Profile | Think | FS | VDR | FPRR | Total | Miss |
| --- | --- | --- | --- | --- | --- | --- |
| qwen3_8b_bnb | on | 0 | 8/10 | 10/10 | 18/20 | 0 |
| qwen3_8b_bnb | on | 2 | 8/10 | 10/10 | 18/20 | 0 |
| qwen3_5_9b_bnb | on | 2 | 8/10 | 10/10 | 18/20 | 0 |
| qwen3_5_9b_bnb | on | 0 | 9/10 | 8/10 | 17/20 | 0 |
| qwen3_14b_bnb | on | 2 | 8/10 | 8/10 | 16/20 | 0 |
| qwen3_14b_bnb | off | 2 | 8/10 | 7/10 | 15/20 | 0 |
| qwen3_14b_bnb | off | 0 | 8/10 | 5/10 | 13/20 | 0 |
| qwen3_14b_bnb | on | 0 | 8/10 | 5/10 | 13/20 | 0 |
| qwen3_coder_30b_bnb | on | 2 | 10/10 | 2/10 | 12/20 | 0 |
| qwen3_8b_bnb | off | 0 | 8/10 | 4/10 | 12/20 | 0 |
| qwen3_5_9b_bnb | off | 2 | 10/10 | 1/10 | 11/20 | 0 |
| qwen3_coder_30b_bnb | off | 2 | 9/10 | 2/10 | 11/20 | 0 |
| qwen3_5_9b_bnb | off | 0 | 10/10 | 0/10 | 10/20 | 0 |
| qwen3_coder_30b_bnb | off | 0 | 8/10 | 2/10 | 10/20 | 0 |
| qwen3_8b_bnb | off | 2 | 0/10 | 10/10 | 10/20 | 0 |
| qwen3_coder_30b_bnb | on | 0 | 8/10 | 1/10 | 9/20 | 0 |
### v7_thinking_on_fs3 (legacy 1TP+2FP) (`v2 fs3`)
| Profile | Think | FS | VDR | FPRR | Total | Miss |
| --- | --- | --- | --- | --- | --- | --- |
| qwen3_5_9b_bnb | on | 3 | 10/10 | 10/10 | 20/20 | 0 |
| qwen3_8b_bnb | on | 3 | 8/10 | 10/10 | 18/20 | 0 |
| qwen3_14b_bnb | on | 3 | 8/10 | 9/10 | 17/20 | 0 |
| qwen3_coder_30b_bnb | on | 3 | 9/10 | 2/10 | 11/20 | 0 |
### v7_thinking_on_fs0 (`zero-shot`)
| Profile | Think | FS | VDR | FPRR | Total | Miss |
| --- | --- | --- | --- | --- | --- | --- |
| qwen3_5_9b_bnb | on | 0 | 9/10 | 7/10 | 16/20 | 0 |
| qwen3_8b_bnb | on | 0 | 8/10 | 8/10 | 16/20 | 0 |
| qwen3_14b_bnb | on | 0 | 8/10 | 3/10 | 11/20 | 0 |
| qwen3_coder_30b_bnb | on | 0 | 8/10 | 2/10 | 10/20 | 0 |
### v7_fewshot_v3 (TP+FP+BL) (`v3 fs3`)
| Profile | Think | FS | VDR | FPRR | Total | Miss |
| --- | --- | --- | --- | --- | --- | --- |
| qwen3_5_9b_bnb | on | 0 | 9/10 | 10/10 | 19/20 | 0 |
| qwen3_14b_bnb | on | 0 | 7/10 | 8/10 | 15/20 | 0 |
| gemma_4_e4b_bnb | off | 0 | 0/10 | 0/10 | 0/20 | 20 |
### v7_fewshot_v2 all profiles (`v2 fs3`)
| Profile | Think | FS | VDR | FPRR | Total | Miss |
| --- | --- | --- | --- | --- | --- | --- |
| qwen3_4b_bnb | off | 0 | 0/10 | 0/10 | 0/20 | 20 |
| qwen3_4b_bnb | off | 3 | 0/10 | 0/10 | 0/20 | 20 |
| qwen3_8b_bnb | off | 0 | 0/10 | 0/10 | 0/20 | 20 |
| qwen3_8b_bnb | off | 3 | 0/10 | 0/10 | 0/20 | 20 |
| qwen3_14b_bnb | off | 0 | 0/10 | 0/10 | 0/20 | 20 |
| qwen3_14b_bnb | off | 3 | 0/10 | 0/10 | 0/20 | 20 |
| qwen3_5_4b_bnb | off | 0 | 0/10 | 0/10 | 0/20 | 20 |
| qwen3_5_4b_bnb | off | 3 | 0/10 | 0/10 | 0/20 | 20 |
| qwen3_5_9b_bnb | off | 0 | 0/10 | 0/10 | 0/20 | 20 |
| qwen3_5_9b_bnb | off | 3 | 0/10 | 0/10 | 0/20 | 20 |
| qwen3_coder_30b_bnb | off | 0 | 0/10 | 0/10 | 0/20 | 20 |
| qwen3_coder_30b_bnb | off | 3 | 0/10 | 0/10 | 0/20 | 20 |
### v7_balanced all profiles

_No summary at `runs/smoke/v7_balanced_all_profiles/summary.json`_
## Key smoke conclusions
- **Best hard-slice score:** legacy fs3 (`v2_3shot_tp_2fp`) · qwen3_5_9b · think=on → **20/20**
- **2TP+1FP fs3 (`v2_3shot_2tp_fp`) regressed** vs legacy on 5.9b (17/20) and 14b (15/20); not adopted
- **8b think=on fs0 or fs3** both hit 18/20 with perfect FPRR; fs0 chosen for Stage 2 (shorter prompts)
- **8b think=off + fs3** → 0/10 VDR; **5.9b think=off + fs3** → 0/10 FPRR — avoid think=off with few-shot
- **Coder-30b** — recall-first (10/10 VDR think=on) but FPRR ~3/10; kept in Stage 2 for comparison only
- **Gemma 4** dropped (transformers/compatibility cost vs benefit)
## Phase 2 Stage 1 (full 200×3 corpus, prior prompt era)
Source: `runs/phase2/summaries/PHASE2_TABLES.md` (Jun 2026).
### Thinking ON · Few-shot 3 (full corpus, 200 cases/track)
| Profile | FPRR | VDR | SRS | Note |
| --- | --- | --- | --- | --- |
| qwen3_5_9b_bnb | 94.0% | 85.5% | 89.8% | Best overall Stage 1 |
| qwen3_8b_bnb | 90.0% | 51.0% | 70.5% | Balanced mid-tier |
| qwen3_coder_30b_bnb | 90.0% | 43.0% | 66.5% | High FP track FPRR, moderate VDR |
| qwen3_14b_bnb | 97.5% | 26.0% | 61.7% | FPRR-heavy, low recall |
| qwen3_4b_bnb | 100.0% | 9.5% | 54.8% | Not in Stage 2 |
### Thinking ON · Few-shot 0 (8b zero-shot baseline, full corpus)
| Profile | FPRR | VDR | SRS | Note |
| --- | --- | --- | --- | --- |
| qwen3_8b_bnb | 96.0% | 65.8% | 80.9% | Stage 1 fs0 reference |
| qwen3_5_9b_bnb | 96.0% | 65.8% | 80.9% | 5.9b fs0 |
## Phase 2 Stage 2 plan (this run)
| Cell | Profile | Think | FS | Config | Note |
| --- | --- | --- | --- | --- | --- |
| 5.9b_fs3_legacy | qwen3_5_9b_bnb | on | 3 | v2_3shot_tp_2fp | Primary quality cell — 20/20 hard slice with legacy 1TP+2FP fs3 |
| 8b_fs0_zeroshot | qwen3_8b_bnb | on | 0 | — | Fast/cheap arm — 18/20 hard slice, perfect FPRR, shortest prompts |
| 14b_fs3_legacy | qwen3_14b_bnb | on | 3 | v2_3shot_tp_2fp | Mid-size baseline — 17/20 hard slice legacy fs3 |
| coder30b_fs3_recall | qwen3_coder_30b_bnb | on | 3 | v2_3shot_tp_2fp | Recall comparison arm — high VDR, low FPRR (~3/10 on hard slice) |

Output: `runs/phase2/stage2/{fp,tp,bl}/thinking_on/fewshot_{0,3}/`
Prompt: `unified-4label-v7-balanced` + versioned few-shot configs in `benchmark/few_shot_configs/`.
