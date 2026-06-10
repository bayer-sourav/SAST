# Phase 2 comparison table (core Qwen3 profiles)

Source: `comparison_*_test_*.json` in `runs/phase2/summaries/`.
One row per model × thinking × few-shot configuration (16 rows per track table).

## Legend

- **Thinking**: `off` = no chain-of-thought; `on` = CoT before JSON
- **Few-shot**: `0` = zero-shot; `3` = 3 exemplars in task.md
- **Coverage**: % of 200 test cases with valid triage label
- **FP FPRR**: false-positive removal rate (higher = better at calling FP)
- **TP VDR**: vulnerability detection rate (higher = better at calling TP)
- **BL Lenient acc**: correct if label matches gold OR acceptable neighbor
- **BL Bench agree**: agreement with benchmark borderline framing

## Table A — FP track (gold label = FP)

| Model | Thinking | Few-shot | Evaluated | Missing | Coverage | Accuracy | FPRR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| qwen3_4b_bnb | off | 0 | 200 | 0 | 100.0% | 94.0% | 94.0% |
| qwen3_4b_bnb | off | 3 | 200 | 0 | 100.0% | 100.0% | 100.0% |
| qwen3_4b_bnb | on | 0 | 200 | 0 | 100.0% | 95.5% | 95.5% |
| qwen3_4b_bnb | on | 3 | 200 | 0 | 100.0% | 100.0% | 100.0% |
| qwen3_8b_bnb | off | 0 | 199 | 1 | 99.5% | 97.0% | 97.0% |
| qwen3_8b_bnb | off | 3 | 200 | 0 | 100.0% | 95.0% | 95.0% |
| qwen3_8b_bnb | on | 0 | 200 | 0 | 100.0% | 82.5% | 82.5% |
| qwen3_8b_bnb | on | 3 | 200 | 0 | 100.0% | 90.0% | 90.0% |
| qwen3_14b_bnb | off | 0 | 200 | 0 | 100.0% | 100.0% | 100.0% |
| qwen3_14b_bnb | off | 3 | 200 | 0 | 100.0% | 100.0% | 100.0% |
| qwen3_14b_bnb | on | 0 | 200 | 0 | 100.0% | 98.5% | 98.5% |
| qwen3_14b_bnb | on | 3 | 200 | 0 | 100.0% | 97.5% | 97.5% |
| qwen3_coder_30b_bnb | off | 0 | 200 | 0 | 100.0% | 92.5% | 92.5% |
| qwen3_coder_30b_bnb | off | 3 | 200 | 0 | 100.0% | 90.5% | 90.5% |
| qwen3_coder_30b_bnb | on | 0 | 200 | 0 | 100.0% | 91.5% | 91.5% |
| qwen3_coder_30b_bnb | on | 3 | 200 | 0 | 100.0% | 90.0% | 90.0% |

## Table B — TP track (gold = TP)

| Model | Thinking | Few-shot | Evaluated | Missing | Coverage | Accuracy | VDR |
| --- | --- | --- | --- | --- | --- | --- | --- |
| qwen3_4b_bnb | off | 0 | 199 | 1 | 99.5% | 31.7% | 31.7% |
| qwen3_4b_bnb | off | 3 | 200 | 0 | 100.0% | 9.5% | 9.5% |
| qwen3_4b_bnb | on | 0 | 200 | 0 | 100.0% | 21.5% | 21.5% |
| qwen3_4b_bnb | on | 3 | 200 | 0 | 100.0% | 9.5% | 9.5% |
| qwen3_8b_bnb | off | 0 | 197 | 3 | 98.5% | 14.7% | 14.7% |
| qwen3_8b_bnb | off | 3 | 199 | 1 | 99.5% | 8.0% | 8.0% |
| qwen3_8b_bnb | on | 0 | 200 | 0 | 100.0% | 54.5% | 54.5% |
| qwen3_8b_bnb | on | 3 | 200 | 0 | 100.0% | 51.0% | 51.0% |
| qwen3_14b_bnb | off | 0 | 200 | 0 | 100.0% | 8.0% | 8.0% |
| qwen3_14b_bnb | off | 3 | 199 | 1 | 99.5% | 16.1% | 16.1% |
| qwen3_14b_bnb | on | 0 | 200 | 0 | 100.0% | 11.5% | 11.5% |
| qwen3_14b_bnb | on | 3 | 200 | 0 | 100.0% | 26.0% | 26.0% |
| qwen3_coder_30b_bnb | off | 0 | 200 | 0 | 100.0% | 37.0% | 37.0% |
| qwen3_coder_30b_bnb | off | 3 | 200 | 0 | 100.0% | 38.5% | 38.5% |
| qwen3_coder_30b_bnb | on | 0 | 200 | 0 | 100.0% | 37.0% | 37.0% |
| qwen3_coder_30b_bnb | on | 3 | 200 | 0 | 100.0% | 43.0% | 43.0% |

## Table C — BL track (gold = BL)

