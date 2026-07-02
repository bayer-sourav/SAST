# Phase 3D TP→FP error analysis

**Source eval:** `/home/ec2-user/Projects/SAST/runs/phase3/stage3c/eval`  
**Errors:** 27 TP-gold → predicted FP  
**Stage 2 recall on same cases:** 17/27 (63.0%)

## Rule family breakdown (short_rule)

| Rule | Count |
| --- | ---: |
| `xss` | 26 |
| `insecure-randomness` | 1 |

## Hard-negative train oversample

Mined **81** train case IDs (max 3/error, cap 120).

| Train case | rule | teacher | matched test error |
| --- | --- | --- | --- |
| `BenchmarkTest00020` | `xss` | TP | `BenchmarkTest00029` |
| `BenchmarkTest00031` | `xss` | TP | `BenchmarkTest00029` |
| `BenchmarkTest00041` | `xss` | TP | `BenchmarkTest00029` |
| `BenchmarkTest00023` | `insecure-randomness` | TP | `BenchmarkTest00162` |
| `BenchmarkTest00068` | `insecure-randomness` | TP | `BenchmarkTest00162` |
| `BenchmarkTest00160` | `insecure-randomness` | TP | `BenchmarkTest00162` |
| `BenchmarkTest00047` | `xss` | TP | `BenchmarkTest00273` |
| `BenchmarkTest00148` | `xss` | TP | `BenchmarkTest00273` |
| `BenchmarkTest00380` | `xss` | TP | `BenchmarkTest00273` |
| `BenchmarkTest00459` | `xss` | TP | `BenchmarkTest00348` |
| `BenchmarkTest00521` | `xss` | TP | `BenchmarkTest00348` |
| `BenchmarkTest00551` | `xss` | TP | `BenchmarkTest00348` |
| `BenchmarkTest00619` | `xss` | TP | `BenchmarkTest00371` |
| `BenchmarkTest00627` | `xss` | TP | `BenchmarkTest00371` |
| `BenchmarkTest00688` | `xss` | TP | `BenchmarkTest00371` |
| `BenchmarkTest00720` | `xss` | TP | `BenchmarkTest00372` |
| `BenchmarkTest00737` | `xss` | TP | `BenchmarkTest00372` |
| `BenchmarkTest00756` | `xss` | TP | `BenchmarkTest00372` |
| `BenchmarkTest00788` | `xss` | TP | `BenchmarkTest00536` |
| `BenchmarkTest00810` | `xss` | TP | `BenchmarkTest00536` |
| `BenchmarkTest00846` | `xss` | TP | `BenchmarkTest00536` |
| `BenchmarkTest00947` | `xss` | TP | `BenchmarkTest00588` |
| `BenchmarkTest00977` | `xss` | TP | `BenchmarkTest00588` |
| `BenchmarkTest01063` | `xss` | TP | `BenchmarkTest00588` |
| `BenchmarkTest01105` | `xss` | TP | `BenchmarkTest00634` |
| `BenchmarkTest01230` | `xss` | TP | `BenchmarkTest00634` |
| `BenchmarkTest01231` | `xss` | TP | `BenchmarkTest00634` |
| `BenchmarkTest01260` | `xss` | TP | `BenchmarkTest00671` |
| `BenchmarkTest01333` | `xss` | TP | `BenchmarkTest00671` |
| `BenchmarkTest01346` | `xss` | TP | `BenchmarkTest00671` |
| `BenchmarkTest01376` | `xss` | TP | `BenchmarkTest00704` |
| `BenchmarkTest01471` | `xss` | TP | `BenchmarkTest00704` |
| `BenchmarkTest01505` | `xss` | TP | `BenchmarkTest00704` |
| `BenchmarkTest01511` | `xss` | TP | `BenchmarkTest00789` |
| `BenchmarkTest01561` | `xss` | TP | `BenchmarkTest00789` |
| `BenchmarkTest01571` | `xss` | TP | `BenchmarkTest00789` |
| `BenchmarkTest01587` | `xss` | TP | `BenchmarkTest00790` |
| `BenchmarkTest01592` | `xss` | TP | `BenchmarkTest00790` |
| `BenchmarkTest01682` | `xss` | TP | `BenchmarkTest00790` |
| `BenchmarkTest01835` | `xss` | TP | `BenchmarkTest00794` |
| … | | | (41 more) |

## Sample errors (first 15)

| case_id | rule | Stage 2 pred |
| --- | --- | --- |
| `BenchmarkTest00029` | `xss` | FP |
| `BenchmarkTest00162` | `insecure-randomness` | TP |
| `BenchmarkTest00273` | `xss` | TP |
| `BenchmarkTest00348` | `xss` | TP |
| `BenchmarkTest00371` | `xss` | TP |
| `BenchmarkTest00372` | `xss` | FP |
| `BenchmarkTest00536` | `xss` | FP |
| `BenchmarkTest00588` | `xss` | TP |
| `BenchmarkTest00634` | `xss` | TP |
| `BenchmarkTest00671` | `xss` | TP |
| `BenchmarkTest00704` | `xss` | TP |
| `BenchmarkTest00789` | `xss` | TP |
| `BenchmarkTest00790` | `xss` | TP |
| `BenchmarkTest00794` | `xss` | FP |
| `BenchmarkTest01168` | `xss` | FP |
