#!/usr/bin/env python3
"""Hard-slice smoke for gemma_4_e4b_bnb with thinking on + off (fewshot v3).

Output layout (phase2-style):
  runs/smoke/v7_fewshot_v3_best_profiles/thinking_{on,off}/gemma_4_e4b_bnb/llm/<case_id>/

Legacy runs at .../gemma_4_e4b_bnb/llm/ (no thinking prefix) count as thinking_off.
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
OUT = SAST / "runs/smoke/v7_fewshot_v3_best_profiles"
PROFILE = "gemma_4_e4b_bnb"
FEWSHOT = 3


def _jobs() -> list[tuple[str, str, Path, str]]:
    slice_data = json.loads(SLICE.read_text())
    jobs: list[tuple[str, str, Path, str]] = []
    for cid in slice_data["tp"]:
        jobs.append(
            (
                "tp",
                cid,
                SAST / f"benchmark/corpora/phase2_tp_test/OWASP_{cid}.json",
                "TP",
            )
        )
    for cid in slice_data["fp"]:
        jobs.append(
            (
                "fp",
                cid,
                SAST / f"benchmark/corpora/phase2_fp_test/OWASP_{cid}.json",
                "FP",
            )
        )
    return jobs


def _run_dir(thinking: bool, case_id: str) -> Path:
    mode = "thinking_on" if thinking else "thinking_off"
    return OUT / mode / PROFILE / "llm" / case_id


def _legacy_run_dir(case_id: str) -> Path:
    return OUT / PROFILE / "llm" / case_id


def _result_path(thinking: bool, case_id: str) -> Path:
    if not thinking:
        legacy = _legacy_run_dir(case_id) / "agent-llm-triage-result.json"
        if legacy.is_file():
            return legacy
    return _run_dir(thinking, case_id) / "agent-llm-triage-result.json"


def _write_progress(out: Path, payload: dict) -> None:
    payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    (out / "gemma4_progress.json").write_text(json.dumps(payload, indent=2))


def main() -> None:
    from benchmark.local_model_unload import release_gpu_memory
    from benchmark.run_llm_local import run_triage_case

    jobs = _jobs()
    modes = (False, True)
    total = len(jobs) * len(modes)
    n = 0
    t0 = time.time()
    results: list[dict] = []

    for thinking in modes:
        label = "on" if thinking else "off"
        print(f"\n=== {PROFILE} thinking={label} fewshot={FEWSHOT} (v3) ===", flush=True)
        for track, cid, case_path, gold in jobs:
            n += 1
            rp = _result_path(thinking, cid)
            if rp.is_file():
                lbl = json.loads(rp.read_text()).get("label", "?")
                results.append(
                    {
                        "profile": PROFILE,
                        "thinking": thinking,
                        "case_id": cid,
                        "gold": gold,
                        "label": lbl,
                        "ok": lbl == gold,
                        "cached": True,
                    }
                )
                print(f"[{n}/{total}] {cid}: {lbl} (cached)", flush=True)
                continue

            run_dir = _run_dir(thinking, cid)
            run_dir.mkdir(parents=True, exist_ok=True)
            print(f"[{n}/{total}] {cid}: generating (think={label})...", flush=True)
            _write_progress(
                OUT,
                {
                    "case": n,
                    "total": total,
                    "case_id": cid,
                    "thinking": label,
                    "status": "running",
                },
            )
            try:
                run_triage_case(
                    case_path=case_path,
                    profile=PROFILE,
                    run_dir=run_dir,
                    sast_root=SAST,
                    gold=gold,
                    thinking=thinking,
                    few_shot=FEWSHOT,
                    quiet=True,
                )
                lbl = json.loads(rp.read_text()).get("label", "?")
                meta = json.loads((run_dir / "run_meta.json").read_text())
                ok = lbl == gold
                results.append(
                    {
                        "profile": PROFILE,
                        "thinking": thinking,
                        "case_id": cid,
                        "gold": gold,
                        "label": lbl,
                        "ok": ok,
                        "elapsed_sec": meta.get("elapsed_sec"),
                        "output_tokens": meta.get("output_tokens"),
                    }
                )
                print(
                    f"[{n}/{total}] {cid}: {lbl} ({'OK' if ok else 'MISS'}) "
                    f"{meta.get('elapsed_sec', 0):.0f}s out={meta.get('output_tokens')}",
                    flush=True,
                )
            except Exception as exc:
                results.append(
                    {
                        "profile": PROFILE,
                        "thinking": thinking,
                        "case_id": cid,
                        "gold": gold,
                        "label": "ERROR",
                        "ok": False,
                        "error": str(exc),
                    }
                )
                print(f"[{n}/{total}] {cid}: ERROR {exc}", flush=True)
        release_gpu_memory()

    slice_data = json.loads(SLICE.read_text())

    def score(thinking: bool) -> tuple[int, int]:
        tp = fp = 0
        for cid in slice_data["tp"]:
            p = _result_path(thinking, cid)
            if p.is_file() and json.loads(p.read_text()).get("label") == "TP":
                tp += 1
        for cid in slice_data["fp"]:
            p = _result_path(thinking, cid)
            if p.is_file() and json.loads(p.read_text()).get("label") == "FP":
                fp += 1
        return tp, fp

    print("\n=== Gemma 4 E4B v3 hard slice ===", flush=True)
    for thinking in modes:
        tp, fp = score(thinking)
        label = "on" if thinking else "off"
        print(f"  thinking_{label}: VDR {tp}/10 FPRR {fp}/10 ({tp + fp}/20)", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    summary = {
        "profile": PROFILE,
        "fewshot": "v3",
        "elapsed_s": time.time() - t0,
        "results": results,
    }
    (OUT / "gemma4_thinking_summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nWrote {OUT / 'gemma4_thinking_summary.json'}", flush=True)


if __name__ == "__main__":
    main()
