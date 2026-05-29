#!/usr/bin/env python3
"""Re-parse llm_raw.txt into agent-llm-triage-result.json (no model re-run)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

AGENT = "llm"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, default=Path("runs"))
    ap.add_argument("--profile", default="qwen3_4b_bnb")
    ap.add_argument("--agent", default=AGENT)
    args = ap.parse_args()

    sast_root = Path(__file__).resolve().parent.parent
    if str(sast_root) not in sys.path:
        sys.path.insert(0, str(sast_root))

    from benchmark.run_llm_local import _extract_json_object

    root = args.runs / args.profile.replace("/", "_") / args.agent
    fixed = failed = 0
    for case_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        raw_path = case_dir / "llm_raw.txt"
        out_path = case_dir / f"agent-{AGENT}-triage-result.json"
        if not raw_path.is_file():
            continue
        if out_path.is_file():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                lbl = str(existing.get("label", "")).strip().upper()
                if lbl in {"TP", "FP", "BL", "UNKNOWN"}:
                    continue
            except json.JSONDecodeError:
                pass
        try:
            result = _extract_json_object(raw_path.read_text(encoding="utf-8"))
            result.setdefault("agent", AGENT)
            result.setdefault("case_id", case_dir.name)
            out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"fixed {case_dir.name}")
            fixed += 1
        except Exception as exc:
            print(f"failed {case_dir.name}: {exc}")
            failed += 1
    print(f"done: fixed={fixed} still_failed={failed}")


if __name__ == "__main__":
    main()
