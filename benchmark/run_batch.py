#!/usr/bin/env python3
"""Batch ``llm`` or ``openhands`` only; skips existing run dirs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

VALID_LABELS = frozenset({"TP", "FP", "UNKNOWN"})


def _case_id(eval_fw: Path, case_path: Path) -> str:
    sys.path.insert(0, str(eval_fw))
    from make_task import stable_case_id  # type: ignore[import-not-found]

    case = json.loads(case_path.read_text(encoding="utf-8"))
    return stable_case_id(case)


def _safe_model_dir(model: str) -> str:
    sanitized = model.replace("/", "_")
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in sanitized)


def _write_cell_timing(
    *,
    runs_root: Path,
    profile: str,
    agent: str,
    gold: str | None,
    thinking: bool,
    case_dir: Path,
    cases: list[dict],
    cell_started_at: str,
    cell_elapsed_sec: float,
) -> None:
    from timing import aggregate_seconds, aggregate_tokens, utc_now_iso, write_json

    model_dir = runs_root / _safe_model_dir(profile)
    elapsed = [float(c["elapsed_sec"]) for c in cases if c.get("elapsed_sec") is not None]
    infer = [float(c["inference_sec"]) for c in cases if c.get("inference_sec") is not None]
    payload = {
        "profile": profile,
        "agent": agent,
        "gold": gold,
        "thinking": thinking,
        "case_dir": str(case_dir),
        "runs_root": str(runs_root),
        "started_at": cell_started_at,
        "finished_at": utc_now_iso(),
        "elapsed_sec": round(cell_elapsed_sec, 3),
        "n_cases": len(cases),
        "cases": cases,
        "aggregate": {
            "wall_clock_sec": round(cell_elapsed_sec, 3),
            "per_case": aggregate_seconds(elapsed),
            "inference": aggregate_seconds(infer),
            "tokens": {
                "input": aggregate_tokens(cases, "input_tokens"),
                "output": aggregate_tokens(cases, "output_tokens"),
                "total": aggregate_tokens(cases, "total_tokens"),
            },
        },
    }
    write_json(model_dir / "cell_timing.json", payload)


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True, choices=("llm", "openhands"))
    ap.add_argument("--case-dir", type=Path, required=True)
    ap.add_argument("--repo", type=Path, default=None, help="BenchmarkJava root (default: ../BenchmarkJava if it contains the case file).")
    ap.add_argument(
        "--profile",
        default="qwen3_8b_bnb",
        help="Model profile for --agent llm (see benchmark/llm_generate.py)",
    )
    ap.add_argument(
        "--thinking",
        action="store_true",
        help="Enable chain-of-thought before JSON (passed to run_llm_local.py)",
    )
    ap.add_argument("--llm-model", default="local-qwen", help="LLM_MODEL for --agent openhands")
    ap.add_argument("--llm-provider", default="openai")
    ap.add_argument("--max-cases", type=int, default=None)
    ap.add_argument(
        "--runs-root",
        type=Path,
        default=Path("runs"),
        help="Root for run artifacts (default: ./runs)",
    )
    ap.add_argument(
        "--retry-missing",
        action="store_true",
        help="Re-run cases without a valid agent-llm-triage-result.json label",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-run even if run directory exists",
    )
    ap.add_argument(
        "--retry-wrong",
        action="store_true",
        help="Re-run cases whose label differs from --gold (requires --gold)",
    )
    ap.add_argument(
        "--gold",
        choices=("FP", "TP"),
        default=None,
        help="Gold label for --retry-wrong and passed to run_llm_local.py",
    )
    ap.add_argument(
        "--eval-framework",
        type=Path,
        default=None,
    )
    ap.add_argument(
        "--subprocess-per-case",
        action="store_true",
        help="Spawn a new Python process per case (reloads model each time). Default: in-process batch.",
    )
    args = ap.parse_args()

    if args.profile == "gpt_oss_20b":
        import os

        os.environ.setdefault("GPT_OSS_HF_ONLY", "1")
        os.environ.setdefault("GPT_OSS_MAX_SEQ_LEN", "12288")
        os.environ.setdefault("AGENT_MAX_NEW_TOKENS", "2048")

    sast_root = Path(__file__).resolve().parent.parent
    bench = Path(__file__).resolve().parent
    eval_fw = args.eval_framework or (sast_root.parent / "SAST-Paper-Artifacts" / "Evaluation Framework")
    eval_fw = eval_fw.expanduser().resolve()
    if str(bench) not in sys.path:
        sys.path.insert(0, str(bench))
    import repo_root as _repo  # noqa: E402
    from timing import case_elapsed_sec, read_run_meta, tokens_from_meta, utc_now_iso  # noqa: E402

    case_dir = args.case_dir.expanduser().resolve()
    files = sorted(p for p in case_dir.glob("*.json") if p.name != "slice_manifest.json")
    if args.max_cases is not None:
        files = files[: args.max_cases]

    script_llm = bench / "run_llm_local.py"
    script_oh = bench / "run_openhands.py"
    # Default in-process for all LLM profiles (load once per cell). Unsloth OOM on GPT-OSS
    # disables Unsloth for the rest of the cell and uses cached HF. Use
    # --subprocess-per-case only to debug CUDA assert isolation.
    in_process_llm = args.agent == "llm" and not args.subprocess_per_case

    runs_root = args.runs_root.expanduser().resolve()
    cell_started_at = utc_now_iso()
    t_cell_start = time.perf_counter()
    case_timings: list[dict] = []

    if in_process_llm:
        if str(sast_root) not in sys.path:
            sys.path.insert(0, str(sast_root))
        from benchmark.run_llm_local import run_triage_case  # noqa: E402

        print(
            f"[batch] in-process mode: load model once for profile={args.profile!r} "
            f"({len(files)} cases)",
            flush=True,
        )
        # Build all task.md before any model weights touch GPU (make_task fails if VRAM full).
        prebuild = bench / "prebuild_cell_tasks.py"
        pb_cmd = [
            sys.executable,
            str(prebuild),
            "--case-dir",
            str(case_dir),
            "--runs-root",
            str(runs_root),
            "--profile",
            args.profile,
        ]
        if args.repo:
            pb_cmd.extend(["--repo", str(args.repo)])
        print("[batch] prebuilding task.md for all cases (CPU, no model load)...", flush=True)
        subprocess.run(pb_cmd, cwd=str(sast_root), check=False)

    for case_path in files:
        cid = _case_id(eval_fw, case_path)
        model_key = args.profile if args.agent == "llm" else args.llm_model
        run_dir = runs_root / _safe_model_dir(model_key) / args.agent / cid
        result_path = run_dir / "agent-llm-triage-result.json"
        lbl: str | None = None
        if result_path.is_file():
            try:
                data = json.loads(result_path.read_text(encoding="utf-8"))
                lbl = str(data.get("label", "")).strip().upper()
            except Exception:
                lbl = None

        skipped = False
        if run_dir.exists() and not args.force:
            if args.retry_wrong and args.gold:
                gold_u = args.gold.strip().upper()
                if lbl in VALID_LABELS and lbl == gold_u:
                    print(f"[skip] {cid} (correct {lbl})")
                    skipped = True
            elif not args.retry_missing:
                print(f"[skip] {cid}")
                skipped = True
            elif lbl in VALID_LABELS and not args.retry_wrong:
                print(f"[skip] {cid} (valid result)")
                skipped = True

        if skipped:
            meta = read_run_meta(run_dir)
            elapsed = case_elapsed_sec(run_dir)
            tok = tokens_from_meta(meta)
            case_timings.append(
                {
                    "case_id": cid,
                    "skipped": True,
                    "elapsed_sec": round(elapsed, 3) if elapsed is not None else None,
                    "inference_sec": meta.get("inference_sec"),
                    **tok,
                }
            )
            continue

        case = json.loads(case_path.read_text(encoding="utf-8"))
        repo = _repo.resolve_benchmark_java_root(sast_root, case, args.repo)

        t_case = time.perf_counter()
        if in_process_llm:
            meta = run_triage_case(
                case_path=case_path,
                profile=args.profile,
                run_dir=run_dir,
                sast_root=sast_root,
                eval_fw=eval_fw,
                gold=args.gold,
                thinking=args.thinking,
                repo=repo,
                quiet=True,
            )
            rc = int(meta.get("returncode", 1))
        elif args.agent == "llm":
            cmd = [
                sys.executable,
                str(script_llm),
                "--case",
                str(case_path),
                "--repo",
                str(repo),
                "--profile",
                args.profile,
                "--eval-framework",
                str(eval_fw),
                "--run-dir",
                str(run_dir),
            ]
            if args.gold:
                cmd.extend(["--gold", args.gold])
            if args.thinking:
                cmd.append("--thinking")
            r = subprocess.run(cmd, cwd=str(sast_root))
            rc = r.returncode
            meta = read_run_meta(run_dir)
        else:
            cmd = [
                sys.executable,
                str(script_oh),
                "--case",
                str(case_path),
                "--repo",
                str(repo),
                "--eval-framework",
                str(eval_fw),
                "--llm-model",
                args.llm_model,
                "--llm-provider",
                args.llm_provider,
                "--run-dir",
                str(run_dir),
            ]
            r = subprocess.run(cmd, cwd=str(sast_root))
            rc = r.returncode
            meta = read_run_meta(run_dir)

        wall_sec = time.perf_counter() - t_case
        elapsed = meta.get("elapsed_sec", wall_sec)
        tok = tokens_from_meta(meta)
        case_timings.append(
            {
                "case_id": cid,
                "skipped": False,
                "returncode": rc,
                "elapsed_sec": round(float(elapsed), 3),
                "wall_sec": round(wall_sec, 3),
                "inference_sec": meta.get("inference_sec"),
                "task_sec": meta.get("task_sec"),
                **tok,
            }
        )
        tok_s = f" tok={tok['total_tokens']}" if tok.get("total_tokens") else ""
        print(f"[rc={rc}] {cid} ({float(elapsed):.1f}s){tok_s}")

    cell_elapsed = time.perf_counter() - t_cell_start
    _write_cell_timing(
        runs_root=runs_root,
        profile=args.profile if args.agent == "llm" else args.llm_model,
        agent=args.agent,
        gold=args.gold,
        thinking=args.thinking,
        case_dir=case_dir,
        cases=case_timings,
        cell_started_at=cell_started_at,
        cell_elapsed_sec=cell_elapsed,
    )
    ran = sum(1 for c in case_timings if not c.get("skipped"))
    print(
        f"[cell timing] profile={args.profile} gold={args.gold} "
        f"wall={cell_elapsed:.1f}s ran={ran} skipped={len(case_timings) - ran}"
    )


def main() -> None:
    try:
        _main()
    finally:
        import os
        from local_model_unload import release_gpu_memory

        release_gpu_memory(verbose=os.environ.get("PHASE1_VERBOSE", "0") == "1")


if __name__ == "__main__":
    main()
