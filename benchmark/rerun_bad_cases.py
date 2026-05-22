#!/usr/bin/env python3
"""Force re-run triage cases with thinking leakage or missing/invalid JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VALID_LABELS = frozenset({"TP", "FP", "UNKNOWN"})


def _needs_rerun(case_dir: Path) -> tuple[bool, str]:
    raw_path = case_dir / "llm_raw.txt"
    result_path = case_dir / "agent-llm-triage-result.json"
    if raw_path.is_file():
        head = raw_path.read_text(encoding="utf-8", errors="replace").lstrip()[:200]
        if head.startswith("<think>"):
            return True, "thinking_in_raw"
    meta_path = case_dir / "run_meta.json"
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if meta.get("thinking") is False and meta.get("output_tokens") == 1024:
                return True, "hit_max_tokens_1024"
            err = str(meta.get("error", "")).lower()
            if "acceleratorerror" in err or "device-side assert" in err:
                return True, "cuda_assert"
            if meta.get("returncode", 0) != 0 and not result_path.is_file():
                return True, "failed_run_meta"
            if "calledprocesserror" in err or "make_task.py failed" in err:
                return True, "make_task_failed"
            if "no json object" in err or "valueerror" in err:
                return True, "no_json"
        except json.JSONDecodeError:
            pass
    if not result_path.is_file():
        return True, "missing_result"
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True, "invalid_result_json"
    lbl = str(data.get("label", "")).strip().upper()
    if lbl not in VALID_LABELS:
        return True, "bad_label"
    return False, "ok"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--runs-root", type=Path, required=True)
    ap.add_argument("--profile", required=True)
    ap.add_argument("--case-dir", type=Path, required=True)
    ap.add_argument("--gold", choices=("FP", "TP"), required=True)
    ap.add_argument("--thinking", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    sast_root = Path(__file__).resolve().parent.parent
    bench = Path(__file__).resolve().parent
    llm_root = args.runs_root / args.profile.replace("/", "_") / "llm"
    if not llm_root.is_dir():
        raise SystemExit(f"Missing {llm_root}")

    case_files = {
        json.loads(p.read_text(encoding="utf-8")).get("case_id") or p.stem: p
        for p in sorted(args.case_dir.glob("*.json"))
        if p.name != "slice_manifest.json"
    }

    to_run: list[tuple[str, str, Path]] = []
    for case_dir in sorted(llm_root.iterdir()):
        if not case_dir.is_dir():
            continue
        cid = case_dir.name
        bad, reason = _needs_rerun(case_dir)
        if bad:
            case_path = case_files.get(cid)
            if case_path:
                to_run.append((cid, reason, case_path))

    print(f"Profile={args.profile} gold={args.gold} thinking={args.thinking}")
    print(f"Re-run candidates: {len(to_run)} / {len(case_files)}")
    for cid, reason, _ in to_run[:20]:
        print(f"  {cid}: {reason}")
    if len(to_run) > 20:
        print(f"  ... +{len(to_run) - 20} more")

    if args.dry_run or not to_run:
        return

    eval_fw = (sast_root.parent / "SAST-Paper-Artifacts" / "Evaluation Framework").resolve()
    if str(sast_root) not in sys.path:
        sys.path.insert(0, str(sast_root))
    from benchmark.run_llm_local import run_triage_case  # noqa: E402

    for cid, reason, case_path in to_run:
        run_dir = llm_root / cid
        print(f"[rerun] {cid} ({reason})")
        run_triage_case(
            case_path=case_path.resolve(),
            profile=args.profile,
            run_dir=run_dir.resolve(),
            sast_root=sast_root,
            eval_fw=eval_fw,
            gold=args.gold,
            thinking=args.thinking,
            quiet=True,
        )


if __name__ == "__main__":
    main()
