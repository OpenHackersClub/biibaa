"""Scoring per SPEC §6 — popularity × severity × effort."""

from __future__ import annotations

import math
from typing import Final

# Per §6.1 — flatten the long tail. Per-ecosystem refs would live in config
# in the full implementation; npm-only MVP hardcodes here.
DOWNLOADS_REF_NPM: Final[int] = 100_000_000  # 100M / week
STARS_REF: Final[int] = 100_000

# Default blend (§6.1)
W_DOWNLOADS: Final[float] = 0.7
W_STARS: Final[float] = 0.3

# Final blend (§6.3)
W_IMPACT: Final[float] = 0.7
W_EFFORT: Final[float] = 0.3


def popularity(*, downloads_weekly: int | None, stars: int | None) -> float:
    """Log-normalized popularity ∈ [0, 100]."""
    d = downloads_weekly or 0
    s = stars or 0
    pd = math.log10(1 + d) / math.log10(1 + DOWNLOADS_REF_NPM)
    ps = math.log10(1 + s) / math.log10(1 + STARS_REF)
    score = 100.0 * (W_DOWNLOADS * pd + W_STARS * ps)
    return max(0.0, min(100.0, score))


def severity_score(*, cvss: float | None) -> float:
    """CVSS 0-10 → 0-100. Missing CVSS treated as moderate (50)."""
    if cvss is None:
        return 50.0
    return max(0.0, min(100.0, cvss * 10.0))


REPLACEMENT_EFFORT_SCORE: dict[str, float] = {
    # SPEC §6.2 Effort table
    "drop-in": 95.0,
    "minor-migration": 70.0,
    "codemod-available": 60.0,
    "rewrite": 20.0,
}


def replacement_effort_score(*, band: str) -> float:
    return REPLACEMENT_EFFORT_SCORE.get(band, 50.0)


def replacement_severity(*, axis: str, native: bool) -> float:
    """Baseline axis severity for replacements lacking measured savings.

    `native` replacements remove the dep entirely → highest baseline.
    `bloat` non-native sits below `perf` since perf wins are usually
    user-visible while bloat wins are install-time.
    """
    if native:
        return 75.0
    if axis == "perf":
        return 60.0
    return 45.0  # bloat default


def effort_score(*, fixed_versions: list[str], advisory_summary: str) -> float:
    """Heuristic effort estimate. Higher = easier.

    A version-bump fix (one fixed version, no breaking-change keywords) is the
    canonical drop-in. When no fixed version exists, the contribution is to
    *write* the upstream patch — rewrite-class effort per SPEC §6.2.
    """
    if not fixed_versions:
        # Unpatched: the contribution is the patch itself, not a version bump.
        return 20.0
    bump = fixed_versions[0]
    summary = (advisory_summary or "").lower()
    if any(word in summary for word in ("breaking", "rewrite", "rearchitect", "removed api")):
        return 60.0
    # Major version bumps imply migration risk
    if bump and bump.split(".", 1)[0].lstrip("vV").isdigit():
        return 95.0  # drop-in version bump
    return 70.0


def impact(*, pop: float, sev: float) -> float:
    return (pop / 100.0) * sev  # 0-100


def final_score(*, impact_value: float, effort_value: float) -> float:
    return W_IMPACT * impact_value + W_EFFORT * effort_value
