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

1. **Pipeline bar** — four steps: git commit → CodeQL SARIF → AI triage → metrics.
2. **CodeQL findings** — each finding card shows rule, alert message, sink location, dataflow trail, and a **highlighted Java snippet** (sink lines in amber).
3. **Run AI triage** — cached (instant) or live Bedrock/GPU; cards update with **TP / FP / BL** verdict, status, and reasoning.
4. **Aggregate metrics** — VDR, FPRR, SRS, borderline handling, summary table, and CodeQL-vs-AI chart.

Toggle **Show eval ground truth** in the sidebar to reveal benchmark gold labels after triage.

## Finding packs

| Pack | Size | Use when |
|------|------|----------|
| `quick` | 8 cases (3× SSRF + 3× P-SSRF + 2× Type Confusion; TP/FP/BL mix) | Live demo with vuln-category variety |
| `hard_slice` | 20 cases | Deeper metrics; prefer cached mode |

**Quick pack categories** (research taxonomy over CodeQL CWE buckets):
- **SSRF** — full taint-to-sink (e.g. XSS reflection)
- **P-SSRF** — partial structured-target control (path / SQL injection)
- **Type Confusion** — wrong primitive or format at sink (randomness, format strings)

**Borderline cases in quick pack:**
- `BenchmarkTest02197` — P-SSRF path alert; 14B=FP vs 5.9B/Coder=TP
- `BenchmarkTest02201` — SSRF XSS alert; Coder=TP vs 5.9B=FP

## Metrics (business ↔ technical)

| Metric | Business label | Meaning |
|--------|------------------|---------|
| **VDR** | Threat detection | % of real vulns correctly labeled TP |
| **FPRR** | Noise reduction | % of false alarms correctly labeled FP |
| **SRS** | Security score | Penalty-weighted score over TP/FP/BL transitions |
| **TPR** | Recall | Same as VDR on TP-gold cases |
| **FPR** | False alarm rate | Safe cases wrongly flagged as vuln |

CodeQL baseline row shows **no AI filter** (everything stays flagged).

## Configuration

Sidebar: prompt version (`v7-balanced`, `v8-dual-gate`, `v9-fprr-first`), thinking on/off, BenchmarkJava path.

| **Qwen3-5.9B** | Primary (local GPU) | Best FPRR on structural FPs |
| **Qwen3-Coder-30B** | Bedrock (live) | Fast live demo; often keeps structural FPs |
| **Compare all models** | Cached | Side-by-side VDR/FPRR chart for presentations |

Default model is now **5.9B**. Use **Compare all models (cached)** to show why Coder-30B live run missed 2 FPs.
