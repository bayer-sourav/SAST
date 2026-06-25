"""Composite Selection Score (CSS) for LoRA checkpoint ranking on validation split."""

from __future__ import annotations

from typing import Any

# Weights (must sum to 1.0)
W_SRS = 0.35
W_VDR = 0.35
W_FPRR = 0.20
W_MACRO_F1 = 0.10

# Hard disqualifier — exploratory checkpoint gate (looser than test-set PoC gates)
VDR_DISQUALIFY = 0.75


def compute_css(
    *,
    srs: float,
    vdr: float,
    fprr: float,
    macro_f1: float,
    vdr_disqualify: float = VDR_DISQUALIFY,
) -> float:
    """
    Rank checkpoints on validation split during fine-tuning.

    CSS = 0.35·SRS + 0.35·VDR + 0.20·FPRR + 0.10·Macro-F1
    Returns 0.0 if VDR < vdr_disqualify (disqualified).
    """
    if vdr < vdr_disqualify:
        return 0.0
    return (
        W_SRS * float(srs)
        + W_VDR * float(vdr)
        + W_FPRR * float(fprr)
        + W_MACRO_F1 * float(macro_f1)
    )


def css_from_metrics_pack(pack: dict[str, Any], *, macro_f1: float | None = None) -> dict[str, Any]:
    """Build CSS result dict from merged track metrics (srs/vdr/fprr keys)."""
    srs = float(pack["srs"])
    vdr = float(pack["vdr"])
    fprr = float(pack["fprr"])
    f1 = float(macro_f1 if macro_f1 is not None else pack.get("macro_f1") or 0.0)
    disqualified = vdr < VDR_DISQUALIFY
    css = compute_css(srs=srs, vdr=vdr, fprr=fprr, macro_f1=f1)
    return {
        "css": css,
        "disqualified": disqualified,
        "disqualify_reason": f"VDR {vdr:.3f} < {VDR_DISQUALIFY}" if disqualified else None,
        "components": {
            "srs": srs,
            "vdr": vdr,
            "fprr": fprr,
            "macro_f1": f1,
        },
        "weights": {
            "srs": W_SRS,
            "vdr": W_VDR,
            "fprr": W_FPRR,
            "macro_f1": W_MACRO_F1,
        },
    }
