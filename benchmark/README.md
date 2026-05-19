# Benchmark: local Qwen triage vs CodeQL baseline

Reproduce paper-style SAST triage experiments with **local Qwen3 (4B / 8B, 4-bit)** and compare against a **CodeQL no-filter baseline**.

Assumes this repo (`SAST`) sits next to:

- `SAST-Paper-Artifacts/` (task prompts via `Evaluation Framework/make_task.py`)
- `BenchmarkJava/` (OWASP Benchmark source; optional if you pass `--repo`)

Use **`uv`** for the Python environment (`uv sync` from repo root).

---

## Prerequisites

```bash
cd /path/to/SAST
uv sync
```

GPU recommended for Unsloth inference. Run **one model profile at a time** on a single GPU (do not batch 4B and 8B in parallel).

Sibling layout (typical):

```
Projects/
  SAST/
  SAST-Paper-Artifacts/
  BenchmarkJava/
```

If **BenchmarkJava** is a sibling, you can **omit `--repo`** on most commands; scripts auto-detect `../BenchmarkJava` when it contains the case file.

---

## Corpora (gold labels)

| Directory | Built from | Gold label | Meaning |
|-----------|------------|------------|---------|
| `benchmark/rq1_codeql_only/` | Paper RQ1 FP set | **FP** | Alerts are false positives; correct triage = dismiss (`FP`) |
| `benchmark/tp_codeql_only/` | Paper TP-retention set | **TP** | Alerts are true positives; correct triage = keep (`TP`) |

Build CodeQL-only JSON case files:

```bash
# RQ1 false-positive filter corpus (~904 cases with CodeQL)
uv run python benchmark/build_codeql_cases.py

# TP retention corpus (~1373 cases with CodeQL)
uv run python benchmark/build_tp_codeql_cases.py
```

Sources default to:

- `../SAST-Paper-Artifacts/RQ1/triage-owasp-benchmark`
- `../SAST-Paper-Artifacts/Discussion (TP Retention)/triage-owasp-benchmark-tp`

Override with `--src` and `--out` on the build scripts.

---

## Scripts overview

| Script | Purpose |
|--------|---------|
| `run_llm_local.py` | One case → Qwen inference → `agent-llm-triage-result.json` |
| `run_batch.py` | Many cases; skip / retry flags |
| `summarize_triage.py` | Metrics table: CodeQL vs Qwen profiles |
| `repair_llm_results.py` | Re-parse `llm_raw.txt` without re-running the model |
| `run_comparison.sh` | Full pipeline: batch 4B + 8B → repair → summarize |
| `run_rq1_comparison.sh` | Shortcut: FP corpus only (same as `run_comparison.sh` with defaults) |
| `run_openhands.py` | OpenHands agent (optional; needs chat server) |

---

## Single case (smoke test)

```bash
cd /path/to/SAST

# FP corpus
uv run python benchmark/run_llm_local.py \
  --case benchmark/rq1_codeql_only/OWASP_benchmark_java_BenchmarkTest02721.json \
  --profile qwen3_4b_bnb \
  --gold FP

# TP corpus
uv run python benchmark/run_llm_local.py \
  --case benchmark/tp_codeql_only/OWASP_benchmark_java_BenchmarkTest00001.json \
  --profile qwen3_4b_bnb \
  --gold TP
```

**`--gold FP|TP`** selects corpus-specific prompts in `run_llm_local.py` (FP-filter vs TP-retention policy).

**Artifacts** (default):

```
runs/<profile>/llm/<case_id>/
  task.md
  llm_raw.txt
  agent-llm-triage-result.json
```

Custom output: `--run-dir /path/to/dir`.

---

## Full comparison (recommended)

`run_comparison.sh` runs **Qwen3-4B** then **Qwen3-8B**, repairs parses, writes a JSON summary.

```bash
cd /path/to/SAST
chmod +x benchmark/run_comparison.sh

# RQ1: 45-case slice, gold=FP
./benchmark/run_comparison.sh 45 benchmark/rq1_codeql_only FP runs

# TP retention: 45-case slice, gold=TP (separate runs root)
./benchmark/run_comparison.sh 45 benchmark/tp_codeql_only TP runs/tp_retention
```

**Usage:** `./benchmark/run_comparison.sh <N> <case-dir> <gold> [runs-root]`

**Outputs:**

- Per case: `{runs-root}/<profile>/llm/<case_id>/`
- Summary: `{runs-root}/comparison_{fp|tp}_{N}.json`

Example: `runs/comparison_fp_45.json`, `runs/tp_retention/comparison_tp_45.json`.

Expect ~1–2 min/case on an L40S → ~1.5–2 h for 45 cases × 2 profiles. Use one GPU; run profiles sequentially.

Shortcut for FP only:

```bash
./benchmark/run_rq1_comparison.sh 45
# equivalent to: ./benchmark/run_comparison.sh 45 benchmark/rq1_codeql_only FP runs
```

---

## Retry missing / wrong results

