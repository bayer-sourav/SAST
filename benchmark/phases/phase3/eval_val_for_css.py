#!/usr/bin/env python3
"""Run validation infer + compute CSS for a LoRA checkpoint (fast or full val)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.css import css_from_metrics_pack  # noqa: E402
from benchmark.phases.phase3._phase3b_common import (  # noqa: E402
    css_val_case_ids,
    load_manifest,
    output_path,
    write_css_val_ids,
)
from benchmark.phases.phase3.phase3_inference import run_batch_tracks, vllm_env_for_adapter  # noqa: E402
from benchmark.phases.phase3.build_split_corpus import build_split_corpus  # noqa: E402
from benchmark.build_phase2_corpora import _dataset_root  # noqa: E402
from benchmark.srs import compute_srs  # noqa: E402
from benchmark.summarize_triage import macro_f1_from_track_f1s  # noqa: E402

PROFILE = "qwen3_5_9b_bnb"


def _slm_metrics_from_comparison(data: dict[str, Any], profile: str) -> dict[str, Any]:
    """summarize_*.py writes rows as ``SLM ({profile})``, not bare profile id."""
    from benchmark.summarize_triage import _model_row_name

    for key in (_model_row_name(profile), profile, f"SLM ({profile})"):
        row = data.get(key)
        if isinstance(row, dict) and row:
            return row
    return {}


def _summarize_track(
    *,
    corpus_dir: Path,
    runs_root: Path,
    gold: str,
    profile: str,
    json_out: Path,
) -> dict:
    cmd = [
        sys.executable,
        str(_sast / "benchmark/summarize_triage.py"),
        "--case-dir",
        str(corpus_dir),
        "--gold",
        gold,
        "--runs",
        str(runs_root),
        "--profile",
        profile,
        "--json-out",
        str(json_out),
    ]
    if gold == "BL":
        cmd = [
            sys.executable,
            str(_sast / "benchmark/summarize_borderline.py"),
            "--case-dir",
            str(corpus_dir),
            "--runs",
            str(runs_root),
            "--profile",
            profile,
            "--json-out",
            str(json_out),
        ]
    subprocess.run(cmd, cwd=str(_sast), check=True)
    data = json.loads(json_out.read_text(encoding="utf-8"))
    return _slm_metrics_from_comparison(data, profile)


def _corpus_base(manifest: dict[str, Any], mode: str) -> Path:
    corpus_base = output_path(manifest, "summaries").parent / "corpora" / "validation"
    case_ids_path = output_path(manifest, "summaries") / "css_val_case_ids.json"
    if mode == "fast":
        write_css_val_ids(case_ids_path, manifest)
        ids = set(json.loads(case_ids_path.read_text(encoding="utf-8")))
        build_split_corpus(
            dataset=_dataset_root(None),
            split="validation",
            out_root=corpus_base,
            case_ids=ids,
        )
    else:
        build_split_corpus(
            dataset=_dataset_root(None),
            split="validation",
            out_root=corpus_base,
        )
    return corpus_base


def _infer_layout(
    manifest: dict[str, Any],
    *,
    thinking: str | None = None,
    fewshot: int | None = None,
) -> tuple[str, int, str, bool]:
    icfg = manifest["inference_eval"]
    think = thinking or ("on" if icfg.get("thinking") else "off")
    fs = int(fewshot if fewshot is not None else icfg["fewshot"])
    return think, fs, icfg["few_shot_config"], think == "on"


def _track_runs_root(out_dir: Path, track: str, *, thinking: str, fewshot: int) -> Path:
    return out_dir / track / f"thinking_{thinking}/fewshot_{fewshot}"


def _val_tracks(manifest: dict[str, Any], corpus_base: Path) -> list[tuple[str, str, Path]]:
    return [
        ("fp", "FP", corpus_base / "fp"),
        ("tp", "TP", corpus_base / "tp"),
        ("borderline", "BL", corpus_base / "borderline"),
    ]


_VALID_LABELS = frozenset({"TP", "FP", "BL", "UNKNOWN"})


def _valid_triage_result(result_path: Path) -> bool:
    if not result_path.is_file():
        return False
    try:
        lbl = str(json.loads(result_path.read_text(encoding="utf-8")).get("label", "")).strip().upper()
        return lbl in _VALID_LABELS
    except Exception:
        return False


def clear_invalid_val_runs(
    out_dir: Path,
    manifest: dict[str, Any],
    mode: str,
    *,
    thinking: str | None = None,
    fewshot: int | None = None,
) -> int:
    """Remove run dirs with failed inference or invalid JSON so --retry-missing re-runs them."""
    import shutil

    think, fs, _, _ = _infer_layout(manifest, thinking=thinking, fewshot=fewshot)
    corpus_base = _corpus_base(manifest, mode)
    removed = 0
    for track, _gold, case_dir in _val_tracks(manifest, corpus_base):
        runs_root = _track_llm_root(out_dir, track, thinking=think, fewshot=fs)
        if not runs_root.is_dir():
            continue
        for case_file in case_dir.glob("*.json"):
            cid = case_file.stem
            run_dir = runs_root / cid
            result = run_dir / "agent-llm-triage-result.json"
            if run_dir.is_dir() and not _valid_triage_result(result):
                shutil.rmtree(run_dir)
                removed += 1
                print(f"[css-clear] removed stale run {track}/{cid}", flush=True)
    return removed


def _infer_tracks_for_adapter(
    *,
    adapter: Path,
    manifest: dict[str, Any],
    out_dir: Path,
    mode: str,
    prompt: str,
    fs: int,
    fs_config: str,
    clear_stale: bool,
    thinking: bool,
    thinking_tag: str,
) -> None:
    """Gap-fill / val infer for all tracks in one vLLM session."""
    corpus_base = _corpus_base(manifest, mode)
    env = vllm_env_for_adapter(adapter)
    env["SAST_PROMPT_VERSION"] = prompt
    env.setdefault("PYTHONPATH", f"{_sast}:{_sast / 'benchmark'}")
    css_gpu = os.environ.get("PHASE3_CSS_VLLM_GPU_UTIL", "").strip()
    if css_gpu:
        env["QWEN_VLLM_GPU_MEMORY_UTILIZATION"] = css_gpu

    if clear_stale:
        n_cleared = clear_invalid_val_runs(
            out_dir, manifest, mode, thinking=thinking_tag, fewshot=fs
        )
        if n_cleared:
            print(f"[css-retry] cleared {n_cleared} stale run dirs under {out_dir.name}", flush=True)

    tracks: list[dict[str, str]] = []
    for track, gold, case_dir in _val_tracks(manifest, corpus_base):
        runs_root = _track_runs_root(out_dir, track, thinking=thinking_tag, fewshot=fs)
        if not runs_root.is_dir() and clear_stale:
            print(f"[css-retry] skip {track}: no runs at {runs_root}", flush=True)
            continue
        tracks.append(
            {
                "gold": gold,
                "case_dir": str(case_dir.resolve()),
                "runs_root": str(runs_root.resolve()),
            }
        )
    if not tracks:
        print(f"[css-retry] no tracks to infer for {out_dir.name}", flush=True)
        return

    print(
        f"[css-retry] adapter={adapter.name} think={thinking_tag} fs={fs} "
        f"tracks={[t['gold'] for t in tracks]}",
        flush=True,
    )
    run_batch_tracks(
        tracks,
        env=env,
        sast_root=_sast,
        profile=PROFILE,
        thinking=thinking,
        few_shot=fs,
        few_shot_config=fs_config,
        prompt_version=prompt,
        retry_missing=True,
    )


def retry_missing_on_val_dir(
    *,
    adapter: Path,
    out_dir: Path,
    manifest: dict[str, Any],
    mode: str,
    thinking: str | None = None,
    fewshot: int | None = None,
) -> None:
    """Re-run only cases missing a valid triage result under an existing val eval tree."""
    icfg = manifest["inference_eval"]
    think, fs, fs_config, thinking_on = _infer_layout(
        manifest, thinking=thinking, fewshot=fewshot
    )
    _infer_tracks_for_adapter(
        adapter=adapter,
        manifest=manifest,
        out_dir=out_dir,
        mode=mode,
        prompt=icfg["prompt_version"],
        fs=fs,
        fs_config=fs_config,
        clear_stale=True,
        thinking=thinking_on,
        thinking_tag=think,
    )


def resummarize_val_css(
    *,
    out_dir: Path,
    manifest: dict[str, Any],
    adapter: Path,
    mode: str,
    lora_r: int | None = None,
    epoch: int | None = None,
    thinking: str | None = None,
    fewshot: int | None = None,
) -> dict[str, Any]:
    """Recompute SRS/VDR/FPRR/macro-F1/CSS from on-disk val runs (no inference)."""
    think, fs, _, _ = _infer_layout(manifest, thinking=thinking, fewshot=fewshot)
    corpus_base = _corpus_base(manifest, mode)
    summaries_dir = out_dir / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)

    fp_m = tp_m = bl_m = {}
    for track, gold, case_dir in _val_tracks(manifest, corpus_base):
        runs_root = _track_runs_root(out_dir, track, thinking=think, fewshot=fs)
        json_out = summaries_dir / f"comparison_{track}.json"
        m = _summarize_track(
            corpus_dir=case_dir,
            runs_root=runs_root,
            gold=gold,
            profile=PROFILE,
            json_out=json_out,
        )
        if gold == "FP":
            fp_m = m
        elif gold == "TP":
            tp_m = m
        else:
            bl_m = m

    n_val = manifest["dataset"]["val_n_expected"]
    if mode == "fast":
        n_val = int(manifest["performance"]["css_val_during_training"]["n_cases"])
    srs = compute_srs(fp_m, tp_m, bl_m or None, test_n=n_val)
    macro = macro_f1_from_track_f1s(
        float(fp_m.get("f1") or 0),
        float(tp_m.get("f1") or 0),
        float(bl_m.get("f1") or 0) if bl_m else None,
    )["macro_f1"]
    pack = {
        "srs": float(srs or 0),
        "vdr": float(tp_m.get("vdr") or tp_m.get("tp_rate") or 0),
        "fprr": float(fp_m.get("fprr") or fp_m.get("fp_removal_rate") or 0),
        "macro_f1": float(macro),
    }
    css_result = css_from_metrics_pack(pack)

    prev_path = out_dir / "css_result.json"
    prev: dict[str, Any] = {}
    if prev_path.is_file():
        try:
            prev = json.loads(prev_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    result = {
        "adapter": str(adapter.resolve()),
        "mode": mode,
        "lora_r": lora_r,
        "epoch": epoch,
        "thinking": think,
        "fewshot": fs,
        "metrics": pack,
        "css": css_result,
        "rescored": True,
        "previous_metrics": prev.get("metrics"),
        "previous_css": prev.get("css", {}).get("css"),
    }
    (out_dir / "css_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def run_val_eval(
    *,
    adapter: Path,
    manifest: dict[str, Any],
    out_dir: Path,
    mode: str,
    lora_r: int | None = None,
    epoch: int | None = None,
    thinking: str | None = None,
    fewshot: int | None = None,
) -> dict[str, Any]:
    icfg = manifest["inference_eval"]
    prompt = icfg["prompt_version"]
    think, fs, fs_config, thinking_on = _infer_layout(
        manifest, thinking=thinking, fewshot=fewshot
    )

    corpus_base = _corpus_base(manifest, mode)
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir = out_dir / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)

    _infer_tracks_for_adapter(
        adapter=adapter,
        manifest=manifest,
        out_dir=out_dir,
        mode=mode,
        prompt=prompt,
        fs=fs,
        fs_config=fs_config,
        clear_stale=False,
        thinking=thinking_on,
        thinking_tag=think,
    )

    fp_m = tp_m = bl_m = {}
    for track, gold, case_dir in _val_tracks(manifest, corpus_base):
        runs_root = _track_runs_root(out_dir, track, thinking=think, fewshot=fs)
        json_out = summaries_dir / f"comparison_{track}.json"
        m = _summarize_track(
            corpus_dir=case_dir,
            runs_root=runs_root,
            gold=gold,
            profile=PROFILE,
            json_out=json_out,
        )
        if gold == "FP":
            fp_m = m
        elif gold == "TP":
            tp_m = m
        else:
            bl_m = m

    n_val = manifest["dataset"]["val_n_expected"]
    if mode == "fast":
        n_val = int(manifest["performance"]["css_val_during_training"]["n_cases"])
    srs = compute_srs(fp_m, tp_m, bl_m or None, test_n=n_val)
    macro = macro_f1_from_track_f1s(
        float(fp_m.get("f1") or 0),
        float(tp_m.get("f1") or 0),
        float(bl_m.get("f1") or 0) if bl_m else None,
    )["macro_f1"]
    pack = {
        "srs": float(srs or 0),
        "vdr": float(tp_m.get("vdr") or tp_m.get("tp_rate") or 0),
        "fprr": float(fp_m.get("fprr") or fp_m.get("fp_removal_rate") or 0),
        "macro_f1": float(macro),
    }
    css_result = css_from_metrics_pack(pack)

    result = {
        "adapter": str(adapter.resolve()),
        "mode": mode,
        "lora_r": lora_r,
        "epoch": epoch,
        "thinking": think,
        "fewshot": fs,
        "metrics": pack,
        "css": css_result,
    }
    (out_dir / "css_result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--adapter", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--mode", choices=("fast", "full"), default=os.environ.get("PHASE3_CSS_VAL_MODE", "fast"))
    ap.add_argument("--lora-r", type=int, default=None)
    ap.add_argument("--epoch", type=int, default=None)
    ap.add_argument("--thinking", choices=("on", "off"), default=None)
    ap.add_argument("--fewshot", type=int, default=None)
    args = ap.parse_args()

    os.environ.setdefault("TORCHINDUCTOR_FX_GRAPH_REMOTE_CACHE", "0")
    try:
        from models.qwen.vllm_backend import kill_vllm_workers

        kill_vllm_workers()
    except Exception:
        pass

    manifest = load_manifest()
    result = run_val_eval(
        adapter=args.adapter,
        manifest=manifest,
        out_dir=args.out_dir,
        mode=args.mode,
        lora_r=args.lora_r,
        epoch=args.epoch,
        thinking=args.thinking,
        fewshot=args.fewshot,
    )
    print(
        f"[css] mode={result['mode']} think={result.get('thinking')} fs={result.get('fewshot')} "
        f"css={result['css']['css']:.4f} "
        f"srs={result['metrics']['srs']:.3f} vdr={result['metrics']['vdr']:.3f} "
        f"fprr={result['metrics']['fprr']:.3f} "
        f"eligible={not result['css']['disqualified']}"
    )


if __name__ == "__main__":
    main()
