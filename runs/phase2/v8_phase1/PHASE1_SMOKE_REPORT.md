# v8 Phase 1 — hard slice smoke

Slice: 10 TP + 10 FP · gates: VDR≥9/10 · FPRR≥7/10 · total≥17/20

600-case baseline (v8-ship-bl): VDR 74.6% · FPRR 67.5% · SRS 86.1% · TP→FP 43

| Cell | VDR | FPRR | Total | Pass | Notes |
|------|----:|-----:|------:|:----:|-------|
| **8C-think-off** | 9/10 | 7/10 | **16/20** | ✗ | Test whether CoT hurts VDR when BL rules are in prompt. |
| **8B-vdr-fs3** | 8/10 | 8/10 | **16/20** | ✗ | VDR-first exemplars (Stage 2 layout) under v8 BL calibration text. |
| **8B-bl-fs3** | 8/10 | 6/10 | **14/20** | ✗ | 3-shot with one BL exemplar; fewer shots than 8A. |
| **8A-baseline** | 8/10 | 5/10 | **13/20** | ✗ | Current prod ship config (600-case BL rate 41.5%, VDR 74.6%). |

**No cell passed smoke gates.** Review tp_errors in JSON.

### 8C-think-off TP misses
- BenchmarkTest00071:FP

### 8B-vdr-fs3 TP misses
- BenchmarkTest00029:FP
- BenchmarkTest00082:FP

### 8B-bl-fs3 TP misses
- BenchmarkTest00029:FP
- BenchmarkTest00071:FP

### 8A-baseline TP misses
- BenchmarkTest00029:FP
- BenchmarkTest00071:FP

JSON: `runs/phase2/v8_phase1/PHASE1_SMOKE_SUMMARY.json`
