#!/usr/bin/env python3
"""Emit CodeQL-only triage JSONs from the TP-retention OWASP corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--src",
        type=Path,
        help=(
            "TP triage folder (default: sibling SAST-Paper-Artifacts/"
            "Discussion (TP Retention)/triage-owasp-benchmark-tp)"
        ),
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "tp_codeql_only",
        help="Output directory",
    )
    args = ap.parse_args()

    sast_root = Path(__file__).resolve().parent.parent
    src = args.src
    if src is None:
        src = (
            sast_root.parent
            / "SAST-Paper-Artifacts"
            / "Discussion (TP Retention)"
            / "triage-owasp-benchmark-tp"
        )

    src = src.expanduser().resolve()
    out = args.out.expanduser().resolve()
    if not src.is_dir():
        raise SystemExit(f"Missing source dir: {src}")

    out.mkdir(parents=True, exist_ok=True)
    n_in = 0
    n_out = 0
    for p in sorted(src.glob("*.json")):
        n_in += 1
        case = json.loads(p.read_text(encoding="utf-8"))
        raw = case.get("raw_output") or {}
        if not isinstance(raw, dict) or "CodeQL" not in raw:
            continue
        case["tool"] = ["CodeQL"]
        case["raw_output"] = {"CodeQL": raw["CodeQL"]}
        (out / p.name).write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
        n_out += 1

    print(f"Wrote {n_out} cases (skipped {n_in - n_out} without CodeQL) -> {out}")


if __name__ == "__main__":
    main()
