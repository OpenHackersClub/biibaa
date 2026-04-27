"""Minimal semver range matcher for GHSA `vulnerable_version_range` strings.

The GHSA format is comma-separated comparisons (logical AND), e.g.:
  "<= 0.23.0"
  "< 1.2.3"
  ">= 1.0.0, < 1.2.3"
  "= 1.0.0"

We strip pre-release and build metadata before comparison: that's a small
loss of fidelity, but advisories almost always pin to released versions, and
the alternative — pulling in a full semver lib — adds dependency weight for
a single comparison.
"""

from __future__ import annotations


def _parse_version(value: str) -> tuple[int, ...] | None:
    v = value.lstrip("v").strip()
    v = v.split("-", 1)[0].split("+", 1)[0]
    if not v:
        return None
    parts = v.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def _cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    n = max(len(a), len(b))
    a2 = a + (0,) * (n - len(a))
    b2 = b + (0,) * (n - len(b))
    return (a2 > b2) - (a2 < b2)


_OPS = ("<=", ">=", "<", ">", "=")


def is_version_in_range(version: str, range_str: str) -> bool | None:
    """Return True if `version` matches every clause in `range_str`.

    Returns None when either input can't be parsed — callers should treat
    None as "unknown" and keep the advisory rather than drop it.
    """
    target = _parse_version(version)
    if target is None:
        return None
    for raw in range_str.split(","):
        clause = raw.strip()
        if not clause:
            continue
        op_match: str | None = None
        for op in _OPS:
            if clause.startswith(op):
                op_match = op
                break
        if op_match is None:
            return None
        bound = _parse_version(clause[len(op_match) :].strip())
        if bound is None:
            return None
        c = _cmp(target, bound)
        if op_match == "<" and not c < 0:
            return False
        if op_match == "<=" and not c <= 0:
            return False
        if op_match == ">" and not c > 0:
            return False
        if op_match == ">=" and not c >= 0:
            return False
        if op_match == "=" and c != 0:
            return False
    return True
