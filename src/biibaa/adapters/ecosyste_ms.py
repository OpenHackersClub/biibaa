"""ecosyste.ms adapter — fan out from a package to its top dependents.

Implements the SPEC §3 dependents-fan-out signal via the ecosyste.ms
public API instead of scraping npmjs.com/browse/depended/<pkg>.
ecosyste.ms aggregates registry + git metadata into one structured
endpoint, with no auth required.

  GET /api/v1/registries/npmjs.org/packages/{name}/dependent_packages
      ?sort=downloads&order=desc&per_page=K

Returns up to K dependents ranked by lifetime npm downloads, each with
the repository_url we need to make a brief actionable.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import structlog

from biibaa.adapters._http import make_client

log = structlog.get_logger(__name__)

ECOSYSTEMS_BASE = "https://packages.ecosyste.ms/api/v1/registries/npmjs.org/packages"


@dataclass(frozen=True)
class Dependent:
    name: str
    purl: str
    repo_url: str | None
    lifetime_downloads: int | None


def _purl(name: str) -> str:
    return f"pkg:npm/{name}"


class EcosystemsSource:
    name = "ecosyste_ms_dependents"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        # Tight timeout: many popular-package endpoints 500 instantly,
        # but a few hang with no response — don't let those starve the run.
        self._client = client or make_client(timeout=8.0)

    def fetch_dependents(self, *, package: str, top_k: int = 10) -> list[Dependent]:
        url = f"{ECOSYSTEMS_BASE}/{package}/dependent_packages"
        params = {"sort": "downloads", "order": "desc", "per_page": top_k}
        try:
            r = self._client.get(url, params=params)
        except httpx.HTTPError as e:
            log.warning("ecosyste_ms.error", package=package, error=str(e))
            return []
        if r.status_code == 404:
            return []
        if r.status_code != 200:
            log.warning(
                "ecosyste_ms.bad_status", package=package, status=r.status_code
            )
            return []
        data = r.json()
        out: list[Dependent] = []
        for entry in data or []:
            name = entry.get("name")
            if not name:
                continue
            out.append(
                Dependent(
                    name=name,
                    purl=_purl(name),
                    repo_url=entry.get("repository_url"),
                    lifetime_downloads=entry.get("downloads"),
                )
            )
        return out

    def close(self) -> None:
        self._client.close()
