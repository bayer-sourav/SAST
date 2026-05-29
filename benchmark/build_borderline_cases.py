#!/usr/bin/env python3
"""Build borderline CodeQL corpus (weak/bypassable sanitization, ambiguous FP vs TP)."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import defaultdict
from pathlib import Path

INJECTION_CATS = frozenset({"xss", "sqli", "cmdi", "ldapi", "pathtraver"})
SAN_RE = re.compile(
    r"encode|sanitize|escape|ESAPI|Pattern\.compile|replaceAll|"
    r"Normalizer|HtmlUtils|StringEscapeUtils|OWASP",
    re.I,
)


def _load_truth(csv_path: Path) -> dict[str, dict[str, str]]:
    truth: dict[str, dict[str, str]] = {}
    with csv_path.open(newline="", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = [p.strip() for p in line.strip().split(",")]
            if len(parts) < 3 or parts[0] == "test name":
                continue
            truth[parts[0]] = {
                "category": parts[1].lower(),
                "real_vuln": parts[2].lower() == "true",
                "cwe": parts[3] if len(parts) > 3 else "",
            }
    return truth


def _cwe_bucket(case: dict, truth: dict[str, dict[str, str]]) -> str:
    cid = str(case.get("case_id", ""))
    tr = truth.get(cid)
    if tr and tr.get("cwe"):
        return f"cwe-{tr['cwe']}"
    raw = case.get("raw_output") or {}
    if isinstance(raw, dict):
        for entries in raw.values():
            if isinstance(entries, list) and entries:
                first = entries[0] if isinstance(entries[0], dict) else {}
                rule_id = str(first.get("ruleId", "") or "")
                if "/" in rule_id:
                    return rule_id.split("/")[-1].lower()
                if rule_id:
                    return rule_id.lower()
    return "unknown"


def _has_sanitization(bench_root: Path, case: dict) -> bool:
    rel = case.get("file")
    if not rel:
        return False
    src = bench_root / str(rel)
    if not src.is_file():
        return False
    return bool(SAN_RE.search(src.read_text(encoding="utf-8", errors="replace")))


def _strict_candidates(
    *,
    fp_dir: Path,
    tp_dir: Path,
    bench_root: Path,
    truth: dict[str, dict[str, str]],
) -> list[tuple[Path, dict, str]]:
    """Return (source_path, case_dict, tier_note)."""
    out: list[tuple[Path, dict, str]] = []
    seen: set[str] = set()

    def consider(p: Path, *, prefer: str) -> None:
        case = json.loads(p.read_text(encoding="utf-8"))
        cid = str(case.get("case_id") or p.stem)
        if cid in seen:
            return
        tr = truth.get(cid)
        if not tr or tr["category"] not in INJECTION_CATS:
            return
        if not _has_sanitization(bench_root, case):
            return
        real = tr["real_vuln"]
        if prefer == "tp" and not real:
            return
        if prefer == "fp" and real:
            return
        seen.add(cid)
        note = (
            "benchmark_real_vuln_with_partial_sanitization"
            if real
            else "codeql_fp_with_sanitization_present"
        )
        out.append((p, case, note))

    for p in sorted(tp_dir.glob("*.json")):
        if p.name == "slice_manifest.json":
            continue
        consider(p, prefer="tp")
    for p in sorted(fp_dir.glob("*.json")):
        if p.name == "slice_manifest.json":
            continue
        consider(p, prefer="fp")

    return out


def _select_balanced(
    items: list[tuple[Path, dict, str]],
    *,
    n: int,
    seed: int,
    truth: dict[str, dict[str, str]],
) -> list[tuple[Path, dict, str]]:
    import sys

    bench_dir = Path(__file__).resolve().parent
    if str(bench_dir) not in sys.path:
        sys.path.insert(0, str(bench_dir))
    from select_balanced_cases import select_balanced  # noqa: E402

    paths = [t[0] for t in items]
    picked_paths = set(select_balanced(paths, n=n, seed=seed))
    return [t for t in items if t[0] in picked_paths][:n]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fp-dir", type=Path, default=Path("benchmark/corpora/fp_codeql"))
    ap.add_argument("--tp-dir", type=Path, default=Path("benchmark/corpora/tp_codeql"))
    ap.add_argument(
        "--bench-root",
        type=Path,
        default=None,
        help="BenchmarkJava root (default: ../BenchmarkJava)",
    )
    ap.add_argument(
        "--expected-csv",
        type=Path,
        default=None,
        help="expectedresults-1.2.csv",
    )
    ap.add_argument("--out", type=Path, default=Path("benchmark/corpora/borderline_n200_seed42"))
    ap.add_argument("-n", "--count", type=int, default=200)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument(
        "--full-strict-pool",
        action="store_true",
        help="Write all strict candidates (no balanced subsample)",
    )
    args = ap.parse_args()

    sast = Path(__file__).resolve().parent.parent
    fp_dir = (sast / args.fp_dir).resolve()
    tp_dir = (sast / args.tp_dir).resolve()
    bench = (args.bench_root or sast.parent / "BenchmarkJava").expanduser().resolve()
    csv_path = (args.expected_csv or bench / "expectedresults-1.2.csv").resolve()
    out = (sast / args.out).resolve()

    if not fp_dir.is_dir() or not tp_dir.is_dir():
        raise SystemExit(f"Missing corpora: {fp_dir} or {tp_dir}")
    if not csv_path.is_file():
        raise SystemExit(f"Missing {csv_path}")
    if not bench.is_dir():
        raise SystemExit(f"Missing BenchmarkJava: {bench}")

    truth = _load_truth(csv_path)
    pool = _strict_candidates(fp_dir=fp_dir, tp_dir=tp_dir, bench_root=bench, truth=truth)
    print(f"Strict borderline pool: {len(pool)} cases")

    if args.full_strict_pool:
        picked = pool
    else:
        if len(pool) < args.count:
            raise SystemExit(f"Pool {len(pool)} < requested n={args.count}")
        picked = _select_balanced(pool, n=args.count, seed=args.seed, truth=truth)

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    cat_counts: dict[str, int] = defaultdict(int)
    manifest_cases: list[dict] = []
    for src_path, case, note in picked:
        cid = str(case.get("case_id") or src_path.stem)
        tr = truth.get(cid, {})
        bucket = _cwe_bucket(case, truth)
        cat_counts[bucket] += 1
        bench_real = tr.get("real_vuln", False)
        acceptable = ["TP", "FP", "BL"]
        enriched = dict(case)
        enriched["gold_track"] = "BL"
        enriched["benchmark_real_vuln"] = bench_real
        enriched["benchmark_category"] = tr.get("category", "")
        enriched["borderline_tier"] = "strict"
        enriched["acceptable_labels"] = acceptable
        enriched["borderline_notes"] = note
        dest = out / src_path.name
        dest.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest_cases.append(
            {
                "file": src_path.name,
                "case_id": cid,
                "cwe_bucket": bucket,
                "benchmark_real_vuln": bench_real,
                "borderline_notes": note,
            }
        )

    manifest = {
        "seed": args.seed,
        "n_cases": len(picked),
        "tier": "strict",
        "pool_size": len(pool),
        "fp_source": str(fp_dir),
        "tp_source": str(tp_dir),
        "out_dir": str(out),
        "cwe_bucket_counts": dict(sorted(cat_counts.items())),
        "cases": manifest_cases,
    }
    manifest_path = out.parent / f"{out.name}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {len(picked)} borderline cases -> {out}")
    print(f"Manifest: {manifest_path}")
    print(f"CWE buckets: {dict(sorted(cat_counts.items()))}")


if __name__ == "__main__":
    main()
