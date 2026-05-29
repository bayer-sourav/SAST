# Phase 1 replication runbook

## Stage 2 (full corpora + borderline)

**904 FP + 1,373 TP + 200 borderline** · **Qwen 4B/8B/14B** · **thinking off only** · seed **42**

**Labels:** unified prompt via `benchmark/make_task.py` — model outputs **`TP | FP | BL | UNKNOWN`**.  
Stage 1 artifacts (`FP-runs/phase1_n50/`, `TP-runs/phase1_n50/`) stay **frozen** on the old **3-label** setup; do not mix metrics across stages.

```bash
bash benchmark/setup_corpora.sh
uv run python benchmark/build_borderline_cases.py   # if borderline dir missing
nohup bash benchmark/phases/phase1/stage2/run_phase1_stage2.sh \
  >> runs/phase1/stage2/logs/master.log 2>&1 &
uv run python benchmark/phases/phase1/stage2/status_stage2.py
```

Smoke (3 cases per cell): `PHASE1_STAGE2_SMOKE_MAX=3 bash benchmark/phases/phase1/stage2/run_phase1_stage2.sh`

Fill missing/failed cases (parse errors, no JSON):  
`uv run python benchmark/phases/phase1/stage2/finish_gaps.py --attempts 3`  
Refresh summaries only: `bash benchmark/phases/phase1/stage2/refresh_summaries.sh`

Details: [`phases/phase1/stage2/PLAN.md`](phases/phase1/stage2/PLAN.md)

---

## Stage 1 matrix (frozen archive)

Reproduce the Phase 1 matrix: **50 FP + 50 TP** cases (seed **42**), **5 model profiles** × **thinking off/on**, zero-shot triage.  
**Labels:** **`TP | FP | UNKNOWN` only** (track-specific prompts). Keep as historical baseline; new work uses Stage 2+ **4-label** runs under `runs/phase1/stage2/`.

| Profile | Notes |
|---------|--------|
| `qwen3_4b_bnb` | Unsloth 4-bit |
| `qwen3_8b_bnb` | Unsloth 4-bit |
| `qwen3_14b_bnb` | Unsloth 4-bit |
| `gpt_oss_20b` | HF / Unsloth fallback |
| `qwen3_coder_30b_bnb` | Optional; skipped if `phase1_logs/phase1_skip_coder.txt` exists |

`google_gemma_3_12b_it` is **not** in the matrix (too slow on L40S). See `phase1_manifest.json`.

---

## Prerequisites

```bash
cd /path/to/SAST
uv sync
```

Layout (siblings of `SAST/`):

- `benchmark/make_task.py` — unified triage prompt (labels: TP, FP, BL, UNKNOWN)
- `BenchmarkJava/` — OWASP Benchmark sources (auto-detected as `../BenchmarkJava` when present)

Hardware: **one GPU** per job (e.g. NVIDIA L40S 44GB). Run **one profile cell at a time**; do not parallelize two model loads on the same GPU.

Hugging Face: models download to `~/.cache/huggingface` unless `PHASE1_HF_HOME` is set.

---

## Fresh run (from zero)

### 1. Build CodeQL corpora (once per machine)

```bash
uv run python benchmark/build_codeql_cases.py
uv run python benchmark/build_tp_codeql_cases.py
```

### 2. Run the full matrix

Builds balanced slices, runs every cell, repairs JSON, writes summaries. **Resumes** automatically: cells with 50 valid `agent-llm-triage-result.json` files are skipped.

```bash
mkdir -p benchmark/phase1_logs
nohup bash ./benchmark/run_phase1_matrix.sh >> benchmark/phase1_logs/phase1_master.log 2>&1 &
```

To **skip coder 30B** (recommended on 44GB GPUs until a stable path exists):

```bash
touch benchmark/phase1_logs/phase1_skip_coder.txt
nohup bash ./benchmark/run_phase1_matrix.sh >> benchmark/phase1_logs/phase1_master.log 2>&1 &
```

To **force re-run** every cell (ignore existing results):

```bash
PHASE1_FORCE=1 bash ./benchmark/run_phase1_matrix.sh
```

To **reuse existing slices** (do not reshuffle cases):

```bash
PHASE1_SKIP_SLICE=1 bash ./benchmark/run_phase1_matrix.sh
```

### 3. Monitor progress

```bash
uv run python benchmark/phase1_status.py
tail -f benchmark/phase1_logs/phase1_master.log
nvidia-smi
```

