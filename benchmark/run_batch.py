#!/usr/bin/env python3
"""Batch ``llm`` or ``openhands`` only; skips existing run dirs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _case_id(eval_fw: Path, case_path: Path) -> str:
    sys.path.insert(0, str(eval_fw))
    from make_task import stable_case_id  # type: ignore[import-not-found]

    case = json.loads(case_path.read_text(encoding="utf-8"))
    return stable_case_id(case)


def _safe_model_dir(model: str) -> str:
    sanitized = model.replace("/", "_")
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in sanitized)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", required=True, choices=("llm", "openhands"))
    ap.add_argument("--case-dir", type=Path, required=True)
    ap.add_argument("--repo", type=Path, default=None, help="BenchmarkJava root (default: ../BenchmarkJava if it contains the case file).")
    ap.add_argument("--profile", default="qwen3_8b_bnb", help="Qwen profile for --agent llm")
    ap.add_argument("--llm-model", default="local-qwen", help="LLM_MODEL for --agent openhands")
    ap.add_argument("--llm-provider", default="openai")
    ap.add_argument("--max-cases", type=int, default=None)
    ap.add_argument(
        "--eval-framework",
        type=Path,
        default=None,
    )
    args = ap.parse_args()

    sast_root = Path(__file__).resolve().parent.parent
    bench = Path(__file__).resolve().parent
    eval_fw = args.eval_framework or (sast_root.parent / "SAST_paper_artifacts" / "Evaluation Framework")
    eval_fw = eval_fw.expanduser().resolve()
    if str(bench) not in sys.path:
        sys.path.insert(0, str(bench))
    import repo_root as _repo  # noqa: E402

    case_dir = args.case_dir.expanduser().resolve()
    files = sorted(case_dir.glob("*.json"))
    if args.max_cases is not None:
        files = files[: args.max_cases]

    script_llm = bench / "run_llm_local.py"
    script_oh = bench / "run_openhands.py"

    for case_path in files:
        cid = _case_id(eval_fw, case_path)
        model_key = args.profile if args.agent == "llm" else args.llm_model
        run_dir = Path.cwd() / "runs" / _safe_model_dir(model_key) / args.agent / cid
        if run_dir.exists():
            print(f"[skip] {cid}")
            continue

        case = json.loads(case_path.read_text(encoding="utf-8"))
        repo = _repo.resolve_benchmark_java_root(sast_root, case, args.repo)

        if args.agent == "llm":
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
        print(f"[rc={r.returncode}] {cid}")


if __name__ == "__main__":
    main()