After a first pass, improve coverage and accuracy:

```bash
cd /path/to/SAST

uv run python benchmark/run_batch.py \
  --agent llm \
  --case-dir benchmark/tp_codeql_only \
  --max-cases 45 \
  --profile qwen3_4b_bnb \
  --runs-root runs/tp_retention \
  --gold TP \
  --retry-missing \
  --retry-wrong

uv run python benchmark/repair_llm_results.py \
  --runs runs/tp_retention \
  --profile qwen3_4b_bnb

uv run python benchmark/summarize_triage.py \
  --case-dir benchmark/tp_codeql_only \
  --max-cases 45 \
  --gold TP \
  --runs runs/tp_retention \
  --json-out runs/tp_retention/comparison_tp_45_v2.json
```

| Flag | Behavior |
|------|----------|
| `--retry-missing` | Re-run if result missing or no valid `label` |
| `--retry-wrong` | Re-run if label ≠ `--gold` (requires `--gold`) |
| `--force` | Re-run all cases |

Repeat for `qwen3_8b_bnb`. Use different `--runs-root` for FP vs TP.

---

## Manual batch (step by step)

```bash
cd /path/to/SAST

uv run python benchmark/run_batch.py \
  --agent llm \
  --case-dir benchmark/rq1_codeql_only \
  --max-cases 45 \
  --profile qwen3_4b_bnb \
  --runs-root runs \
  --gold FP

uv run python benchmark/repair_llm_results.py --runs runs --profile qwen3_4b_bnb

uv run python benchmark/summarize_triage.py \
  --case-dir benchmark/rq1_codeql_only \
  --max-cases 45 \
  --gold FP \
  --runs runs \
  --json-out runs/comparison_fp_45.json
```

Skipped directories: existing valid results are kept unless retry/force flags are set.

---

## Reading results

Example (TP corpus, 45 cases, after retry + prompt v2):

```
System                         Acc*    All    Cov     FP    TP  Miss    N
CodeQL (no filter)           100.0% 100.0% 100.0%   0.0% 100.0%     0   45
Qwen (qwen3_4b_bnb)           68.8%  48.9%  71.1%  31.2% 68.8%    13   45
Qwen (qwen3_8b_bnb)           70.0%  62.2%  88.9%  30.0% 70.0%     5   45
```

| Column | Meaning |
|--------|---------|
| **Acc\*** | Correct ÷ cases with valid model JSON |
| **All** | Correct ÷ N (missing = wrong) |
| **Cov** | Share with valid model JSON |
| **FP / TP** | Model label rates on evaluated cases |
| **Miss** | No valid `label` |

**Gold = FP:** CodeQL baseline = 0% accuracy (keeps all alerts as TP). Qwen should label **FP**.

**Gold = TP:** CodeQL baseline = 100% accuracy. Qwen should label **TP**; **FP** = false dismiss.

Per case: read `llm_raw.txt` and `agent-llm-triage-result.json` under the run directory.

---

## Example artifacts (reference runs)

| Experiment | Summary JSON |
|------------|----------------|
| RQ1 FP, 45 cases | `runs/comparison_fp_45.json` |
| TP retention, 45 cases (first pass) | `runs/tp_retention/comparison_tp_45.json` |
| TP retention, retry + TP prompts | `runs/tp_retention/comparison_tp_45_v2.json` |

Batch logs: `runs/batch_qwen3_4b_45.log`, `runs/batch_qwen3_8b_45.log`, `runs/tp_retention_45.log`, `runs/tp_retention_rerun.log`.

---

## OpenHands (optional)

```bash
# Terminal A
uv run python -m models.qwen.openai_chat_server \
  --host 127.0.0.1 --port 8000 --profile qwen3_8b_bnb

# Terminal B
export LLM_API_KEY=sk-local
uv run python benchmark/run_openhands.py \
  --case benchmark/rq1_codeql_only/OWASP_benchmark_java_BenchmarkTest02721.json \
  --llm-model local-qwen --llm-provider openai
```

---

## Environment / tuning

| Variable | Default | Notes |
|----------|---------|--------|
| `AGENT_MAX_NEW_TOKENS` | `1024` | Increase if JSON is truncated |
| `AGENT_TEMPERATURE` | `0.2` | |
| `AGENT_REPETITION_PENALTY` | `1.12` | Set `1` to disable |

Profiles: `qwen3_4b_bnb`, `qwen3_8b_bnb` (see `models/qwen/runner.py`).

Stack: `uv sync` installs `unsloth`, `transformers` (≤5.5), `torch` (<2.11) per `pyproject.toml`.

---

## Notes

- Task body from `SAST-Paper-Artifacts/Evaluation Framework/make_task.py` (`--eval-framework` to override).
- Local prompt policy in `run_llm_local.py` via `--gold`.
- JSON parsing: `core.parsing.extract_triage_result` (prefers last valid triage object).
- `unsloth_compiled_cache/` is runtime cache; safe to delete; do not commit.
