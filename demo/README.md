# Live SAST Triage Demo

Minimal Streamlit app for technical and business audiences: **Git push → CodeQL → AI triage → metrics**.

## Quick start

```bash
cd /path/to/SAST
chmod +x demo/run_demo.sh
./demo/run_demo.sh
```

Open **http://localhost:8501** (or `DEMO_PORT=8502 ./demo/run_demo.sh`).

**If you see `ModuleNotFoundError: timing`:** stop the app (Ctrl+C) and restart — `run_demo.sh` now adds `benchmark/` to `PYTHONPATH` automatically.

To refresh cached results for the 4-case quick pack:

```bash
PYTHONPATH="$PWD:$PWD/benchmark" .venv/bin/python3 demo/build_cache.py
```

## Prerequisites

1. **BenchmarkJava** cloned as sibling of SAST (`../BenchmarkJava`) — Java source for findings.
2. **Bedrock** (live mode): set in `.env`:
   - `OPENAI_BASE_URL` or `BEDROCK_MANTLE_BASE_URL`
   - `OPENAI_API_KEY` or `AWS_BEARER_TOKEN_BEDROCK`
3. **Cached mode** (no API): uses completed runs under `runs/phase2/stage3/smoke/` when available.

## Demo flow (live presentation)

1. **Pipeline** — four steps: git commit, CodeQL SARIF, Qwen3-Coder-30B triage, metrics.
2. **CodeQL table** — findings from the selected pack (file, rule, alert count, ground truth).
3. **Run AI triage** — cached (instant) or live Bedrock.
4. **Dashboard** — VDR, FPRR, SRS, TPR, FPR, confusion matrix, per-finding reasoning.

## Finding packs

| Pack | Size | Use when |
|------|------|----------|
| `quick` | 6 cases (2 TP + 2 FP + 2 BL) | Live demo; includes borderline disagreement |
| `hard_slice` | 20 cases | Deeper metrics; prefer cached mode |

**Best smoke prompt** (default): `v7-balanced` + `v2_3shot_tp_2fp` fs3 · think=on — 20/20 hard slice on qwen3_5_9b.

**Borderline cases in quick pack:**
- `BenchmarkTest02201` — Coder labels TP, 5.9B/14B label FP
- `BenchmarkTest02197` — 14B labels FP, 5.9B/Coder label TP

## Metrics (business ↔ technical)

| Metric | Business label | Meaning |
|--------|------------------|---------|
| **VDR** | Threat detection | % of real vulns correctly labeled TP |
| **FPRR** | Noise reduction | % of false alarms correctly labeled FP |
| **SRS** | Combined score | Average of VDR and FPRR |
| **TPR** | Recall | Same as VDR on TP-gold cases |
| **FPR** | False alarm rate | Safe cases wrongly flagged as vuln |

CodeQL baseline row shows **no AI filter** (everything stays flagged).

## Configuration

Sidebar: prompt version (`v7-balanced`, `v8-dual-gate`, `v9-fprr-first`), thinking on/off, BenchmarkJava path.

| **Qwen3-5.9B** | Primary (local GPU) | Best FPRR on structural FPs |
| **Qwen3-Coder-30B** | Bedrock (live) | Fast live demo; often keeps structural FPs |
| **Compare all models** | Cached | Side-by-side VDR/FPRR chart for presentations |

Default model is now **5.9B**. Use **Compare all models (cached)** to show why Coder-30B live run missed 2 FPs.
