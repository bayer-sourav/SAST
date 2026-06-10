#!/usr/bin/env python3
"""Re-run Phase 2 core-profile cells missing a valid agent-llm-triage-result.json."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.make_task import stable_case_id  # noqa: E402
from benchmark.triage_labels import VALID_LABELS  # noqa: E402

# track -> (corpus_dir, runs/phase2/{track}, gold, MANIFEST.json tracks key)
TRACKS = {
    "fp": ("benchmark/corpora/phase2_fp_test", "runs/phase2/fp", "FP", "fp"),
    "tp": ("benchmark/corpora/phase2_tp_test", "runs/phase2/tp", "TP", "tp"),
    "bl": ("benchmark/corpora/phase2_bl_test", "runs/phase2/bl", "BL", "borderline"),
}
CORE_PROFILES = (
    "qwen3_4b_bnb",
    "qwen3_8b_bnb",
    "qwen3_14b_bnb",
    "qwen3_coder_30b_bnb",
)
THINKING_MODES = ("off", "on")
FEWSHOT_VALUES = (0, 3)
MANIFEST_PATH = _sast / "benchmark/phases/phase2/MANIFEST.json"
ENV_SH = _sast / "benchmark/phase2_cell_env.sh"
GAP_LOG = _sast / "runs/phase2/logs/gap_fill.log"


def _case_index(track: str) -> dict[str, Path]:
    corpus, _, _, manifest_key = TRACKS[track]
    corpus_path = _sast / corpus
    by_cid: dict[str, Path] = {}
    for p in corpus_path.glob("OWASP_*.json"):
        if p.name == "slice_manifest.json":
            continue
        case = json.loads(p.read_text(encoding="utf-8"))
        by_cid[stable_case_id(case)] = p

    if MANIFEST_PATH.is_file():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        case_ids = manifest["tracks"][manifest_key]["case_ids"]
        return {cid: by_cid[cid] for cid in case_ids if cid in by_cid}
    return by_cid


def _runs_subroot(track: str, thinking: str, fewshot: int) -> Path:
    _, runs_track, _, _ = TRACKS[track]
    return _sast / runs_track / f"thinking_{thinking}" / f"fewshot_{fewshot}"


def _has_valid_result(run_dir: Path) -> bool:
    p = run_dir / "agent-llm-triage-result.json"
    if not p.is_file():
        return False
    try:
        lbl = str(json.loads(p.read_text(encoding="utf-8")).get("label", "")).strip().upper()
    except json.JSONDecodeError:
        return False
    return lbl in VALID_LABELS


def _find_missing() -> list[dict[str, str | int]]:
    missing: list[dict[str, str | int]] = []
    for track in TRACKS:
        cases = _case_index(track)
        _, _, gold, _ = TRACKS[track]
        for thinking in THINKING_MODES:
            for fewshot in FEWSHOT_VALUES:
                sub = _runs_subroot(track, thinking, fewshot)
                for profile in CORE_PROFILES:
                    llm_root = sub / profile / "llm"
                    for cid in sorted(cases):
                        run_dir = llm_root / cid
                        if not _has_valid_result(run_dir):
                            missing.append(
                                {
                                    "track": track,
                                    "thinking": thinking,
                                    "fewshot": fewshot,
                                    "profile": profile,
                                    "case_id": cid,
                                    "gold": gold,
                                    "case_path": str(cases[cid]),
                                }
                            )
    return missing


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


def _repair_cell(track: str, thinking: str, fewshot: int, profile: str) -> None:
    sub = _runs_subroot(track, thinking, fewshot)
    subprocess.run(
        [
            sys.executable,
            str(_sast / "benchmark/repair_llm_results.py"),
            "--runs",
            str(sub),
            "--profile",
            profile,
        ],
        cwd=str(_sast),
        check=False,
    )


def _run_cell_batch(
    track: str,
    thinking: str,
    fewshot: int,
    profile: str,
    case_paths: list[Path],
    gold: str,
    attempts: int,
) -> None:
    sub = _runs_subroot(track, thinking, fewshot)
    llm_root = sub / profile / "llm"
    for src in case_paths:
        cid = stable_case_id(json.loads(src.read_text(encoding="utf-8")))
        _clear_bad_run(llm_root / cid)

    tmp_name = f"{track}_{thinking}_fs{fewshot}_{profile}"
    tmp = _sast / "runs/phase2/gap_slices" / tmp_name
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    for src in case_paths:
        shutil.copy2(src, tmp / src.name)

    think_args = "--thinking" if thinking == "on" else ""
    GAP_LOG.parent.mkdir(parents=True, exist_ok=True)

    for attempt in range(1, attempts + 1):
        print(
            f"[gap-batch] {track} think={thinking} fs={fewshot} {profile} "
            f"n={len(case_paths)} attempt {attempt}/{attempts}"
        )
        batch_cmd = f"""
