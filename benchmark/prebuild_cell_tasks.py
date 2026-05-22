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
) -> tuple[bool, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    task_path = run_dir / "task.md"
    if task_path.is_file() and task_path.stat().st_size > 100:
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
    ]
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
    ap.add_argument("--only-missing", action="store_true", help="Skip dirs with valid task.md")
    args = ap.parse_args()

    sast_root = Path(__file__).resolve().parent.parent
    bench = Path(__file__).resolve().parent
    eval_fw = (sast_root.parent / "SAST-Paper-Artifacts" / "Evaluation Framework").resolve()
    make_task = eval_fw / "make_task.py"
    if not make_task.is_file():
        raise SystemExit(f"make_task.py not found: {make_task}")

    if str(bench) not in sys.path:
        sys.path.insert(0, str(bench))
    import repo_root as _repo  # noqa: E402

    case_dir = args.case_dir.expanduser().resolve()
    llm_root = args.runs_root.expanduser().resolve() / args.profile.replace("/", "_") / "llm"
    files = sorted(p for p in case_dir.glob("*.json") if p.name != "slice_manifest.json")

    built = cached = failed = 0
    for case_path in files:
        case = json.loads(case_path.read_text(encoding="utf-8"))
        sys.path.insert(0, str(eval_fw))
        from make_task import stable_case_id  # type: ignore[import-not-found]

        cid = stable_case_id(case)
        run_dir = llm_root / cid
        if args.only_missing and (run_dir / "task.md").is_file():
            sz = (run_dir / "task.md").stat().st_size
            if sz > 100:
                cached += 1
                continue
        repo = _repo.resolve_benchmark_java_root(sast_root, case, args.repo)
        scan = case.get("scan_root") or "."
        ok, msg = _build_one(
            make_task=make_task,
            case_path=case_path,
            repo=repo,
            run_dir=run_dir,
            scan_root=str(scan),
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
