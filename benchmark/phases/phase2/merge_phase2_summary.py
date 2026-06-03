#!/usr/bin/env python3
"""Merge Phase 2 per-cell comparison JSON files into one matrix."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summaries-dir", type=Path, required=True)
    ap.add_argument("--json-out", type=Path, required=True)
    args = ap.parse_args()

    sdir = args.summaries_dir.expanduser().resolve()
    cells: dict[str, dict] = {}
    for path in sorted(sdir.glob("comparison_*_test_thinking_*_fewshot_*.json")):
        name = path.stem.replace("comparison_", "")
        cells[name] = json.loads(path.read_text(encoding="utf-8"))

    out = {"cells": cells, "n_cells": len(cells)}
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"Wrote {args.json_out} ({len(cells)} cells)")


if __name__ == "__main__":
    main()