| Model | Thinking | Few-shot | Evaluated | Missing | Coverage | Lenient acc | Bench agree | BL rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| qwen3_4b_bnb | off | 0 | 199 | 1 | 99.5% | 100.0% | 50.8% | 0.0% |
| qwen3_4b_bnb | off | 3 | 199 | 1 | 99.5% | 85.9% | 77.4% | 14.1% |
| qwen3_4b_bnb | on | 0 | 200 | 0 | 100.0% | 100.0% | 62.0% | 0.0% |
| qwen3_4b_bnb | on | 3 | 200 | 0 | 100.0% | 85.0% | 76.0% | 15.0% |
| qwen3_8b_bnb | off | 0 | 197 | 3 | 98.5% | 93.9% | 68.0% | 6.1% |
| qwen3_8b_bnb | off | 3 | 199 | 1 | 99.5% | 91.0% | 78.9% | 9.0% |
| qwen3_8b_bnb | on | 0 | 200 | 0 | 100.0% | 98.5% | 14.5% | 1.5% |
| qwen3_8b_bnb | on | 3 | 200 | 0 | 100.0% | 95.5% | 21.5% | 4.5% |
| qwen3_14b_bnb | off | 0 | 199 | 1 | 99.5% | 100.0% | 86.9% | 0.0% |
| qwen3_14b_bnb | off | 3 | 199 | 1 | 99.5% | 97.0% | 78.9% | 3.0% |
| qwen3_14b_bnb | on | 0 | 200 | 0 | 100.0% | 100.0% | 84.5% | 0.0% |
| qwen3_14b_bnb | on | 3 | 200 | 0 | 100.0% | 96.5% | 53.5% | 3.5% |
| qwen3_coder_30b_bnb | off | 0 | 200 | 0 | 100.0% | 92.5% | 40.5% | 7.5% |
| qwen3_coder_30b_bnb | off | 3 | 200 | 0 | 100.0% | 96.5% | 53.0% | 3.5% |
| qwen3_coder_30b_bnb | on | 0 | 200 | 0 | 100.0% | 88.5% | 39.5% | 11.5% |
| qwen3_coder_30b_bnb | on | 3 | 200 | 0 | 100.0% | 96.5% | 45.0% | 3.5% |

## Table D — Qwen3.5 progress (live disk counts)

Valid labels on disk (`agent-llm-triage-result.json`).

| Track | Model | Thinking | Few-shot | Completed | Target |
| --- | --- | --- | --- | --- | --- |
| FP | qwen3_5_4b_bnb | off | 0 | 200 | 200 |
| FP | qwen3_5_4b_bnb | off | 3 | 200 | 200 |
| FP | qwen3_5_4b_bnb | on | 0 | 200 | 200 |
| FP | qwen3_5_4b_bnb | on | 3 | 34 | 200 |
| FP | qwen3_5_9b_bnb | off | 0 | 200 | 200 |
| FP | qwen3_5_9b_bnb | off | 3 | 200 | 200 |
| FP | qwen3_5_9b_bnb | on | 0 | 0 | 200 |
| FP | qwen3_5_9b_bnb | on | 3 | 0 | 200 |
| TP | qwen3_5_4b_bnb | off | 0 | 200 | 200 |
| TP | qwen3_5_4b_bnb | off | 3 | 200 | 200 |
| TP | qwen3_5_4b_bnb | on | 0 | 0 | 200 |
| TP | qwen3_5_4b_bnb | on | 3 | 0 | 200 |
| TP | qwen3_5_9b_bnb | off | 0 | 200 | 200 |
| TP | qwen3_5_9b_bnb | off | 3 | 200 | 200 |
| TP | qwen3_5_9b_bnb | on | 0 | 0 | 200 |
| TP | qwen3_5_9b_bnb | on | 3 | 0 | 200 |
| BL | qwen3_5_4b_bnb | off | 0 | 200 | 200 |
| BL | qwen3_5_4b_bnb | off | 3 | 200 | 200 |
| BL | qwen3_5_4b_bnb | on | 0 | 0 | 200 |
| BL | qwen3_5_4b_bnb | on | 3 | 0 | 200 |
| BL | qwen3_5_9b_bnb | off | 0 | 200 | 200 |
| BL | qwen3_5_9b_bnb | off | 3 | 200 | 200 |
| BL | qwen3_5_9b_bnb | on | 0 | 0 | 200 |
| BL | qwen3_5_9b_bnb | on | 3 | 0 | 200 |

## Skipped core gaps (15)

Unfixable missing valid results; case IDs only, grouped by profile.

### `qwen3_14b_bnb`

- BenchmarkTest02396
- BenchmarkTest00383
- BenchmarkTest00383

### `qwen3_4b_bnb`

- BenchmarkTest02396
- BenchmarkTest00383
- BenchmarkTest00383

### `qwen3_8b_bnb`

- BenchmarkTest01089
- BenchmarkTest01964
- BenchmarkTest02281
- BenchmarkTest02396
- BenchmarkTest02396
- BenchmarkTest00383
- BenchmarkTest01390
- BenchmarkTest02275
- BenchmarkTest00383
