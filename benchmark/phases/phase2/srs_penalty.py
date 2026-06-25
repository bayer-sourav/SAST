"""Backward-compatible re-export; prefer ``benchmark.srs``."""

from benchmark.srs import (  # noqa: F401
    MAX_PENALTY,
    compute_srs,
    penalty_from_distribution,
    srs_penalty_from_tracks,
    transition_penalty,
)
