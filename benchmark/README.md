# RQ1 benchmark (CodeQL-only, local Qwen)

Assumes this repo (`SAST`) sits next to `SAST-Paper-Artifacts` (sibling under the same parent folder).

If **BenchmarkJava** is also a sibling (`Projects/SAST`, `Projects/BenchmarkJava`, …), you can **omit `--repo`**; scripts use `../BenchmarkJava` when that folder contains `case["file"]`.

**Otherwise** pass `--repo` to your checkout. The triage task embeds source from `make_task.py` via `repo_root / case["file"]`, so the path must be real.

## 1. CodeQL-only case JSONs

```bash
cd /path/to/SAST
python benchmark/build_codeql_cases.py
```

Writes `benchmark/rq1_codeql_only/*.json` (skips cases with no CodeQL in `raw_output`).

## 2. Local OpenAI-compatible server (for OpenHands)

Terminal A — from `SAST` root (needs GPU for Unsloth path):

```bash
python -m models.qwen.openai_chat_server --host 127.0.0.1 --port 8000 --profile qwen3_8b_bnb
```

OpenHands (Terminal B) needs an API key and base URL pointing at this server. Set whatever your OpenHands version reads for OpenAI-compatible backends, for example:

```bash
export LLM_PROVIDER=openai
export LLM_API_KEY=sk-local
export LLM_MODEL=local-qwen
# If required, set your install's base-URL env for the OpenAI client (often OPENAI_API_BASE or similar).
```

Then run one case:

```bash
cd /path/to/SAST
export LLM_API_KEY=sk-local
python benchmark/run_openhands.py \
  --case benchmark/rq1_codeql_only/OWASP_benchmark_java_BenchmarkTest02721.json \
  --llm-model local-qwen --llm-provider openai
```

(Add `--repo /other/path/BenchmarkJava` only if the repo is not a sibling named `BenchmarkJava`.)

## 3. Vanilla LLM baseline (no LiteLLM)

```bash
cd /path/to/SAST
python benchmark/run_llm_local.py \
  --case benchmark/rq1_codeql_only/OWASP_benchmark_java_BenchmarkTest02721.json \
  --profile qwen3_8b_bnb
```

Artifacts: `runs/<profile>/llm/<case_id>/agent-llm-triage-result.json`.

## 4. Small batch

```bash
cd /path/to/SAST
python benchmark/run_batch.py --agent llm --case-dir benchmark/rq1_codeql_only --max-cases 5 \
  --profile qwen3_8b_bnb
```

With a sibling `BenchmarkJava/`, `--repo` is optional (same as single-case scripts). Use `--repo` only if the checkout lives elsewhere.

For OpenHands, start the chat server first; ensure env vars so OpenHands hits `http://127.0.0.1:8000/v1`.

```bash
python benchmark/run_batch.py --agent openhands --case-dir benchmark/rq1_codeql_only --max-cases 2 \
  --llm-model local-qwen --llm-provider openai
```

Existing run directories are skipped.

## Notes

- `make_task.py` and `openhands_config.toml` are reused from `SAST-Paper-Artifacts/Evaluation Framework` (override with `--eval-framework`).
- Chat server does not support streaming; it parses Qwen ``<tool_call>...</tool_call>`` into OpenAI `tool_calls` when present.
- Qwen profiles: see `models/qwen/runner.py` module docstring.
