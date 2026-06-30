#!/usr/bin/env python3
"""Gap-fill missing Phase 3 test eval cases and recompute comparison summaries."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.phases.phase3._phase3b_common import load_manifest  # noqa: E402
from benchmark.phases.phase3.eval_val_for_css import _valid_triage_result  # noqa: E402
from benchmark.phases.phase3.phase3_inference import run_batch_tracks, vllm_env_for_adapter  # noqa: E402
from benchmark.srs import compute_srs  # noqa: E402
from benchmark.summarize_triage import _model_row_name  # noqa: E402

PROFILE = "qwen3_5_9b_bnb"
TEST_N = 600


def _thinking_tag(thinking: str) -> str:
    return "on" if thinking.strip().lower() in ("on", "true", "1") else "off"


def _track_llm_root(eval_root: Path, track: str, *, thinking: str, fewshot: int) -> Path:
    return eval_root / track / f"thinking_{_thinking_tag(thinking)}" / f"fewshot_{fewshot}" / PROFILE / "llm"


def _case_ids(corpus_dir: Path) -> list[str]:
    ids: list[str] = []
    for path in sorted(corpus_dir.glob("*.json")):
        if path.name == "slice_manifest.json":
            continue
        case = json.loads(path.read_text(encoding="utf-8"))
        ids.append(str(case.get("case_id") or path.stem))
    return ids


def clear_invalid_test_runs(
    *,
    eval_root: Path,
    corpora: dict[str, Path],
    thinking: str,
    fewshot: int,
) -> int:
    removed = 0
    for track, corpus in corpora.items():
        llm_root = _track_llm_root(eval_root, track, thinking=thinking, fewshot=fewshot)
        for cid in _case_ids(corpus):
            run_dir = llm_root / cid
            result = run_dir / "agent-llm-triage-result.json"
            if run_dir.is_dir() and not _valid_triage_result(result):
                shutil.rmtree(run_dir)
                removed += 1
                print(f"[test-clear] removed stale run {track}/{cid}", flush=True)
    return removed


def missing_counts(
    *,
    eval_root: Path,
    corpora: dict[str, Path],
    thinking: str,
    fewshot: int,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for track, corpus in corpora.items():
        llm_root = _track_llm_root(eval_root, track, thinking=thinking, fewshot=fewshot)
        miss = 0
        for cid in _case_ids(corpus):
            result = llm_root / cid / "agent-llm-triage-result.json"
            if not _valid_triage_result(result):
                miss += 1
        counts[track] = miss
    return counts


def resummarize(
    *,
    sast_root: Path,
    sum_dir: Path,
    corpora: dict[str, Path],
    eval_root: Path,
    thinking: str,
    fewshot: int,
    sum_suffix: str,
) -> dict[str, int]:
    sum_dir.mkdir(parents=True, exist_ok=True)
    think = _thinking_tag(thinking)
    runs_suffix = f"thinking_{think}/fewshot_{fewshot}"

    specs = (
        ("fp", "FP", "summarize_triage.py"),
        ("tp", "TP", "summarize_triage.py"),
        ("bl", "BL", "summarize_borderline.py"),
    )
    for track, gold, script in specs:
        cmd = [
            sys.executable,
            str(sast_root / "benchmark" / script),
            "--case-dir",
            str(corpora[track]),
            "--runs",
            str(eval_root / track / runs_suffix),
            "--profile",
            PROFILE,
            "--json-out",
            str(sum_dir / f"comparison_{track}_phase3a{sum_suffix}.json"),
        ]
        if script == "summarize_triage.py":
            cmd.extend(["--gold", gold])
        subprocess.run(cmd, cwd=str(sast_root), check=True)

    return missing_counts(
        eval_root=eval_root, corpora=corpora, thinking=thinking, fewshot=fewshot
    )


def retry_missing(
    *,
    sast_root: Path,
    adapter: Path,
    eval_root: Path,
    corpora: dict[str, Path],
    manifest: dict,
    thinking: str,
    fewshot: int,
    fs_config: str,
    prompt_version: str,
) -> None:
    icfg = manifest["inference_eval"]
    think_bool = _thinking_tag(thinking) == "on"
    think_tag = _thinking_tag(thinking)
    env = vllm_env_for_adapter(adapter)
    env["SAST_PROMPT_VERSION"] = prompt_version

    tracks: list[dict[str, str]] = []
    for track, gold in (("fp", "FP"), ("tp", "TP"), ("bl", "BL")):
        tracks.append(
            {
                "gold": gold,
                "case_dir": str(corpora[track].resolve()),
                "runs_root": str((eval_root / track / f"thinking_{think_tag}" / f"fewshot_{fewshot}").resolve()),
            }
        )
    run_batch_tracks(
        tracks,
        env=env,
        sast_root=sast_root,
        profile=PROFILE,
        thinking=think_bool,
        few_shot=fewshot,
        few_shot_config=fs_config,
        prompt_version=prompt_version,
        retry_missing=True,
    )


def print_metrics(sum_dir: Path, sum_suffix: str) -> None:
    row = _model_row_name(PROFILE)

    def load(track: str) -> dict:
        path = sum_dir / f"comparison_{track}_phase3a{sum_suffix}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get(row) or {}

    fp_m, tp_m, bl_m = load("fp"), load("tp"), load("bl")
    srs = compute_srs(fp_m, tp_m, bl_m or None, test_n=TEST_N)
    missing = int(fp_m.get("missing") or 0) + int(tp_m.get("missing") or 0) + int(bl_m.get("missing") or 0)
    print(
        f"[test-rescore] SRS={srs*100:.1f}% FPRR={fp_m.get('fprr', 0)*100:.1f}% "
        f"VDR={tp_m.get('vdr', 0)*100:.1f}% missing={missing}",
        flush=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapter", type=Path, default=None)
    ap.add_argument("--eval-root", type=Path, default=None)
    ap.add_argument("--sum-dir", type=Path, default=None)
    ap.add_argument("--sum-suffix", default="")
    ap.add_argument("--until-complete", type=int, default=3, metavar="N")
    ap.add_argument("--resummarize-only", action="store_true")
    args = ap.parse_args()

    manifest = load_manifest()
    icfg = manifest["inference_eval"]
    eval_corpora = manifest["dataset"]["eval_corpora"]
    corpora = {
        "fp": (_sast / eval_corpora["fp"]).resolve(),
        "tp": (_sast / eval_corpora["tp"]).resolve(),
        "bl": (_sast / eval_corpora["borderline"]).resolve(),
    }

    outs = manifest["outputs"]
    eval_root = (args.eval_root or _sast / outs.get("test_eval") or outs["eval"]).expanduser().resolve()
    sum_dir = (args.sum_dir or _sast / manifest["outputs"]["summaries"]).expanduser().resolve()
    adapter = (
        args.adapter
        or Path(manifest["outputs"].get("global_best") or "runs/phase3/stage3c/lora/best")
    ).expanduser()
    if not adapter.is_absolute():
        adapter = (_sast / adapter).resolve()

    thinking = str(icfg.get("thinking", "off"))
    if isinstance(icfg.get("thinking"), bool):
        thinking = "on" if icfg["thinking"] else "off"
    fewshot = int(icfg.get("fewshot", 0))
    fs_config = str(icfg.get("few_shot_config") or "")
    prompt = str(icfg.get("prompt_version") or "v7-ship")

    before = missing_counts(
        eval_root=eval_root, corpora=corpora, thinking=thinking, fewshot=fewshot
    )
    print(f"[test-rescore] before missing={before} total={sum(before.values())}", flush=True)

    rounds = 1 if args.resummarize_only else max(1, args.until_complete)
    for round_i in range(rounds):
        if not args.resummarize_only:
            if round_i > 0:
                print(f"[test-rescore] gap-fill round {round_i + 1}/{rounds}", flush=True)
            cleared = clear_invalid_test_runs(
                eval_root=eval_root,
                corpora=corpora,
                thinking=thinking,
                fewshot=fewshot,
            )
            if cleared:
                print(f"[test-rescore] cleared {cleared} stale run dirs", flush=True)
            retry_missing(
                sast_root=_sast,
                adapter=adapter,
                eval_root=eval_root,
                corpora=corpora,
                manifest=manifest,
                thinking=thinking,
                fewshot=fewshot,
                fs_config=fs_config,
                prompt_version=prompt,
            )

        after = resummarize(
            sast_root=_sast,
            sum_dir=sum_dir,
            corpora=corpora,
            eval_root=eval_root,
            thinking=thinking,
            fewshot=fewshot,
            sum_suffix=args.sum_suffix,
        )
        print(f"[test-rescore] after missing={after} total={sum(after.values())}", flush=True)
        print_metrics(sum_dir, args.sum_suffix)
        if args.resummarize_only or sum(after.values()) == 0:
            break

    print("[test-rescore] done", flush=True)


if __name__ == "__main__":
    main()
