#!/usr/bin/env python3
"""Benchmark vLLM inference vs prior Unsloth run_meta (same cases as bench_infer_speed_fix)."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))
bench = _sast / "benchmark"
if str(bench) not in sys.path:
    sys.path.insert(0, str(bench))

from benchmark.run_llm_local import run_triage_case  # noqa: E402
from core.generation_defaults import apply_triage_run_token_limits  # noqa: E402

DEFAULT_CASES = [
    "BenchmarkTest00242",
    "BenchmarkTest00942",
    "BenchmarkTest00524",
    "BenchmarkTest00042",
    "BenchmarkTest02076",
]

OLD_META_ROOTS = [
    _sast / "runs/phase2/stage2/fp/thinking_on/fewshot_3/qwen3_5_9b_bnb/llm",
    _sast / "runs/phase3/stage3b/teacher/train/fp/thinking_on/fewshot_3/qwen3_5_9b_bnb/llm",
]


def _old_meta(case_id: str) -> dict | None:
    for root in OLD_META_ROOTS:
        p = root / case_id / "run_meta.json"
        if p.is_file():
            return json.loads(p.read_text(encoding="utf-8"))
    return None


def _resolve_case_path(case_dir: Path, case_id: str) -> Path | None:
    for name in (f"{case_id}.json", f"OWASP_{case_id}.json"):
        p = case_dir / name
        if p.is_file():
            return p
    for p in case_dir.glob(f"*{case_id}*.json"):
        return p
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case-dir", type=Path, default=_sast / "benchmark/corpora/phase2_fp_test")
    ap.add_argument(
        "--out-root",
        type=Path,
        default=_sast
        / "runs/phase3/stage3b/vllm_bench/thinking_on/fewshot_3/qwen3_5_9b_bnb/llm",
    )
    ap.add_argument("--cases", nargs="*", default=DEFAULT_CASES)
    ap.add_argument("--profile", default="qwen3_5_9b_bnb")
    ap.add_argument("--prompt-version", default="v7-balanced")
    ap.add_argument("--few-shot-config", default="v2_3shot_tp_2fp")
    args = ap.parse_args()

    os.environ.setdefault("QWEN_INFER_BACKEND", "vllm")
    apply_triage_run_token_limits(thinking=True)
    os.environ.setdefault("PHASE2_ON_MAX_NEW_TOKENS_THINKING", "4096")
    os.environ.setdefault("PHASE2_ON_MAX_NEW_TOKENS", "4800")

    from benchmark import repo_root as _repo  # noqa: E402

    rows: list[dict] = []
    for cid in args.cases:
        case_path = _resolve_case_path(args.case_dir, cid)
        if case_path is None:
            print(f"[skip] missing case {cid}", file=sys.stderr)
            continue
        case = json.loads(case_path.read_text(encoding="utf-8"))
        repo = _repo.resolve_benchmark_java_root(_sast, case, None, case_path=case_path)
        run_dir = args.out_root / cid
        if run_dir.exists():
            import shutil

            shutil.rmtree(run_dir)
        meta = run_triage_case(
            case_path=case_path,
            profile=args.profile,
            run_dir=run_dir,
            sast_root=_sast,
            gold="FP",
            thinking=True,
            few_shot=3,
            few_shot_config=args.few_shot_config,
            prompt_version=args.prompt_version,
            repo=repo,
            quiet=True,
        )
        old = _old_meta(cid) or {}
        new_out = meta.get("output_tokens") or 0
        new_inf = meta.get("inference_sec") or 0
        old_out = old.get("output_tokens") or 0
        old_inf = old.get("inference_sec") or 0
        new_tps = (new_out / new_inf) if new_inf and new_out else 0
        old_tps = (old_out / old_inf) if old_inf and old_out else 0
        row = {
            "case_id": cid,
            "backend": os.environ.get("QWEN_INFER_BACKEND", "vllm"),
            "old_out": old_out,
            "new_out": new_out,
            "old_sec": round(old_inf, 1) if old_inf else None,
            "new_sec": round(new_inf, 1) if new_inf else None,
            "old_tps": round(old_tps, 1) if old_tps else None,
            "new_tps": round(new_tps, 1) if new_tps else None,
            "rc": meta.get("returncode"),
        }
        rows.append(row)
        print(
            f"{cid}: out {old_out}->{new_out} sec {old_inf:.0f}->{new_inf:.0f} "
            f"tps {old_tps:.1f}->{new_tps:.1f} rc={meta.get('returncode')}",
            flush=True,
        )

    out_json = args.out_root.parent.parent.parent.parent / "bench_vllm_speed.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "backend": os.environ.get("QWEN_INFER_BACKEND"),
        "model": os.environ.get("QWEN_VLLM_MODEL_ID", "Qwen/Qwen3.5-9B"),
        "cases": rows,
    }
    if rows:
        import statistics as st

        ok = [r for r in rows if r.get("new_tps")]
        if ok:
            summary["mean_new_tps"] = round(st.mean(r["new_tps"] for r in ok), 2)
        old_ok = [r for r in rows if r.get("old_tps")]
        if old_ok:
            summary["mean_old_tps"] = round(st.mean(r["old_tps"] for r in old_ok), 2)
    out_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n[bench] wrote {out_json}")


if __name__ == "__main__":
    main()
