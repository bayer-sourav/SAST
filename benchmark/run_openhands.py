#!/usr/bin/env python3
"""OpenHands triage runner; same behavior as paper ``run_openhands.py`` with configurable ``make_task`` dir."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

AGENT_NAME = "openhands"


def _require_repo_file(repo_root: Path, case: dict[str, Any]) -> None:
    rel = case.get("file")
    if not rel:
        return
    p = (repo_root / str(rel)).resolve()
    if not p.is_file():
        raise SystemExit(
            f"Source file not found:\n  {p}\n"
            "Use --repo pointing at BenchmarkJava, or place it as ``../BenchmarkJava`` next to ``SAST/``.\n"
            "Clone: https://github.com/OWASP-Benchmark/BenchmarkJava"
        )


def _safe_model_dir(model: str | None) -> str:
    if not model:
        return "default"
    sanitized = model.replace("/", "_")
    return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "-" for ch in sanitized)


def _load_case(case_path: Path) -> Dict[str, Any]:
    return json.loads(case_path.read_text(encoding="utf-8"))


def _ensure_case_id(case: Dict[str, Any]) -> str:
    from benchmark.make_task import stable_case_id

    return stable_case_id(case)


def _run_and_tee(
    cmd: list[str], cwd: Path, env: dict[str, str], timeout: int | None
) -> tuple[int, str, str]:
    proc = subprocess.Popen(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    assert proc.stdout is not None
    lines: list[str] = []
    try:
        for line in proc.stdout:
            print(line, end="", flush=True)
            lines.append(line)
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise
    return proc.returncode, "".join(lines), ""


def _extract_last_json_object(text: str) -> Dict[str, Any]:
    decoder = json.JSONDecoder()
    indices = [m.start() for m in re.finditer(r"\{", text)]
    for i in reversed(indices):
        chunk = text[i:].lstrip()
        try:
            obj, _ = decoder.raw_decode(chunk)
            if isinstance(obj, dict) and "label" in obj:
                lbl = str(obj.get("label", "")).strip().upper()
                if lbl in {"TP", "FP", "BL", "UNKNOWN"}:
                    obj["label"] = lbl
                    return obj
        except Exception:
            continue
    raise ValueError("Could not extract a labeled JSON object from OpenHands output.")


def _extract_from_trajectories(traj_dir: Path) -> Dict[str, Any] | None:
    if not traj_dir.exists():
        return None

    def _try_fields(item: Dict[str, Any]) -> Dict[str, Any] | None:
        for field in (
            item.get("args", {}).get("thought"),
            item.get("args", {}).get("final_thought"),
            item.get("message"),
        ):
            if not field or not isinstance(field, str):
                continue
            try:
                return _extract_last_json_object(field)
            except Exception:
                continue
        return None

    files = [p for p in traj_dir.rglob("*") if p.is_file()]
    for path in reversed(sorted(files)):
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            for item in reversed(parsed):
                if not isinstance(item, dict):
                    continue
                if item.get("source") != "agent":
                    continue
                found = _try_fields(item)
                if found:
                    return found
        try:
            return _extract_last_json_object(text)
        except Exception:
            continue
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, type=Path)
    ap.add_argument(
        "--repo",
        default=None,
        help="BenchmarkJava root. If omitted, uses ../BenchmarkJava when it contains the case file.",
    )
    ap.add_argument("--scan-root", default=".")
    ap.add_argument("--run-dir", default=None, type=Path)
    ap.add_argument("--runtime", choices=["local", "docker"], default="local")
    ap.add_argument("--llm-model", default=None)
    ap.add_argument("--llm-provider", default=None)
    ap.add_argument("--llm-api-key", default=None)
    ap.add_argument("--max-iterations", type=int, default=40)
    ap.add_argument("--timeout", type=int, default=None)
    ap.add_argument(
        "--eval-framework",
        type=Path,
        default=None,
        help="Folder with make_task.py and openhands_config.toml",
    )
    args = ap.parse_args()

    sast_root = Path(__file__).resolve().parent.parent
    eval_fw = args.eval_framework
    if eval_fw is None:
        eval_fw = sast_root / "benchmark"
    eval_fw = eval_fw.expanduser().resolve()
    make_task = eval_fw / "make_task.py"
    if not make_task.is_file():
        raise SystemExit(f"make_task.py not found: {make_task}")

    case_path = args.case.expanduser().resolve()
    case = _load_case(case_path)
    _bench = Path(__file__).resolve().parent
    if str(_bench) not in sys.path:
        sys.path.insert(0, str(_bench))
    import repo_root as _repo  # noqa: E402

    case_id = _ensure_case_id(case)
    effective_scan_root = case.get("scan_root") or args.scan_root
    repo_root = _repo.resolve_benchmark_java_root(sast_root, case, args.repo)
    _require_repo_file(repo_root, case)

    model_dir = _safe_model_dir(args.llm_model)
    run_dir = (
        args.run_dir.expanduser().resolve()
        if args.run_dir
        else (Path.cwd() / "runs" / model_dir / AGENT_NAME / case_id)
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    workspace_tmp = run_dir / "workspace_tmp"
    workspace_tmp.mkdir(parents=True, exist_ok=True)

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

    config_src = eval_fw / "openhands_config.toml"
    if not config_src.exists():
        config_src = (
            sast_root.parent / "SAST-Paper-Artifacts" / "Evaluation Framework" / "openhands_config.toml"
        )
    if not config_src.exists():
        raise FileNotFoundError(f"Missing OpenHands config: {config_src}")
    (run_dir / "config.toml").write_text(config_src.read_text(encoding="utf-8"), encoding="utf-8")

    env = os.environ.copy()
    env["RUNTIME"] = args.runtime
    env["DISABLE_COLOR"] = "true"
    env["SAVE_TRAJECTORY_PATH"] = str(run_dir / "trajectories")
    env["MAX_ITERATIONS"] = str(args.max_iterations)
    if args.llm_model:
        env["LLM_MODEL"] = args.llm_model
    if args.llm_provider:
        env["LLM_PROVIDER"] = args.llm_provider
    if args.llm_api_key:
        env["LLM_API_KEY"] = args.llm_api_key

    if args.runtime == "docker":
        env["SANDBOX_VOLUMES"] = f"{workspace_tmp}:/workspace:rw,{repo_root}:/repo:ro"
        workdir = "/repo"
    else:
        env.pop("SANDBOX_VOLUMES", None)
        workdir = str(repo_root)

    cmd = [
        sys.executable,
        "-m",
        "openhands.core.main",
        "-f",
        str(task_path),
        "-d",
        workdir,
        "-i",
        "25",
    ]
    env["LOG_ALL_EVENTS"] = "true"
    env["WORKSPACE_BASE"] = workdir
    proc_rc, proc_stdout, proc_stderr = _run_and_tee(cmd, cwd=run_dir, env=env, timeout=args.timeout)

    log_path = run_dir / "openhands.log"
    log_path.write_text((proc_stdout or "") + "\n\n==== STDERR ====\n" + (proc_stderr or ""), encoding="utf-8")

    result = _extract_from_trajectories(run_dir / "trajectories")
    if result is None:
        result = _extract_last_json_object((proc_stdout or "") + "\n" + (proc_stderr or ""))

    result.setdefault("agent", AGENT_NAME)
    result.setdefault("case_id", case_id)

    out_path = run_dir / f"agent-{AGENT_NAME}-triage-result.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n[{AGENT_NAME}] log: {log_path}")
    print(f"[{AGENT_NAME}] Wrote: {out_path}")


if __name__ == "__main__":
    main()
