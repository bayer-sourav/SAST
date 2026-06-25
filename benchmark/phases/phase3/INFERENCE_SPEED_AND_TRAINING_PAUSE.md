# Phase 3B — Inference Speed Audit & Training Pause (2026-06-22)

## Summary

Phase 3B LoRA training was **paused** to validate inference-speed fixes before continuing.
The dominant latency issue is **~14 output tok/s** on Unsloth native `generate()` (not L40S VRAM).
A real **EOS token bug** caused ~24% of runs to decode until `max_new_tokens` (4096–8192).

---

## Training pause state

| Item | Value |
|------|--------|
| **Stopped** | 2026-06-22 ~07:07 UTC (user request) |
| **Rank** | 32 only (fast path; ranks 16/64 skipped) |
| **Checkpoint** | `runs/phase3/stage3b/lora/r32/checkpoint-159` |
| **Progress** | epoch **1.0**, global_step **159**, loss **0.109** @ step 150 |
| **CSS evals** | None yet (first eval scheduled epoch 2, every 2 epochs) |
| **Distill data** | `runs/phase3/stage3b/data/distill_train.jsonl` — **1265** records |

Training did **not** fail; it was intentionally stopped for inference validation.

---

## Root-cause audit (four hypotheses)

### 1. Missing EOS token — **CONFIRMED & FIXED**

| Finding | Detail |
|---------|--------|
| `AutoConfig.eos_token_id` | **None** for `unsloth/Qwen3.5-9B` |
| `tokenizer.eos_token_id` | **248046** (`<\|redacted_im_end\|>`) |
| Code path | `_generate_unsloth()` called `model.generate()` **without** `eos_token_id` |
| Symptom | **24.1%** of 1,501 runs ended within 50 tokens of 4096/8192 cap |
| Fix | `models/qwen/runner.py` → `_qwen_apply_generate_defaults()` |

**Fix details:**
- Set `eos_token_id` and `pad_token_id` from tokenizer
- Also stop on `<|endoftext|>` (248044) via `QWEN_EXTRA_EOS_TOKEN_IDS` (default `248044`)
- `use_cache=True` for decode-phase KV cache
- Patch `model.generation_config.eos_token_id` when config is null
- Debug: `QWEN_GEN_DEBUG=1`

### 2. Unsloth native inference — **CONFIRMED (main bottleneck)**

| Finding | Detail |
|---------|--------|
| Stack | `FastLanguageModel.for_inference()` + HF `.generate()`, batch=1 |
| Measured | **~14 tok/s** decode (median 14.8) across 1,501 runs |
| Target (vLLM + FA2) | 40–70+ tok/s on L40S |
| Fix (production) | Export LoRA → **vLLM** serving (not yet in repo) |

### 3. flash-attn — **CONFIRMED MISSING**

| Finding | Detail |
|---------|--------|
| `flash_attn` | Not installed (compile killed earlier) |
| Fallback | xformers 0.0.35 |
| Impact | ~1.5–2× slower than FA2 on long sequences |
| Fix | Compile when GPU free: `uv pip install flash-attn --no-build-isolation` |

### 4. Few-shot prefill overhead — **PARTIAL**

| Finding | Detail |
|---------|--------|
| Input tokens | ~9.4k mean (fs3 + code) |
| Mitigation | Model loaded once per batch; `use_cache=True` now explicit |
| Further win | vLLM prefix caching (future) |

---

## Measured baseline (pre-fix, n=1501)

| Metric | Value |
|--------|-------|
| Mean decode speed | **13.8 tok/s** |
| Median output tokens | **2,191** |
| Mean output tokens | **2,769** |
| Cases hitting ~4096 cap | **24.1%** |
| Cases hitting 8192 cap | **1.3%** |
| Median inference time | **~4.5 min** (Stage 2 ship) |

---

## Validation benchmark (post-fix)

**Script:** `benchmark/phases/phase3/bench_infer_speed_fix.py`

```bash
cd /home/ec2-user/Projects/SAST
source benchmark/phases/phase3/phase3b_env.sh
source benchmark/phase2_cell_env.sh
phase2_apply_token_limits on qwen3_5_9b_bnb

QWEN_GEN_DEBUG=1 .venv/bin/python benchmark/phases/phase3/bench_infer_speed_fix.py \
  | tee runs/phase3/stage3b/logs/bench_infer_speed_fix.log
```

**Cases:** 3 prior cap-hitters + 2 typical FP test cases.

**Output:** `runs/phase3/stage3b/infer_fix_bench/bench_infer_speed_fix.json`

Compare columns: `old_out`/`new_out`, `old_sec`/`new_sec`, `old_tps`/`new_tps`.

**Run completed:** 2026-06-22 ~07:40 UTC (~30 min wall time for 5 cases).

