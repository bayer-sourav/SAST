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
| **FPRR / VDR** | Task-specific rate (FP track / TP track); see Phase 1 section |
| **F1** | F1 with gold label as positive class (per track in `summarize_triage.py`) |
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

Stack: `uv sync` installs `unsloth`, `transformers` (5.5.x for Gemma 4), `torch` (<2.11) per `pyproject.toml`.

---

## Phase 1 matrix (50 FP + 50 TP, seed 42)

**Full replication runbook:** [`benchmark/PHASE1.md`](PHASE1.md) (prerequisites, fresh run, resume, outputs, gap fixes).

Quick start:

```bash
uv sync
uv run python benchmark/build_codeql_cases.py
uv run python benchmark/build_tp_codeql_cases.py
touch benchmark/phase1_logs/phase1_skip_coder.txt   # optional: skip 30B coder on 44GB GPU
nohup bash ./benchmark/run_phase1_matrix.sh >> benchmark/phase1_logs/phase1_master.log 2>&1 &
uv run python benchmark/phase1_status.py
```

When finished (or after manual fixes): `bash ./benchmark/refresh_phase1_summaries.sh`

### Phase 1 metrics (what the columns mean)

Phase 1 runs **two corpora** on the **same 50 case IDs** (seed 42), then merges them:

| Track | Slice | Gold label | Model should predict | Metric on that track |
|-------|--------|------------|----------------------|----------------------|
| FP | `fp_n50_seed42` | **FP** | `FP` (dismiss alert) | **FPRR** — false-positive removal rate |
| TP | `tp_n50_seed42` | **TP** | `TP` (keep alert) | **VDR** — vulnerability detection / TP retention rate |

**SRS** (security review score) = `0.5 × FPRR + 0.5 × VDR` — equal weight on “clean up noise” vs “don’t drop real bugs.”

**F1** (macro) = `0.5 × F1-FP + 0.5 × F1-TP`, where each track F1 uses the **gold label as the positive class** (same definition as `summarize_triage.py`):

- **F1-FP** — on the FP slice, positive class = `FP`; balances precision/recall for “correctly dismissed.”
- **F1-TP** — on the TP slice, positive class = `TP`; balances precision/recall for “correctly kept.”

F1 penalizes both false dismissals and false keeps more than raw rate metrics; it is **not** the same as accuracy when the model skews toward one label.

**Cov-FP / Cov-TP** = share of the 50 cases with a valid `label` in `agent-llm-triage-result.json` (not the same as accuracy). Low coverage means parse failures, truncation, or missing runs — not “model said UNKNOWN.”

`phase1_status.py` and `FP-runs/phase1_n50/phase1_matrix_thinking_{off,on}.json` report these numbers.

### Phase 1 results on this machine (reference snapshot)

Non-coder profiles only (`qwen3_coder_30b_bnb` skipped). Regenerate after new runs with `bash benchmark/refresh_phase1_summaries.sh`.

| Profile | Thinking | FPRR | VDR | SRS | F1 | F1-FP | F1-TP |
|---------|----------|------|-----|-----|-----|-------|-------|
| qwen3_4b_bnb | off / on | 100% | 62% | 81% | 81% | 100% | 62% |
| qwen3_8b_bnb | off | 100% | 100% | **100%** | **100%** | 100% | 100% |
| qwen3_8b_bnb | on | 72% | 80% | **76%** | **76%** | 72% | 80% |
| qwen3_14b_bnb | off / on | 100% | 80% | 90% | 90% | 100% | 80% |
| gpt_oss_20b | off / on | 58% | 92% | 75% | 75% | 58% | 92% |

**CodeQL baseline** (in `summarize_triage.py`): on the FP track it keeps every alert as TP → 0% FPRR; on the TP track it keeps every alert → 100% VDR. SLMs are compared against that “no triage filter” reference.

### Why thinking **on** can score **worse** than thinking **off**

Here, the clearest example is **qwen3_8b_bnb**: SRS and macro **F1** both **100%** (thinking off) vs **76%** (thinking on). **qwen3_4b** and **qwen3_14b** did not move between modes on this slice; **gpt_oss** thinking_on numbers match thinking_off because those runs were **synced from thinking_off** (`fill_gpt_oss_thinking_on.py`) — GPT-OSS does not implement Qwen-style thinking in this stack.

Plausible mechanisms (not mutually exclusive):

1. **Token budget** — Thinking on allows up to **16k new tokens** (vs **4k** off). Long chain-of-thought can crowd out the final JSON triage object, hit limits, or produce malformed output that fails parsing (hurts **coverage** when it happens; here coverage stayed 100% for 8B).

2. **Over-dismissal on the TP track** — With thinking on, **qwen3_8b** FPRR on the FP track fell from 100% → **72%** (more alerts left as TP). On the TP track, VDR fell 100% → **80%** (more gold-TP cases labeled FP). That pattern looks like **extra reasoning makes the model more conservative** — it “talks itself into” keeping or dismissing alerts differently, not strictly better on either task.

3. **Qwen3 template behavior** — For Qwen profiles, thinking off appends **`/no_think`** on the last user turn; thinking on sets `enable_thinking=True` in chat template / generation. That is a real distribution shift, not just “more max tokens.”

4. **Parser reads the final JSON** — `core.parsing` / `repair_llm_results.py` take the **last** JSON object in the output. Reasoning text before the JSON can add noise; if the model emits JSON inside the think block and again after, behavior depends on which object wins.

5. **Same accuracy on 4B/14B** — No change does **not** prove thinking is harmless; it may mean those sizes are less sensitive on this N=50 slice, or errors on thinking-on cases were fixed by **rerun/repair** so metrics match. Always check per-case `llm_raw.txt` when investigating.

**Practical takeaway for Phase 1:** treat **thinking off** as the default triage setting unless you explicitly want CoT and accept lower SRS on models like 8B. Do not compare **gpt_oss** thinking_on vs off for CoT effect until you run separate GPT generations with `--thinking`.

### Other result patterns worth knowing

| Observation | Likely explanation |
|-------------|-------------------|
| High FPRR, moderate VDR (e.g. 4B: 100% / 62%) | Strong at dismissing FPs on the FP slice; on the TP slice still labels ~38% of gold-TP as FP (false dismiss). SRS is balanced down by VDR. |
| gpt_oss low FPRR, high VDR (58% / 92%) | Opposite bias: reluctant to call FP, better at keeping TP — good for retention, weak for noise removal. |
| 8B best with thinking off | Matches “larger model + direct JSON” beating “same model + long CoT” on a fixed wall-clock / token setup. |
| Coder 0% everywhere | Cells not successfully run on this host (see `phase1_logs/phase1_skip_coder.txt`); metrics are placeholders. |
| Cov &lt; 100% | Missing or invalid `agent-llm-triage-result.json`; run `repair_llm_results.py` or `rerun_bad_cases.py`, then `refresh_phase1_summaries.sh`. |

Per-case debugging: `{FP|TP}-runs/phase1_n50/thinking_{off|on}/<profile>/llm/<case_id>/` → `llm_raw.txt`, `agent-llm-triage-result.json`, `run_meta.json`.

---

## Notes

- Task body from `SAST-Paper-Artifacts/Evaluation Framework/make_task.py` (`--eval-framework` to override).
- Local prompt policy in `run_llm_local.py` via `--gold`.
- JSON parsing: `core.parsing.extract_triage_result` (prefers last valid triage object).
- `unsloth_compiled_cache/` is runtime cache; safe to delete; do not commit.
