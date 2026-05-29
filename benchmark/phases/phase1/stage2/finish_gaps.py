#!/usr/bin/env python3
"""Re-run only Stage-2 cases missing a valid agent-llm-triage-result.json."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

_sast = Path(__file__).resolve().parents[3].parent
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.make_task import stable_case_id  # noqa: E402
from benchmark.triage_labels import VALID_LABELS  # noqa: E402

TRACKS = {
    "fp": ("benchmark/corpora/fp_codeql", "runs/phase1/stage2/fp/thinking_off", "FP"),
    "tp": ("benchmark/corpora/tp_codeql", "runs/phase1/stage2/tp/thinking_off", "TP"),
    "bl": ("benchmark/corpora/borderline_n200_seed42", "runs/phase1/stage2/bl/thinking_off", "BL"),
}
PROFILES = ("qwen3_4b_bnb", "qwen3_8b_bnb", "qwen3_14b_bnb")


def _case_index(case_dir: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in case_dir.glob("*.json"):
        if p.name == "slice_manifest.json":
            continue
        case = json.loads(p.read_text(encoding="utf-8"))
        out[stable_case_id(case)] = p
    return out


def _has_valid_result(run_dir: Path) -> bool:
    p = run_dir / "agent-llm-triage-result.json"
    if not p.is_file():
        return False
    try:
        lbl = str(json.loads(p.read_text(encoding="utf-8")).get("label", "")).strip().upper()
    except json.JSONDecodeError:
        return False
    return lbl in VALID_LABELS


def _find_missing() -> list[dict[str, str]]:
    missing: list[dict[str, str]] = []
    for track, (corpus, runs_root, gold) in TRACKS.items():
        cases = _case_index(_sast / corpus)
        for profile in PROFILES:
            llm_root = _sast / runs_root / profile / "llm"
            for cid in sorted(cases):
                run_dir = llm_root / cid
                if not _has_valid_result(run_dir):
                    missing.append(
                        {
                            "track": track,
                            "profile": profile,
                            "case_id": cid,
                            "gold": gold,
                            "case_path": str(cases[cid]),
                        }
                    )
    return missing


def _repair_all() -> None:
    for track, (_, runs_root, _) in TRACKS.items():
        for profile in PROFILES:
            root = _sast / runs_root / profile
            if not root.is_dir():
                continue
            subprocess.run(
                [
                    sys.executable,
                    str(_sast / "benchmark/repair_llm_results.py"),
                    "--runs",
                    str(_sast / runs_root),
                    "--profile",
                    profile,
                ],
                cwd=str(_sast),
                check=False,
            )


def _clear_bad_run(run_dir: Path) -> None:
    if not run_dir.is_dir():
        return
    for name in (
        "agent-llm-triage-result.json",
        "llm_raw.txt",
        "run_meta.json",
    ):
        p = run_dir / name
        if p.is_file():
            p.unlink()


def _run_cell_batch(track: str, profile: str, case_paths: list[Path], gold: str, attempts: int) -> None:
    _, runs_root, _ = TRACKS[track]
    llm_root = _sast / runs_root / profile / "llm"
    for src in case_paths:
        cid = stable_case_id(json.loads(src.read_text(encoding="utf-8")))
        _clear_bad_run(llm_root / cid)

    tmp = _sast / "runs/phase1/stage2/gap_slices" / f"{track}_{profile}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    for src in case_paths:
        shutil.copy2(src, tmp / src.name)

    for attempt in range(1, attempts + 1):
        print(f"[gap-batch] {track} {profile} n={len(case_paths)} attempt {attempt}/{attempts}")
        subprocess.run(
            [
                "uv",
                "run",
                "python",
                str(_sast / "benchmark/run_batch.py"),
                "--agent",
                "llm",
                "--case-dir",
                str(tmp),
                "--profile",
                profile,
                "--runs-root",
                str(_sast / runs_root),
                "--gold",
                gold,
                "--retry-missing",
                "--force",
            ],
            cwd=str(_sast),
            check=False,
        )
        left = []
        for p in case_paths:
            cid = stable_case_id(json.loads(p.read_text(encoding="utf-8")))
            if not _has_valid_result(llm_root / cid):
                left.append(cid)
        if not left:
            break
        print(f"  still missing: {len(left)}")
        for cid in left:
            _clear_bad_run(llm_root / cid)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--skip-repair", action="store_true")
    ap.add_argument("--attempts", type=int, default=2)
    args = ap.parse_args()

    if not args.skip_repair:
        print("=== repair_llm_results (all cells) ===")
        _repair_all()

    missing = _find_missing()
    out_path = _sast / "runs/phase1/stage2/logs/missing_cases.json"
    out_path.write_text(json.dumps(missing, indent=2), encoding="utf-8")
    print(f"Missing valid results: {len(missing)} (wrote {out_path})")

    if args.list_only:
        for m in missing:
            print(f"  {m['track']} {m['profile']} {m['case_id']}")
        return
    if not missing:
        subprocess.run(["bash", str(_sast / "benchmark/phases/phase1/stage2/refresh_summaries.sh")], cwd=str(_sast))
        return

    by_cell: dict[tuple[str, str], list[Path]] = defaultdict(list)
    gold_map: dict[tuple[str, str], str] = {}
    for m in missing:
        key = (m["track"], m["profile"])
        by_cell[key].append(Path(m["case_path"]))
        gold_map[key] = m["gold"]

    for (track, profile), paths in sorted(by_cell.items()):
        _run_cell_batch(track, profile, paths, gold_map[(track, profile)], args.attempts)

    missing2 = _find_missing()
    print(f"\nAfter gap fill: {len(missing2)} still missing")
    subprocess.run(
        ["bash", str(_sast / "benchmark/phases/phase1/stage2/refresh_summaries.sh")],
        cwd=str(_sast),
        check=False,
    )


if __name__ == "__main__":
    main()
