#!/usr/bin/env python3
"""Hard-slice smoke for large Qwen models (Stage 2 ship: v7-balanced + fs3 v2_3shot_tp_2fp).

Profiles (default):
  - qwen3_next_80b_bnb (Bedrock)
  - qwen3_6_27b_bnb (local Unsloth 4-bit)
  - qwen3_6_35b_a3b_bnb (local Unsloth 4-bit)

Output: runs/smoke/large_qwen_stage2_v7/thinking_on/fewshot_3/v7-balanced/<profile>/llm/<case_id>/

Env:
  LARGE_QWEN_SMOKE_PROFILES — comma-separated profile subset
  LARGE_QWEN_FORCE=1 — delete stale artifacts and re-run
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
OUT = SAST / "runs/smoke/large_qwen_stage2_v7"
FEWSHOT = 3
FEWSHOT_CONFIG = "v2_3shot_tp_2fp"
PROMPT_VERSION = "v7-balanced"
SMOKE_VDR_MIN = 9
SMOKE_FPRR_MIN = 9
DEFAULT_PROFILES = (
    "qwen3_next_80b_bnb",
    "qwen3_6_27b_bnb",
    "qwen3_6_35b_a3b_bnb",
)
FORCE = os.environ.get("LARGE_QWEN_FORCE", "").strip() in ("1", "true", "yes")


def _profiles() -> list[str]:
    raw = os.environ.get("LARGE_QWEN_SMOKE_PROFILES", "").strip()
    if not raw:
        return list(DEFAULT_PROFILES)
    return [p.strip() for p in raw.split(",") if p.strip()]


def _jobs() -> list[tuple[str, Path, str]]:
    slice_data = json.loads(SLICE.read_text())
    jobs: list[tuple[str, Path, str]] = []
    for cid in slice_data["tp"]:
        jobs.append(
            (cid, SAST / f"benchmark/corpora/phase2_tp_test/OWASP_{cid}.json", "TP")
        )
    for cid in slice_data["fp"]:
        jobs.append(
            (cid, SAST / f"benchmark/corpora/phase2_fp_test/OWASP_{cid}.json", "FP")
        )
    return jobs


def _run_dir(profile: str, case_id: str) -> Path:
    return (
        OUT
        / "thinking_on"
        / f"fewshot_{FEWSHOT}"
        / PROMPT_VERSION
        / profile
        / "llm"
        / case_id
    )


def _score_profile(profile: str) -> dict:
    slice_data = json.loads(SLICE.read_text())
    sub = _run_dir(profile, "x").parent
    tp = fp = unk = miss = 0
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
    n_tp = len(slice_data["tp"])
    n_fp = len(slice_data["fp"])
    return {
        "profile": profile,
        "vdr": tp,
        "vdr_pct": tp / n_tp if n_tp else 0,
        "fprr": fp,
        "fprr_pct": fp / n_fp if n_fp else 0,
        "total": tp + fp,
        "unknown": unk,
        "missing": miss,
        "smoke_pass": tp >= SMOKE_VDR_MIN and fp >= SMOKE_FPRR_MIN,
    }


def main() -> None:
    from benchmark.local_model_unload import release_gpu_memory
    from benchmark.prompt_versions import task_prompt_version_string
    from benchmark.run_llm_local import run_triage_case

    profiles = _profiles()
    jobs = _jobs()
    total = len(jobs) * len(profiles)
    n = 0
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    tag = task_prompt_version_string(PROMPT_VERSION)

    for profile in profiles:
        print(f"\n=== {profile} prompt={PROMPT_VERSION} tag={tag} ===", flush=True)
        for case_id, case_path, gold in jobs:
            n += 1
            run_dir = _run_dir(profile, case_id)
            result_path = run_dir / "agent-llm-triage-result.json"
            task_path = run_dir / "task.md"
            if not FORCE and result_path.is_file():
                try:
                    lbl = json.loads(result_path.read_text()).get("label")
                    if lbl in ("TP", "FP", "BL", "UNKNOWN") and task_path.is_file():
                        head = task_path.read_text(encoding="utf-8", errors="replace")[:800]
                        if tag in head and f"fewshot{FEWSHOT}" in head:
                            print(f"[{n}/{total}] skip {case_id} ({lbl})", flush=True)
                            continue
                except json.JSONDecodeError:
                    pass
            if FORCE and run_dir.exists():
                for stale in (
                    "task.md",
                    "agent-llm-triage-result.json",
                    "llm_raw.txt",
                    "prompt_record.json",
                ):
                    p = run_dir / stale
                    if p.is_file():
                        p.unlink()
            print(f"[{n}/{total}] {case_id} gold={gold}", flush=True)
            meta = run_triage_case(
                case_path=case_path,
                profile=profile,
                run_dir=run_dir,
                sast_root=SAST,
                gold=gold,
                thinking=True,
                few_shot=FEWSHOT,
                few_shot_config=FEWSHOT_CONFIG,
                prompt_version=PROMPT_VERSION,
                quiet=True,
            )
            if meta.get("returncode") != 0:
                print(f"  FAIL: {meta.get('error', 'unknown')}", flush=True)
        release_gpu_memory()

    rows = [_score_profile(p) for p in profiles]
    summary = {
        "slice": str(SLICE),
        "fewshot": FEWSHOT,
        "few_shot_config": FEWSHOT_CONFIG,
        "prompt_version": PROMPT_VERSION,
        "prompt_tag": tag,
        "profiles": profiles,
        "force": FORCE,
        "smoke_gates": {"vdr_min": SMOKE_VDR_MIN, "fprr_min": SMOKE_FPRR_MIN},
        "elapsed_sec": round(time.time() - t0, 1),
        "scores": rows,
    }
    summary_path = OUT / "smoke_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nWrote {summary_path}", flush=True)

    print("\n=== Large Qwen smoke scores (hard slice 20) ===", flush=True)
    print(f"{'profile':<24} {'VDR':>8} {'FPRR':>8} {'pass':>5}", flush=True)
    for r in rows:
        print(
            f"{r['profile']:<24} {r['vdr']:>3}/10 {r['fprr']:>3}/10 "
            f"{'YES' if r['smoke_pass'] else 'no':>5}",
            flush=True,
        )


if __name__ == "__main__":
    main()
