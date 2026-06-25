#!/usr/bin/env python3
"""Batch ``llm`` or ``openhands`` only; skips existing run dirs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_sast_root = Path(__file__).resolve().parent.parent
if str(_sast_root) not in sys.path:
    sys.path.insert(0, str(_sast_root))
from benchmark.triage_labels import VALID_LABELS  # noqa: E402


def _case_id(case_path: Path) -> str:
    from benchmark.make_task import stable_case_id

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
    few_shot: int,
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
        "few_shot": few_shot,
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


def _vllm_batch_enabled(profile: str) -> bool:
    try:
        from models.qwen.vllm_backend import should_use_vllm

        if not should_use_vllm(profile):
            return False
        return int(os.environ.get("QWEN_VLLM_BATCH_SIZE", "4")) > 1
    except Exception:
        return False


def _parse_tracks_json(path: Path) -> list[dict[str, str]]:
    raw = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"--tracks-json must be a non-empty list: {path}")
    specs: list[dict[str, str]] = []
    for i, row in enumerate(raw):
        if not isinstance(row, dict):
            raise ValueError(f"tracks[{i}] must be an object")
        for key in ("gold", "case_dir", "runs_root"):
            if key not in row or not str(row[key]).strip():
                raise ValueError(f"tracks[{i}] missing {key!r}")
        gold = str(row["gold"]).strip().upper()
        if gold not in ("FP", "TP", "BL"):
            raise ValueError(f"tracks[{i}] invalid gold={gold!r}")
        specs.append(
            {
                "gold": gold,
                "case_dir": str(row["case_dir"]),
                "runs_root": str(row["runs_root"]),
            }
        )
    return specs


def _preload_batch_model(
    *,
    args: argparse.Namespace,
    sast_root: Path,
    bench: Path,
    case_dir: Path,
    runs_root: Path,
    files: list[Path],
    in_process_llm: bool,
    use_vllm_batch: bool,
) -> None:
    if not in_process_llm:
        return
    if str(sast_root) not in sys.path:
        sys.path.insert(0, str(sast_root))

    print(
        f"[batch] in-process mode: load model once for profile={args.profile!r} "
        f"({len(files)} cases in {case_dir.name})",
        flush=True,
    )
    if use_vllm_batch:
        print(
            f"[batch] vLLM micro-batch size={int(os.environ.get('QWEN_VLLM_BATCH_SIZE', '4'))} "
            f"prefix_cache={os.environ.get('QWEN_VLLM_PREFIX_CACHING', '1')}",
            flush=True,
        )

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
    if args.max_cases is not None:
        pb_cmd.extend(["--max-cases", str(args.max_cases)])
    pb_cmd.extend(["--few-shot", str(args.few_shot)])
    if args.few_shot_config:
        pb_cmd.extend(["--few-shot-config", str(args.few_shot_config)])
    if args.prompt_version:
        pb_cmd.extend(["--prompt-version", str(args.prompt_version)])
    print(f"[batch] prebuilding task.md for {len(files)} cases (CPU, no model load)...", flush=True)
    pb_env = os.environ.copy()
    pb_env.setdefault("PYTHONPATH", str(sast_root))
    if str(sast_root) not in pb_env.get("PYTHONPATH", "").split(":"):
        pb_env["PYTHONPATH"] = f"{sast_root}:{pb_env.get('PYTHONPATH', '')}".rstrip(":")
    subprocess.run(pb_cmd, cwd=str(sast_root), check=False, env=pb_env)

    if args.profile in ("qwen3_coder_30b_bnb", "gpt_oss_20b"):
        from benchmark.llm_generate import preload_profile

        try:
            preload_profile(args.profile)
            print(f"[batch] preload ok for {args.profile!r}", flush=True)
        except Exception as exc:
            print(f"[batch] preload failed ({exc}); cases will attempt load anyway.", flush=True)
    elif use_vllm_batch or (
        __import__("models.qwen.vllm_backend", fromlist=["should_use_vllm"]).should_use_vllm(args.profile)
    ):
        from models.qwen.vllm_backend import preload_vllm_profile

        print(f"[batch] preloading vLLM for profile={args.profile!r}", flush=True)
        preload_vllm_profile(args.profile)


def _run_batch_track(
    args: argparse.Namespace,
    *,
    sast_root: Path,
    bench: Path,
    case_dir: Path,
    runs_root: Path,
    gold: str | None,
    in_process_llm: bool,
    use_vllm_batch: bool,
    preload_model: bool,
) -> None:
    import repo_root as _repo  # noqa: E402
    from timing import case_elapsed_sec, read_run_meta, tokens_from_meta, utc_now_iso  # noqa: E402

    if in_process_llm:
        from benchmark.run_llm_local import run_triage_case  # noqa: E402

    files = sorted(p for p in case_dir.glob("*.json") if p.name != "slice_manifest.json")
    if args.max_cases is not None:
        files = files[: args.max_cases]

    script_llm = bench / "run_llm_local.py"
    script_oh = bench / "run_openhands.py"
    vllm_batch_size = int(os.environ.get("QWEN_VLLM_BATCH_SIZE", "4"))
    vllm_pending: list[dict] = []

    runs_root = runs_root.expanduser().resolve()
    cell_started_at = utc_now_iso()
    t_cell_start = time.perf_counter()
    case_timings: list[dict] = []

    if preload_model:
        _preload_batch_model(
            args=args,
            sast_root=sast_root,
            bench=bench,
            case_dir=case_dir,
            runs_root=runs_root,
            files=files,
            in_process_llm=in_process_llm,
            use_vllm_batch=use_vllm_batch,
        )

    track_gold = gold
    for case_path in files:
        cid = _case_id(case_path)
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
            if args.retry_wrong and track_gold:
                gold_u = track_gold.strip().upper()
                if lbl in VALID_LABELS and lbl == gold_u:
                    print(f"[skip] {cid} (correct {lbl})")
                    skipped = True
            elif lbl in VALID_LABELS and not args.retry_wrong:
                print(f"[skip] {cid} (valid result)")
                skipped = True
            elif not args.retry_missing:
                print(f"[run] {cid} (stale run dir, no valid result)", flush=True)

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
        repo = _repo.resolve_benchmark_java_root(sast_root, case, args.repo, case_path=case_path)

        t_case = time.perf_counter()
        if use_vllm_batch:
            from benchmark.run_llm_local import prepare_triage_messages  # noqa: E402

            case_id_p, messages, task_sec = prepare_triage_messages(
                case_path=case_path,
                run_dir=run_dir,
                sast_root=sast_root,
                few_shot=args.few_shot,
                few_shot_config=args.few_shot_config,
                prompt_version=args.prompt_version,
                repo=repo,
            )
            vllm_pending.append(
                {
                    "case_id": case_id_p,
                    "run_dir": run_dir,
                    "messages": messages,
                    "task_sec": task_sec,
                    "started_at": utc_now_iso(),
                    "t_run_start": t_case,
                }
            )
            if len(vllm_pending) >= vllm_batch_size:
                _flush_vllm_triage_batch(
                    vllm_pending,
                    profile=args.profile,
                    thinking=args.thinking,
                    gold=track_gold,
                    few_shot=args.few_shot,
                    few_shot_config=args.few_shot_config,
                    prompt_version=args.prompt_version,
                    case_timings=case_timings,
                )
                vllm_pending.clear()
            continue
        if in_process_llm:
            meta = run_triage_case(
                case_path=case_path,
                profile=args.profile,
                run_dir=run_dir,
                sast_root=sast_root,
                gold=track_gold,
                thinking=args.thinking,
                few_shot=args.few_shot,
                few_shot_config=args.few_shot_config,
                prompt_version=args.prompt_version,
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
                "--run-dir",
                str(run_dir),
            ]
            if track_gold:
                cmd.extend(["--gold", track_gold])
            if args.thinking:
                cmd.append("--thinking")
            if args.few_shot:
                cmd.extend(["--few-shot", str(args.few_shot)])
            if args.few_shot_config:
                cmd.extend(["--few-shot-config", str(args.few_shot_config)])
            if args.prompt_version:
                cmd.extend(["--prompt-version", str(args.prompt_version)])
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

    if vllm_pending:
        _flush_vllm_triage_batch(
            vllm_pending,
            profile=args.profile,
            thinking=args.thinking,
            gold=track_gold,
            few_shot=args.few_shot,
            few_shot_config=args.few_shot_config,
            prompt_version=args.prompt_version,
            case_timings=case_timings,
        )

    cell_elapsed = time.perf_counter() - t_cell_start
    _write_cell_timing(
        runs_root=runs_root,
        profile=args.profile if args.agent == "llm" else args.llm_model,
        agent=args.agent,
        gold=track_gold,
        thinking=args.thinking,
        few_shot=args.few_shot,
        case_dir=case_dir,
        cases=case_timings,
        cell_started_at=cell_started_at,
        cell_elapsed_sec=cell_elapsed,
    )
    ran = sum(1 for c in case_timings if not c.get("skipped"))
    print(
        f"[cell timing] profile={args.profile} gold={track_gold} "
        f"wall={cell_elapsed:.1f}s ran={ran} skipped={len(case_timings) - ran}"
    )


def _flush_vllm_triage_batch(
    batch: list[dict],
    *,
    profile: str,
    thinking: bool,
    gold: str | None,
    few_shot: int,
    few_shot_config: str | None,
    prompt_version: str | None,
    case_timings: list[dict],
) -> None:
    from core.generation_defaults import apply_triage_run_token_limits
    from models.qwen.vllm_backend import vllm_generate_batch_from_chat

    from benchmark.run_llm_local import finalize_triage_inference

    apply_triage_run_token_limits(thinking=thinking)
    t_batch = time.perf_counter()
    try:
        results = vllm_generate_batch_from_chat(
            [item["messages"] for item in batch],
            profile=profile,
            enable_thinking=thinking,
        )
    except Exception as exc:
        err_s = f"{type(exc).__name__}: {exc}"
        if "context length" not in err_s.lower() and "input_tokens" not in err_s.lower():
            for item in batch:
                meta = {
                    "profile": profile,
                    "thinking": thinking,
                    "case_id": item["case_id"],
                    "error": err_s,
                    "returncode": 1,
                }
                (item["run_dir"] / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
                case_timings.append(
                    {
                        "case_id": item["case_id"],
                        "skipped": False,
                        "returncode": 1,
                        "elapsed_sec": None,
                        "inference_sec": None,
                    }
                )
                print(f"[rc=1] {item['case_id']} batch error: {exc}", flush=True)
            return
        # Context overflow: retry one-by-one (prompt truncation runs in vLLM backend).
        from models.qwen.vllm_backend import vllm_generate_from_chat

        results = []
        for item in batch:
            try:
                text = vllm_generate_from_chat(
                    item["messages"],
                    profile=profile,
                    enable_thinking=thinking,
                )
                results.append({"text": text, "input_tokens": None, "output_tokens": None})
            except Exception as one_exc:
                results.append({"text": "", "error": str(one_exc), "input_tokens": None, "output_tokens": None})

    batch_infer_sec = time.perf_counter() - t_batch
    per_case_infer = batch_infer_sec / max(len(batch), 1)
    for item, res in zip(batch, results, strict=True):
        t_case = time.perf_counter()
        if res.get("error"):
            err_s = str(res["error"])
            meta = {
                "profile": profile,
                "thinking": thinking,
                "case_id": item["case_id"],
                "error": err_s,
                "returncode": 1,
            }
            (item["run_dir"] / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            case_timings.append(
                {
                    "case_id": item["case_id"],
                    "skipped": False,
                    "returncode": 1,
                    "elapsed_sec": None,
                    "inference_sec": None,
                }
            )
            print(f"[rc=1] {item['case_id']} batch error: {err_s}", flush=True)
            continue
        try:
            meta = finalize_triage_inference(
                run_dir=item["run_dir"],
                case_id=item["case_id"],
                messages=item["messages"],
                profile=profile,
                thinking=thinking,
                raw=res["text"],
                inference_sec=per_case_infer,
                task_sec=item["task_sec"],
                started_at=item["started_at"],
                gold=gold,
                few_shot=few_shot,
                few_shot_config=few_shot_config,
                prompt_version=prompt_version,
                input_tokens=res.get("input_tokens"),
                output_tokens=res.get("output_tokens"),
                quiet=True,
            )
            meta["elapsed_sec"] = round(time.perf_counter() - item["t_run_start"], 3)
            (item["run_dir"] / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            rc = 0
        except Exception as exc:
            err_s = f"{type(exc).__name__}: {exc}"
            meta = {
                "profile": profile,
                "thinking": thinking,
                "case_id": item["case_id"],
                "error": err_s,
                "returncode": 1,
            }
            (item["run_dir"] / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            rc = 1
        wall_sec = time.perf_counter() - item["t_run_start"]
        tok = {
            "input_tokens": meta.get("input_tokens"),
            "output_tokens": meta.get("output_tokens"),
            "total_tokens": meta.get("total_tokens"),
        }
        case_timings.append(
            {
                "case_id": item["case_id"],
                "skipped": False,
                "returncode": rc,
                "elapsed_sec": round(float(meta.get("elapsed_sec") or wall_sec), 3),
                "wall_sec": round(wall_sec, 3),
                "inference_sec": meta.get("inference_sec"),
                "task_sec": meta.get("task_sec"),
                **tok,
            }
        )
        tok_s = f" tok={tok['total_tokens']}" if tok.get("total_tokens") else ""
        print(f"[rc={rc}] {item['case_id']} ({float(meta.get('elapsed_sec') or wall_sec):.1f}s){tok_s}")


def _main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True, choices=("llm", "openhands"))
    ap.add_argument("--case-dir", type=Path, default=None)
    ap.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="BenchmarkJava root (default: ../BenchmarkJava if it contains the case file).",
    )
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
    ap.add_argument(
        "--few-shot",
        type=int,
        default=0,
        help="Few-shot exemplars in task body (0 or configured exemplar count).",
    )
    ap.add_argument(
        "--few-shot-config",
        default=None,
        help="Few-shot config name or path (see benchmark/few_shot_configs/manifest.json).",
    )
    ap.add_argument(
        "--prompt-version",
        default=None,
        help="Prompt version key (v7-balanced, v8-dual-gate, v9-fprr-first).",
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
        choices=("FP", "TP", "BL"),
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
    ap.add_argument(
        "--tracks-json",
        type=Path,
        default=None,
        help="JSON list of {gold, case_dir, runs_root} — one vLLM session for all tracks",
    )
    args = ap.parse_args()
    from benchmark.few_shot import validate_few_shot_k

    validate_few_shot_k(args.few_shot, args.few_shot_config)

    from benchmark.phases.phase3.phase3_inference import require_vllm_for_eval

    require_vllm_for_eval(args.profile)

    if args.tracks_json:
        track_specs = _parse_tracks_json(args.tracks_json)
    elif args.case_dir is None:
        raise SystemExit("either --tracks-json or --case-dir is required")
    else:
        track_specs = [
            {
                "gold": (args.gold or "").strip().upper() or None,
                "case_dir": str(args.case_dir),
                "runs_root": str(args.runs_root),
            }
        ]

    if args.profile == "gpt_oss_20b":
        os.environ.setdefault("GPT_OSS_HF_ONLY", "1")
        os.environ.setdefault("GPT_OSS_MAX_SEQ_LEN", "12288")
        os.environ.setdefault("AGENT_MAX_NEW_TOKENS", "2048")

    sast_root = Path(__file__).resolve().parent.parent
    try:
        from dotenv import load_dotenv

        load_dotenv(sast_root / ".env")
    except ImportError:
        pass
    bench = Path(__file__).resolve().parent
    if args.eval_framework:
        print("[batch] warning: --eval-framework is deprecated; using benchmark/make_task.py", flush=True)
    if str(bench) not in sys.path:
        sys.path.insert(0, str(bench))

    in_process_llm = args.agent == "llm" and not args.subprocess_per_case
    use_vllm_batch = in_process_llm and _vllm_batch_enabled(args.profile)
    model_preloaded = False
    n_tracks = len(track_specs)
    if n_tracks > 1:
        print(
            f"[batch] multi-track mode: {n_tracks} tracks, one model load "
            f"(profile={args.profile!r})",
            flush=True,
        )

    for ti, spec in enumerate(track_specs):
        gold = spec["gold"]
        case_dir = Path(spec["case_dir"]).expanduser().resolve()
        runs_root = Path(spec["runs_root"]).expanduser().resolve()
        if ti > 0:
            print(f"[batch] track {ti + 1}/{n_tracks} gold={gold} (reuse loaded model)", flush=True)
        _run_batch_track(
            args,
            sast_root=sast_root,
            bench=bench,
            case_dir=case_dir,
            runs_root=runs_root,
            gold=gold,
            in_process_llm=in_process_llm,
            use_vllm_batch=use_vllm_batch,
            preload_model=not model_preloaded,
        )
        model_preloaded = True


def main() -> None:
    try:
        _main()
    finally:
        from local_model_unload import release_gpu_memory

        release_gpu_memory(verbose=os.environ.get("PHASE1_VERBOSE", "0") == "1")


if __name__ == "__main__":
    main()
