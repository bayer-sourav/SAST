#!/usr/bin/env python3
"""Hard-slice smoke: 4 Qwen profiles × thinking on/off × fs3 (v2 2TP+1FP).

Few-shot config: benchmark/few_shot_configs/v2_3shot_2tp_fp.json
  Order TP→TP→FP: BenchmarkTest02272, BenchmarkTest00008, BenchmarkTest00200

Output: runs/smoke/v7_3shot_2tp_fp/thinking_{off,on}/fewshot_3/<profile>/llm/<case_id>/
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

SAST = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(SAST))
sys.path.insert(0, str(SAST / "benchmark"))
os.chdir(SAST)

SLICE = Path("/tmp/smoke_slice_cases.json")
OUT = SAST / "runs/smoke/v7_3shot_2tp_fp"
FEWSHOT_CONFIG = "v2_3shot_2tp_fp"
FEWSHOT = 3

PROFILES = (
    "qwen3_8b_bnb",
    "qwen3_14b_bnb",
    "qwen3_5_9b_bnb",
    "qwen3_coder_30b_bnb",
)


def _jobs() -> list[tuple[str, str, Path, str]]:
    slice_data = json.loads(SLICE.read_text())
    jobs: list[tuple[str, str, Path, str]] = []
    for cid in slice_data["tp"]:
        jobs.append(
            ("tp", cid, SAST / f"benchmark/corpora/phase2_tp_test/OWASP_{cid}.json", "TP")
        )
    for cid in slice_data["fp"]:
        jobs.append(
            ("fp", cid, SAST / f"benchmark/corpora/phase2_fp_test/OWASP_{cid}.json", "FP")
        )
    return jobs


def _run_dir(thinking: bool, profile: str, case_id: str) -> Path:
    mode = "thinking_on" if thinking else "thinking_off"
    return OUT / mode / f"fewshot_{FEWSHOT}" / profile / "llm" / case_id


def _write_progress(payload: dict) -> None:
    payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (OUT / "progress.json").write_text(json.dumps(payload, indent=2))


def _score_all() -> list[dict]:
    slice_data = json.loads(SLICE.read_text())
    rows: list[dict] = []
    for profile in PROFILES:
        for thinking in (False, True):
            tp = fp = unk = miss = 0
            sub = _run_dir(thinking, profile, "x").parent
            for cid in slice_data["tp"]:
                p = sub / cid / "agent-llm-triage-result.json"
                if not p.is_file():
                    miss += 1
                    continue
                lbl = json.loads(p.read_text()).get("label", "?")
                if lbl == "TP":
                    tp += 1
                elif lbl == "UNKNOWN":
                    unk += 1
            for cid in slice_data["fp"]:
                p = sub / cid / "agent-llm-triage-result.json"
                if not p.is_file():
                    miss += 1
                    continue
                lbl = json.loads(p.read_text()).get("label", "?")
                if lbl == "FP":
                    fp += 1
                elif lbl == "UNKNOWN":
                    unk += 1
            rows.append(
                {
                    "profile": profile,
                    "thinking": "on" if thinking else "off",
                    "fewshot": FEWSHOT,
                    "few_shot_config": FEWSHOT_CONFIG,
                    "vdr": tp,
                    "fprr": fp,
                    "total": tp + fp,
                    "unknown": unk,
                    "missing": miss,
                }
            )
    return rows


def main() -> None:
    from benchmark.few_shot import configured_few_shot_k, resolve_few_shot_config_path
    from benchmark.local_model_unload import release_gpu_memory
    from benchmark.run_llm_local import run_triage_case

    cfg_path = resolve_few_shot_config_path(FEWSHOT_CONFIG)
    if configured_few_shot_k(FEWSHOT_CONFIG) != FEWSHOT:
        raise SystemExit(f"config {FEWSHOT_CONFIG} must have {FEWSHOT} exemplars")

    jobs = _jobs()
    total = len(jobs) * len(PROFILES) * 2
    n = 0
    t0 = time.time()
    results: list[dict] = []

    OUT.mkdir(parents=True, exist_ok=True)
    log_dir = OUT / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    for thinking in (False, True):
        think_label = "on" if thinking else "off"
        for profile in PROFILES:
            print(
                f"\n=== {profile} think={think_label} fs={FEWSHOT} ({FEWSHOT_CONFIG}) ===",
                flush=True,
            )
            for track, cid, case_path, gold in jobs:
                n += 1
                run_dir = _run_dir(thinking, profile, cid)
                rp = run_dir / "agent-llm-triage-result.json"
                if rp.is_file():
                    lbl = json.loads(rp.read_text()).get("label", "?")
                    results.append(
                        {
                            "profile": profile,
                            "thinking": thinking,
                            "fewshot": FEWSHOT,
                            "few_shot_config": FEWSHOT_CONFIG,
                            "case_id": cid,
                            "gold": gold,
                            "label": lbl,
                            "ok": lbl == gold,
                            "cached": True,
                        }
                    )
                    print(f"[{n}/{total}] {profile} {cid}: {lbl} (cached)", flush=True)
                    continue

                run_dir.mkdir(parents=True, exist_ok=True)
                _write_progress(
                    {
                        "case": n,
                        "total": total,
                        "profile": profile,
                        "thinking": think_label,
                        "fewshot": FEWSHOT,
                        "few_shot_config": FEWSHOT_CONFIG,
                        "case_id": cid,
                        "status": "running",
                    }
                )
                print(
                    f"[{n}/{total}] {profile} {cid} think={think_label} fs={FEWSHOT} ...",
                    flush=True,
                )
                try:
                    run_triage_case(
                        case_path=case_path,
                        profile=profile,
                        run_dir=run_dir,
                        sast_root=SAST,
                        gold=gold,
                        thinking=thinking,
                        few_shot=FEWSHOT,
                        few_shot_config=FEWSHOT_CONFIG,
                        quiet=True,
                    )
                    lbl = json.loads(rp.read_text()).get("label", "?")
                    meta = json.loads((run_dir / "run_meta.json").read_text())
                    ok = lbl == gold
                    row = {
                        "profile": profile,
                        "thinking": thinking,
                        "fewshot": FEWSHOT,
                        "few_shot_config": FEWSHOT_CONFIG,
                        "case_id": cid,
                        "gold": gold,
                        "label": lbl,
                        "ok": ok,
                        "elapsed_sec": meta.get("elapsed_sec"),
                        "output_tokens": meta.get("output_tokens"),
                    }
                    results.append(row)
                    print(
                        f"[{n}/{total}] {profile} {cid}: {lbl} ({'OK' if ok else 'MISS'}) "
                        f"{meta.get('elapsed_sec', 0):.0f}s",
                        flush=True,
                    )
                except Exception as exc:
                    results.append(
                        {
                            "profile": profile,
                            "thinking": thinking,
                            "fewshot": FEWSHOT,
                            "few_shot_config": FEWSHOT_CONFIG,
                            "case_id": cid,
                            "gold": gold,
                            "label": "ERROR",
                            "ok": False,
                            "error": str(exc),
                        }
                    )
                    print(f"[{n}/{total}] {profile} {cid}: ERROR {exc}", flush=True)
            release_gpu_memory()

    rows = _score_all()
    print("\n=== SCORES (hard slice 20, v2 3shot 2TP+1FP) ===", flush=True)
    print(f"{'Profile':22s} {'Think':5s} {'FS':3s} {'VDR':>8s} {'FPRR':>8s} {'Total':>8s}", flush=True)
    print("-" * 60, flush=True)
    for r in sorted(rows, key=lambda x: (-x["total"], -x["vdr"], -x["fprr"])):
        print(
            f"{r['profile']:22s} {r['thinking']:5s} {r['fewshot']:3d} "
            f"{r['vdr']:3d}/10 {r['fprr']:3d}/10 {r['total']:3d}/20",
            flush=True,
        )

    summary = {
        "fewshot_layout": "v2-3shot-2tp-fp",
        "few_shot_config": FEWSHOT_CONFIG,
        "few_shot_config_path": str(cfg_path),
        "fewshot_exemplars": [
            "BenchmarkTest02272 (TP, multi-alert)",
            "BenchmarkTest00008 (TP, header SQLi)",
            "BenchmarkTest00200 (FP, list remove/get)",
        ],
        "elapsed_s": time.time() - t0,
        "scores": rows,
        "results": results,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {OUT / 'summary.json'}", flush=True)


if __name__ == "__main__":
    main()
