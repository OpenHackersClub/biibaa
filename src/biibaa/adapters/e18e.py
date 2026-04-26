"""e18e module-replacements adapter.

Pulls the canonical manifests from github.com/e18e/module-replacements:

- preferred.json — preferred modern alternatives (perf + bloat axis)
- native.json — replace with built-in browser/Node API (bloat axis)
- micro-utilities.json — small utility replacements (bloat axis)

Each manifest follows manifest-schema.json: a `mappings` map of from-package →
list-of-replacement-ids, plus a `replacements` map describing each id by type
(`documented`, `native`, `simple`, `removal`).

We emit one Replacement per (from_package, manifest) — when multiple targets
exist they're collapsed into Replacement.to_purls.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import structlog

from biibaa.adapters._http import make_client
from biibaa.domain import Replacement

log = structlog.get_logger(__name__)

RAW_BASE = "https://raw.githubusercontent.com/e18e/module-replacements/main/manifests"

# (manifest filename, axis to record on emitted Replacements)
_MANIFESTS: tuple[tuple[str, str], ...] = (
    ("preferred.json", "perf"),
    ("native.json", "bloat"),
    ("micro-utilities.json", "bloat"),
)

# Effort band per replacement type (SPEC §6.2).
_EFFORT_BY_TYPE: dict[str, str] = {
    "native": "drop-in",
    "documented": "minor-migration",
    "simple": "codemod-available",
    "removal": "drop-in",
}


def _purl(name: str) -> str:
    return f"pkg:npm/{name}"


def _resolve_target(
    rep_id: str, replacements: dict[str, dict[str, Any]]
) -> tuple[str | None, str | None]:
    """Return (target_module_name | None, replacement_type) for a replacement id.

    `documented` types resolve to a concrete `replacementModule`. `native`
    has no module (it's a built-in API). `simple` / `removal` have neither.
    """
    rep = replacements.get(rep_id)
    if rep is None:
        # Unknown id — best-effort: treat the id itself as the target package.
        return rep_id, "documented"
    rtype = rep.get("type")
    if rtype == "documented":
        return rep.get("replacementModule") or rep_id, rtype
    if rtype == "native":
        return None, rtype
    return None, rtype


class E18eReplacementsSource:
    name = "e18e_module_replacements"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or make_client(timeout=30.0)

    def _load(self, filename: str) -> dict[str, Any]:
        url = f"{RAW_BASE}/{filename}"
        r = self._client.get(url)
        r.raise_for_status()
        return r.json()

    def fetch(self) -> Iterator[Replacement]:
        for filename, axis in _MANIFESTS:
            log.info("e18e.fetch", manifest=filename, axis=axis)
            try:
                doc = self._load(filename)
            except httpx.HTTPError as e:
                log.warning("e18e.fetch_failed", manifest=filename, error=str(e))
                continue
            mappings: dict[str, dict[str, Any]] = doc.get("mappings", {})
            replacements: dict[str, dict[str, Any]] = doc.get("replacements", {})
            for from_name, mapping in mappings.items():
                rep_ids: list[str] = mapping.get("replacements") or []
                resolved_targets: list[str] = []
                effort_band = "minor-migration"
                for rid in rep_ids:
                    target, rtype = _resolve_target(rid, replacements)
                    if target:
                        resolved_targets.append(target)
                    band = _EFFORT_BY_TYPE.get(rtype or "", "minor-migration")
                    # Pick the easiest band across resolutions.
                    effort_band = _easier(effort_band, band)
                if not resolved_targets and not any(
                    replacements.get(rid, {}).get("type") == "native" for rid in rep_ids
                ):
                    # No actionable replacement — skip.
                    continue
                yield Replacement(
                    id=f"e18e:{filename}:{from_name}",
                    from_purl=_purl(from_name),
                    to_purls=[_purl(t) for t in resolved_targets] or [_purl("<native>")],
                    axis=axis,  # type: ignore[arg-type]
                    effort=effort_band,  # type: ignore[arg-type]
                    evidence={"source": "e18e", "manifest": filename, "ids": ",".join(rep_ids)},
                )

    def close(self) -> None:
        self._client.close()


_BAND_RANK: dict[str, int] = {
    "drop-in": 4,
    "codemod-available": 3,
    "minor-migration": 2,
    "rewrite": 1,
}


def _easier(a: str, b: str) -> str:
    return a if _BAND_RANK.get(a, 0) >= _BAND_RANK.get(b, 0) else b
