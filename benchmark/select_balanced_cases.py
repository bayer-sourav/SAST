#!/usr/bin/env python3
"""Select a reproducible, CWE-balanced case slice (fixed seed) for benchmark runs."""

from __future__ import annotations

import argparse
import json
import random
import shutil
from collections import defaultdict
from pathlib import Path


def _cwe_bucket(case: dict) -> str:
    raw = case.get("raw_output") or {}
    if not isinstance(raw, dict):
        return "unknown"
    for entries in raw.values():
        if not isinstance(entries, list) or not entries:
            continue
        first = entries[0] if isinstance(entries[0], dict) else {}
        rule_id = str(first.get("ruleId", "") or "")
        if "/" in rule_id:
            return rule_id.split("/")[-1].lower()
        if rule_id:
            return rule_id.lower()
    return "unknown"


def select_balanced(paths: list[Path], *, n: int, seed: int) -> list[Path]:
    rng = random.Random(seed)
    by_cat: dict[str, list[Path]] = defaultdict(list)
    for p in paths:
        case = json.loads(p.read_text(encoding="utf-8"))
        by_cat[_cwe_bucket(case)].append(p)
    for bucket in by_cat:
        rng.shuffle(by_cat[bucket])

    buckets = sorted(by_cat.keys())
    idx = {b: 0 for b in buckets}
    selected: list[Path] = []
    seen: set[Path] = set()

    while len(selected) < n:
        progressed = False
        for bucket in buckets:
            if len(selected) >= n:
                break
            i = idx[bucket]
            if i < len(by_cat[bucket]):
                p = by_cat[bucket][i]
                idx[bucket] = i + 1
                if p not in seen:
                    selected.append(p)
                    seen.add(p)
                    progressed = True
        if not progressed:
            break

    if len(selected) < n:
        pool: list[Path] = []
        for bucket in buckets:
            pool.extend(by_cat[bucket][idx[bucket] :])
        rng.shuffle(pool)
        for p in pool:
            if len(selected) >= n:
                break
            if p not in seen:
                selected.append(p)
                seen.add(p)

    return selected[:n]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", type=Path, required=True, help="Full corpus directory (*.json)")
    ap.add_argument("--out", type=Path, required=True, help="Output slice directory")
    ap.add_argument("-n", "--count", type=int, default=50)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--manifest", type=Path, default=None, help="Write manifest JSON (default: <out>/slice_manifest.json)")
    args = ap.parse_args()

    src = args.src.expanduser().resolve()
    out = args.out.expanduser().resolve()
    if not src.is_dir():
        raise SystemExit(f"Missing source dir: {src}")

    paths = sorted(src.glob("*.json"))
    if len(paths) < args.count:
        raise SystemExit(f"Only {len(paths)} cases in {src}; need {args.count}")

    picked = select_balanced(paths, n=args.count, seed=args.seed)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    manifest_entries: list[dict] = []
    cat_counts: dict[str, int] = defaultdict(int)
    for p in picked:
        case = json.loads(p.read_text(encoding="utf-8"))
        bucket = _cwe_bucket(case)
        cat_counts[bucket] += 1
        dest = out / p.name
        shutil.copy2(p, dest)
        manifest_entries.append(
            {
                "file": p.name,
                "case_id": case.get("case_id") or p.stem,
                "cwe_bucket": bucket,
            }
        )

    manifest_path = (args.manifest or (out.parent / f"{out.name}_manifest.json")).expanduser().resolve()
    manifest = {
        "seed": args.seed,
        "n_cases": len(picked),
        "source_dir": str(src),
        "out_dir": str(out),
        "cwe_bucket_counts": dict(sorted(cat_counts.items())),
        "cases": manifest_entries,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {len(picked)} cases -> {out}")
    print(f"Manifest: {manifest_path}")
    print(f"CWE buckets: {dict(sorted(cat_counts.items()))}")


if __name__ == "__main__":
    main()
