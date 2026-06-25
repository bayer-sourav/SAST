# Phase 3 — Fine-tuning roadmap

**Current focus:** Phase 3B (teacher distillation + CSS early stopping)  
**Frozen baseline:** Stage 2 GOOD · `5.9b_fs3_legacy` — SRS **92.5%** (VDR 92.5%, FPRR 73.5%)

---

## Phase 3A — completed (post-mortem)

| Item | What we did | Outcome |
|------|-------------|---------|
| Supervision | Gold labels + generic reason string | Model learned label shortcuts, not triage reasoning |
| Train prompt | fs0, thinking **off** | Mismatch vs eval (fs3, thinking **on**) |
| Target | JSON only, no CoT | Eval expects chain-of-thought before JSON |
| Selection | 1 epoch, loss ~0.03, no val metric | No signal that VDR was collapsing |
| Eval | 600-case Phase 2 test | **SRS 70.0%** vs baseline 92.5% |

**Failure mode (confusion matrix):** 83 TP→FP (6× baseline), heavy BL hedging (154 BL predictions vs ~5 for Stage 2). VDR 33.5%, FPRR 58.5%.

**Artifacts:** `runs/phase3/stage3a/` · report `summaries/PHASE3A_REPORT.md`  
**Keep from 3A:** export/preflight/eval shell wiring, LoRA loader path, benchmark test corpora.

---

## Phase 3B — planned (recommended next)

### Data splits & teacher (confirmed)

| Split | Cases | Teacher (Stage 2) | Student use |
|-------|-------|---------------------|-------------|
| **Train** | 500×3 = **1,500** | **Yes** — run `5.9b_fs3_legacy` on every train bundle; distill assistant turn (CoT + JSON) into SFT JSONL | **Fine-tune** on these targets only |
| **Validation** | 200×3 = **600** | **No** — val is never training supervision | **CSS checkpoint selection** — run student + LoRA on val; score vs **dataset gold** (SRS, VDR, FPRR, macro-F1 → CSS) |
| **Test** | 200×3 = **600** (Phase 2 corpora) | **No** | **Final report only** — one chosen checkpoint; same metric suite as val |

Teacher outputs live under `runs/phase3/stage3b/teacher/train/`.  
Validation gold comes from BenchmarkJava **validation** bundles (same label schema: FP / TP / BL).

**Leakage rule:** Phase 2 test case IDs never appear in train SFT or val CSS runs.

### Goal

Compress **Stage 2 teacher** behavior into a LoRA adapter that **beats or matches** Stage 2 on the 600-case held-out test, while keeping **ship prompts language-agnostic**.

### Why teacher distillation (not more gold-label SFT)

1. Stage 2 already encodes the decision boundary we want (92.5% VDR, real evidence chains).
2. Phase 3A showed gold labels alone **destroy recall** — the model never learns *how* the teacher reasons.
3. Teacher `reason` + `evidence` fields on train cases are rich supervision (see Stage 2 `agent-llm-triage-result.json`).
4. Distillation targets can include **full assistant turns** (CoT + JSON), aligning train and eval.

### Why CoT fine-tuning

Eval always runs with **thinking ON**. Training with `enable_thinking=False` (3A) teaches the adapter to skip the reasoning channel the base model uses at inference. **3B trains with thinking ON** and distills the teacher’s reasoning pattern (from `llm_raw.txt` or reconstructed assistant turn).

CoT adds sequence length cost; mitigate with:
- `max_seq_len=16384` (already used)
- Optional cap on thinking tokens in export (truncate only if OOM; prefer full teacher trace)

### Language-agnostic ship prompts

Production will triage **multiple languages**; the **procedure and JSON schema** must not hard-code Java/CodeQL-only wording in the shipped prompt.

| Layer | 3A | 3B plan |
|-------|-----|---------|
| Procedure | `v7-balanced` (Java-flavored) | **`v7-ship`** or scrubbed `v7-balanced`: rule-agnostic steps (trace → resolve sink → structural FP → mitigate → case label) |
| Task body | Per-case code + alerts (language-specific facts) | Unchanged — code/snippets stay language-specific |
| Few-shot | fs0 train / fs3 eval | **fs3 train and eval** (same pack: `v2_3shot_tp_2fp`) |
| System prompt | `_SYSTEM_PROMPT` | Same stable system block |

**Action:** add `v7-ship` prompt version (or env flag) before 3B export; use it for train, val CSS, and test eval.

---

## Composite Selection Score (CSS) — early stopping

CSS ranks **validation-split** checkpoints during training. It is **not** reported as a ship metric.

