#!/usr/bin/env python3
"""Phase 1 watchdog: status snapshot, error counts, optional auto-rerun trigger."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROFILES = (
    "qwen3_4b_bnb",
    "qwen3_8b_bnb",
    "qwen3_14b_bnb",
    "gpt_oss_20b",
    "qwen3_coder_30b_bnb",
)
N = 50


def _count_cell(runs_root: Path, thinking: str, profile: str) -> dict:
    llm = runs_root / f"thinking_{thinking}" / profile / "llm"
    ok = err = 0
    err_types: dict[str, int] = {}
    if not llm.is_dir():
        return {"ok": 0, "errors": 0, "err_types": {}}
    for case_dir in llm.iterdir():
        if not case_dir.is_dir():
            continue
        result = case_dir / "agent-llm-triage-result.json"
        if result.is_file():
            ok += 1
            continue
        meta_p = case_dir / "run_meta.json"
        if meta_p.is_file():
            err += 1
            try:
                meta = json.loads(meta_p.read_text(encoding="utf-8"))
                e = str(meta.get("error", "unknown"))[:80]
                key = e.split(":")[0] if e else "unknown"
                err_types[key] = err_types.get(key, 0) + 1
            except json.JSONDecodeError:
                err_types["bad_meta"] = err_types.get("bad_meta", 0) + 1
    return {"ok": ok, "errors": err, "err_types": err_types}


def _gpu_line() -> str:
    try:
        r = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return "n/a"


def _running_jobs() -> list[str]:
    try:
        r = subprocess.run(
            ["pgrep", "-af", "run_batch|run_phase1|monitor_gpt|run_llm_local"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return [ln.strip() for ln in r.stdout.strip().splitlines()[:8]]
    except Exception:
        pass
    return []


def snapshot(sast: Path) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [f"Phase 1 watchdog @ {now}", f"GPU: {_gpu_line()}", ""]
    jobs = _running_jobs()
    if jobs:
        lines.append("Running:")
        lines.extend(f"  {j}" for j in jobs)
    else:
        lines.append("Running: (none)")
    lines.append("")

    total_ok = total_target = 0
    for track, runs_name in (("FP", "FP-runs/phase1_n50"), ("TP", "TP-runs/phase1_n50")):
        runs = sast / runs_name
        lines.append(f"=== {track} ===")
        for thinking in ("off", "on"):
            lines.append(f"  thinking_{thinking}:")
            for profile in PROFILES:
                c = _count_cell(runs, thinking, profile)
                ok, er = c["ok"], c["errors"]
                total_ok += ok
                total_target += N
                mark = "done" if ok >= N else f"{ok}/{N}"
                extra = ""
                if er:
                    tops = ", ".join(f"{k}×{v}" for k, v in sorted(c["err_types"].items())[:3])
                    extra = f"  errs={er} ({tops})"
                lines.append(f"    {profile:28} {mark}{extra}")
        lines.append("")

    pct = 100.0 * total_ok / total_target if total_target else 0
    lines.append(f"Overall: {total_ok}/{total_target} ({pct:.1f}%)")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-out", type=Path, default=None)
    ap.add_argument("--status-out", type=Path, default=None)
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    sast = Path(__file__).resolve().parent.parent
    text = snapshot(sast)
    if not args.quiet:
        print(text, end="")

    log_dir = sast / "benchmark" / "phase1_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    status_out = args.status_out or (log_dir / "watchdog_status.txt")
    status_out.write_text(text, encoding="utf-8")

    if args.json_out:
        args.json_out.write_text(json.dumps({"text": text}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
