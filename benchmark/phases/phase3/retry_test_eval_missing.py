#!/usr/bin/env python3
"""Re-run Phase 3B test eval cases missing a valid triage result, then resummarize."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.phases.phase3._phase3b_common import load_manifest  # noqa: E402
from benchmark.phases.phase3.phase3_inference import run_batch_tracks, vllm_env_for_adapter  # noqa: E402
from benchmark.srs import compute_srs  # noqa: E402
from benchmark.summarize_triage import _model_row_name  # noqa: E402

PROFILE = "qwen3_5_9b_bnb"
VALID_LABELS = frozenset({"TP", "FP", "BL", "UNKNOWN"})
TRACKS = (
    ("fp", "FP", "benchmark/corpora/phase2_fp_test"),
    ("tp", "TP", "benchmark/corpora/phase2_tp_test"),
    ("bl", "BL", "benchmark/corpora/phase2_bl_test"),
)


def _valid_result(result_path: Path) -> bool:
    if not result_path.is_file():
        return False
    try:
        lbl = str(json.loads(result_path.read_text(encoding="utf-8")).get("label", "")).strip().upper()
        return lbl in VALID_LABELS
    except Exception:
        return False


def _track_runs_root(eval_root: Path, track: str, *, thinking: str, fewshot: int) -> Path:
    model_dir = PROFILE.replace("/", "_")
    return eval_root / track / f"thinking_{thinking}/fewshot_{fewshot}" / model_dir / "llm"


def _count_missing(eval_root: Path, *, thinking: str, fewshot: int) -> dict[str, int]:
    counts: dict[str, int] = {}
    for track, _, _ in TRACKS:
        runs_root = _track_runs_root(eval_root, track, thinking=thinking, fewshot=fewshot)
        if not runs_root.is_dir():
            counts[track] = 0
            continue
        n = 0
        for run_dir in runs_root.iterdir():
            if run_dir.is_dir() and not _valid_result(run_dir / "agent-llm-triage-result.json"):
                n += 1
        counts[track] = n
    return counts


def _missing_run_dirs(
    eval_root: Path, *, thinking: str, fewshot: int
) -> list[tuple[str, str, Path]]:
    """Return (track, gold, run_dir) for cases without a valid triage result."""
    missing: list[tuple[str, str, Path]] = []
    for track, gold, _ in TRACKS:
        runs_root = _track_runs_root(eval_root, track, thinking=thinking, fewshot=fewshot)
        if not runs_root.is_dir():
            continue
        for run_dir in sorted(runs_root.iterdir()):
            if run_dir.is_dir() and not _valid_result(run_dir / "agent-llm-triage-result.json"):
                missing.append((track, gold, run_dir))
    return missing


def run_compact_retries(
    *,
    eval_root: Path,
    adapter: Path,
    thinking: str,
    fewshot: int,
    prompt: str,
    fs_config: str,
) -> dict[str, int]:
    """Compact JSON-only retry for missing cases (preserves existing run dirs)."""
    from benchmark.run_llm_local import run_compact_triage_retry

    env = vllm_env_for_adapter(adapter)
    env["SAST_PROMPT_VERSION"] = prompt
    env.setdefault("PYTHONPATH", f"{_sast}:{_sast / 'benchmark'}")
    for key, val in env.items():
        os.environ[key] = val

    missing = _missing_run_dirs(eval_root, thinking=thinking, fewshot=fewshot)
    print(f"[retry-test] compact retry n={len(missing)}", flush=True)
    ok = 0
    for track, gold, run_dir in missing:
        case_id = run_dir.name
        meta = run_compact_triage_retry(
            run_dir=run_dir,
            case_id=case_id,
            profile=PROFILE,
            gold=gold,
            few_shot=fewshot,
            few_shot_config=fs_config,
            prompt_version=prompt,
            quiet=False,
        )
        if int(meta.get("returncode", 1)) == 0:
            ok += 1
        else:
            print(f"[retry-test] compact failed {track}/{case_id}", flush=True)
    print(f"[retry-test] compact recovered {ok}/{len(missing)}", flush=True)
    return _count_missing(eval_root, thinking=thinking, fewshot=fewshot)


def recover_from_llm_raw(
    eval_root: Path, *, thinking: str, fewshot: int
) -> dict[str, int]:
    """Re-parse llm_raw.txt with improved parser; write triage JSON when recovered."""
    from core.parsing import extract_triage_result

    recovered = 0
    for track, gold, run_dir in _missing_run_dirs(eval_root, thinking=thinking, fewshot=fewshot):
        raw_path = run_dir / "llm_raw.txt"
        if not raw_path.is_file():
            continue
        try:
            result = extract_triage_result(raw_path.read_text(encoding="utf-8"))
            lbl = str(result.get("label", "")).strip().upper()
            if lbl not in VALID_LABELS:
                continue
            result["agent"] = "llm"
            result["case_id"] = run_dir.name
            out = run_dir / "agent-llm-triage-result.json"
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            recovered += 1
            print(f"[retry-test] recovered {track}/{run_dir.name} label={lbl}", flush=True)
        except Exception:
            continue
    print(f"[retry-test] recover_from_raw n={recovered}", flush=True)
    return _count_missing(eval_root, thinking=thinking, fewshot=fewshot)


def clear_failed_runs(eval_root: Path, *, thinking: str, fewshot: int) -> int:
    """Remove run dirs without a valid triage result so inference starts clean."""
    removed = 0
    for track, _, _ in TRACKS:
        runs_root = _track_runs_root(eval_root, track, thinking=thinking, fewshot=fewshot)
        if not runs_root.is_dir():
            continue
        for run_dir in list(runs_root.iterdir()):
            if not run_dir.is_dir():
                continue
            if not _valid_result(run_dir / "agent-llm-triage-result.json"):
                shutil.rmtree(run_dir)
                removed += 1
                print(f"[retry-test] cleared {track}/{run_dir.name}", flush=True)
    return removed


def resummarize(
    *,
    eval_root: Path,
    sum_dir: Path,
    thinking: str,
    fewshot: int,
    sum_suffix: str = "",
) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for track, gold, corpus_rel in TRACKS:
        corpus = _sast / corpus_rel
        runs = eval_root / track / f"thinking_{thinking}/fewshot_{fewshot}"
        json_out = sum_dir / f"comparison_{track}_phase3a{sum_suffix}.json"
        script = "summarize_borderline.py" if gold == "BL" else "summarize_triage.py"
        cmd = [
            sys.executable,
            str(_sast / f"benchmark/{script}"),
            "--case-dir",
            str(corpus),
            "--runs",
            str(runs),
            "--profile",
            PROFILE,
            "--json-out",
            str(json_out),
        ]
        if gold != "BL":
            cmd.extend(["--gold", gold])
        subprocess.run(cmd, cwd=str(_sast), check=True)
        data = json.loads(json_out.read_text(encoding="utf-8"))
        rows[track] = data.get(_model_row_name(PROFILE)) or {}
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--adapter",
        type=Path,
        default=_sast / "runs/phase3/stage3b/lora/best",
    )
    ap.add_argument(
        "--eval-root",
        type=Path,
        default=_sast / "runs/phase3/stage3b/eval",
    )
    ap.add_argument(
        "--sum-dir",
        type=Path,
        default=_sast / "runs/phase3/stage3b/summaries",
    )
    ap.add_argument("--thinking", choices=("on", "off"), default=None)
    ap.add_argument("--fewshot", type=int, default=None)
    ap.add_argument("--sum-suffix", default=None, help="e.g. _fs0_off for ablation summaries")
    ap.add_argument("--prompt-version", default=None, help="Override manifest prompt (default: manifest)")
    ap.add_argument("--rounds", type=int, default=1, help="Max gap-fill rounds (default 1; 0=skip infer)")
    ap.add_argument("--compact-only", action="store_true", help="Compact JSON-only retry (no dir wipe)")
    ap.add_argument("--recover-only", action="store_true", help="Re-parse llm_raw.txt only (no infer)")
    ap.add_argument("--no-infer", action="store_true", help="Resummarize only")
    args = ap.parse_args()

    manifest = load_manifest()
    icfg = manifest["inference_eval"]
    fewshot = int(args.fewshot if args.fewshot is not None else icfg["fewshot"])
    thinking = args.thinking or ("on" if icfg.get("thinking") else "off")
    prompt = args.prompt_version or icfg["prompt_version"]
    fs_config = icfg["few_shot_config"]
    sum_suffix = args.sum_suffix if args.sum_suffix is not None else ""

    eval_root = args.eval_root.resolve()
    sum_dir = args.sum_dir.resolve()
    sum_dir.mkdir(parents=True, exist_ok=True)

    before = _count_missing(eval_root, thinking=thinking, fewshot=fewshot)
    print(
        f"[retry-test] think={thinking} fs={fewshot} before missing={before} "
        f"total={sum(before.values())}",
        flush=True,
    )

    if not args.no_infer:
        adapter = args.adapter.resolve()
        if args.recover_only:
            after = recover_from_llm_raw(eval_root, thinking=thinking, fewshot=fewshot)
            print(f"[retry-test] after recover missing={after}", flush=True)
        elif not adapter.is_dir():
            raise SystemExit(f"adapter missing: {adapter}")
        elif args.compact_only:
            after = run_compact_retries(
                eval_root=eval_root,
                adapter=adapter,
                thinking=thinking,
                fewshot=fewshot,
                prompt=prompt,
                fs_config=fs_config,
            )
            print(f"[retry-test] after compact missing={after}", flush=True)
        else:
            env = vllm_env_for_adapter(adapter)
            env["SAST_PROMPT_VERSION"] = prompt
            env.setdefault("PYTHONPATH", f"{_sast}:{_sast / 'benchmark'}")

            tracks = [
                {
                    "gold": gold,
                    "case_dir": str((_sast / corpus_rel).resolve()),
                    "runs_root": str(
                        (eval_root / track / f"thinking_{thinking}/fewshot_{fewshot}").resolve()
                    ),
                }
                for track, gold, corpus_rel in TRACKS
            ]

            for round_i in range(max(0, args.rounds)):
                miss = _count_missing(eval_root, thinking=thinking, fewshot=fewshot)
                total_miss = sum(miss.values())
                print(f"[retry-test] round {round_i + 1}/{args.rounds} missing={miss}", flush=True)
                if total_miss == 0:
                    break
                cleared = clear_failed_runs(eval_root, thinking=thinking, fewshot=fewshot)
                print(f"[retry-test] cleared {cleared} stale run dirs", flush=True)
                run_batch_tracks(
                    tracks,
                    env=env,
                    sast_root=_sast,
                    profile=PROFILE,
                    thinking=(thinking == "on"),
                    few_shot=fewshot,
                    few_shot_config=fs_config,
                    prompt_version=prompt,
                    retry_missing=True,
                )
                after = _count_missing(eval_root, thinking=thinking, fewshot=fewshot)
                print(f"[retry-test] round {round_i + 1} after missing={after}", flush=True)
                if sum(after.values()) == 0:
                    break

    rows = resummarize(
        eval_root=eval_root,
        sum_dir=sum_dir,
        thinking=thinking,
        fewshot=fewshot,
        sum_suffix=sum_suffix,
    )
    fp_m, tp_m, bl_m = rows["fp"], rows["tp"], rows["bl"]
    srs = compute_srs(fp_m, tp_m, bl_m or None, test_n=600)
    print(
        f"[retry-test] SRS={srs:.4f} "
        f"FPRR={fp_m.get('fprr')} VDR={tp_m.get('vdr')} "
        f"missing fp={fp_m.get('missing')} tp={tp_m.get('missing')} bl={bl_m.get('missing')}",
        flush=True,
    )


if __name__ == "__main__":
    main()