$$
\text{CSS} = 0.35 \times \text{SRS} + 0.35 \times \text{VDR} + 0.20 \times \text{FPRR} + 0.10 \times \text{Macro-F1}
$$

| Weight | Metric | Rationale |
|--------|--------|-----------|
| 0.35 | SRS | Full asymmetric penalty structure |
| 0.35 | VDR | Missing vulns is worst outcome |
| 0.20 | FPRR | Business value of dismissing noise |
| 0.10 | Macro-F1 | Balanced quality; SRS already weights severity |

**Hard disqualifier:** if **VDR < 0.75** on val → **CSS = 0** (checkpoint not eligible).

Implementation: `benchmark/css.py` · metrics from `benchmark/srs.py` + per-track macro-F1 (same as Phase 2 merge).

### Training loop (3B) — CSS checkpoint selection + rank sweep

**Metrics during training and selection** (identical on val and test):

- SRS, VDR, FPRR, macro-F1 (Phase 2 merge / penalty SRS)
- CSS composite for **ranking only** on val
- Confusion matrix (TP / FP / BL tracks) in summaries

**Do not** use training loss for checkpoint selection.

```
Teacher on TRAIN (1500) → export distill JSONL
     ↓
For each LoRA rank r ∈ {16, 32, 64}:
     train with thinking ON, fs3, ship prompt
     save checkpoint every epoch (and/or every N steps)
     ↓  after each checkpoint
     run student on VAL (600) → SRS, VDR, FPRR, macro-F1 → CSS
     record css_history.json; mark eligible if CSS > 0 (VDR ≥ 0.75)
     early-stop rank run if CSS flat for `patience` evals (default 3)
     hard cap: 10 epochs per rank (safety only — CSS picks the checkpoint)
     ↓
After all ranks finish:
     pool ALL val-eligible checkpoints (every rank × every epoch that passed CSS gate)
     re-run full VAL eval on each eligible adapter (same metrics — confirmation pass)
     pick global best by CSS on val
     ↓
Run TEST (600) once on that single best adapter — authoritative results
```

**LoRA rank sweep** — fixed at **{16, 32, 64}** (see infra rationale below):

| Rank | Alpha | Role |
|------|-------|------|
| 16 | 16 | Same capacity as 3A — isolates supervision/prompt fixes from rank |
| 32 | 32 | **Primary candidate** — typical sweet spot for 9B distillation SFT |
| 64 | 64 | Extra capacity for long CoT traces without 128’s overfitting risk |

**Not in sweep:** rank **128** — on 1,500 distillation examples, returns diminish and memorization risk rises; LoRA VRAM delta vs 64 is negligible on our box, so 128 only adds wall-clock.

**Infra (decided):** single **NVIDIA L40S · 46 GB VRAM** · 124 GB RAM. Phase 3A at r=16, `max_seq_len=16384`, thinking **off** completed in ~73 min/epoch with ~29M trainable params. Phase 3B bottleneck is **sequence length** (thinking ON + teacher CoT), not LoRA rank — 3A train JSONL is already p50 ~25k chars without thinking.

**VRAM / runtime guards:**

- One rank at a time (never parallel on single GPU).
- **Unload trainer before val eval** — never hold train graph + inference model simultaneously.
- Keep `max_seq_len=16384` (train), `batch_size=1`, `grad_accum=8`, Unsloth gradient checkpointing + **`packing=True`**. Do **not** use 8192 — fs3 user prompts alone are ~9.5k tokens at median.
- If OOM with thinking ON: truncate longest teacher assistant turns at export (cap ~12k target tokens), **do not** add higher rank.
- Skip a rank only on hard OOM after truncation — not preemptively.

Each rank produces `runs/phase3/stage3b/lora/r{r}/` with checkpoints + `css_history.json`.

**Final model:** highest **CSS on validation** among all re-evaluated eligible checkpoints across all ranks — not best loss, not last epoch.

**Stopping policy:** train until **CSS stops improving** on val (patience 3 epoch-level evals). No fixed low epoch budget — run as many epochs as needed up to a **hard cap of 10** per rank. Every saved checkpoint stays in the val pool; the global best may be epoch 2 or epoch 9.

Default hyperparameters (shared across ranks unless noted):

| Param | 3A | 3B |
|-------|-----|-----|
| LR | 2e-4 | **5e-5** |
| Epochs | 1 | **open (CSS early stop; hard cap ≤10)** |
| Thinking | off | **on** |
| Few-shot | 0 train / 3 eval | **3 / 3** |
| Supervision | gold JSON | **teacher turn (train only)** |
| Selection | last epoch | **best CSS on val (global across ranks)** |

