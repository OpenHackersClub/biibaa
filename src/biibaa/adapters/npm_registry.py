"""npm registry adapter — resolves the `latest` dist-tag for a package.

Used to drop GHSA advisories whose affected range no longer covers the
current published version: GHSA often leaves `first_patched_version` null
even when the project moved past the affected range without backporting,
and those advisories aren't a contribution opportunity.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx
import structlog

from biibaa.adapters._http import make_client

log = structlog.get_logger(__name__)

NPM_REGISTRY_URL = "https://registry.npmjs.org"


class NpmRegistrySource:
    name = "npm_registry"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or make_client(timeout=30.0)

    def latest_version(self, *, package: str) -> str | None:
        url = f"{NPM_REGISTRY_URL}/{quote(package, safe='@/')}"
        try:
            r = self._client.get(url, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            log.warning("npm_registry.error", package=package, error=str(e))
            return None
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            log.warning(
                "npm_registry.bad_status", package=package, status=r.status_code
            )
            return None
        body = r.json()
        latest = (body.get("dist-tags") or {}).get("latest")
        return str(latest) if latest else None

    def latest_versions(self, *, packages: list[str]) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for p in packages:
            out[p] = self.latest_version(package=p)
        return out

    def close(self) -> None:
        self._client.close()
