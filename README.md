# Cutting SAST Noise with Small Language Models

**Supplementary material** for the workshop paper:

> *Cutting SAST Noise with Small Language Models: Prompting, Thinking, Distillation, and Deployment*

<!-- Public artifact: [github.com/bayer-sourav/SAST](https://github.com/bayer-sourav/SAST) -->

This repo holds the **research** stack used in the paper: OWASP BenchmarkJava + CodeQL case construction, versioned prompts / few-shot packs, local SLM runners, Phase 1–3 ablations, and frozen result tables. Production advisory service code lives in a separate integration repo (not required to reproduce the benchmark numbers).

---

## Paper claim (frozen)

| Item | Value |
|------|--------|
| Ship cell | Qwen3.5-9B · prompt `v7-balanced` · thinking **ON** · few-shot `v2_3shot_tp_2fp` |
| Holdout | 600 cases (200 FP + 200 TP + 200 BL) |
| Metrics | **FPRR 73.5%** · **VDR 92.5%** · **SRS 92.5%** (asymmetric) |
| Distillation | Gold-label SFT collapses; best LoRA ~89.9% SRS (does not beat Stage 2) |
| Borderline | `v8-ship-bl` raises BL rate but costs VDR — not the shipped prompt |

Numbers come from existing `runs/` JSON / HTML tables. Do not re-tune on the holdout.

---

## Reproduce the main result (Stage 2)

1. Build / use the Phase 2 corpora under [`benchmark/`](benchmark/) (see [`benchmark/README.md`](benchmark/README.md)).
2. Stage 2 ship config: [`benchmark/phases/phase2/stage2/MANIFEST.json`](benchmark/phases/phase2/stage2/MANIFEST.json).
3. Prompt lineage + few-shot packs: [`benchmark/prompt_versions.py`](benchmark/prompt_versions.py), [`benchmark/few_shot_configs/`](benchmark/few_shot_configs/).
4. Leaderboard / tables: [`runs/phase2/phase2_benchmark_tables/BENCHMARK_RESULTS.html`](runs/phase2/phase2_benchmark_tables/BENCHMARK_RESULTS.html).

<!-- Paper draft (LaTeX): [`docs/paper/draft.tex`](docs/paper/draft.tex). -->

---

## Repo map

| Path | What |
|------|------|
| `benchmark/` | Case builders, prompts, few-shot, CSS/SRS metrics, phase plans |
| `models/qwen/` | Local Qwen runners (Unsloth / vLLM paths used in experiments) |
| `runs/phase2/` | Stage 2 / 3 prompting results and benchmark HTML |
| `runs/phase3/` | LoRA / BL distillation tracks (incl. failed 3C gates) |
| `runs/phase3/lora/` | Adapter checkpoints referenced by Phase 3 manifests (if present) |
<!-- | `docs/paper/` | Workshop draft + writing notes | -->

---

## What this artifact is / is not

**Is:** reproducible local-SLM triage experiments on OWASP+CodeQL; negative results (SFT collapse, BL cost, LoRA vs prompt).

**Is not:** a drop-in production scanner; multi-language enterprise accuracy; a same-split bake-off against frontier agent systems ([Xiong & Zhang, ISSTA 2026](https://arxiv.org/abs/2601.22952) is complementary prior art).

---

## Citation

```bibtex
@inproceedings{verma2027sastslm,
  title={Cutting SAST Noise with Small Language Models: Prompting, Thinking, Distillation, and Deployment},
  author={Verma, Sourav and Mohammadi, Sadegh},
  booktitle={ICSE Workshops},
  year={2027},
  note={Supplementary: https://github.com/bayer-sourav/SAST}
}
```

<!-- Update `booktitle` once the concrete workshop acronym (e.g. LLM4Code) is fixed. -->

---

## License / disclosure

Internal Bayer naming and production architecture details may be redacted or summarized in the paper. Do not commit secrets, API keys, or customer SARIF. If you fork for anonymous review, strip author/org identifiers from docs and history as required by the venue.
