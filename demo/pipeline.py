"""Run triage for demo cases (Bedrock coder-30b by default)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from demo.bootstrap import SAST_ROOT, ensure_import_paths

ensure_import_paths()


def load_manifest() -> dict[str, Any]:
    return json.loads((SAST_ROOT / "demo" / "demo_manifest.json").read_text(encoding="utf-8"))


def list_models() -> list[dict[str, Any]]:
    return load_manifest().get("models", [])


def model_by_id(profile: str) -> dict[str, Any] | None:
    return next((m for m in list_models() if m["id"] == profile), None)


def configure_backend(profile: str) -> str:
    """Return backend label: bedrock | local."""
    meta = model_by_id(profile) or {}
    backend = meta.get("backend", "local")
    if profile == "qwen3_coder_30b_bnb" or backend == "bedrock":
        os.environ["QWEN3_CODER_BACKEND"] = "bedrock"
        return "bedrock"
    os.environ.pop("QWEN3_CODER_BACKEND", None)
    return "local"


def case_json_path(corpus: str, case_id: str) -> Path:
    return SAST_ROOT / "benchmark" / "corpora" / corpus / f"OWASP_{case_id}.json"


def load_case_entry(entry: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    path = case_json_path(entry["corpus"], entry["case_id"])
    if not path.is_file():
        raise FileNotFoundError(f"Case not found: {path}")
    case = json.loads(path.read_text(encoding="utf-8"))
    return path, case


def case_meta(entry: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    """Merge manifest entry with corpus metadata for triage/display."""
    return {
        "acceptable_labels": case.get("acceptable_labels")
        or entry.get("acceptable_labels")
        or (["TP", "FP", "BL"] if entry.get("gold") == "BL" else []),
        "borderline_rationale": case.get("borderline_rationale") or entry.get("borderline_rationale") or "",
    }


def codeql_alert_count(case: dict[str, Any]) -> int:
    raw = case.get("raw_output") or {}
    alerts = raw.get("CodeQL") if isinstance(raw, dict) else None
    return len(alerts) if isinstance(alerts, list) else 0


def codeql_rules(case: dict[str, Any]) -> list[str]:
    raw = case.get("raw_output") or {}
    alerts = raw.get("CodeQL") if isinstance(raw, dict) else []
    rules: list[str] = []
    for a in alerts if isinstance(alerts, list) else []:
        rid = a.get("ruleId") or (a.get("rule") or {}).get("id") or "?"
        rules.append(str(rid))
    return rules or ["unknown"]


def _candidate_paths(
    *,
    case_id: str,
    profile: str,
    prompt_version: str,
    fewshot: int,
    gold: str | None,
) -> list[Path]:
    paths: list[Path] = []
    gold_u = (gold or "").upper()

    # Demo cache + stage3 smoke (prompt-versioned)
    for root in (
        SAST_ROOT / "runs/demo/cache",
        SAST_ROOT / "runs/phase2/stage3/smoke",
    ):
        paths.append(
            root
            / "thinking_on"
            / f"fewshot_{fewshot}"
            / prompt_version
            / profile
            / "llm"
            / case_id
            / "agent-llm-triage-result.json"
        )

    # Stage 2 (v7 era, track-specific, no prompt in path)
    if gold_u == "TP":
        track = "tp"
    elif gold_u == "FP":
        track = "fp"
    elif gold_u == "BL":
        track = "bl"
    else:
        track = None
    if track:
        paths.append(
            SAST_ROOT
            / "runs/phase2/stage2"
            / track
            / "thinking_on"
            / f"fewshot_{fewshot}"
            / profile
            / "llm"
            / case_id
            / "agent-llm-triage-result.json"
        )

    return paths


def cached_result_path(
    *,
    case_id: str,
    profile: str,
    prompt_version: str,
    fewshot: int = 3,
    gold: str | None = None,
    smoke_root: Path | None = None,
) -> Path | None:
    profiles_to_try = [profile]

    extra: list[Path] = []
    if smoke_root is not None:
        extra.append(
            smoke_root
            / "thinking_on"
            / f"fewshot_{fewshot}"
            / prompt_version
            / profile
            / "llm"
            / case_id
            / "agent-llm-triage-result.json"
        )

    for prof in profiles_to_try:
        for p in extra + _candidate_paths(
            case_id=case_id,
            profile=prof,
            prompt_version=prompt_version,
            fewshot=fewshot,
            gold=gold,
        ):
            if p.is_file():
                return p
    return None


def load_cached_result(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_cached_outcomes(
    entries: list[dict[str, Any]],
    *,
    profile: str,
    prompt_version: str,
    fewshot: int,
) -> list[dict[str, Any]]:
    """Load cached triage for each case; returns list of outcome dicts."""
    rows = []
    for entry in entries:
        cid = entry["case_id"]
        cp = cached_result_path(
            case_id=cid,
            profile=profile,
            prompt_version=prompt_version,
            fewshot=fewshot,
            gold=entry.get("gold"),
        )
        if not cp:
            rows.append({"case_id": cid, "predicted": None, "source": "missing", "cache_path": None})
            continue
        data = load_cached_result(cp)
        source = "cached"
        meta_path = cp.parent / "cache_meta.json"
        if meta_path.is_file():
            source = "cached (seed)"
        rows.append(
            {
                "case_id": cid,
                "predicted": data.get("label"),
                "reason": data.get("reason", ""),
                "confidence": data.get("confidence", ""),
                "source": source,
                "cache_path": str(cp),
            }
        )
    return rows


def run_live_triage(
    *,
    case_path: Path,
    case: dict[str, Any],
    gold: str,
    profile: str,
    prompt_version: str,
    fewshot: int,
    few_shot_config: str,
    thinking: bool,
    run_dir: Path,
    repo: Path | None = None,
) -> dict[str, Any]:
    ensure_import_paths()
    configure_backend(profile)

    from benchmark.run_llm_local import run_triage_case

    run_dir.mkdir(parents=True, exist_ok=True)
    meta = run_triage_case(
        case_path=case_path,
        profile=profile,
        run_dir=run_dir,
        sast_root=SAST_ROOT,
        gold=gold,
        thinking=thinking,
        few_shot=fewshot,
        few_shot_config=few_shot_config,
        prompt_version=prompt_version,
        repo=repo,
        quiet=True,
    )
    result_path = run_dir / "agent-llm-triage-result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.is_file() else {}
    return {"meta": meta, "result": result}


def resolve_repo(case_path: Path, case: dict[str, Any], repo: Path | None) -> Path:
    ensure_import_paths()
    import repo_root as _repo

    return _repo.resolve_benchmark_java_root(SAST_ROOT, case, repo, case_path=case_path)
