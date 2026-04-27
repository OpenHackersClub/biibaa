"""Tiered dependents source: cache → primary → fallback.

Order of operations per `fetch_dependents` call:

  1. Read the SQLite cache. Cache hit → return.
  2. Call the primary source (deps.dev). Non-empty → cache + return.
  3. Call the fallback source (ecosyste.ms). Non-empty → cache + return.
  4. Return [] (and don't cache, so next run can retry).

The cache key is (system, name, iso_week) so weekly biibaa runs naturally
hit it. We don't cache empty results — an empty list is more likely "both
backends were down" than "this package has zero dependents."
"""

from __future__ import annotations

import structlog

from biibaa.adapters.dependents_cache import DependentsCache
from biibaa.ports.dependents import Dependent, DependentsSource

log = structlog.get_logger(__name__)


class TieredDependentsSource:
    name = "tiered_dependents"

    def __init__(
        self,
        *,
        cache: DependentsCache,
        primary: DependentsSource | None,
        fallback: DependentsSource,
        system: str = "npm",
    ) -> None:
        self._cache = cache
        self._primary = primary
        self._fallback = fallback
        self._system = system

    def fetch_dependents(self, *, package: str, top_k: int = 10) -> list[Dependent]:
        cached = self._cache.get(system=self._system, name=package)
        if cached is not None:
            log.info("dependents.cache_hit", package=package, count=len(cached))
            return cached[:top_k]

        if self._primary is not None:
            primary_result = self._primary.fetch_dependents(
                package=package, top_k=top_k
            )
            if primary_result:
                log.info(
                    "dependents.primary_hit",
                    source=self._primary.name,
                    package=package,
                    count=len(primary_result),
                )
                self._cache.put(
                    system=self._system, name=package, dependents=primary_result
                )
                return primary_result

        fallback_result = self._fallback.fetch_dependents(
            package=package, top_k=top_k
        )
        if fallback_result:
            log.info(
                "dependents.fallback_hit",
                source=self._fallback.name,
                package=package,
                count=len(fallback_result),
            )
            self._cache.put(
                system=self._system, name=package, dependents=fallback_result
            )
        return fallback_result

    def close(self) -> None:
        if self._primary is not None:
            self._primary.close()
        self._fallback.close()
        self._cache.close()
