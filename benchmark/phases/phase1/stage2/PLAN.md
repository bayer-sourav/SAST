# Phase 1 — Stage 2 plan (for approval)

**Status:** Approved — implementation in `run_phase1_stage2.sh` (thinking off only; BL n=200).

**Goal:** Repeat the Stage 1 triage experiment at **full corpus scale** on **Qwen3 4B / 8B / 14B** only, and add a third track **Borderline** (ambiguous FP/TP: weak or bypassable sanitization). Exclude GPT-OSS (weak on N=50) and Qwen3-Coder-30B (GPU issues; deferred).

---

## 1. What Stage 1 already did (unchanged archive)

| Item | Stage 1 |
|------|---------|
| Cases | **50 FP + 50 TP** (CWE-balanced, seed 42) |
| Models | 4B, 8B, 14B, GPT-OSS, Coder-30B |
| Thinking | off + on |
| Runs | `FP-runs/phase1_n50/`, `TP-runs/phase1_n50/` |
| Docs | `benchmark/PHASE1.md`, `benchmark/README.md` |

Stage 2 does **not** delete Stage 1 artifacts; it adds new paths under `runs/phase1/stage2/`.

---

## 2. Stage 2 experiment definition

### 2.1 Models (3)

| Profile | Included |
|---------|----------|
| `qwen3_4b_bnb` | Yes |
| `qwen3_8b_bnb` | Yes |
| `qwen3_14b_bnb` | Yes |
| `gpt_oss_20b` | **No** (poor FPRR on slice; full run not justified yet) |
| `qwen3_coder_30b_bnb` | **No** (deferred; GPU/load issues) |

### 2.2 Corpora (3 tracks)

| Track | Source directory | Cases (approx.) | Gold / evaluation |
|-------|------------------|-----------------|-------------------|
| **FP** | `benchmark/corpora/fp_codeql/` ← today `rq1_codeql_only/` | **904** | Gold = **FP** → FPRR, F1-FP |
| **TP** | `benchmark/corpora/tp_codeql/` ← today `tp_codeql_only/` | **1,373** | Gold = **TP** → VDR, F1-TP |
| **BL** (Borderline) | `benchmark/corpora/borderline_codeql/` (**new**) | **TBD: 150–400** (see §4) | **Dual / soft gold** (see §4.3) |

FP and TP sets are **disjoint** (0 overlap on `case_id`). Total unique OWASP cases with CodeQL: **2,277**.

### 2.3 Thinking mode (needs your choice)

| Option | Cells | Rough GPU time (1× L40S, order-of-magnitude) |
|--------|-------|-----------------------------------------------|
| **A — thinking off only** (recommended for first pass) | 3 models × (904+1373+N_bl) × 1 | ~4–7 days |
| **B — thinking off + on** (same as Stage 1) | × 2 | ~8–14 days |

Stage 1 showed **thinking on hurts** 8B on the slice (SRS/F1 100% → 76%). For a full run, **Option A** saves half the cost; we can add thinking-on on a **subset** later if needed.

**Default proposal:** **Option A (thinking off only)** unless you want both.

### 2.4 Prompting & metrics

- Same zero-shot JSON triage as Stage 1 (`run_llm_local.py`).
- **FP / TP tracks:** same metrics as Stage 1 — FPRR, VDR, SRS, F1, F1-FP, F1-TP, coverage.
- **Borderline track:** new prompt policy `gold=BL` (neutral; no “prefer FP/TP”) + new summary metrics (§4.3).

---

## 3. Proposed repo layout (phases / stages)

Keep existing paths working; introduce a clear hierarchy:

```text
benchmark/
  corpora/                          # inputs (symlinks or moves from flat dirs)
    fp_codeql/                      # was rq1_codeql_only
    tp_codeql/                      # was tp_codeql_only
    borderline_codeql/              # new
    README.md
  phases/
    phase1/
      stage1/                       # N=50 (reference only)
        MANIFEST.json               # copy/update from phase1_manifest.json
        slices/                     # optional symlink → ../../phase1_slices/
      stage2/
        PLAN.md                     # this file
        MANIFEST.json               # models, N, thinking, excluded
        run_phase1_stage2.sh        # orchestrator (to implement after approval)
        status_stage2.py            # progress + metrics (to implement)
  scripts/                          # optional: thin wrappers (or keep names at benchmark/*.py)

runs/                               # all experiment outputs (gitignored)
  phase1/
    stage1/                         # optional future: migrate FP-runs/phase1_n50 here
    stage2/
      fp/thinking_off/<profile>/llm/<case_id>/
      tp/thinking_off/<profile>/llm/<case_id>/
      bl/thinking_off/<profile>/llm/<case_id>/
      summaries/                    # comparison_*.json, matrix_*.json

docs/
  EXPERIMENT_PLAN.md                # link to phase1/stage2/PLAN.md
```

**Migration strategy (low risk):**

1. Add `benchmark/corpora/*` as **symlinks** to current `rq1_codeql_only` / `tp_codeql_only` (no mass file move in v1).
2. New runs only under `runs/phase1/stage2/`.
3. Leave `FP-runs/phase1_n50/` and `TP-runs/phase1_n50/` as Stage 1 archive.

---

## 4. Borderline (BL) track — design

### 4.1 Intent

Cases where **reasonable reviewers disagree** or **sanitization may be incomplete / bypassable**, so both **TP** (keep alert) and **FP** (dismiss) are defensible. This is **not** the same as FP or TP gold corpora.

### 4.2 Building the corpus (proposed pipeline)

**Script (to implement):** `benchmark/build_borderline_cases.py`

