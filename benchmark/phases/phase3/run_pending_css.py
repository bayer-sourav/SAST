#!/usr/bin/env python3
"""Run deferred CSS val eval outside the training process (no GPU contention with Unsloth)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.phases.phase3._phase3b_common import load_manifest, output_path  # noqa: E402
from benchmark.phases.phase3.lora_disk_guard import ensure_disk_gb, prune_vllm_merged  # noqa: E402


def _css_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("QWEN_INFER_BACKEND", "vllm")
    env.pop("SAST_LORA_ADAPTER", None)
    env["TORCHINDUCTOR_FX_GRAPH_REMOTE_CACHE"] = "0"
    env["QWEN_VLLM_GPU_MEMORY_UTILIZATION"] = os.environ.get(
        "PHASE3_CSS_VLLM_GPU_UTIL", "0.75"
    )
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_sast), str(_sast / "benchmark"), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    return env


def _append_registry(registry_path: Path, *, adapter: Path, rank: int, epoch: int, result: dict) -> None:
    if result["css"]["disqualified"]:
        return
    reg: list[dict[str, Any]] = []
    if registry_path.is_file():
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
    adapter_s = str(adapter.resolve())
    if any(str(Path(e.get("adapter", "")).resolve()) == adapter_s for e in reg):
        print(f"[pending-css] registry already has {adapter.name}", flush=True)
        return
    reg.append(
        {
            "adapter": adapter_s,
            "rank": rank,
            "epoch": epoch,
            "css": float(result["css"]["css"]),
            "metrics": result["metrics"],
        }
    )
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(reg, indent=2), encoding="utf-8")


def _update_css_history(adapter_dir: Path, result: dict) -> None:
    hist_path = adapter_dir / "css_history.json"
    hist: list[dict] = []
    if hist_path.is_file():
        hist = json.loads(hist_path.read_text(encoding="utf-8"))
    hist.append(result)
    hist_path.write_text(json.dumps(hist, indent=2), encoding="utf-8")


def run_one(
    *,
    adapter: Path,
    out_dir: Path,
    epoch: int,
    rank: int,
    registry_path: Path,
    css_script: Path,
) -> bool:
    result_path = out_dir / "css_result.json"
    if result_path.is_file():
        print(f"[pending-css] reuse {result_path}", flush=True)
        result = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        cmd = [
            sys.executable,
            str(css_script),
            "--adapter",
            str(adapter),
            "--out-dir",
            str(out_dir),
            "--mode",
            os.environ.get("PHASE3_CSS_VAL_MODE", "fast"),
            "--lora-r",
            str(rank),
            "--epoch",
            str(epoch),
        ]
        print(f"[pending-css] epoch={epoch} adapter={adapter.name}", flush=True)
        min_disk = float(os.environ.get("PHASE3_MIN_DISK_GB", "25"))
        ensure_disk_gb(_sast, min_disk, lora_run_dir=adapter.parent)
        timeout = int(os.environ.get("PHASE3_CSS_TIMEOUT_SEC", "7200"))
        try:
            subprocess.run(
                cmd,
                cwd=str(_sast),
                env=_css_env(),
                check=True,
                start_new_session=True,
                timeout=timeout if timeout > 0 else None,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            print(f"[pending-css] failed epoch={epoch}: {exc}", flush=True)
            try:
                from models.qwen.vllm_backend import kill_vllm_workers

                kill_vllm_workers()
            except Exception:
                pass
            prune_vllm_merged(adapter.parent)
            return False
        finally:
            try:
                from models.qwen.vllm_backend import kill_vllm_workers

                kill_vllm_workers()
            except Exception:
                pass
            prune_vllm_merged(adapter.parent)
        if not result_path.is_file():
            print(f"[pending-css] no css_result.json after epoch={epoch}", flush=True)
            return False
        result = json.loads(result_path.read_text(encoding="utf-8"))

    _append_registry(registry_path, adapter=adapter, rank=rank, epoch=epoch, result=result)
    _update_css_history(adapter.parent, result)
    print(
        f"[pending-css] epoch={epoch} css={result['css']['css']:.4f} "
        f"eligible={not result['css']['disqualified']}",
        flush=True,
    )
    return True


def process_pending(*, lora_dir: Path, rank: int) -> int:
    pending_path = lora_dir / "pending_css.json"
    if not pending_path.is_file():
        return 0

    manifest = load_manifest()
    val_eval_root = output_path(manifest, "val_eval")
    registry_path = output_path(manifest, "summaries") / "css_eligible.json"
    css_script = _sast / "benchmark/phases/phase3/eval_val_for_css.py"
    items: list[dict] = json.loads(pending_path.read_text(encoding="utf-8"))
    remaining: list[dict] = []
    done = 0

    for item in items:
        epoch = int(item["epoch"])
        adapter = Path(item["adapter"]).expanduser().resolve()
        step = int(item.get("step") or adapter.name.rsplit("-", 1)[-1])
        out_dir = val_eval_root / f"r{rank}" / f"ckpt-{step}"

        if registry_path.is_file():
            reg = json.loads(registry_path.read_text(encoding="utf-8"))
            adapter_s = str(adapter.resolve())
            if any(str(Path(e.get("adapter", "")).resolve()) == adapter_s for e in reg):
                print(f"[pending-css] skip {adapter.name} (already in css_eligible.json)", flush=True)
                done += 1
                continue

        if run_one(
            adapter=adapter,
            out_dir=out_dir,
            epoch=epoch,
            rank=rank,
            registry_path=registry_path,
            css_script=css_script,
        ):
            done += 1
        else:
            remaining.append(item)

    if remaining:
        pending_path.write_text(json.dumps(remaining, indent=2), encoding="utf-8")
        print(f"[pending-css] {len(remaining)} item(s) still pending", flush=True)
    else:
        pending_path.unlink(missing_ok=True)
        print(f"[pending-css] cleared pending queue ({done} eval(s))", flush=True)
    return done


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lora-dir", type=Path, required=True)
    ap.add_argument("--rank", type=int, default=int(os.environ.get("PHASE3_LORA_R", "32")))
    args = ap.parse_args()
    n = process_pending(lora_dir=args.lora_dir.expanduser().resolve(), rank=args.rank)
    sys.exit(0 if n >= 0 else 1)


if __name__ == "__main__":
    main()
