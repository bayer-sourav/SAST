#!/usr/bin/env python3
"""Stage 3 hard-slice smoke: 2 profiles × 3 prompt variants × fs3 × think=on.

Uses /tmp/smoke_slice_cases.json (10 TP + 10 FP).
Output: runs/phase2/stage3/smoke/thinking_on/fewshot_3/<prompt>/<profile>/llm/<case_id>/
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

SAST = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(SAST))
sys.path.insert(0, str(SAST / "benchmark"))
os.chdir(SAST)

SLICE = Path("/tmp/smoke_slice_cases.json")
MANIFEST = Path(__file__).resolve().parent / "MANIFEST.json"
OUT = SAST / "runs/phase2/stage3/smoke"
FEWSHOT = 3
FEWSHOT_CONFIG = "v2_3shot_tp_2fp"
SMOKE_VDR_MIN = 9  # of 10 TP
SMOKE_FPRR_MIN = 9  # of 10 FP
CELL_FILTER = os.environ.get("STAGE3_SMOKE_CELL", "").strip() or None
FORCE = os.environ.get("STAGE3_FORCE", "").strip() in ("1", "true", "yes")


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


def _run_dir(prompt_version: str, profile: str, case_id: str) -> Path:
    return (
        OUT
        / "thinking_on"
        / f"fewshot_{FEWSHOT}"
        / prompt_version
        / profile
        / "llm"
        / case_id
    )


def _score_all(cells: list[dict]) -> list[dict]:
    slice_data = json.loads(SLICE.read_text())
    rows: list[dict] = []
    for cell in cells:
        profile = cell["profile"]
        pv = cell["prompt_version"]
        tp = fp = unk = miss = 0
        sub = _run_dir(pv, profile, "x").parent
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
        rows.append(
            {
                "cell_id": cell["id"],
                "profile": profile,
                "prompt_version": pv,
                "vdr": tp,
                "vdr_pct": tp / n_tp if n_tp else 0,
                "fprr": fp,
                "fprr_pct": fp / n_fp if n_fp else 0,
                "total": tp + fp,
                "unknown": unk,
                "missing": miss,
                "smoke_pass": tp >= SMOKE_VDR_MIN and fp >= SMOKE_FPRR_MIN,
            }
        )
    return rows


def main() -> None:
    from benchmark.local_model_unload import release_gpu_memory
    from benchmark.prompt_versions import task_prompt_version_string
    from benchmark.run_llm_local import run_triage_case

    manifest = json.loads(MANIFEST.read_text())
    cells = manifest["cells"]
    if CELL_FILTER:
        cells = [c for c in cells if c["id"] == CELL_FILTER]
        if not cells:
            raise SystemExit(f"unknown STAGE3_SMOKE_CELL={CELL_FILTER!r}")
    jobs = _jobs()
    total = len(jobs) * len(cells)
    n = 0
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)

    # 5.9b before coder-30b; v7 baseline before v8/v9
    order = {"qwen3_5_9b_bnb": 0, "qwen3_coder_30b_bnb": 1}
    pv_order = {"v7-balanced": 0, "v8-dual-gate": 1, "v9-fprr-first": 2}
    cells = sorted(
        cells,
        key=lambda c: (order.get(c["profile"], 9), pv_order.get(c["prompt_version"], 9)),
    )

    for cell in cells:
        profile = cell["profile"]
        pv = cell["prompt_version"]
        print(f"\n=== {cell['id']} {profile} prompt={pv} ===", flush=True)
        for case_id, case_path, gold in jobs:
            n += 1
            run_dir = _run_dir(pv, profile, case_id)
            result_path = run_dir / "agent-llm-triage-result.json"
            task_path = run_dir / "task.md"
            if not FORCE and result_path.is_file():
                try:
                    lbl = json.loads(result_path.read_text()).get("label")
                    if lbl in ("TP", "FP", "BL", "UNKNOWN") and task_path.is_file():
                        head = task_path.read_text(encoding="utf-8", errors="replace")[:800]
                        tag = task_prompt_version_string(pv)
                        fs_tag = f"fewshot{FEWSHOT}"
                        if tag in head and fs_tag in head:
                            print(f"[{n}/{total}] skip {case_id} ({lbl})", flush=True)
                            continue
                except json.JSONDecodeError:
                    pass
            if FORCE and run_dir.exists():
                for stale in ("task.md", "agent-llm-triage-result.json", "llm_raw.txt", "prompt_record.json"):
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
                prompt_version=pv,
                quiet=True,
            )
            if meta.get("returncode") != 0:
                print(f"  FAIL: {meta.get('error', 'unknown')}", flush=True)
        release_gpu_memory()

    rows = _score_all(cells)
    summary = {
        "slice": str(SLICE),
        "fewshot": FEWSHOT,
        "few_shot_config": FEWSHOT_CONFIG,
        "cell_filter": CELL_FILTER,
        "force": FORCE,
        "prompt_tag": task_prompt_version_string("v7-balanced") if not CELL_FILTER else task_prompt_version_string(cells[0]["prompt_version"]),
        "smoke_gates": {"vdr_min": SMOKE_VDR_MIN, "fprr_min": SMOKE_FPRR_MIN},
        "elapsed_sec": round(time.time() - t0, 1),
        "scores": rows,
    }
    out_name = "smoke_summary_59b_v7_langagnostic.json" if CELL_FILTER == "59b_v7" else "smoke_summary.json"
    (OUT / out_name).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if CELL_FILTER:
        print(f"\nWrote {OUT / out_name}", flush=True)

    print("\n=== Stage 3 smoke scores (hard slice 20) ===", flush=True)
    print(f"{'cell':<12} {'profile':<22} {'prompt':<16} {'VDR':>8} {'FPRR':>8} {'pass':>5}", flush=True)
    for r in rows:
        print(
            f"{r['cell_id']:<12} {r['profile']:<22} {r['prompt_version']:<16} "
            f"{r['vdr']:>3}/10 {r['fprr']:>3}/10 {'YES' if r['smoke_pass'] else 'no':>5}",
            flush=True,
        )
    passed = [r for r in rows if r["smoke_pass"]]
    print(f"\nSmoke pass ({SMOKE_VDR_MIN}/10 VDR & {SMOKE_FPRR_MIN}/10 FPRR): {len(passed)}/{len(rows)} cells", flush=True)
    if passed:
        print("Candidates for full Stage 3 corpus:", ", ".join(r["cell_id"] for r in passed), flush=True)


if __name__ == "__main__":
    main()
