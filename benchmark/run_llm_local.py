#!/usr/bin/env python3
"""Vanilla LLM triage using local Unsloth/HF models (Qwen, Gemma, GPT-OSS)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

AGENT_NAME = "llm"
VALID_LABELS = frozenset({"TP", "FP", "BL", "UNKNOWN"})

# Minimal system message; full triage policy lives in task.md (benchmark/make_task.py).
_JSON_RULES = """Output requirements (strict):
- After any internal reasoning, output EXACTLY ONE JSON object matching the schema in the user message.
- Do NOT duplicate the JSON. Do NOT put JSON inside redacted_thinking blocks.
- No markdown code fences. No prose before or after the final JSON object.
- Set "agent" to "llm" and "case_id" exactly as given in the task.
- "label" must be one of: TP, FP, BL, UNKNOWN.
- Use valid JSON only: double-quoted keys/strings; escape inner quotes with backslash.
"""

_SYSTEM_PROMPT = (
    "You are a security-oriented SAST triage assistant.\n"
    + _JSON_RULES
    + "\nFollow the triage policy and label definitions in the user message exactly.\n"
)


def _require_repo_file(repo_root: Path, case: dict[str, Any]) -> None:
    rel = case.get("file")
    if not rel:
        return
    p = (repo_root / str(rel)).resolve()
    if not p.is_file():
        raise FileNotFoundError(
            f"Source file not found:\n  {p}\n"
            "Pass --repo to the BenchmarkJava root, or clone it as a sibling of this repo "
            "(``../BenchmarkJava`` from ``SAST/``) so it is auto-detected.\n"
            "Clone: https://github.com/OWASP-Benchmark/BenchmarkJava"
        )


def _extract_json_object(text: str) -> dict[str, Any]:
    from core.parsing import extract_triage_result

    return extract_triage_result(text)


def _normalize_label(result: dict[str, Any]) -> dict[str, Any]:
    lbl = str(result.get("label", "")).strip().upper()
    if lbl not in VALID_LABELS:
        raise ValueError(f"Invalid triage label: {lbl!r}")
    out = dict(result)
    out["label"] = lbl
    return out


def _ensure_paths(sast_root: Path) -> None:
    if str(sast_root) not in sys.path:
        sys.path.insert(0, str(sast_root))


def _system_prompt() -> str:
    """JSON/output rules only; few-shot exemplars live in task.md (see make_task --few-shot)."""
    return _SYSTEM_PROMPT


def run_triage_case(
    *,
    case_path: Path,
    profile: str,
    run_dir: Path,
    sast_root: Path,
    gold: str | None = None,
    thinking: bool = False,
    few_shot: int = 0,
    repo: Path | None = None,
    scan_root: str = ".",
    quiet: bool = False,
) -> dict[str, Any]:
    """
    Run one triage case in-process (model stays loaded across calls in the same process).

    ``gold`` is recorded in run_meta for the corpus track (FP/TP/BL); it does not change the prompt.
    """
    t_run_start = time.perf_counter()
    bench = Path(__file__).resolve().parent
    if str(bench.parent) not in sys.path:
        sys.path.insert(0, str(bench.parent))
    from timing import utc_now_iso  # noqa: E402

    started_at = utc_now_iso()
    make_task = bench / "make_task.py"
    if not make_task.is_file():
        raise FileNotFoundError(f"make_task.py not found: {make_task}")

    case_path = case_path.expanduser().resolve()
    case = json.loads(case_path.read_text(encoding="utf-8"))
    import repo_root as _repo  # noqa: E402
    from benchmark.make_task import stable_case_id  # noqa: E402
    from benchmark.triage_labels import task_markdown_current, task_prompt_tag  # noqa: E402

    case_id = stable_case_id(case)
    effective_scan_root = case.get("scan_root") or scan_root
    repo_root = _repo.resolve_benchmark_java_root(sast_root, case, repo, case_path=case_path)
    _require_repo_file(repo_root, case)

    run_dir = run_dir.expanduser().resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        task_path = run_dir / "task.md"
        t_task_start = time.perf_counter()
        task_cmd = [
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
            "--few-shot",
            str(few_shot),
        ]
        if task_markdown_current(task_path, few_shot=few_shot):
            task_sec = 0.0
        else:
            last_err: str | None = None
            for attempt in range(3):
                proc = subprocess.run(task_cmd, capture_output=True, text=True)
                if proc.returncode == 0 and task_path.is_file():
                    break
                last_err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
                if attempt < 2:
                    time.sleep(1.0 * (attempt + 1))
            else:
                raise RuntimeError(
                    f"make_task.py failed after 3 attempts (last rc={proc.returncode}): {last_err}"
                )
            task_sec = time.perf_counter() - t_task_start

        task_text = task_path.read_text(encoding="utf-8")
        system_text = _system_prompt()
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": task_text},
        ]
        (run_dir / "system_prompt.txt").write_text(system_text, encoding="utf-8")
        prompt_record = {
            "few_shot": few_shot,
            "task_prompt_tag": task_prompt_tag(few_shot=few_shot),
            "messages": messages,
        }
        (run_dir / "prompt_record.json").write_text(
            json.dumps(prompt_record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        _ensure_paths(sast_root)
        from core.gen_meta import get_gen_meta, reset_gen_meta
        from benchmark.llm_generate import generate_triage

        reset_gen_meta()
        t_infer_start = time.perf_counter()

        def _degenerate(text: str) -> bool:
            t = (text or "").strip()
            if len(t) < 80:
                return False
            head = t[:600]
            if head.count("!") > len(head) * 0.4:
                return True
            chars = {c for c in head if not c.isspace()}
            return len(chars) <= 3

        def _gpt_json_retry(msgs: list[dict[str, str]], *, max_new: str) -> str:
            prev = os.environ.get("AGENT_MAX_NEW_TOKENS")
            os.environ["AGENT_MAX_NEW_TOKENS"] = max_new
            print(f"[llm] gpt_oss_20b JSON retry max_new_tokens={max_new}", flush=True)
            reset_gen_meta()
            out = generate_triage(msgs, profile, thinking=thinking, use_4bit=True)
            if prev is not None:
                os.environ["AGENT_MAX_NEW_TOKENS"] = prev
            else:
                os.environ.pop("AGENT_MAX_NEW_TOKENS", None)
            return out

        raw = generate_triage(messages, profile, thinking=thinking, use_4bit=True)
        if _degenerate(raw) and profile == "gpt_oss_20b":
            raw = _gpt_json_retry(messages, max_new="1024")
        inference_sec = time.perf_counter() - t_infer_start
        (run_dir / "llm_raw.txt").write_text(raw or "", encoding="utf-8")

        try:
            result = _normalize_label(_extract_json_object(raw))
        except ValueError as parse_exc:
            if profile != "gpt_oss_20b":
                raise
            json_msgs = list(messages) + [
                {
                    "role": "user",
                    "content": (
                        "Your previous reply did not include valid triage JSON. "
                        "Reply with EXACTLY ONE JSON object and no other text. "
                        'Required keys: "label" (TP|FP|BL|UNKNOWN), "confidence", '
                        '"confidence_score", "reason", "evidence", "agent", "case_id".'
                    ),
                }
            ]
            raw_retry = _gpt_json_retry(json_msgs, max_new="768")
            inference_sec = time.perf_counter() - t_infer_start
            combined = (raw or "").rstrip() + "\n\n--- json_retry ---\n\n" + raw_retry
            (run_dir / "llm_raw.txt").write_text(combined, encoding="utf-8")
            result = _normalize_label(_extract_json_object(raw_retry))

        result["agent"] = AGENT_NAME
        result["case_id"] = case_id
        out_path = run_dir / f"agent-{AGENT_NAME}-triage-result.json"
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

        elapsed_sec = time.perf_counter() - t_run_start
        gen = get_gen_meta()
        inp_tok = int(gen.get("input_tokens") or -1)
        out_tok = int(gen.get("output_tokens") or -1)
        meta = {
            "profile": profile,
            "thinking": thinking,
            "few_shot": few_shot,
            "gold": gold,
            "case_id": case_id,
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "elapsed_sec": round(elapsed_sec, 3),
            "task_sec": round(task_sec, 3),
            "inference_sec": round(inference_sec, 3),
            "input_tokens": inp_tok if inp_tok >= 0 else None,
            "output_tokens": out_tok if out_tok >= 0 else None,
            "total_tokens": (inp_tok + out_tok) if inp_tok >= 0 and out_tok >= 0 else None,
            "returncode": 0,
        }
        (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        if not quiet:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            print(f"\n[{AGENT_NAME}] Wrote: {out_path}")
        return meta
    except Exception as exc:
        elapsed_sec = time.perf_counter() - t_run_start
        err_s = f"{type(exc).__name__}: {exc}"
        meta = {
            "profile": profile,
            "thinking": thinking,
            "few_shot": few_shot,
            "gold": gold,
            "case_id": case_id,
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "elapsed_sec": round(elapsed_sec, 3),
            "error": err_s,
            "returncode": 1,
        }
        (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        if not quiet:
            print(f"[error] {case_id}: {exc}", file=sys.stderr)
        if any(
            x in err_s.lower()
            for x in ("cuda", "acceleratorerror", "device-side assert", "out of memory")
        ):
            try:
                from local_model_unload import release_gpu_memory

                release_gpu_memory()
            except Exception:
                pass
        return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, type=Path)
    ap.add_argument("--repo", default=None)
    ap.add_argument("--scan-root", default=".")
    ap.add_argument("--profile", default="qwen3_8b_bnb")
    ap.add_argument("--run-dir", default=None, type=Path)
    ap.add_argument(
        "--gold",
        choices=("FP", "TP", "BL"),
        default=None,
        help="Corpus track for run_meta only (prompt is unified).",
    )
    ap.add_argument("--thinking", action="store_true")
    ap.add_argument(
        "--few-shot",
        type=int,
        default=0,
        choices=(0, 3),
        help="Number of few-shot exemplars in system prompt (0 or 3).",
    )
    args = ap.parse_args()

    sast_root = Path(__file__).resolve().parent.parent
    case_path = args.case.expanduser().resolve()
    case = json.loads(case_path.read_text(encoding="utf-8"))
    from benchmark.make_task import stable_case_id  # noqa: E402

    case_id = stable_case_id(case)
    run_dir = args.run_dir or Path(f"runs/llm/{args.profile}/{case_id}")
    meta = run_triage_case(
        case_path=case_path,
        profile=args.profile,
        run_dir=run_dir,
        sast_root=sast_root,
        gold=args.gold,
        thinking=args.thinking,
        few_shot=args.few_shot,
        repo=args.repo,
        scan_root=args.scan_root,
        quiet=False,
    )
    raise SystemExit(int(meta.get("returncode", 1)))


if __name__ == "__main__":
    main()
