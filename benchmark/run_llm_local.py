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
    + "\nFollow the triage policy in the user message exactly: assess every CodeQL alert, "
    "then assign one case-level label.\n"
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


def prepare_triage_messages(
    *,
    case_path: Path,
    run_dir: Path,
    sast_root: Path,
    few_shot: int = 0,
    few_shot_config: str | Path | None = None,
    prompt_version: str | None = None,
    repo: Path | None = None,
    scan_root: str = ".",
) -> tuple[str, list[dict[str, str]], float]:
    """Build task.md + chat messages; returns (case_id, messages, task_sec)."""
    bench = Path(__file__).resolve().parent
    make_task = bench / "make_task.py"
    case_path = case_path.expanduser().resolve()
    case = json.loads(case_path.read_text(encoding="utf-8"))
    import repo_root as _repo  # noqa: E402
    from benchmark.make_task import stable_case_id  # noqa: E402
    from benchmark.triage_labels import task_markdown_current, task_prompt_tag  # noqa: E402
    from benchmark.few_shot import layout_tag_from_config  # noqa: E402

    case_id = stable_case_id(case)
    layout_version = layout_tag_from_config(few_shot_config) if few_shot > 0 else None
    effective_scan_root = case.get("scan_root") or scan_root
    repo_root = _repo.resolve_benchmark_java_root(sast_root, case, repo, case_path=case_path)
    _require_repo_file(repo_root, case)

    run_dir = run_dir.expanduser().resolve()
    run_dir.mkdir(parents=True, exist_ok=True)

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
    if few_shot_config is not None:
        task_cmd.extend(["--few-shot-config", str(few_shot_config)])
    if prompt_version is not None:
        task_cmd.extend(["--prompt-version", str(prompt_version)])
    if task_markdown_current(
        task_path,
        few_shot=few_shot,
        layout_version=layout_version,
        prompt_version=prompt_version,
    ):
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
        "few_shot_config": str(few_shot_config) if few_shot_config else None,
        "prompt_version": prompt_version,
        "task_prompt_tag": task_prompt_tag(
            few_shot=few_shot,
            layout_version=layout_version,
            prompt_version=prompt_version,
        ),
        "messages": messages,
    }
    (run_dir / "prompt_record.json").write_text(
        json.dumps(prompt_record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return case_id, messages, task_sec


def finalize_triage_inference(
    *,
    run_dir: Path,
    case_id: str,
    messages: list[dict[str, str]],
    profile: str,
    thinking: bool,
    raw: str,
    inference_sec: float,
    task_sec: float,
    started_at: str,
    gold: str | None,
    few_shot: int,
    few_shot_config: str | Path | None,
    prompt_version: str | None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    """Parse JSON, optional retry, write artifacts; return run_meta."""
    from core.gen_meta import reset_gen_meta
    from benchmark.llm_generate import infer_triage

    sast_root = Path(__file__).resolve().parent.parent
    _ensure_paths(sast_root)

    def _json_retry(
        msgs: list[dict[str, str]],
        *,
        max_new: str,
        thinking_on: bool | None = None,
    ) -> str:
        max_new_i = int(max_new)
        use_thinking = thinking if thinking_on is None else thinking_on
        reset_gen_meta()
        from models.qwen.vllm_backend import should_use_vllm

        if should_use_vllm(profile):
            print(
                f"[llm] JSON retry via vLLM max_new_tokens={max_new} thinking={use_thinking}",
                flush=True,
            )
            return infer_triage(
                msgs,
                profile,
                thinking=use_thinking,
                use_4bit=True,
                max_new=max_new_i,
            )
        prev = os.environ.get("AGENT_MAX_NEW_TOKENS")
        os.environ["AGENT_MAX_NEW_TOKENS"] = max_new
        print(
            f"[llm] JSON retry max_new_tokens={max_new} thinking={use_thinking}",
            flush=True,
        )
        try:
            return infer_triage(msgs, profile, thinking=use_thinking, use_4bit=True)
        finally:
            if prev is not None:
                os.environ["AGENT_MAX_NEW_TOKENS"] = prev
            else:
                os.environ.pop("AGENT_MAX_NEW_TOKENS", None)

    (run_dir / "llm_raw.txt").write_text(raw or "", encoding="utf-8")
    json_retry_prompt = (
        "Your previous reply did not include valid triage JSON. "
        "Reply with EXACTLY ONE JSON object and no other text. "
        'Required keys: "label" (TP|FP|BL|UNKNOWN), "confidence", '
        '"confidence_score", "reason", "evidence", "agent", "case_id".'
    )
    json_retry_max = os.environ.get("AGENT_JSON_RETRY_MAX_NEW", "1024")
    json_retry_strict_max = os.environ.get("AGENT_JSON_RETRY_STRICT_MAX", "768")
    json_retry_compact_max = os.environ.get("AGENT_JSON_RETRY_COMPACT_MAX", "512")

    def _compact_json_retry_msgs() -> list[dict[str, str]] | None:
        from benchmark.compact_triage_prompt import compact_messages_from_task_path

        task_path = run_dir / "task.md"
        if not task_path.is_file():
            return None
        _, msgs = compact_messages_from_task_path(task_path, case_id=case_id)
        return msgs

    def _strict_json_retry_msgs() -> list[dict[str, str]]:
        task_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        return [
            {
                "role": "system",
                "content": _SYSTEM_PROMPT
                + "\nCRITICAL: Your entire response must be one JSON object starting with { and ending with }. "
                "No markdown. No headings. No analysis before or after the JSON.",
            },
            {
                "role": "user",
                "content": task_user + "\n\n" + json_retry_prompt,
            },
        ]

    try:
        result = _normalize_label(_extract_json_object(raw))
    except ValueError as parse_exc:
        json_msgs = list(messages) + [{"role": "user", "content": json_retry_prompt}]
        t_retry = time.perf_counter()
        raw_retry = _json_retry(json_msgs, max_new=json_retry_max)
        inference_sec += time.perf_counter() - t_retry
        combined = (raw or "").rstrip() + "\n\n--- json_retry ---\n\n" + raw_retry
        (run_dir / "llm_raw.txt").write_text(combined, encoding="utf-8")
        from core.gen_meta import get_gen_meta

        gen = get_gen_meta()
        if int(gen.get("input_tokens") or -1) >= 0:
            input_tokens = (input_tokens or 0) + int(gen["input_tokens"])
        if int(gen.get("output_tokens") or -1) >= 0:
            output_tokens = (output_tokens or 0) + int(gen["output_tokens"])
        try:
            result = _normalize_label(_extract_json_object(raw_retry))
        except ValueError:
            json_msgs_off = list(messages) + [
                {
                    "role": "user",
                    "content": json_retry_prompt
                    + " Do not use chain-of-thought. Reply with JSON only.",
                }
            ]
            t_retry2 = time.perf_counter()
            raw_retry2 = _json_retry(json_msgs_off, max_new=json_retry_strict_max, thinking_on=False)
            inference_sec += time.perf_counter() - t_retry2
            combined += "\n\n--- json_retry_thinking_off ---\n\n" + raw_retry2
            (run_dir / "llm_raw.txt").write_text(combined, encoding="utf-8")
            from core.gen_meta import get_gen_meta

            gen = get_gen_meta()
            if int(gen.get("input_tokens") or -1) >= 0:
                input_tokens = (input_tokens or 0) + int(gen["input_tokens"])
            if int(gen.get("output_tokens") or -1) >= 0:
                output_tokens = (output_tokens or 0) + int(gen["output_tokens"])
            try:
                result = _normalize_label(_extract_json_object(raw_retry2))
            except ValueError:
                t_retry3 = time.perf_counter()
                raw_retry3 = _json_retry(
                    _strict_json_retry_msgs(),
                    max_new=json_retry_strict_max,
                    thinking_on=False,
                )
                inference_sec += time.perf_counter() - t_retry3
                combined += "\n\n--- json_retry_strict ---\n\n" + raw_retry3
                (run_dir / "llm_raw.txt").write_text(combined, encoding="utf-8")
                from core.gen_meta import get_gen_meta

                gen = get_gen_meta()
                if int(gen.get("input_tokens") or -1) >= 0:
                    input_tokens = (input_tokens or 0) + int(gen["input_tokens"])
                if int(gen.get("output_tokens") or -1) >= 0:
                    output_tokens = (output_tokens or 0) + int(gen["output_tokens"])
                try:
                    result = _normalize_label(_extract_json_object(raw_retry3))
                except ValueError:
                    compact_msgs = _compact_json_retry_msgs()
                    if compact_msgs is None:
                        raise parse_exc from None
                    t_retry4 = time.perf_counter()
                    raw_retry4 = _json_retry(
                        compact_msgs,
                        max_new=json_retry_compact_max,
                        thinking_on=False,
                    )
                    inference_sec += time.perf_counter() - t_retry4
                    combined += "\n\n--- json_retry_compact ---\n\n" + raw_retry4
                    (run_dir / "llm_raw.txt").write_text(combined, encoding="utf-8")
                    from core.gen_meta import get_gen_meta

                    gen = get_gen_meta()
                    if int(gen.get("input_tokens") or -1) >= 0:
                        input_tokens = (input_tokens or 0) + int(gen["input_tokens"])
                    if int(gen.get("output_tokens") or -1) >= 0:
                        output_tokens = (output_tokens or 0) + int(gen["output_tokens"])
                    try:
                        result = _normalize_label(_extract_json_object(raw_retry4))
                    except ValueError:
                        raise parse_exc from None

    result["agent"] = AGENT_NAME
    result["case_id"] = case_id
    out_path = run_dir / f"agent-{AGENT_NAME}-triage-result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    from timing import utc_now_iso  # noqa: E402

    inp_tok = input_tokens if input_tokens is not None else -1
    out_tok = output_tokens if output_tokens is not None else -1
    meta = {
        "profile": profile,
        "thinking": thinking,
        "few_shot": few_shot,
        "few_shot_config": str(few_shot_config) if few_shot_config else None,
        "prompt_version": prompt_version,
        "gold": gold,
        "case_id": case_id,
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "elapsed_sec": round(inference_sec + task_sec, 3),
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


def run_compact_triage_retry(
    *,
    run_dir: Path,
    case_id: str,
    profile: str,
    gold: str | None = None,
    few_shot: int = 0,
    few_shot_config: str | Path | None = None,
    prompt_version: str | None = None,
    quiet: bool = False,
) -> dict[str, Any]:
    """JSON-only retry using a compact prompt built from existing task.md."""
    from benchmark.compact_triage_prompt import compact_messages_from_task_path
    from benchmark.llm_generate import infer_triage
    from core.gen_meta import get_gen_meta, reset_gen_meta
    from timing import utc_now_iso

    sast_root = Path(__file__).resolve().parent.parent
    _ensure_paths(sast_root)
    run_dir = run_dir.expanduser().resolve()
    task_path = run_dir / "task.md"
    if not task_path.is_file():
        raise FileNotFoundError(f"task.md missing in {run_dir}")

    started_at = utc_now_iso()
    t_start = time.perf_counter()
    task_path = run_dir / "task.md"
    _, messages = compact_messages_from_task_path(task_path, case_id=case_id)
    compact_max = int(os.environ.get("AGENT_JSON_RETRY_COMPACT_MAX", "512"))
    compact_max2 = int(os.environ.get("AGENT_JSON_RETRY_COMPACT_MAX2", "1024"))
    raw_path = run_dir / "llm_raw.txt"
    prior_raw = raw_path.read_text(encoding="utf-8").rstrip() if raw_path.is_file() else ""

    def _infer_compact(msgs: list[dict[str, str]], max_new: int) -> str:
        reset_gen_meta()
        return infer_triage(
            msgs,
            profile,
            thinking=False,
            use_4bit=True,
            max_new=max_new,
        )

    inference_sec = 0.0
    input_tokens: int | None = None
    output_tokens: int | None = None
    raw = ""
    parse_exc: ValueError | None = None
    combined = prior_raw
    attempts: list[tuple[str, list[dict[str, str]], int]] = [
        ("json_retry_compact", messages, compact_max),
        ("json_retry_compact2", messages, compact_max2),
    ]
    _, alerts_only_msgs = compact_messages_from_task_path(
        task_path, case_id=case_id, alerts_only=True
    )
    attempts.append(("json_retry_compact_ultra", alerts_only_msgs, 384))

    result: dict[str, Any] | None = None
    for marker, msgs, max_new in attempts:
        t0 = time.perf_counter()
        raw = _infer_compact(msgs, max_new)
        inference_sec += time.perf_counter() - t0
        gen = get_gen_meta()
        if int(gen.get("input_tokens") or -1) >= 0:
            input_tokens = (input_tokens or 0) + int(gen["input_tokens"])
        if int(gen.get("output_tokens") or -1) >= 0:
            output_tokens = (output_tokens or 0) + int(gen["output_tokens"])
        combined = combined + f"\n\n--- {marker} ---\n\n" + (raw or "")
        raw_path.write_text(combined, encoding="utf-8")
        try:
            result = _normalize_label(_extract_json_object(raw))
            parse_exc = None
            break
        except ValueError as exc:
            parse_exc = exc
            try:
                result = _normalize_label(_extract_json_object(combined))
                parse_exc = None
                break
            except ValueError:
                pass

    if result is None:
        err_s = f"ValueError: {parse_exc}"
        meta = {
            "profile": profile,
            "thinking": False,
            "few_shot": few_shot,
            "few_shot_config": str(few_shot_config) if few_shot_config else None,
            "prompt_version": prompt_version,
            "gold": gold,
            "case_id": case_id,
            "started_at": started_at,
            "finished_at": utc_now_iso(),
            "elapsed_sec": round(time.perf_counter() - t_start, 3),
            "inference_sec": round(inference_sec, 3),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "compact_retry": True,
            "error": err_s,
            "returncode": 1,
        }
        (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        if not quiet:
            print(f"[compact-retry] failed {case_id}: {parse_exc}", file=sys.stderr)
        return meta

    result["agent"] = AGENT_NAME
    result["case_id"] = case_id
    out_path = run_dir / f"agent-{AGENT_NAME}-triage-result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = {
        "profile": profile,
        "thinking": False,
        "few_shot": few_shot,
        "few_shot_config": str(few_shot_config) if few_shot_config else None,
        "prompt_version": prompt_version,
        "gold": gold,
        "case_id": case_id,
        "started_at": started_at,
        "finished_at": utc_now_iso(),
        "elapsed_sec": round(time.perf_counter() - t_start, 3),
        "inference_sec": round(inference_sec, 3),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": (input_tokens + output_tokens)
        if input_tokens is not None and output_tokens is not None
        else None,
        "compact_retry": True,
        "returncode": 0,
    }
    (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if not quiet:
        print(f"[compact-retry] ok {case_id} label={result.get('label')}", flush=True)
    return meta


def run_triage_case(
    *,
    case_path: Path,
    profile: str,
    run_dir: Path,
    sast_root: Path,
    gold: str | None = None,
    thinking: bool = False,
    few_shot: int = 0,
    few_shot_config: str | Path | None = None,
    prompt_version: str | None = None,
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
    from core.generation_defaults import apply_triage_run_token_limits  # noqa: E402
    from timing import utc_now_iso  # noqa: E402

    apply_triage_run_token_limits(thinking=thinking)

    started_at = utc_now_iso()
    case_path = case_path.expanduser().resolve()
    case = json.loads(case_path.read_text(encoding="utf-8"))
    from benchmark.make_task import stable_case_id  # noqa: E402

    case_id = stable_case_id(case)

    try:
        case_id, messages, task_sec = prepare_triage_messages(
            case_path=case_path,
            run_dir=run_dir,
            sast_root=sast_root,
            few_shot=few_shot,
            few_shot_config=few_shot_config,
            prompt_version=prompt_version,
            repo=repo,
            scan_root=scan_root,
        )
        _ensure_paths(sast_root)
        from core.gen_meta import get_gen_meta, reset_gen_meta
        from benchmark.llm_generate import infer_triage

        reset_gen_meta()
        t_infer_start = time.perf_counter()
        raw = infer_triage(messages, profile, thinking=thinking, use_4bit=True)
        if profile == "gpt_oss_20b":
            t = (raw or "").strip()
            head = t[:600]
            degenerate = len(t) >= 80 and (
                head.count("!") > len(head) * 0.4
                or len({c for c in head if not c.isspace()}) <= 3
            )
            if degenerate:
                prev = os.environ.get("AGENT_MAX_NEW_TOKENS")
                os.environ["AGENT_MAX_NEW_TOKENS"] = "1024"
                reset_gen_meta()
                raw = infer_triage(messages, profile, thinking=thinking, use_4bit=True)
                if prev is not None:
                    os.environ["AGENT_MAX_NEW_TOKENS"] = prev
                else:
                    os.environ.pop("AGENT_MAX_NEW_TOKENS", None)
        inference_sec = time.perf_counter() - t_infer_start
        gen = get_gen_meta()
        meta = finalize_triage_inference(
            run_dir=run_dir,
            case_id=case_id,
            messages=messages,
            profile=profile,
            thinking=thinking,
            raw=raw,
            inference_sec=inference_sec,
            task_sec=task_sec,
            started_at=started_at,
            gold=gold,
            few_shot=few_shot,
            few_shot_config=few_shot_config,
            prompt_version=prompt_version,
            input_tokens=int(gen["input_tokens"]) if int(gen.get("input_tokens") or -1) >= 0 else None,
            output_tokens=int(gen["output_tokens"]) if int(gen.get("output_tokens") or -1) >= 0 else None,
            quiet=quiet,
        )
        meta["elapsed_sec"] = round(time.perf_counter() - t_run_start, 3)
        (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta
    except Exception as exc:
        elapsed_sec = time.perf_counter() - t_run_start
        err_s = f"{type(exc).__name__}: {exc}"
        meta = {
            "profile": profile,
            "thinking": thinking,
            "few_shot": few_shot,
            "few_shot_config": str(few_shot_config) if few_shot_config else None,
            "prompt_version": prompt_version,
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
        help="Number of few-shot exemplars in task body (0 or configured exemplar count).",
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
    args = ap.parse_args()
    from benchmark.few_shot import validate_few_shot_k

    validate_few_shot_k(args.few_shot, args.few_shot_config)

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
        few_shot_config=args.few_shot_config,
        prompt_version=args.prompt_version,
        repo=args.repo,
        scan_root=args.scan_root,
        quiet=False,
    )
    raise SystemExit(int(meta.get("returncode", 1)))


if __name__ == "__main__":
    main()