```bash
PYTHONPATH="$PWD:$PWD/benchmark" QWEN_GEN_DEBUG=1 .venv/bin/python \
  benchmark/phases/phase3/bench_infer_speed_fix.py \
  | tee runs/phase3/stage3b/logs/bench_infer_speed_fix.log
```

### Benchmark results (n=5)

| Case | old_out → new_out | old_sec → new_sec | old_tps → new_tps | rc | Notes |
|------|-------------------|-------------------|-------------------|-----|-------|
| BenchmarkTest00242 | 8192 → **4096** | 573 → 574 | 14.3 → 7.1 | 0 | Still **hits 4096 cap**; wall time unchanged (token limit halved, not EOS stop) |
| BenchmarkTest00942 | 8192 → — | 579 → — | 14.1 → — | **1** | Inference ran ~551s; **JSON parse failed** after decode (unrelated to EOS) |
| BenchmarkTest00524 | 8077 → **2111** | 574 → **426** | 14.1 → 5.0 | 0 | **−26% wall time**; EOS stopped early |
| BenchmarkTest00042 | 1197 → 1566 | 107 → 104 | 11.2 → **15.1** | 0 | Typical case; decode speed ~15 tok/s |
| BenchmarkTest02076 | 5518 → **2446** | 377 → **163** | 14.6 → **15.0** | 0 | **−57% wall time**; EOS stopped early |

**Successful cases (n=4):** median wall-time **−24%** (107→104s typical; 377→163s long-tail).

**Verdict:**

| Fix | Effect |
|-----|--------|
| EOS + `use_cache` | **Helps long-tail cases** where the model emits stop tokens before cap (02076, 00524). **No gain** when output still runs to `max_new_tokens` (00242). |
| Token cap 8192→4096 | Cuts worst-case decode length in half for cap-hitters; does not improve tok/s (~14–15 unchanged on normal cases). |
| Unsloth native decode | Still **~15 tok/s** on typical cases — main bottleneck remains. |

**Conclusion:** EOS/`use_cache` fixes are **insufficient** (~15 tok/s Unsloth unchanged). **Training paused** — pivot to **vLLM + flash-attn** before resuming LoRA.

Full JSON: `runs/phase3/stage3b/infer_fix_bench/bench_infer_speed_fix.json`

---

## vLLM + flash-attn (current work)

**Decision (2026-06-22):** Do **not** resume LoRA training until inference is fast enough. Training remains stopped at `checkpoint-159`.

### Install

```bash
cd /home/ec2-user/Projects/SAST
bash benchmark/phases/phase3/install_vllm_flash_attn.sh
```

- **vLLM** `0.17.0` — Qwen3.5 support, compatible with torch 2.10 (project pin).
- **flash-attn** — compile via `uv pip install flash-attn --no-build-isolation` (15–45 min).
- **Note:** vLLM downgrades `transformers` to 4.x; restore `transformers>=5.5` before Unsloth LoRA training.

### Enable vLLM inference

```bash
export QWEN_INFER_BACKEND=vllm
export QWEN_VLLM_MODEL_ID=Qwen/Qwen3.5-9B   # BF16 on L40S (~18GB weights)
source benchmark/phases/phase3/phase3b_env.sh
source benchmark/phase2_cell_env.sh
phase2_apply_token_limits on qwen3_5_9b_bnb
```

Code: `models/qwen/vllm_backend.py` — wired via `QWEN_INFER_BACKEND=vllm` in `models/qwen/runner.py`.

Optional LoRA at inference: `export SAST_LORA_ADAPTER=runs/phase3/stage3b/lora/r32/checkpoint-159`

### Benchmark vLLM vs baseline

```bash
PYTHONPATH="$PWD:$PWD/benchmark" QWEN_INFER_BACKEND=vllm QWEN_GEN_DEBUG=1 \
  .venv/bin/python benchmark/phases/phase3/bench_vllm_speed.py \
  | tee runs/phase3/stage3b/logs/bench_vllm_speed.log
```

Output: `runs/phase3/stage3b/vllm_bench/bench_vllm_speed.json`

Target: **40–70+ tok/s** decode on L40S (vs ~15 Unsloth).

### Throughput tuning (enabled by default)

| Env | Default | Effect |
|-----|---------|--------|
| `QWEN_VLLM_PREFIX_CACHING` | `1` | Reuse KV for shared few-shot/system prefix across cases |
| `QWEN_VLLM_BATCH_SIZE` | `4` | Micro-batch N cases per vLLM `chat()` call in `run_batch.py` |
| `QWEN_VLLM_MAX_NUM_BATCHED_TOKENS` | `16384` | Scheduler token budget for batched prefill |

CSS eval (`eval_val_for_css.py` → `run_batch.py`) picks these up automatically when `phase3b_env.sh` is sourced.

