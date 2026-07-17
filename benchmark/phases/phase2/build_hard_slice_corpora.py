#!/usr/bin/env python3
"""Build hard-slice case dirs (symlinks) from smoke_slice_cases.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

SLICE = Path(__file__).resolve().parent / "smoke_slice_cases.json"
OUT_TP = _sast / "benchmark" / "corpora" / "phase2_hard_slice_tp"
OUT_FP = _sast / "benchmark" / "corpora" / "phase2_hard_slice_fp"
SRC_TP = _sast / "benchmark" / "corpora" / "phase2_tp_test"
SRC_FP = _sast / "benchmark" / "corpora" / "phase2_fp_test"


def _link_slice(out_dir: Path, src_dir: Path, case_ids: list[str]) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("OWASP_*.json"):
        old.unlink()
    n = 0
    for cid in case_ids:
        src = src_dir / f"OWASP_{cid}.json"
        dst = out_dir / f"OWASP_{cid}.json"
        if not src.is_file():
            raise FileNotFoundError(src)
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(src.resolve())
        n += 1
    return n


def main() -> None:
    data = json.loads(SLICE.read_text(encoding="utf-8"))
    tp_ids = list(data["tp"])
    fp_ids = list(data["fp"])
    n_tp = _link_slice(OUT_TP, SRC_TP, tp_ids)
    n_fp = _link_slice(OUT_FP, SRC_FP, fp_ids)
    print(f"Hard slice corpora: {n_tp} TP -> {OUT_TP.relative_to(_sast)}")
    print(f"Hard slice corpora: {n_fp} FP -> {OUT_FP.relative_to(_sast)}")


if __name__ == "__main__":
    main()
