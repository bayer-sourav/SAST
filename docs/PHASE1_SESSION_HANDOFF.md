# Phase 1 experiment — session handoff (continue here)

Last updated: 2026-05-22 (paused end of day)

## Goal

Phase 1 SLM SAST triage on **50 FP + 50 TP** cases (seed **42**, CWE-balanced slices), **5 models** ascending size (Gemma 12B skipped), **thinking on/off**, zero-shot. Metrics: **FPRR**, **VDR**, **F1**, **SRS**, timing, tokens.

## Corpora & slices

| Track | Slice dir | Gold | Runs root |
|-------|-----------|------|-----------|
| FP | `benchmark/phase1_slices/fp_n50_seed42/` | FP | `FP-runs/phase1_n50/` |
| TP | `benchmark/phase1_slices/tp_n50_seed42/` | TP | `TP-runs/phase1_n50/` |

Manifests: `benchmark/phase1_slices/fp_n50_seed42_manifest.json`, `tp_n50_seed42_manifest.json`.

## Model order (by params)

1. `qwen3_4b_bnb`
2. `qwen3_8b_bnb`
3. `qwen3_14b_bnb`
4. `gpt_oss_20b`
5. `qwen3_coder_30b_bnb`

Skipped: `google_gemma_3_12b_it` (~25+ min/case on L40S). Partial FP `thinking_off` artifacts may remain under `FP-runs/.../google_gemma_3_12b_it/`.

## Orchestration

```bash
cd /home/ec2-user/Projects/SAST
PHASE1_SKIP_SLICE=1 ./benchmark/run_phase1_matrix.sh   # resume
uv run python benchmark/phase1_status.py
uv run python benchmark/report_timing.py

# Auto-monitor (status every 5 min, restarts GPT-OSS rerun if stalled):
nohup bash ./benchmark/phase1_watchdog_loop.sh >> benchmark/phase1_logs/watchdog.log 2>&1 &
cat benchmark/phase1_logs/watchdog_status.txt   # human-readable snapshot
```

Logs: `benchmark/phase1_logs/nohup_resume2.out`, `phase1_master.log`.

Resume skips cells with **50/50** valid results unless `PHASE1_FORCE=1`.

## Key code paths

| Piece | Path |
|-------|------|
| Batch / single case | `benchmark/run_batch.py` (in-process by default), `run_llm_local.py` |
| Model dispatch | `benchmark/llm_generate.py` |
| Qwen + thinking fix | `models/qwen/runner.py` |
| Decoding limits | `core/generation_defaults.py` |
| Metrics | `benchmark/summarize_triage.py`, `merge_phase1_summary.py` |
| Timing / tokens | `benchmark/timing.py`, `report_timing.py`, `run_meta.json` per case |
| Re-run bad outputs | `benchmark/rerun_bad_cases.py` |

## Bugs fixed this session

### 1. Qwen3 `thinking=off` still generated think blocks

- **Cause:** Unsloth `apply_chat_template` signature hides `enable_thinking`; it was never passed.
- **Fix:** Always pass `enable_thinking` in kwargs for Qwen3 profiles; append `/no_think` on user turn when off.
- **Re-run:** Early `qwen3_8b_bnb` FP `thinking_off` cases (~11) re-run via `rerun_bad_cases.py`.

### 2. Truncation at 1024 tokens (no JSON)

- **Cause:** `AGENT_MAX_NEW_TOKENS=1024`; thinking consumed full budget.
- **Fix:** Default **`AGENT_MAX_NEW_TOKENS=32768`**, clamped per call to `max_seq_len - prompt_tokens` via `cap_max_new_tokens()` in `generation_defaults.py`.

### 3. `slice_manifest.json` inside slice dirs

- Counted as 51st case. Manifest now at `*_manifest.json` outside slice; excluded in batch/summarize.

### 4. Disk / infra

- Root volume grown to **150GB**; `HF_HOME=~/.cache/huggingface`.
- `qwen3_coder_30b_bnb` hub id: `unsloth/Qwen3-Coder-30B-A3B-Instruct` (not GGUF).

## Env defaults (phase 1 matrix)

```bash
AGENT_MAX_SEQ_LEN=32768
AGENT_MAX_NEW_TOKENS=32768
QWEN_MAX_SEQ_LEN=32768
GPT_OSS_MAX_SEQ_LEN=32768
```

## Outputs when complete

- `FP-runs/phase1_n50/comparison_fp_n50_thinking_{off,on}.json`
- `TP-runs/phase1_n50/comparison_tp_n50_thinking_{off,on}.json`
- `FP-runs/phase1_n50/phase1_matrix_thinking_{off,on}.json` (FPRR + VDR + SRS)
- `benchmark/phase1_combined_summary.json`
- `benchmark/phase1_timing_report.json`

## Progress snapshot (paused 2026-05-22)

- **Overall:** 400/1000 (40%) — see `benchmark/phase1_logs/PAUSED.txt`
- **thinking_off done:** Qwen 4B/8B/14B + GPT-OSS (FP+TP, 50/50 each)
- **Next up:** `qwen3_coder_30b_bnb` thinking_off (FP+TP), then all **thinking_on** cells
- **Orchestrator:** `benchmark/phase1_watchdog_loop.sh` (auto-finish GPT, then matrix). `benchmark/phase1_lib.sh` + JSON retry in `run_llm_local.py` for stubborn GPT cases.

## Commands for next session

```bash
cd /home/ec2-user/Projects/SAST
uv run python benchmark/phase1_status.py

# Recommended: watchdog resumes matrix automatically (skips completed cells)
nohup bash ./benchmark/phase1_watchdog_loop.sh >> benchmark/phase1_logs/watchdog.log 2>&1 &
tail -f benchmark/phase1_logs/watchdog_status.txt

# Or matrix only:
# PHASE1_SKIP_SLICE=1 ./benchmark/run_phase1_matrix.sh
```

## Notes

- New runs record `run_meta.json`: timing, `input_tokens`, `output_tokens`, `thinking` flag.
- Parser strips `redacted_thinking` before JSON extract (`core/parsing.py`).
- One model at a time on GPU; do not parallelize profiles.
- **Batch loads model once per cell** (in-process for all models including GPT-OSS). After first Unsloth OOM, GPT-OSS uses cached HF for the rest of the cell. `--subprocess-per-case` only for debugging.
- **Token caps** (`benchmark/phase1_cell_env.sh`): `thinking_off` → 4096 new / 16k ctx; `thinking_on` → 16k new / 32k ctx; GPT-OSS → 4096 new / 12k ctx.
- **Inference path:** Unsloth first, Hugging Face only on failure (Qwen/Gemma/GPT-OSS runners). Optional `PHASE1_GPT_OSS_HF_ONLY=1` to skip Unsloth for GPT-OSS.
- **GPU cleanup** after every cell: `run_batch` finally + `phase1_gpu_cleanup` in matrix (before and after each cell).