set -euo pipefail
cd "{_sast}"
source "{ENV_SH}"
phase2_save_env
phase2_apply_token_limits "{thinking}" "{profile}"
set +e
uv run python "{_sast}/benchmark/run_batch.py" \\
  --agent llm \\
  --case-dir "{tmp}" \\
  --profile "{profile}" \\
  --runs-root "{sub}" \\
  --gold "{gold}" \\
  --few-shot "{fewshot}" \\
  --retry-missing \\
  --force \\
  {think_args}
batch_ec=$?
phase2_restore_env
phase2_gpu_cleanup "{GAP_LOG}"
exit $batch_ec
"""
        subprocess.run(["bash", "-c", batch_cmd], cwd=str(_sast), check=False)

        left: list[str] = []
        for p in case_paths:
            cid = stable_case_id(json.loads(p.read_text(encoding="utf-8")))
            if not _has_valid_result(llm_root / cid):
                left.append(cid)
        if not left:
            break
        print(f"  still missing: {len(left)}")
        for cid in left:
            _clear_bad_run(llm_root / cid)


def _refresh_summaries() -> None:
    script = _sast / "benchmark/phases/phase2/refresh_core_summaries.sh"
    subprocess.run(["bash", str(script)], cwd=str(_sast), check=False)


def _repair_affected(cells: set[tuple[str, str, int, str]]) -> None:
    for track, thinking, fewshot, profile in sorted(cells):
        print(f"=== repair {track} think={thinking} fs={fewshot} {profile} ===")
        _repair_cell(track, thinking, fewshot, profile)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list-only", action="store_true")
    ap.add_argument("--skip-repair", action="store_true", help="Skip post-fill repair on affected cells")
    ap.add_argument("--attempts", type=int, default=2)
    args = ap.parse_args()

    missing = _find_missing()
    out_path = _sast / "runs/phase2/logs/missing_core.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(missing, indent=2), encoding="utf-8")
    print(f"Missing valid results: {len(missing)} (wrote {out_path})")

    if args.list_only:
        for m in missing:
            print(
                f"  {m['track']} think={m['thinking']} fs={m['fewshot']} "
                f"{m['profile']} {m['case_id']}"
            )
        return
    if not missing:
        _refresh_summaries()
        return

    by_cell: dict[tuple[str, str, int, str], list[Path]] = defaultdict(list)
    gold_map: dict[tuple[str, str, int, str], str] = {}
    for m in missing:
        key = (m["track"], str(m["thinking"]), int(m["fewshot"]), str(m["profile"]))
        by_cell[key].append(Path(str(m["case_path"])))
        gold_map[key] = str(m["gold"])

    for (track, thinking, fewshot, profile), paths in sorted(by_cell.items()):
        _run_cell_batch(
            track,
            thinking,
            fewshot,
            profile,
            paths,
            gold_map[(track, thinking, fewshot, profile)],
            args.attempts,
        )

    missing2 = _find_missing()
    print(f"\nAfter gap fill: {len(missing2)} still missing")
    out_path.write_text(json.dumps(missing2, indent=2), encoding="utf-8")

    if not args.skip_repair:
        affected = set(by_cell.keys())
        _repair_affected(affected)

    _refresh_summaries()


if __name__ == "__main__":
    main()
