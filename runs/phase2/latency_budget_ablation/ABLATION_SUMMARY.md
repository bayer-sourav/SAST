# Latency budget ablation (hard slice, thinking ON)

vLLM micro-batch shares wall time across cases — `tok_per_sec_p50` from run_meta can look high; prefer `inference_sec_p50` for per-case latency.

| Cell | Arm | Score | Recovered | inf p50 (s) | inf p90 (s) | out_tok p50 | tok/s p50* |
|---|---|---:|---:|---:|---:|---:|---:|
| 5.9b_fs3_legacy | baseline | 17/20 | 3 | 31.5 | 55.0 | 1709 | 67.3 |
| 5.9b_fs3_legacy | t1536_short | 15/20 | 20 | 40.8 | 65.1 | 2560 | 62.7 |
| 5.9b_fs3_legacy | t2048 | 15/20 | 4 | 19.4 | 44.7 | 1780 | 68.9 |
| 5.9b_fs3_legacy | t2048_short | 9/20 | 18 | 31.1 | 67.3 | 2048 | 67.8 |
| langagnostic_fs3 | baseline | 15/20 | 5 | 32.2 | 56.7 | 2754 | 73.0 |
| langagnostic_fs3 | t1536_short | 12/19 | 19 | 40.7 | 63.8 | 2560 | 62.8 |
| langagnostic_fs3 | t2048 | 15/20 | 9 | 21.1 | 47.1 | 2046 | 66.5 |
| langagnostic_fs3 | t2048_short | 15/20 | 19 | 21.3 | 81.4 | 2048 | 96.2 |

\*Attributed tok/s from run_meta (batch-diluted).
