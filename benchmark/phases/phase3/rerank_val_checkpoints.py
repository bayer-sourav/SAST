#!/usr/bin/env python3
"""Re-run full validation on all CSS-eligible checkpoints; pick global best."""

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

from benchmark.phases.phase3._phase3b_common import load_manifest, output_path  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="css_eligible.json from training (default: manifest path).",
    )
    args = ap.parse_args()

    manifest = load_manifest()
    registry_path = args.registry or output_path(manifest, "css_eligible_registry")
    if not registry_path.is_file():
        raise FileNotFoundError(f"no CSS registry at {registry_path}")

    entries = json.loads(registry_path.read_text(encoding="utf-8"))
    if not entries:
        raise SystemExit("CSS registry empty — no eligible checkpoints")

    rerank_root = output_path(manifest, "val_eval") / "rerank"
    rerank_root.mkdir(parents=True, exist_ok=True)
    css_script = _sast / "benchmark/phases/phase3/eval_val_for_css.py"
    confirmed: list[dict] = []

    for i, entry in enumerate(entries):
        adapter = Path(entry["adapter"])
        if not adapter.is_dir():
            print(f"[rerank] skip missing {adapter}", file=sys.stderr)
            continue
        out_dir = rerank_root / f"ckpt_{i:03d}_r{entry.get('rank')}_e{entry.get('epoch')}"
        cmd = [
            sys.executable,
            str(css_script),
            "--adapter",
            str(adapter),
            "--out-dir",
            str(out_dir),
            "--mode",
            "full",
            "--lora-r",
            str(entry.get("rank", "")),
            "--epoch",
            str(entry.get("epoch", "")),
        ]
        subprocess.run(cmd, cwd=str(_sast), check=True)
        result = json.loads((out_dir / "css_result.json").read_text(encoding="utf-8"))
        confirmed.append(result)

    best = max(confirmed, key=lambda r: float(r["css"]["css"]))
    best_adapter = Path(best["adapter"])
    global_best = output_path(manifest, "global_best")
    if global_best.exists() or global_best.is_symlink():
        if global_best.is_symlink():
            global_best.unlink()
        elif global_best.is_dir():
            shutil.rmtree(global_best)
    shutil.copytree(best_adapter, global_best)

    summary = {
        "n_reranked": len(confirmed),
        "best": best,
        "global_best_path": str(global_best.resolve()),
    }
    out = output_path(manifest, "summaries") / "css_rerank_best.json"
    out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"[rerank] best css={best['css']['css']:.4f} adapter={best_adapter} -> {global_best}"
    )


if __name__ == "__main__":
    main()
