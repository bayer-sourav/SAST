#!/usr/bin/env python3
"""Retry missing val cases and recompute SRS / CSS for existing epoch eval trees."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.phases.phase3._phase3b_common import load_manifest, output_path  # noqa: E402
from benchmark.phases.phase3.eval_val_for_css import (  # noqa: E402
    PROFILE,
    _slm_metrics_from_comparison,
    clear_invalid_val_runs,
    resummarize_val_css,
    retry_missing_on_val_dir,
)


def _missing_counts(out_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    summaries = out_dir / "summaries"
    if not summaries.is_dir():
        return counts
    for path in sorted(summaries.glob("comparison_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        row = _slm_metrics_from_comparison(data, PROFILE)
        if row:
            counts[path.stem.replace("comparison_", "")] = int(row.get("missing") or 0)
    return counts


def _epoch_dirs(val_root: Path, epochs: list[int] | None) -> list[Path]:
    found = sorted(val_root.glob("epoch-*"), key=lambda p: int(p.name.split("-", 1)[1]))
    if not epochs:
        return found
    want = {int(e) for e in epochs}
    return [p for p in found if int(p.name.split("-", 1)[1]) in want]


def _load_epoch_meta(out_dir: Path) -> dict[str, Any]:
    css_path = out_dir / "css_result.json"
    if not css_path.is_file():
        raise FileNotFoundError(f"no css_result.json under {out_dir}")
    meta = json.loads(css_path.read_text(encoding="utf-8"))
    adapter = Path(meta["adapter"])
    if not adapter.is_dir():
        raise FileNotFoundError(f"adapter missing: {adapter}")
    return meta


def update_registry_and_best(
    results: list[dict[str, Any]],
    manifest: dict[str, Any],
    *,
    update_best: bool,
) -> dict[str, Any]:
    registry_path = output_path(manifest, "css_eligible_registry")
    eligible = [r for r in results if not r["css"]["disqualified"]]
    registry = [
        {
            "adapter": r["adapter"],
            "rank": r.get("lora_r"),
            "epoch": r.get("epoch"),
            "css": float(r["css"]["css"]),
            "metrics": r["metrics"],
        }
        for r in eligible
    ]
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")

    summary: dict[str, Any] = {
        "n_epochs": len(results),
        "n_eligible": len(eligible),
        "epochs": [
            {
                "epoch": r.get("epoch"),
                "css": float(r["css"]["css"]),
                "srs": r["metrics"]["srs"],
                "vdr": r["metrics"]["vdr"],
                "fprr": r["metrics"]["fprr"],
                "eligible": not r["css"]["disqualified"],
            }
            for r in sorted(results, key=lambda x: int(x.get("epoch") or 0))
        ],
    }

    if not eligible:
        summary["best"] = None
        return summary

    best = max(eligible, key=lambda r: float(r["css"]["css"]))
    summary["best"] = {
        "epoch": best.get("epoch"),
        "adapter": best["adapter"],
        "css": float(best["css"]["css"]),
        "metrics": best["metrics"],
    }

    if update_best:
        best_adapter = Path(best["adapter"])
        global_best = output_path(manifest, "global_best")
        if global_best.exists() or global_best.is_symlink():
            if global_best.is_symlink():
                global_best.unlink()
            elif global_best.is_dir():
                shutil.rmtree(global_best)
        shutil.copytree(best_adapter, global_best)
        summary["global_best_path"] = str(global_best.resolve())

    out = output_path(manifest, "summaries") / "css_rescore_summary.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _total_missing(counts: dict[str, int]) -> int:
    return sum(int(v) for v in counts.values())


def _rescore_epochs(
    *,
    val_root: Path,
    manifest: dict[str, Any],
    epochs: list[int] | None,
    mode: str | None,
    retry_missing: bool,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for out_dir in _epoch_dirs(val_root, epochs):
        meta = _load_epoch_meta(out_dir)
        adapter = Path(meta["adapter"])
        epoch_mode = mode or meta.get("mode") or "fast"
        epoch = meta.get("epoch")
        lora_r = meta.get("lora_r")

        before = _missing_counts(out_dir)
        print(
            f"[rescore] epoch={epoch} before missing={before} "
            f"css={meta.get('css', {}).get('css')}",
            flush=True,
        )

        if retry_missing:
            clear_invalid_val_runs(out_dir, manifest, epoch_mode)
            retry_missing_on_val_dir(
                adapter=adapter,
                out_dir=out_dir,
                manifest=manifest,
                mode=epoch_mode,
            )

        result = resummarize_val_css(
            out_dir=out_dir,
            manifest=manifest,
            adapter=adapter,
            mode=epoch_mode,
            lora_r=lora_r,
            epoch=epoch,
        )
        after = _missing_counts(out_dir)
        print(
            f"[rescore] epoch={epoch} after missing={after} "
            f"css={result['css']['css']:.4f} srs={result['metrics']['srs']:.3f} "
            f"vdr={result['metrics']['vdr']:.3f} fprr={result['metrics']['fprr']:.3f} "
            f"prev_css={result.get('previous_css')}",
            flush=True,
        )
        results.append(result)
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--val-root",
        type=Path,
        default=None,
        help="e.g. runs/phase3/stage3b/val_eval/r32",
    )
    ap.add_argument("--epochs", type=int, nargs="*", help="Subset of epochs (default: all epoch-* dirs)")
    ap.add_argument(
        "--mode",
        choices=("fast", "full"),
        default=None,
        help="Val corpus mode (default: from css_result.json per epoch)",
    )
    ap.add_argument(
        "--retry-missing",
        action="store_true",
        help="Re-infer cases without valid triage results before resummarizing",
    )
    ap.add_argument(
        "--resummarize-only",
        action="store_true",
        help="Skip inference; only re-read on-disk runs and recompute CSS",
    )
    ap.add_argument(
        "--update-best",
        action="store_true",
        help="Rewrite css_eligible.json and copy highest-CSS adapter to lora/best",
    )
    ap.add_argument(
        "--until-complete",
        type=int,
        default=0,
        metavar="N",
        help="With --retry-missing, repeat up to N rounds until zero missing (default 0=single pass)",
    )
    args = ap.parse_args()

    if args.retry_missing and args.resummarize_only:
        raise SystemExit("Use either --retry-missing or --resummarize-only, not both")

    manifest = load_manifest()
    val_root = args.val_root or (output_path(manifest, "val_eval") / "r32")
    val_root = val_root.expanduser().resolve()
    if not val_root.is_dir():
        raise FileNotFoundError(f"val root not found: {val_root}")

    results: list[dict[str, Any]] = []
    rounds = max(1, args.until_complete) if args.until_complete else 1
    for round_i in range(rounds):
        if args.until_complete and round_i > 0:
            print(f"[rescore] gap-fill round {round_i + 1}/{rounds}", flush=True)
        results = _rescore_epochs(
            val_root=val_root,
            manifest=manifest,
            epochs=args.epochs,
            mode=args.mode,
            retry_missing=args.retry_missing,
        )
        if not args.retry_missing or not args.until_complete:
            break
        total_miss = sum(_total_missing(_missing_counts(p)) for p in _epoch_dirs(val_root, args.epochs))
        print(f"[rescore] round {round_i + 1} total missing={total_miss}", flush=True)
        if total_miss == 0:
            break

    if not results:
        raise SystemExit(f"no epoch dirs under {val_root}")

    summary = update_registry_and_best(results, manifest, update_best=args.update_best)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
