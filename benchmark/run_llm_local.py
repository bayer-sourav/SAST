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

_JSON_RULES = """Output requirements (strict):
- After any internal reasoning, output EXACTLY ONE JSON object matching the schema in the user message.
- Do NOT duplicate the JSON. Do NOT put JSON inside  or <think> blocks.
- No markdown code fences. No prose before or after the final JSON object.
- Set "agent" to "llm" and "case_id" exactly as given in the task.
- Use valid JSON only: double-quoted keys/strings; escape inner quotes with backslash.
"""

_PROMPTS: dict[str, tuple[str, str]] = {
    "FP": (
        "You are a security-oriented code reviewer performing SAST false-positive triage.\n"
        + _JSON_RULES
        + "\nTriage policy:\n"
        "- Label FP when the alert does NOT reflect a real vulnerability (sanitized input, dead code, wrong sink, benign API use).\n"
        "- Label TP only if you can cite a concrete exploitable path in the shown code.\n"
        "- Use UNKNOWN only if the snippet is insufficient; prefer FP or TP when the code is clear.\n",
        "\n---\nFINAL OUTPUT: One JSON object only. "
        'Prefer label "FP" when the CodeQL finding is a false alarm on this code.\n',
    ),
    "TP": (
        "You are a security-oriented code reviewer performing SAST true-positive retention triage.\n"
        + _JSON_RULES
        + "\nTriage policy:\n"
        "- These cases are from a known true-vulnerability benchmark: the alert usually reflects a real issue.\n"
        "- Label TP when user-controlled or unsafe data can reach a dangerous sink (XSS, injection, path traversal, etc.).\n"
        "- Label FP only with strong code proof (effective encoding, hardcoded safe values, unreachable path).\n"
        "- Do not dismiss alerts merely because a helper exists; verify it is applied on the reported path.\n",
        "\n---\nFINAL OUTPUT: One JSON object only. "
        'Prefer label "TP" when the finding matches an exploitable pattern in the shown code.\n',
    ),
}


def _prompts_for_gold(gold: str | None) -> tuple[str, str]:
    key = (gold or "FP").strip().upper()
    if key not in _PROMPTS:
        key = "FP"
    return _PROMPTS[key]


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
    from core.parsing import extract_triage_result

    return extract_triage_result(text)


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
    ap.add_argument(
        "--gold",
        choices=("FP", "TP"),
        default=None,
        help="Corpus gold label: tunes triage policy (FP=false-positive filter, TP=retention).",
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
    system_text, user_suffix = _prompts_for_gold(args.gold)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": task_text + user_suffix},
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