**Inputs:**

- `benchmark/corpora/fp_codeql/` + `tp_codeql/`
- `../BenchmarkJava/expectedresults-1.2.csv` (benchmark truth: `real vulnerability`, category, CWE)
- BenchmarkJava sources (for sanitization heuristics)

**Candidate rules (tiered — pick one tier for v1):**

| Tier | Rule | Approx. count (measured on this host) |
|------|------|--------------------------------------|
| **Strict** | Injection-related categories (`xss`, `sqli`, `cmdi`, `ldapi`, `pathtraver`) **and** source matches weak-sanitization regex **and** (`real vulnerability=true` **or** case appears in FP corpus with sanitization present) | ~200–400 (to be refined) |
| **Broad** | Any case with sanitization-like keywords in source + CodeQL alert | ~1,400+ (too large for “borderline” label quality) |

**Recommendation for v1:** **Strict tier**, target **N_bl = 200** (CWE-balanced, seed 42) for parity with Stage 1 slice discipline — with a flag `--full` to export the full strict set later.

**Synthetic extension (optional Phase 2b):**

- Clone 20–30 real case JSON shells; vary `task.md` / metadata only if we add **synthetic Java snippets** in BenchmarkJava (higher effort, needs your sign-off).
- **Not required** for first Stage 2 run if strict-mined set is approved.

Each BL case JSON adds:

```json
{
  "case_id": "BenchmarkTest00xxx",
  "gold_track": "BL",
  "benchmark_real_vuln": true,
  "borderline_tier": "strict",
  "acceptable_labels": ["TP", "FP"],
  "notes": "partial sanitization on data-flow path"
}
```

### 4.3 Borderline metrics (new)

Standard FPRR/VDR assume a single gold label. For BL we report:

| Metric | Meaning |
|--------|---------|
| **Coverage** | Valid JSON / N |
| **TP rate / FP rate** | Distribution of model labels (shows bias) |
| **Benchmark-agreement** | % matching OWASP `real vulnerability` mapped to TP/FP |
| **Ambiguity index** | e.g. \|P(TP) − 0.5\| averaged (0 = always hedging to one side) |
| **Cross-track flip** | Same model on same `case_id` if we ever overlap (not in v1) |

Optional: treat **either** label as correct → **lenient accuracy** (upper bound; report separately from strict metrics).

### 4.4 Prompt (`gold=BL`)

Neutral policy (to add in `run_llm_local.py`):

- Do **not** prefer FP or TP.
- Encourage citing sanitization strength and bypass scenarios.
- Still output one of `TP | FP | UNKNOWN`.

---

## 5. Execution plan (after approval)

### 5.1 Implement (estimated 1–2 days engineering)

| Task | Deliverable |
|------|-------------|
| Repo layout | `corpora/`, `phases/phase1/stage2/`, `runs/phase1/stage2/` |
| `build_borderline_cases.py` | `corpora/borderline_codeql/` + manifest |
| `run_phase1_stage2.sh` | Generalize matrix: full FP, full TP, BL; 3 profiles; resume |
| `status_stage2.py` | Progress + FPRR/VDR/SRS/F1 + BL metrics |
| `summarize` / `merge` | Third track or separate `comparison_bl_*.json` |
| Docs | Update `PHASE1.md`, README, `MANIFEST.json` |

### 5.2 Pre-flight (smoke)

```bash
# Per model: 3 FP + 3 TP + 3 BL cases
PHASE1_STAGE2_SMOKE=1 ./benchmark/phases/phase1/stage2/run_phase1_stage2.sh
```

### 5.3 Full run (background)

```bash
nohup ./benchmark/phases/phase1/stage2/run_phase1_stage2.sh \
  >> runs/phase1/stage2/logs/master.log 2>&1 &
```

**Cell order (recommended):** 4B → 8B → 14B; within each model: FP full → TP full → BL; one thinking mode.

**Resume:** skip cases with valid `agent-llm-triage-result.json` (same as Stage 1).

### 5.4 Post-run

```bash
uv run python benchmark/phases/phase1/stage2/status_stage2.py
bash benchmark/phases/phase1/stage2/refresh_summaries.sh
```

---

## 6. Scale & cost summary

| Quantity | thinking off only | thinking off + on |
|----------|-------------------|-------------------|
| FP cases | 904 | 904 |
| TP cases | 1,373 | 1,373 |
| BL cases (proposed) | 200 | 200 |
| **Case runs per model** | **2,477** | **4,954** |
| **Case runs total (3 models)** | **7,431** | **14,862** |

Using Stage 1 timing (~25s/case 4B, ~40s 8B, ~17s 14B on slice — full tasks may be slower):

- **Order of magnitude:** ~5–10 GPU-days for thinking off only on one L40S.

---

## 7. Decisions needed from you

Please confirm or adjust:

1. **Thinking:** Option A (off only) or B (off + on)?
2. **Borderline size:** N_bl = **200** (balanced slice) vs **full strict set** (~300–400) vs start with **100** smoke then full?
3. **Borderline definition:** OK with **strict heuristic** from OWASP truth + sanitization patterns, **no synthetic Java** in v1?
4. **Repo layout:** Approve `benchmark/corpora/` + `runs/phase1/stage2/` (symlinks for existing corpora)?
5. **Run order:** Approve 4B → 8B → 14B, FP → TP → BL?
6. **Metrics for BL:** Agreement + label distribution + lenient accuracy — anything else?

Reply with approvals/changes (e.g. `approve A, N_bl=200, strict BL, layout OK`). After that we implement scripts and start the smoke run, then the full matrix.
