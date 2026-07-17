#!/usr/bin/env python3
"""Score hard-slice latency ablation arms (accuracy + wall + tok/s)."""

from __future__ import annotations

import argparse
import json
import statistics as st
from pathlib import Path

SLICE = Path(__file__).resolve().parent / "smoke_slice_cases.json"


def _load_slice() -> dict[str, list[str]]:
    data = json.loads(SLICE.read_text(encoding="utf-8"))
    return {"TP": list(data["tp"]), "FP": list(data["fp"])}


def _pred_label(run_dir: Path) -> str | None:
    p = run_dir / "agent-llm-triage-result.json"
    if not p.is_file():
        return None
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("label") or "").upper() or None
    except Exception:
        return None


def _meta(run_dir: Path) -> dict:
    p = run_dir / "run_meta.json"
    if not p.is_file():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def summarize_cell_root(cell_root: Path) -> dict:
    gold_map = _load_slice()
    rows: list[dict] = []
    correct = 0
    total = 0
    recovered = 0
    for gold, ids in gold_map.items():
        for cid in ids:
            run_dir = cell_root / "llm" / cid
            # run_batch layout: runs_root/thinking_on/fewshot_N/profile/llm/case
            if not run_dir.is_dir():
                matches = list(cell_root.glob(f"**/llm/{cid}"))
                run_dir = matches[0] if matches else run_dir
            pred = _pred_label(run_dir)
            meta = _meta(run_dir)
            raw_path = run_dir / "llm_raw.txt"
            reason = ""
            res_path = run_dir / "agent-llm-triage-result.json"
            if res_path.is_file():
                try:
                    reason = str(json.loads(res_path.read_text(encoding="utf-8")).get("reason") or "")
                except Exception:
                    reason = ""
            if "Recovered" in reason:
                recovered += 1
            ok = pred == gold
            if pred is not None:
                total += 1
                if ok:
                    correct += 1
            out_tok = int(meta.get("output_tokens") or 0)
            inf = float(meta.get("inference_sec") or 0)
            tps = (out_tok / inf) if inf > 0 and out_tok > 0 else None
            rows.append(
                {
                    "case_id": cid,
                    "gold": gold,
                    "pred": pred,
                    "ok": ok,
                    "inference_sec": round(inf, 2) if inf else None,
                    "output_tokens": out_tok or None,
                    "tok_per_sec": round(tps, 2) if tps else None,
                    "recovered": "Recovered" in reason,
                    "has_raw": raw_path.is_file(),
                }
            )

    infs = [r["inference_sec"] for r in rows if r["inference_sec"]]
    outs = [r["output_tokens"] for r in rows if r["output_tokens"]]
    tpss = [r["tok_per_sec"] for r in rows if r["tok_per_sec"]]
    return {
        "n": total,
        "correct": correct,
        "accuracy": round(correct / total, 4) if total else None,
        "score_20": f"{correct}/{total}" if total else "0/0",
        "recovered_n": recovered,
        "inference_sec_p50": round(st.median(infs), 1) if infs else None,
        "inference_sec_mean": round(st.mean(infs), 1) if infs else None,
        "inference_sec_p90": round(sorted(infs)[max(0, int(0.9 * len(infs)) - 1)], 1) if infs else None,
        "output_tokens_p50": int(st.median(outs)) if outs else None,
        "tok_per_sec_p50": round(st.median(tpss), 1) if tpss else None,
        # Note: with vLLM micro-batch, run_meta inference_sec is batch_wall/n — tok/s is inflated.
        "cases": rows,
    }


def merge_all(eval_root: Path) -> dict:
    arms: list[dict] = []
    for cell_dir in sorted(p for p in eval_root.iterdir() if p.is_dir()):
        for arm_dir in sorted(p for p in cell_dir.iterdir() if p.is_dir()):
            summary_path = arm_dir / "arm_summary.json"
            if summary_path.is_file():
                arms.append(json.loads(summary_path.read_text(encoding="utf-8")))
                continue
            # synthesize if missing
            s = summarize_cell_root(arm_dir)
            s.update({"cell_id": cell_dir.name, "arm": arm_dir.name})
            arms.append(s)
    return {"n_arms": len(arms), "arms": arms}


def to_markdown(merged: dict) -> str:
    lines = [
        "# Latency budget ablation (hard slice, thinking ON)",
        "",
        "vLLM micro-batch shares wall time across cases — `tok_per_sec_p50` from run_meta can look high; "
        "prefer `inference_sec_p50` for per-case latency.",
        "",
        "| Cell | Arm | Score | Recovered | inf p50 (s) | inf p90 (s) | out_tok p50 | tok/s p50* |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for a in merged.get("arms") or []:
        lines.append(
            f"| {a.get('cell_id')} | {a.get('arm')} | {a.get('score_20')} | {a.get('recovered_n')} | "
            f"{a.get('inference_sec_p50')} | {a.get('inference_sec_p90')} | "
            f"{a.get('output_tokens_p50')} | {a.get('tok_per_sec_p50')} |"
        )
    lines.append("")
    lines.append("\\*Attributed tok/s from run_meta (batch-diluted).")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cell-root", type=Path)
    ap.add_argument("--cell-id")
    ap.add_argument("--arm")
    ap.add_argument("--think-cap", type=int)
    ap.add_argument("--short", type=int, default=0)
    ap.add_argument("--prompt")
    ap.add_argument("--merge-root", type=Path)
    ap.add_argument("--json-out", type=Path, required=True)
    ap.add_argument("--md-out", type=Path)
    args = ap.parse_args()

    if args.merge_root:
        merged = merge_all(args.merge_root.resolve())
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        if args.md_out:
            args.md_out.write_text(to_markdown(merged), encoding="utf-8")
        print(f"Wrote {args.json_out}", flush=True)
        if args.md_out:
            print(f"Wrote {args.md_out}", flush=True)
        return

    if not args.cell_root:
        raise SystemExit("--cell-root or --merge-root required")
    summary = summarize_cell_root(args.cell_root.resolve())
    summary.update(
        {
            "cell_id": args.cell_id,
            "arm": args.arm,
            "think_cap": args.think_cap,
            "short": bool(args.short),
            "prompt": args.prompt,
        }
    )
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"[{args.cell_id}/{args.arm}] {summary['score_20']} "
        f"inf_p50={summary['inference_sec_p50']}s out_p50={summary['output_tokens_p50']} "
        f"recovered={summary['recovered_n']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