Target: **50/50** per cell in the status table. Non-coder only: **800/1000** when coder is skipped.

### 4. Final metrics (also run automatically at end of matrix)

```bash
bash ./benchmark/refresh_phase1_summaries.sh
uv run python benchmark/phase1_status.py
```

**Outputs:**

| Artifact | Path |
|----------|------|
| Per-case runs (FP) | `FP-runs/phase1_n50/thinking_{off,on}/<profile>/llm/<case_id>/` |
| Per-case runs (TP) | `TP-runs/phase1_n50/thinking_{off,on}/<profile>/llm/<case_id>/` |
| Track comparisons | `FP-runs/phase1_n50/comparison_fp_n50_thinking_*.json`, `TP-runs/phase1_n50/comparison_tp_n50_thinking_*.json` |
| Matrix metrics | `FP-runs/phase1_n50/phase1_matrix_thinking_{off,on}.json` |
| Combined | `benchmark/phase1_combined_summary.json` |
| Timing | `benchmark/phase1_timing_report.json` |

---

## After the matrix: fix gaps

### Re-parse JSON from `llm_raw.txt` (no GPU)

```bash
uv run python benchmark/repair_llm_results.py \
  --runs FP-runs/phase1_n50/thinking_on \
  --profile qwen3_4b_bnb
```

### Re-run bad cases only (GPU)

Example: TP track, thinking on, qwen3-14b (thinking leaked into raw output):

```bash
source benchmark/phase1_cell_env.sh
phase1_apply_token_limits on qwen3_14b_bnb
uv run python benchmark/rerun_bad_cases.py \
  --runs-root TP-runs/phase1_n50/thinking_on \
  --profile qwen3_14b_bnb \
  --case-dir benchmark/phase1_slices/tp_n50_seed42 \
  --gold TP \
  --thinking
```

Dry-run first:

```bash
uv run python benchmark/rerun_bad_cases.py ... --dry-run
```

### GPT-OSS thinking_on

GPT-OSS ignores the thinking flag. Sync thinking_on from thinking_off without re-inference:

```bash
uv run python benchmark/fill_gpt_oss_thinking_on.py
bash ./benchmark/refresh_phase1_summaries.sh
```

---

## Environment knobs

Set before `run_phase1_matrix.sh` or export in the shell. Defaults are in `benchmark/phase1_cell_env.sh`.

| Variable | Purpose |
|----------|---------|
| `PHASE1_N` | Cases per track (default `50`) |
| `PHASE1_SEED` | Slice seed (default `42`) |
| `PHASE1_FORCE` | `1` = re-run all cells |
| `PHASE1_SKIP_SLICE` | `1` = do not rebuild slices |
| `PHASE1_HF_HOME` | Hugging Face cache root |
| `PHASE1_OFF_MAX_NEW_TOKENS` / `PHASE1_ON_MAX_NEW_TOKENS` | Token caps for thinking off/on |

Per-profile overrides (coder, GPT-OSS): see `phase1_apply_token_limits` in `phase1_cell_env.sh`.

---

## Script index

| Script | When to use |
|--------|-------------|
| `run_phase1_matrix.sh` | Full or resumed matrix |
| `phase1_status.py` | Progress + FPRR/VDR/SRS/coverage |
| `refresh_phase1_summaries.sh` | Rebuild all summary JSON from disk |
| `select_balanced_cases.py` | Called by matrix; run alone to rebuild slices |
| `summarize_triage.py` | Single-track metrics (used by refresh) |
| `merge_phase1_summary.py` | FP+TP merge (used by refresh) |
| `run_batch.py` / `run_llm_local.py` | Lower-level; matrix wraps these |
| `rerun_bad_cases.py` | Targeted GPU re-runs |
| `repair_llm_results.py` | CPU re-parse only |
| `fill_gpt_oss_thinking_on.py` | GPT thinking_on copy |

Design notes: `docs/EXPERIMENT_PLAN.md`. Machine-readable config: `benchmark/phase1_manifest.json`.

---

## Interpreting results

See **Phase 1 metrics** (FPRR, VDR, SRS, **F1**, F1-FP, F1-TP, coverage), **reference snapshot table**, **why thinking on can score worse than off**, and **other patterns** in [`README.md` — Phase 1 results](README.md#phase-1-metrics-what-the-columns-mean). Re-run `phase1_status.py` after `refresh_phase1_summaries.sh` for up-to-date numbers.
