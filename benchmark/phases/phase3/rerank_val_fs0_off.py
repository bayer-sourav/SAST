#!/usr/bin/env python3
"""Full validation rerank under fs0_off ship config; pick best epoch by val SRS."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.phases.phase3._phase3b_common import load_manifest, output_path  # noqa: E402
from benchmark.phases.phase3.eval_val_for_css import resummarize_val_css  # noqa: E402

CSS_SCRIPT = _sast / "benchmark/phases/phase3/eval_val_for_css.py"
STAGE2_SRS = 0.925


def _epoch_sources(val_root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for epoch_dir in sorted(val_root.glob("epoch-*"), key=lambda p: int(p.name.split("-", 1)[1])):
        css_path = epoch_dir / "css_result.json"
        if not css_path.is_file():
            continue
        meta = json.loads(css_path.read_text(encoding="utf-8"))
        adapter = Path(meta["adapter"])
        if not adapter.is_dir():
            print(f"[fs0-rerank] skip missing adapter {adapter}", file=sys.stderr)
            continue
        out.append(
            {
                "epoch": int(meta.get("epoch") or epoch_dir.name.split("-", 1)[1]),
                "adapter": adapter,
                "lora_r": meta.get("lora_r"),
                "fs3_css": (meta.get("css") or {}).get("css"),
                "fs3_srs": (meta.get("metrics") or {}).get("srs"),
            }
        )
    return out


def _run_epoch_val(
    *,
    entry: dict[str, Any],
    out_dir: Path,
    mode: str,
    skip_infer: bool,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    if not skip_infer or not (out_dir / "css_result.json").is_file():
        cmd = [
            sys.executable,
            str(CSS_SCRIPT),
            "--adapter",
            str(entry["adapter"]),
            "--out-dir",
            str(out_dir),
            "--mode",
            mode,
            "--lora-r",
            str(entry.get("lora_r") or 32),
            "--epoch",
            str(entry["epoch"]),
            "--thinking",
            "off",
            "--fewshot",
            "0",
        ]
        subprocess.run(cmd, cwd=str(_sast), check=True)
    manifest = load_manifest()
    return resummarize_val_css(
        out_dir=out_dir,
        manifest=manifest,
        adapter=entry["adapter"],
        mode=mode,
        lora_r=entry.get("lora_r"),
        epoch=entry["epoch"],
        thinking="off",
        fewshot=0,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--val-root",
        type=Path,
        default=_sast / "runs/phase3/stage3b/val_eval/r32",
    )
    ap.add_argument(
        "--out-root",
        type=Path,
        default=_sast / "runs/phase3/stage3b/val_eval/r32_fs0_off",
    )
    ap.add_argument("--epochs", type=int, nargs="*", help="Subset (default: all epoch-* with css_result)")
    ap.add_argument("--mode", choices=("fast", "full"), default="full")
    ap.add_argument(
        "--pick-by",
        choices=("srs", "css"),
        default="srs",
        help="Ship proxy metric on fs0_off val (default srs)",
    )
    ap.add_argument(
        "--update-best",
        action="store_true",
        help="Copy best epoch adapter to runs/phase3/stage3b/lora/best_fs0_off",
    )
    ap.add_argument(
        "--resummarize-only",
        action="store_true",
        help="Skip inference if css_result.json exists; recompute summaries only",
    )
    args = ap.parse_args()

    manifest = load_manifest()
    val_root = args.val_root.expanduser().resolve()
    out_root = args.out_root.expanduser().resolve()
    out_root.mkdir(parents=True, exist_ok=True)

    sources = _epoch_sources(val_root)
    if args.epochs:
        want = {int(e) for e in args.epochs}
        sources = [s for s in sources if s["epoch"] in want]
    if not sources:
        raise SystemExit(f"no epoch adapters under {val_root}")

    results: list[dict[str, Any]] = []
    for entry in sources:
        epoch = entry["epoch"]
        out_dir = out_root / f"epoch-{epoch}"
        print(
            f"[fs0-rerank] epoch={epoch} adapter={entry['adapter'].name} "
            f"fs3_css={entry.get('fs3_css')}",
            flush=True,
        )
        result = _run_epoch_val(
            entry=entry,
            out_dir=out_dir,
            mode=args.mode,
            skip_infer=args.resummarize_only,
        )
        result["fs3_css"] = entry.get("fs3_css")
        result["fs3_srs"] = entry.get("fs3_srs")
        results.append(result)
        m = result["metrics"]
        print(
            f"[fs0-rerank] epoch={epoch} val SRS={m['srs']:.4f} "
            f"VDR={m['vdr']:.3f} FPRR={m['fprr']:.3f} CSS={result['css']['css']:.4f}",
            flush=True,
        )

    key = args.pick_by
    best = max(results, key=lambda r: float(r["metrics"][key]))
    best_epoch = best.get("epoch")
    best_adapter = Path(best["adapter"])

    summary = {
        "infer_config": {"thinking": "off", "fewshot": 0, "prompt": "v7-ship"},
        "pick_by": key,
        "mode": args.mode,
        "n_epochs": len(results),
        "epochs": [
            {
                "epoch": r.get("epoch"),
                "adapter": r["adapter"],
                "fs3_css": r.get("fs3_css"),
                "fs3_srs": r.get("fs3_srs"),
                "val_srs": r["metrics"]["srs"],
                "val_vdr": r["metrics"]["vdr"],
                "val_fprr": r["metrics"]["fprr"],
                "val_css": r["css"]["css"],
            }
            for r in sorted(results, key=lambda x: int(x.get("epoch") or 0))
        ],
        "best": {
            "epoch": best_epoch,
            "adapter": str(best_adapter.resolve()),
            "val_srs": best["metrics"]["srs"],
            "val_vdr": best["metrics"]["vdr"],
            "val_fprr": best["metrics"]["fprr"],
            "val_css": best["css"]["css"],
            "prior_best_epoch": 6,
            "stage2_test_srs": STAGE2_SRS,
        },
    }

    sum_path = output_path(manifest, "summaries") / "css_fs0_off_rerank.json"
    sum_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    if args.update_best:
        best_out = output_path(manifest, "global_best").parent / "best_fs0_off"
        if best_out.exists() or best_out.is_symlink():
            if best_out.is_symlink():
                best_out.unlink()
            elif best_out.is_dir():
                shutil.rmtree(best_out)
        shutil.copytree(best_adapter, best_out)
        summary["best_fs0_off_path"] = str(best_out.resolve())

    print(json.dumps(summary, indent=2), flush=True)
    print(
        f"[fs0-rerank] best epoch={best_epoch} by val {key}={best['metrics'][key]:.4f} "
        f"(prior fs3-on pick was epoch 6)",
        flush=True,
    )


if __name__ == "__main__":
    main()
