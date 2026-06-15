#!/usr/bin/env python3
"""Build task.md for all cases in a slice before GPU model load (avoids make_task OOM)."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def _build_one(
    *,
    make_task: Path,
    case_path: Path,
    repo: Path,
    run_dir: Path,
    scan_root: str,
    few_shot: int,
    few_shot_config: str | None = None,
    prompt_version: str | None = None,
) -> tuple[bool, str]:
    from benchmark.few_shot import layout_tag_from_config
    from benchmark.triage_labels import task_markdown_current

    layout_version = layout_tag_from_config(few_shot_config) if few_shot > 0 else None
    run_dir.mkdir(parents=True, exist_ok=True)
    task_path = run_dir / "task.md"
    if task_markdown_current(
        task_path,
        few_shot=few_shot,
        layout_version=layout_version,
        prompt_version=prompt_version,
    ):
        return True, "cached"
    cmd = [
        sys.executable,
        str(make_task),
        "--case",
        str(case_path),
        "--repo",
        str(repo),
        "--scan-root",
        scan_root,
        "--agent",
        "llm",
        "--out",
        str(task_path),
        "--few-shot",
        str(few_shot),
    ]
    if few_shot_config:
        cmd.extend(["--few-shot-config", str(few_shot_config)])
    if prompt_version:
        cmd.extend(["--prompt-version", str(prompt_version)])
    last = ""
    for attempt in range(3):
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode == 0 and task_path.is_file():
            return True, "built"
        last = (proc.stderr or proc.stdout or "").strip()[:200]
        time.sleep(0.5 * (attempt + 1))
    return False, last or "failed"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-dir", type=Path, required=True)
    ap.add_argument("--runs-root", type=Path, required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--repo", type=Path, default=None)
    ap.add_argument("--only-missing", action="store_true", help="Skip dirs with current task.md")
    ap.add_argument("--max-cases", type=int, default=None, help="Only prebuild first N cases (sorted).")
    ap.add_argument("--few-shot", type=int, default=0)
    ap.add_argument("--few-shot-config", default=None)
    ap.add_argument("--prompt-version", default=None)
    args = ap.parse_args()
    from benchmark.few_shot import layout_tag_from_config, validate_few_shot_k

    validate_few_shot_k(args.few_shot, args.few_shot_config)
    layout_version = (
        layout_tag_from_config(args.few_shot_config) if args.few_shot > 0 else None
    )

    sast_root = Path(__file__).resolve().parent.parent
    bench = Path(__file__).resolve().parent
    if str(sast_root) not in sys.path:
        sys.path.insert(0, str(sast_root))
    make_task = bench / "make_task.py"
    if not make_task.is_file():
        raise SystemExit(f"make_task.py not found: {make_task}")

    import repo_root as _repo  # noqa: E402
    from benchmark.make_task import stable_case_id  # noqa: E402
    from benchmark.triage_labels import task_markdown_current  # noqa: E402

    case_dir = args.case_dir.expanduser().resolve()
    llm_root = args.runs_root.expanduser().resolve() / args.profile.replace("/", "_") / "llm"
    files = sorted(p for p in case_dir.glob("*.json") if p.name != "slice_manifest.json")
    if args.max_cases is not None:
        files = files[: args.max_cases]

    built = cached = failed = 0
    for case_path in files:
        case = json.loads(case_path.read_text(encoding="utf-8"))
        cid = stable_case_id(case)
        run_dir = llm_root / cid
        if args.only_missing and task_markdown_current(
            run_dir / "task.md",
            few_shot=args.few_shot,
            layout_version=layout_version,
            prompt_version=args.prompt_version,
        ):
            cached += 1
            continue
        repo = _repo.resolve_benchmark_java_root(
            sast_root, case, args.repo, case_path=case_path
        )
        scan = case.get("scan_root") or "."
        ok, msg = _build_one(
            make_task=make_task,
            case_path=case_path,
            repo=repo,
            run_dir=run_dir,
            scan_root=str(scan),
            few_shot=args.few_shot,
            few_shot_config=args.few_shot_config,
            prompt_version=args.prompt_version,
        )
        if ok:
            if msg == "built":
                built += 1
                print(f"[task] {cid} built")
            else:
                cached += 1
        else:
            failed += 1
            print(f"[task] {cid} FAIL: {msg}")

    print(f"[prebuild] built={built} cached={cached} failed={failed} total={len(files)}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
