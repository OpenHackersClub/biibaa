"""Build the right DependentsSource for the current environment.

Preference order:
  1. pyoso (`OSO_API_KEY` set + `pyoso` extra installed) — joins sboms_v0 +
     repositories_v0, returns GitHub repos ranked by stars. The right
     primary because deps.dev BigQuery `Dependents` is not clustered, so
     per-package live queries scan ~500 GB / $2.59 each.
  2. ecosyste.ms only — works for cold-tail packages but reliably 500s on
     hot packages like lodash/debug/axios. Wrapped with a circuit breaker.

Returns a TieredDependentsSource (cache → primary → ecosyste.ms fallback)
when a primary is available, otherwise the bare ecosyste.ms adapter.
"""

from __future__ import annotations

import os
from pathlib import Path

import structlog

from biibaa.adapters.dependents_cache import DependentsCache
from biibaa.adapters.dependents_tiered import TieredDependentsSource
from biibaa.adapters.ecosyste_ms import EcosystemsSource
from biibaa.ports.dependents import DependentsSource

log = structlog.get_logger(__name__)

_DEFAULT_CACHE_PATH = Path("data/dependents_cache.sqlite")


def build_dependents_source(
    *,
    cache_path: Path = _DEFAULT_CACHE_PATH,
    oso_api_key_env: str = "OSO_API_KEY",
) -> DependentsSource:
    fallback = EcosystemsSource()
    api_key = os.environ.get(oso_api_key_env)
    if not api_key:
        log.info(
            "dependents.factory", backend="ecosyste_ms_only", reason="no_oso_api_key"
        )
        return fallback

    try:
        from biibaa.adapters.pyoso_dependents import PyosoSource
    except ImportError:
        log.warning(
            "dependents.factory",
            backend="ecosyste_ms_only",
            reason="pyoso_extra_missing",
        )
        return fallback

    primary = PyosoSource(api_key=api_key)
    cache = DependentsCache(path=cache_path)
    log.info("dependents.factory", backend="tiered", primary="pyoso")
    return TieredDependentsSource(cache=cache, primary=primary, fallback=fallback)
