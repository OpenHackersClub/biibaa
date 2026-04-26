"""npm downloads adapter — weekly downloads via api.npmjs.org/downloads/point/last-week."""

from __future__ import annotations

import httpx
import structlog

from biibaa.adapters._http import make_client

log = structlog.get_logger(__name__)

NPM_DOWNLOADS_URL = "https://api.npmjs.org/downloads/point/last-week"


class NpmDownloadsSource:
    name = "npm_downloads"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or make_client(timeout=15.0)

    def weekly_downloads(self, *, package: str) -> int | None:
        url = f"{NPM_DOWNLOADS_URL}/{package}"
        try:
            r = self._client.get(url)
        except httpx.HTTPError as e:
            log.warning("npm_downloads.error", package=package, error=str(e))
            return None
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            log.warning("npm_downloads.bad_status", package=package, status=r.status_code)
            return None
        body = r.json()
        downloads = body.get("downloads")
        return int(downloads) if downloads is not None else None

    def close(self) -> None:
        self._client.close()
