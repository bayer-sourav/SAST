# Phase 2 — Prompting ablation (approved)

**Status:** Implemented — `run_phase2_matrix.sh`

## Design

| Dimension | Levels |
|-----------|--------|
| Dataset | `SAST-Benchmark-Dataset` Java **test** split: 200 FP + 200 TP + 200 BL |
| Models (core) | `qwen3_4b_bnb`, `qwen3_8b_bnb`, `qwen3_14b_bnb` (Unsloth); `qwen3_coder_30b_bnb` (Bedrock) |
| Models (extension) | `qwen3_5_4b_bnb`, `qwen3_5_9b_bnb` (Unsloth 4-bit: `unsloth/Qwen3.5-4B`, `unsloth/Qwen3.5-9B`) |
| Few-shot | 0 (zero-shot), 3 (frozen train exemplars in `benchmark/few_shot_examples.json`) |
| Thinking | **off** (full matrix first), then **on** |
| Prompt | Unified 4-label `make_task.py` + optional few-shot in system message |

## Run order

1. All **thinking off** cells: 4B → 8B → 14B → coder; per model FP → TP → BL; fewshot 0 → 3  
2. All **thinking on** cells: same order  

## Token limits (`phase2_cell_env.sh`)

| Mode | `AGENT_MAX_SEQ_LEN` | `AGENT_MAX_NEW_TOKENS` |
|------|---------------------|-------------------------|
| thinking off | 16384 | 4096 |
| thinking on | 32768 | 8192 (+ `AGENT_MAX_NEW_TOKENS_THINKING`) |

Coder Bedrock uses the same caps; `QWEN3_CODER_BACKEND=bedrock`.

## Few-shot exemplars (train only — review)

| Slot | case_id | Track |
|------|---------|-------|
| FP | `BenchmarkTest00340` | fp/train |
| TP | `BenchmarkTest02272` | tp/train |
| BL | `BenchmarkTest02094` | borderline/train (empirical) |

## Commands

```bash
# Preflight (corpora + leakage check)
PHASE2_PREFLIGHT_ONLY=1 bash benchmark/phases/phase2/run_phase2_matrix.sh

# Smoke (2 cases/cell)
PHASE2_SMOKE_MAX=2 bash benchmark/phases/phase2/run_phase2_matrix.sh

# Full matrix (background)
nohup bash benchmark/phases/phase2/run_phase2_matrix.sh >> runs/phase2/logs/master.log 2>&1 &

# After core matrix completes — Qwen3.5 4B + 9B (same cells, skips finished)
nohup bash benchmark/phases/phase2/run_phase2_qwen35_extension.sh >> runs/phase2/logs/qwen35_extension.log 2>&1 &

uv run python benchmark/phases/phase2/status_phase2.py
```

Extension adds **24 cells** (2 models × 3 tracks × 2 few-shot × 2 thinking) × 200 cases = **4,800** more runs. Summaries refresh with all six profiles when the extension script finishes.

## Outputs

`runs/phase2/{fp,tp,bl}/thinking_{off,on}/fewshot_{0,3}/<profile>/llm/<case_id>/`