---

## Resume training (after vLLM validated)

### Option A — Resume from checkpoint

```bash
# Restore Unsloth stack first:
uv pip install 'transformers>=5.5.0,<5.6.0' 'unsloth>=2026.5.2'
unset QWEN_INFER_BACKEND   # or export QWEN_INFER_BACKEND=unsloth

cd /home/ec2-user/Projects/SAST
source benchmark/phases/phase3/phase3b_env.sh
source benchmark/phase2_cell_env.sh
phase2_apply_token_limits on qwen3_5_9b_bnb

export PHASE3_RESUME_CHECKPOINT=runs/phase3/stage3b/lora/r32/checkpoint-159
export PHASE3_LORA_RANKS=32
export PHASE3_CSS_EVAL_EVERY=2

PHASE3B_SKIP_INFRA=1 PHASE3B_SKIP_TEACHER=1 PHASE3B_SKIP_EXPORT=1 \
PHASE3B_SKIP_RERANK=1 PHASE3B_SKIP_TRAIN=0 \
nohup bash benchmark/phases/phase3/run_phase3b.sh \
  >> runs/phase3/stage3b/logs/phase3b_train.log 2>&1 &
```

Use `QWEN_INFER_BACKEND=vllm` for CSS eval during training once benchmark confirms speedup.

### Option B — Restart rank-32 from scratch

```bash
rm -rf runs/phase3/stage3b/lora/r32   # only if you accept losing checkpoint-159
PHASE3B_SKIP_INFRA=1 PHASE3B_SKIP_TEACHER=1 PHASE3B_SKIP_EXPORT=1 \
  nohup bash benchmark/phases/phase3/run_phase3b.sh \
  >> runs/phase3/stage3b/logs/phase3b_train.log 2>&1 &
```

### After training completes

Orchestrator continues with rerank + test eval unless skipped:

```bash
PHASE3B_SKIP_INFRA=1 PHASE3B_SKIP_TEACHER=1 PHASE3B_SKIP_EXPORT=1 \
PHASE3B_SKIP_TRAIN=1 \
bash benchmark/phases/phase3/run_phase3b.sh
```

---

## Code changes (this session)

| File | Change |
|------|--------|
| `models/qwen/runner.py` | `_qwen_apply_generate_defaults()` — EOS, pad, use_cache |
| `benchmark/phases/phase3/bench_infer_speed_fix.py` | Before/after inference benchmark |
| `benchmark/phases/phase3/run_unsloth_lora_css.py` | `PHASE3_RESUME_CHECKPOINT` support |
| `benchmark/phases/phase3/phase3b_env.sh` | Default `PHASE3_LORA_RANKS=32`, `PHASE3_CSS_EVAL_EVERY=2` |
| `benchmark/phases/phase3/eval_val_for_css.py` | Drop `uv run` in summarize subprocesses |
| `benchmark/phases/phase3/bench_infer_speed_fix.py` | `PYTHONPATH` fix for `timing` module; OWASP case path resolver |

---

## Timeline

| Time (UTC) | Event |
|------------|-------|
| 2026-06-22 ~07:07 | LoRA r=32 training **stopped** at `checkpoint-159` (epoch 1.0, loss ~0.109) |
| 2026-06-22 ~07:10 | Inference benchmark started (EOS validation) |
| 2026-06-22 ~07:40 | EOS benchmark completed — insufficient (~15 tok/s) |
| 2026-06-22 ~07:42 | Training briefly resumed, then **stopped** per user — pivot to vLLM |
| 2026-06-22 ~08:xx | Full vLLM benchmark done — mean **25.7 tok/s** (4/5 cases); flash-attn built |
| 2026-06-22 ~08:xx | **Resumed** LoRA r=32 from `checkpoint-159`; `QWEN_INFER_BACKEND=vllm` default for CSS/eval |

---

## Roadmap (inference speed)

| Priority | Action | Expected gain |
|----------|--------|---------------|
| **P0** | EOS fix (done) | Large on cap-hit cases; moderate overall |
| **P1** | vLLM export + serve | **3–5×** throughput |
| **P2** | flash-attn compile | **~1.5–2×** on long decode |
| **P3** | vLLM prefix cache for fs3 | Faster prefill on repeated prompt prefix |

**Note:** CSS validation during training also runs inference (150 fast val cases per eval).
Faster inference directly speeds up the train→eval loop, not just teacher/batch jobs.

---

## Monitor commands

```bash
# Training
tail -f runs/phase3/stage3b/logs/phase3b_train.log

# Inference benchmark
tail -f runs/phase3/stage3b/logs/bench_infer_speed_fix.log
cat runs/phase3/stage3b/infer_fix_bench/bench_infer_speed_fix.json

# GPU
watch -n 10 nvidia-smi
```
