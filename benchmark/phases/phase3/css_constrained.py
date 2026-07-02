"""Constrained checkpoint selection: VDR/FPRR floors then maximize SRS."""

from __future__ import annotations

from typing import Any

from benchmark.css import VDR_DISQUALIFY


def constrained_floors(manifest: dict[str, Any] | None = None) -> dict[str, float]:
    """Read eligibility floors from manifest or defaults."""
    manifest = manifest or {}
    sel = manifest.get("checkpoint_selection") or {}
    floors = sel.get("constrained_floors") or {}
    return {
        "vdr": float(floors.get("vdr", 0.90)),
        "fprr": float(floors.get("fprr", 0.735)),
        "vdr_disqualify": float(floors.get("vdr_disqualify", VDR_DISQUALIFY)),
    }


def is_eligible(
    metrics: dict[str, Any],
    *,
    manifest: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """Return (eligible, reason_if_not)."""
    floors = constrained_floors(manifest)
    vdr = float(metrics.get("vdr", 0.0))
    fprr = float(metrics.get("fprr", 0.0))
    if vdr < floors["vdr_disqualify"]:
        return False, f"VDR {vdr:.3f} < disqualify {floors['vdr_disqualify']}"
    if vdr < floors["vdr"]:
        return False, f"VDR {vdr:.3f} < floor {floors['vdr']}"
    if fprr < floors["fprr"]:
        return False, f"FPRR {fprr:.3f} < floor {floors['fprr']}"
    return True, None


def pick_best(
    results: list[dict[str, Any]],
    *,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Pick checkpoint: eligible by VDR/FPRR floors, then max SRS.
    Tie-break: VDR, then FPRR, then CSS.
  """
    if not results:
        raise ValueError("no results to pick from")

    scored: list[tuple[tuple[float, float, float, float], dict[str, Any]]] = []
    for row in results:
        metrics = row.get("metrics") or {}
        eligible, reason = is_eligible(metrics, manifest=manifest)
        row = {**row, "constrained_eligible": eligible, "constrained_reason": reason}
        if not eligible:
            continue
        srs = float(metrics.get("srs", 0.0))
        vdr = float(metrics.get("vdr", 0.0))
        fprr = float(metrics.get("fprr", 0.0))
        css = float((row.get("css") or {}).get("css", 0.0))
        scored.append(((srs, vdr, fprr, css), row))

    if scored:
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[0][1]

    # Fallback: max CSS among all (log warning upstream)
    return max(
        results,
        key=lambda r: float((r.get("css") or {}).get("css", 0.0)),
    )
