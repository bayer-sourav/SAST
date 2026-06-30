# Phase 3C — Ship-aligned distillation (fs0_off train + val)

**Status:** Complete (2026-06-30)  
**Prior:** Phase 3B complete — best ship test SRS **89.9%** (epoch 4, `best_fs0_off`) vs Stage 2 **92.5%**  
**Frozen baseline:** Stage 2 GOOD · `5.9b_fs3_legacy` — SRS 92.5% · FPRR 73.5% · VDR 92.5%

---

## Problem statement (from 3B)

Phase 3B trained and selected checkpoints under **fs3 + CoT** (teacher-matched), but production ships **fs0 + thinking off**. That train/serve mismatch:

| Issue | Evidence |
|-------|----------|
| Wrong val pick | fs3 CSS best = epoch **6**; fs0_off rerank best = epoch **4** |
| FPRR gap | Ship test FPRR **66.2%** vs Stage 2 **73.5%** (−7.3pp) — main SRS gap |
| VDR recovered | Ship VDR **90.3%** ≈ acceptable; recall less of a blocker |

**Hypothesis:** Retrain with **user prompts and val CSS identical to ship inference**, supervising **teacher JSON verdict only** (no CoT in the training target). Checkpoint selection on val under fs0_off should pick adapters that generalize to test without a post-hoc rerank correction.

**Ship constraint:** Production triages **multiple languages** — procedure and prompts must be **language-agnostic** (`v7-ship`). Case snippets and teacher `reason` text remain language-specific facts; the **policy** must not hard-code Java/CodeQL.

---

## Language-agnostic ship (`v7-ship`)

| Layer | Language-specific (OK in inputs) | Language-agnostic (ship policy) |
|-------|----------------------------------|--------------------------------|
| Procedure (`Your task`) | — | Rule-agnostic steps; no `java/` rule IDs; "SAST tool" not CodeQL |
| Alerts header | Tool SARIF/flow metadata | "SAST tool alerts"; `java/xss` displayed as `xss` |
| Source snippet | Java (BenchmarkJava) | Model reads whatever language is shown |
| Teacher JSON `reason` | May cite ESAPI, methods, etc. | Distilled as-is — evidence, not procedure |

Implementation: `benchmark/prompt_versions.py` (`_procedure_v7_ship`) + `make_task.py` ship-aware alert formatting.

---

## Design

### What changes vs 3B

| Layer | Phase 3B | Phase 3C |
|-------|----------|----------|
| Teacher source | Stage 2 fs3+CoT on train | **Reuse** `runs/phase3/stage3b/teacher/train` |
| Train user prompt | v7-ship · fs3 · thinking on | v7-ship · **fs0 · thinking off** |
| Train target | Full assistant (CoT + JSON) | **JSON verdict only** (parsed from teacher) |
| Val CSS infer | fs3 + CoT (mismatch) | **fs0 + thinking off** (ship) |
| `max_seq_len` | 16384 | **12288** (fs0+json; recovers long sources) |
| LoRA rank | r=32 primary | **r=32** first; optional r=64 if FPRR still short |
| Test eval | fs3 + fs0 ablations | **fs0_off only** (authoritative ship) |

### What stays the same

- Base model: Qwen3.5-9B 4-bit (Unsloth)
- Train split: 1500 cases (500×3), teacher distillation labels
- Val split: 600 cases, gold labels for CSS
- Test split: 600 Phase 2 holdout (never in train/val)
- CSS formula + VDR ≥ 0.75 disqualifier (`benchmark/css.py`)
- Fast val (150 stratified) during training; full val (600) on CSS-eligible checkpoints after training

---

## Workflow

```
Reuse 3B teacher cache (1500 train)
     ↓
export_distill_dataset.py  (target=json_only, fs0 user prompt)
     ↓
preflight_phase3.py --stage 3c
     ↓
run_unsloth_lora_css.py  (enable_thinking=False, CSS val fs0_off each epoch)
     ↓
rerank_val_checkpoints.py  (full 600 val on CSS-eligible ckpts)
     ↓
run_phase3_eval.sh  (fs0_off test, once on global best)
     ↓
reports → runs/phase3/stage3c/summaries/ + reports/phase3c/
```

---

## Success gates

| Gate | Target |
|------|--------|
| **Primary** | Test SRS ≥ Stage 2 (92.5%) under fs0_off |
| **FPRR** | ≥ 73.5% (close −7pp gap from 3B ship) |
| **VDR** | ≥ 90% (maintain 3B ship level) |
| **Critical** | TP→FP ≤ 20 (3B ship was 17; Stage 2 was 14) |

Secondary: val pick epoch at train time ≈ fs0_off rerank pick (no train/serve correction needed).

---

## Artifacts

| Path | Role |
|------|------|
| `benchmark/phases/phase3/stage3c/MANIFEST.json` | Authoritative config |
| `runs/phase3/stage3c/data/distill_train.jsonl` | Ship-aligned SFT |
| `runs/phase3/stage3c/lora/r32/` | Training checkpoints |
| `runs/phase3/stage3c/val_eval/` | Per-epoch CSS (fs0_off) |
| `runs/phase3/stage3c/lora/best` | Global best after full val rerank |
| `runs/phase3/stage3c/eval/` | Final test eval |
| `runs/phase3/stage3c/summaries/` | Metrics + reports |

---

## Commands

```bash
cd /path/to/SAST
source benchmark/phases/phase3/phase3c_env.sh

# Full pipeline (teacher skipped — reuses 3B)
bash benchmark/phases/phase3/run_phase3c.sh

# Or stepwise:
PHASE3C_SKIP_TRAIN=1 bash benchmark/phases/phase3/run_phase3c.sh  # export + preflight only
```

---

## Fallback / Phase 3D ideas

See `reports/phase3c/PHASE3C_NEXT.md` for full plan. Summary:

- **3D primary:** hard-negative mining on TP→FP errors; VDR-weighted CSS; rank 64 json_only
- **Data recovery:** re-export toward 1500 train records (217 currently dropped)
- **Not recommended:** remove BL from train only (see NEXT doc)
- DPO on Stage 2 vs 3C confusion deltas (3E)