---

## Performance (decided)

### Why not switch to Qwen3-8B

Phase 2 measured **fs3 + CoT** on the same 600-case test:

| Model | Mean infer (fs3 CoT) | SRS | VDR | Tier |
|-------|----------------------|-----|-----|------|
| **Qwen3.5-9B** (Stage 2 ship) | ~2–5 min/case (long CoT) | **92.5%** | **92.5%** | GOOD |
| **Qwen3-8B** | ~50–60s/case | 79.0% | 51.0% | FAIL |

8B is faster mainly because it emits **~1.5k** output tokens vs 9B’s **~3.9k** (BL fs3), not because the architecture is a free lunch. More importantly:

- Stage 2 **teacher** is **Qwen3.5-9B** — distillation targets are 9B behavior.
- LoRA adapters are **base-model-specific** — an 8B adapter cannot load on 9B.
- 3B goal is to **compress the GOOD-tier 9B ship cell**, not re-benchmark 8B.

**Decision:** stay on **`qwen3_5_9b_bnb`** for teacher, student, train, val CSS, and test — the Phase 2 GOOD ship model. Qwen3-8B was only a speed observation from Phase 2; it is **not** a fine-tuning target for 3B.

### Where time actually goes (3A measured)

| Phase | Observed | Notes |
|-------|----------|-------|
| Train (thinking off, r=16) | ~73 min/epoch | Will rise with thinking ON + longer distill targets |
| Val/test infer (600, LoRA, fs3 CoT) | **~40–50 h** full run | ~12–16 h per 200-case track; heavy tail on long CoT |
| Teacher (1500, one-time) | ~similar per-case to Stage 2 | Acceptable as upfront cost |

The **CSS val loop** (up to 10 epochs × 3 ranks) dominates wall-clock if each epoch runs **full 600-case val**.

### Speed levers (implement in 3B pipeline)

| Lever | Applies to | Expected gain | Risk |
|-------|------------|---------------|------|
| **Fast CSS val (150 stratified)** | Val during training | **~4×** vs full 600 | Noisier CSS; mitigated by full 600 on rerank |
| **Full val only on rerank + test** | Post-train selection | Keeps final pick authoritative | — |
| **Distill truncation** (`PHASE3_MAX_THINKING_TOKENS=4096`) | Train + export | Shorter assistant CoT; **user prompt kept intact** | Truncate thinking block only; never clip JSON |
| **Train `max_seq_len=16384`** | Train | Required — user+fs3 alone is ~10–14k tok at p50 | 8192 clips the case prompt for most rows (see below) |
| **Unsloth `packing=True`** | Train | **~1.3–1.5×** throughput | Verify no cross-example leakage in packed batches |
| **Unsloth import first + FA2** | Train + infer | **~10–30%** | Train logs show FA2 broken → xformers fallback today |
| **In-process batch infer** | Val/test | Already default in `run_batch.py` | — |
| **Skip-existing on teacher** | Teacher 1500 | Resume-friendly | — |

**Fast CSS val spec:** 50 cases per track (FP/TP/BL) from validation split, fixed seed — **150 cases** per epoch checkpoint. Score CSS on this subset during training. **Re-run full 600** on all CSS-eligible checkpoints in `rerank_val_checkpoints.py`. Test eval stays **600**.

**Distill truncation spec:** keep full **user** turn (system + fs3 task with code/alerts). Cap **assistant thinking** at 4096 tokens (trim from the middle if needed); always preserve the final JSON block. If user+assistant still exceeds 16384 after thinking trim, drop the case from SFT (log in export manifest) rather than silently truncating the prompt.

**Why not `max_seq_len=8192` for training:** measured on fs3 eval prompts + Stage 2 teacher CoT:

| Component | Est. tokens (p50 / p95) |
|-----------|-------------------------|
| User prompt alone (`task.md`, fs3) | **~9.5k / ~18k** |
| Teacher assistant CoT (`llm_raw`) | ~4k / ~8.3k |
| **Combined (3B train row)** | **~13.5k / ~26k** |

At 8192, **most rows lose the case context or the label** — the bottleneck is the fs3 **input**, not LoRA rank. **16384** fits ~p50 combined sequences after thinking truncation; ~4% of rows may still need thinking trim or drop at p99. Speed comes from **truncating CoT**, **packing**, and **fast val** — not from shrinking `max_seq_len` below the prompt size.

**Fast CSS val (150):** agreed — 50 per track (FP/TP/BL), fixed seed, during training only. Full **600** on rerank + test.

