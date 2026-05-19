#!/usr/bin/env python3
"""Batch ``llm`` or ``openhands`` only; skips existing run dirs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
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
    args = ap.parse_args()

    sast_root = Path(__file__).resolve().parent.parent
    bench = Path(__file__).resolve().parent
    eval_fw = args.eval_framework or (sast_root.parent / "SAST-Paper-Artifacts" / "Evaluation Framework")
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
        runs_root = args.runs_root.expanduser().resolve()
        run_dir = runs_root / _safe_model_dir(model_key) / args.agent / cid
        result_path = run_dir / "agent-llm-triage-result.json"
        lbl: str | None = None
        if result_path.is_file():
            try:
                data = json.loads(result_path.read_text(encoding="utf-8"))
                lbl = str(data.get("label", "")).strip().upper()
            except Exception:
                lbl = None

        if run_dir.exists() and not args.force:
            if args.retry_wrong and args.gold:
                gold_u = args.gold.strip().upper()
                if lbl in VALID_LABELS and lbl == gold_u:
                    print(f"[skip] {cid} (correct {lbl})")
                    continue
            elif not args.retry_missing:
                print(f"[skip] {cid}")
                continue
            elif lbl in VALID_LABELS and not args.retry_wrong:
                print(f"[skip] {cid} (valid result)")
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
            if args.gold:
                cmd.extend(["--gold", args.gold])
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
