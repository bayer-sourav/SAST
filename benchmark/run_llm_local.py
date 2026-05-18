#!/usr/bin/env python3
"""Vanilla LLM triage using local Qwen (no LiteLLM)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

AGENT_NAME = "llm"


def _require_repo_file(repo_root: Path, case: dict[str, Any]) -> None:
    rel = case.get("file")
    if not rel:
        return
    p = (repo_root / str(rel)).resolve()
    if not p.is_file():
        raise SystemExit(
            f"Source file not found:\n  {p}\n"
            "Pass --repo to the BenchmarkJava root, or clone it as a sibling of this repo "
            "(``../BenchmarkJava`` from ``SAST/``) so it is auto-detected.\n"
            "Clone: https://github.com/OWASP-Benchmark/BenchmarkJava"
        )


def _extract_json_object(text: str) -> dict[str, Any]:
    if not text:
        raise ValueError("Empty response from model")
    t = text.strip()
    if t.startswith("{") and t.endswith("}"):
        return json.loads(t)
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(t[start : end + 1].strip())
    raise ValueError("Could not locate a JSON object in model output")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, type=Path)
    ap.add_argument(
        "--repo",
        default=None,
        help="BenchmarkJava root. If omitted, uses ../BenchmarkJava when it contains the case file.",
    )
    ap.add_argument("--scan-root", default=".")
    ap.add_argument("--profile", default="qwen3_8b_bnb", help="Qwen profile (see models/qwen/runner.py).")
    ap.add_argument("--run-dir", default=None, type=Path)
    ap.add_argument(
        "--eval-framework",
        type=Path,
        default=None,
        help="Folder containing make_task.py (default: ../SAST-Paper-Artifacts/Evaluation Framework)",
    )
    args = ap.parse_args()

    sast_root = Path(__file__).resolve().parent.parent
    eval_fw = args.eval_framework
    if eval_fw is None:
        eval_fw = sast_root.parent / "SAST-Paper-Artifacts" / "Evaluation Framework"
    eval_fw = eval_fw.expanduser().resolve()
    make_task = eval_fw / "make_task.py"
    if not make_task.is_file():
        raise SystemExit(f"make_task.py not found under {eval_fw}")

    case_path = args.case.expanduser().resolve()
    case = json.loads(case_path.read_text(encoding="utf-8"))
    _bench = Path(__file__).resolve().parent
    if str(_bench) not in sys.path:
        sys.path.insert(0, str(_bench))
    import repo_root as _repo  # noqa: E402

    sys.path.insert(0, str(eval_fw))
    from make_task import stable_case_id  # type: ignore[import-not-found]

    case_id = stable_case_id(case)
    effective_scan_root = case.get("scan_root") or args.scan_root
    repo_root = _repo.resolve_benchmark_java_root(sast_root, case, args.repo)
    _require_repo_file(repo_root, case)

    model_dir = args.profile.replace("/", "_")
    run_dir = (
        args.run_dir.expanduser().resolve()
        if args.run_dir
        else (Path.cwd() / "runs" / model_dir / AGENT_NAME / case_id)
    )
    run_dir.mkdir(parents=True, exist_ok=True)

    task_path = run_dir / "task.md"
    subprocess.run(
        [
            sys.executable,
            str(make_task),
            "--case",
            str(case_path),
            "--repo",
            str(repo_root),
            "--scan-root",
            effective_scan_root,
            "--agent",
            AGENT_NAME,
            "--out",
            str(task_path),
        ],
        check=True,
    )

    task_text = task_path.read_text(encoding="utf-8")
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are a security-oriented code reviewer performing SAST triage. "
                "Return only a single JSON object that follows the schema in the prompt."
            ),
        },
        {"role": "user", "content": task_text},
    ]

    if str(sast_root) not in sys.path:
        sys.path.insert(0, str(sast_root))
    from models.qwen.runner import generate_from_chat_messages

    raw = generate_from_chat_messages(messages, profile=args.profile, use_4bit=True, tools=None)
    (run_dir / "llm_raw.txt").write_text(raw or "", encoding="utf-8")

    result = _extract_json_object(raw)
    result.setdefault("agent", AGENT_NAME)
    result.setdefault("case_id", case_id)

    out_path = run_dir / f"agent-{AGENT_NAME}-triage-result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[{AGENT_NAME}] Wrote: {out_path}")


if __name__ == "__main__":
    main()