**Not doing for 3B.0:** vLLM, multi-GPU, switching base model, `max_seq_len=8192`.

### Env knobs (3B)

```bash
# Training — 16384 required for fs3 user prompts; speed via CoT trim + packing
PHASE3_MAX_SEQ_LEN=16384
PHASE3_MAX_THINKING_TOKENS=4096
PHASE3_PACKING=1

# Fast CSS val during training (full 600 on rerank only)
PHASE3_CSS_VAL_MODE=fast
PHASE3_CSS_VAL_N=150

# Inference (same caps as Phase 2 ship)
PHASE2_ON_MAX_NEW_TOKENS=8192
PHASE2_ON_MAX_NEW_TOKENS_THINKING=8192
```

---

## Pipeline (3B — to implement)

```bash
# 0. Teacher on TRAIN only (1500 cases)
uv run python benchmark/phases/phase3/run_stage2_teacher_on_split.py --split train

# 1. Export distillation JSONL from teacher cache
uv run python benchmark/phases/phase3/export_distill_dataset.py \
  --split train --prompt-version v7-ship --thinking --fewshot 3

# 2. Preflight (leakage, teacher coverage, val/test IDs disjoint)
uv run python benchmark/phases/phase3/preflight_phase3.py --stage 3b

# 3. Train + CSS val eval — rank sweep (sequential)
for r in 16 32 64; do
  PHASE3_LORA_R=$r PHASE3_LORA_ALPHA=$r \
    uv run python benchmark/phases/phase3/run_unsloth_lora_css.py
done

# 4. Re-eval all CSS-eligible checkpoints on val (confirmation pass)
uv run python benchmark/phases/phase3/rerank_val_checkpoints.py

# 5. Test eval on single global-best adapter
PHASE3_STAGE=3b PHASE3_BEST_ADAPTER=runs/phase3/stage3b/lora/best \
  bash benchmark/phases/phase3/run_phase3_eval.sh

# 6. Report vs Stage 2 (same metrics as val CSS)
uv run python benchmark/phases/phase3/report_phase3_status.py --stage 3b
```

Orchestrator: `run_phase3b.sh` (train sweep → val rerank → test eval).

---

## Data & leakage

| Split | N | Teacher | Use |
|-------|---|---------|-----|
| Train | 500×3 | **Yes** (distillation targets) | SFT only |
| Validation | 200×3 | No (score vs **gold**) | CSS checkpoint pool + rerank |
| Test (Phase 2 corpora) | 200×3 | No | Final report only |

Teacher cache: `runs/phase3/stage3b/teacher/train/{fp,tp,bl}/...`  
Val eval artifacts: `runs/phase3/stage3b/val_eval/r{rank}/checkpoint-{step}/...`  
Checkpoint registry: `runs/phase3/stage3b/summaries/css_eligible.json`

---

## Iteration ladder

| Stage | Change | Success criterion |
|-------|--------|-------------------|
| **3B.0** | Teacher distill + CoT + fs3 + CSS + **rank sweep {16,32,64}** | Best val CSS eligible; test SRS ≥ Stage 2 |
| **3B.1** | TP class oversampling (1.5×) if VDR weak | Val VDR ≥ 0.90 |
| **3B.2** | DPO pairs: (teacher correct, student wrong) from val | Test SRS +2pp vs 3B.0 |
| **3C** | Cross-language corpora + same `v7-ship` procedure | Per-language val CSS |

Log every run in [`EXPERIMENTS.md`](EXPERIMENTS.md).

---

## Phase 3A artifacts (reference)

| Path | Role |
|------|------|
| `stage3a/MANIFEST.json` | 3A config |
| `export_sft_dataset.py` | Gold-label export (superseded by distill export) |
| `run_unsloth_lora.py` | Loss-only trainer (superseded by CSS trainer) |
| `runs/phase3/stage3a/summaries/` | 3A eval + confusion comparison |

---

## Open decisions (resolve before coding 3B.0)

1. **`v7-ship` prompt text** — fork from `v7-balanced` with Java/CodeQL examples moved to few-shot only, or new procedure file?
2. **Teacher on wrong gold** — keep teacher label always, or override with gold when teacher disagrees with dataset label?
3. **Val eval cost** — **decided:** fast 150-case stratified CSS during training; full 600 on rerank only.
4. **Thinking in target** — full `llm_raw.txt` vs parsed thinking block + JSON only?

**Recommendation:** (1) fork `v7-ship` now; (2) teacher label + teacher reason, drop cases with missing teacher; (3) full val every epoch first, subsample only if too slow; (4) full raw assistant turn for maximum CoT alignment.
