#!/usr/bin/env python3
"""Export teacher-distillation JSONL from Stage 2 teacher cache (train split)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_sast = Path(__file__).resolve().parents[3]
if str(_sast) not in sys.path:
    sys.path.insert(0, str(_sast))

from benchmark.build_phase2_corpora import _dataset_root  # noqa: E402
from benchmark.make_task import build_task_markdown, stable_case_id  # noqa: E402
from benchmark.phases.phase3._phase3b_common import load_manifest, output_path, teacher_run_dir  # noqa: E402
from benchmark.phases.phase3.export_sft_dataset import (  # noqa: E402
    _TRACKS,
    _gold_label,
    _phase2_test_ids_by_track,
    _split_entries,
)
from benchmark.run_llm_local import _SYSTEM_PROMPT  # noqa: E402
from core.parsing import extract_json_object  # noqa: E402

_JSON_TAIL_RE = re.compile(r"\{[\s\S]*\}\s*\Z")


def _load_tokenizer():
    try:
        from transformers import AutoTokenizer

        model_id = os.environ.get("PHASE3_BASE_MODEL", "unsloth/Qwen3.5-9B")
        return AutoTokenizer.from_pretrained(model_id, trust_remote_code=True)
    except Exception:
        return None


def _count_tokens(tok, text: str) -> int:
    if tok is None:
        return max(1, len(text) // 3.5)
    return len(tok.encode(text, add_special_tokens=False))


def _truncate_assistant(raw: str, *, max_tokens: int, tok) -> str:
    """Preserve JSON tail; trim thinking prefix if over budget."""
    raw = raw.strip()
    if not raw:
        return raw
    if _count_tokens(tok, raw) <= max_tokens:
        return raw

    m = _JSON_TAIL_RE.search(raw)
    json_part = m.group(0).strip() if m else ""
    thinking_part = raw[: m.start()].strip() if m else raw
    json_tok = _count_tokens(tok, json_part) if json_part else 0
    budget = max(256, max_tokens - json_tok)
    if _count_tokens(tok, thinking_part) <= budget:
        return f"{thinking_part}\n{json_part}".strip() if json_part else thinking_part

    # Trim thinking from the middle
    words = thinking_part.split()
    lo, hi = 0, len(words)
    best = thinking_part[: max(1, budget * 4)]  # char fallback
    while lo < hi:
        mid = (lo + hi) // 2
        chunk = " ".join(words[:mid])
        if _count_tokens(tok, chunk) <= budget:
            best = chunk
            lo = mid + 1
        else:
            hi = mid
    trimmed = best.rstrip() + "\n...[truncated]...\n"
    return f"{trimmed}{json_part}".strip() if json_part else trimmed.strip()


def _read_teacher_assistant(run_dir: Path) -> str | None:
    raw_path = run_dir / "llm_raw.txt"
    if raw_path.is_file():
        return raw_path.read_text(encoding="utf-8", errors="replace").strip()
    result_path = run_dir / "agent-llm-triage-result.json"
    if result_path.is_file():
        return result_path.read_text(encoding="utf-8").strip()
    return None


def _teacher_json_compact(run_dir: Path) -> str | None:
    """Prefer parsed triage result; fall back to JSON tail in llm_raw."""
    result_path = run_dir / "agent-llm-triage-result.json"
    if result_path.is_file():
        try:
            doc = json.loads(result_path.read_text(encoding="utf-8"))
            payload: dict[str, Any] = {}
            for key in ("label", "confidence", "confidence_score", "reason", "evidence"):
                if key in doc and doc[key] is not None:
                    payload[key] = doc[key]
            if payload.get("label"):
                return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            pass
    raw = _read_teacher_assistant(run_dir)
    if not raw:
        return None
    try:
        parsed = extract_json_object(raw)
        return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        m = _JSON_TAIL_RE.search(raw)
        if not m:
            return None
        try:
            parsed = json.loads(m.group(0))
            return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return None


def _assistant_content(raw: str, *, target: str, run_dir: Path | None = None) -> str | None:
    """Build training assistant turn from teacher output."""
    if target == "json_only":
        if run_dir is not None:
            compact = _teacher_json_compact(run_dir)
            if compact:
                return compact
        return None
    raw = raw.strip()
    if not raw:
        return None
    return raw


def export_distill(
    *,
    dataset: Path,
    manifest: dict[str, Any],
    out_path: Path,
    max_thinking_tokens: int,
    max_total_tokens: int,
) -> dict[str, Any]:
    tok = _load_tokenizer()
    train_cfg = manifest["train_prompt"]
    supervision = manifest.get("supervision") or {}
    target = str(supervision.get("target") or "teacher_assistant_turn")
    use_cot_target = target == "teacher_assistant_turn"
    test_ids = _phase2_test_ids_by_track(_sast)
    records: list[dict] = []
    dropped: list[dict] = []
    stats = {"missing_teacher": 0, "unparseable_teacher": 0, "too_long": 0, "leak": 0}

    for cls, _ in _TRACKS:
        mpath = dataset / cls / "manifest.json"
        entries = _split_entries(json.loads(mpath.read_text(encoding="utf-8")), "train")
        track_test = test_ids.get(cls) or set()
        for row in entries:
            cid = row["case_id"]
            if cid in track_test:
                stats["leak"] += 1
                dropped.append({"case_id": cid, "reason": "phase2_test_leak"})
                continue
            bundle = (dataset / row["bundle"]).resolve()
            case = json.loads((bundle / "case.json").read_text(encoding="utf-8"))
            run_dir = teacher_run_dir(manifest, case_id=cid, track=cls)
            assistant = _read_teacher_assistant(run_dir)
            if not assistant:
                stats["missing_teacher"] += 1
                dropped.append({"case_id": cid, "reason": "missing_teacher"})
                continue

            if use_cot_target:
                assistant = _truncate_assistant(
                    assistant,
                    max_tokens=max_thinking_tokens + 800,
                    tok=tok,
                )
            else:
                compact = _assistant_content(assistant, target=target, run_dir=run_dir)
                if not compact:
                    stats["unparseable_teacher"] += 1
                    dropped.append({"case_id": cid, "reason": "unparseable_teacher_json"})
                    continue
                assistant = compact
            user_text = build_task_markdown(
                case=case,
                repo_root=bundle,
                scan_root=case.get("scan_root") or ".",
                agent="llm",
                few_shot=train_cfg["fewshot"],
                few_shot_config=train_cfg["few_shot_config"],
                prompt_version=train_cfg["prompt_version"],
            )
            user_tok = _count_tokens(tok, _SYSTEM_PROMPT + user_text)
            asst_tok = _count_tokens(tok, assistant)
            if user_tok + asst_tok > max_total_tokens:
                stats["too_long"] += 1
                dropped.append({"case_id": cid, "reason": "exceeds_max_total_tokens", "tokens": user_tok + asst_tok})
                continue

            try:
                parsed = extract_json_object(assistant)
                teacher_label = str(parsed.get("label", "")).upper()
            except Exception:
                teacher_label = _gold_label(cls)

            records.append(
                {
                    "case_id": cid,
                    "gold_label": _gold_label(cls),
                    "teacher_label": teacher_label,
                    "bundle": str(bundle),
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_text},
                        {"role": "assistant", "content": assistant},
                    ],
                }
            )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    meta = {
        "n_records": len(records),
        "n_dropped": len(dropped),
        "stats": stats,
        "max_thinking_tokens": max_thinking_tokens,
        "max_total_tokens": max_total_tokens,
        "supervision_target": target,
        "prompt_version": train_cfg["prompt_version"],
        "out_path": str(out_path),
    }
    out_path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    drop_path = out_path.parent / "distill_dropped.json"
    drop_path.write_text(json.dumps(dropped, indent=2), encoding="utf-8")
    return meta


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--split", choices=("train",), default="train")
    ap.add_argument(
        "--max-thinking-tokens",
        type=int,
        default=int(os.environ.get("PHASE3_MAX_THINKING_TOKENS", "4096")),
    )
    ap.add_argument(
        "--max-total-tokens",
        type=int,
        default=int(os.environ.get("PHASE3_MAX_SEQ_LEN", "16384")),
    )
    args = ap.parse_args()

    manifest = load_manifest()
    out_path = output_path(manifest, "sft_data") / f"distill_{args.split}.jsonl"
    meta = export_distill(
        dataset=_dataset_root(None),
        manifest=manifest,
        out_path=out_path,
        max_thinking_tokens=args.max_thinking_tokens,
        max_total_tokens=args.max_total_tokens,
    )
    print(
        f"[distill] {meta['n_records']} records -> {out_path} "
        f"(dropped={meta['n_dropped']} stats={meta['stats']})"
    )


if __name__ == "__main__":
    main()
