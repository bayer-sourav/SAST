"""Run triage inference for GitHub advisory cases."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SAST = Path(__file__).resolve().parents[2]
if str(_SAST) not in sys.path:
    sys.path.insert(0, str(_SAST))

from integrations.github.config import inference_config, load_manifest, ui_label  # noqa: E402


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def triage_result_to_advisory(
    case: dict[str, Any],
    triage: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    manifest = manifest or load_manifest()
    infer = inference_config(manifest)
    meta = case.get("metadata") or {}
    label = str(triage.get("label") or "UNKNOWN").upper()
    advisory = {
        "label": label,
        "confidence": triage.get("confidence") or "low",
        "confidence_score": triage.get("confidence_score"),
        "reason": triage.get("reason") or "",
        "evidence": triage.get("evidence") or [],
        "ui_headline": ui_label(label, manifest),
    }
    return {
        "alert_fingerprint": meta.get("alert_fingerprint") or case.get("case_id"),
        "rule_id": meta.get("rule_id") or "unknown",
        "file": case.get("file") or "",
        "start_line": meta.get("start_line") or 1,
        "end_line": meta.get("end_line") or meta.get("start_line") or 1,
        "advisory": advisory,
        "provenance": {
            "model_profile": infer["profile"],
            "lora_checkpoint": infer.get("lora_adapter"),
            "prompt_version": infer["prompt_version"],
            "manifest_id": manifest.get("id", "github-advisory-v1"),
            "inferred_at": _utc_now(),
        },
    }


def run_cases(
    case_paths: list[Path],
    out_dir: Path,
    *,
    sast_root: Path | None = None,
) -> dict[str, Any]:
    from benchmark.run_llm_local import run_triage_case  # noqa: E402

    manifest = load_manifest()
    infer = inference_config(manifest)
    sast_root = (sast_root or _SAST).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    findings: list[dict[str, Any]] = []
    counts = {"TP": 0, "FP": 0, "BL": 0, "UNKNOWN": 0}

    for case_path in case_paths:
        case = json.loads(case_path.read_text(encoding="utf-8"))
        run_dir = out_dir / "runs" / case_path.stem
        run_dir.mkdir(parents=True, exist_ok=True)
        try:
            result = run_triage_case(
                case_path=case_path,
                profile=infer["profile"],
                run_dir=run_dir,
                sast_root=sast_root,
                thinking=bool(infer.get("thinking")),
                few_shot=int(infer.get("fewshot") or 0),
                few_shot_config=infer.get("few_shot_config"),
                prompt_version=infer["prompt_version"],
                repo=Path(case.get("repo_root") or "."),
                quiet=True,
            )
            triage = result.get("triage") or {}
        except Exception as exc:  # noqa: BLE001
            triage = {
                "label": "UNKNOWN",
                "confidence": "low",
                "reason": f"Triage failed: {exc}",
                "evidence": [],
            }
        advisory = triage_result_to_advisory(case, triage, manifest=manifest)
        label = advisory["advisory"]["label"]
        counts[label] = counts.get(label, 0) + 1
        findings.append(advisory)
        (out_dir / "findings" / f"{case_path.stem}.json").parent.mkdir(parents=True, exist_ok=True)
        (out_dir / "findings" / f"{case_path.stem}.json").write_text(
            json.dumps(advisory, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    summary = {
        "status": "completed",
        "n_cases": len(findings),
        "summary": counts,
        "findings": findings,
    }
    (out_dir / "job.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cases", required=True, help="Directory of case JSON files")
    ap.add_argument("--out", required=True, help="Output directory")
    ap.add_argument("--sast-root", default=str(_SAST))
    args = ap.parse_args()

    cases_dir = Path(args.cases).expanduser().resolve()
    case_paths = sorted(cases_dir.glob("*.json"))
    summary = run_cases(case_paths, Path(args.out).expanduser().resolve(), sast_root=Path(args.sast_root))
    print(json.dumps({"n_cases": summary["n_cases"], "summary": summary["summary"]}, indent=2))


if __name__ == "__main__":
    main()
