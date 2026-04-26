"""npm downloads adapter — weekly downloads via api.npmjs.org/downloads.

Supports the bulk endpoint (up to 128 packages per request) for unscoped names.
The bulk endpoint rejects scoped packages (`@foo/bar`), so those fall back to
the per-package endpoint.
"""

from __future__ import annotations

import time
from collections.abc import Iterable

import httpx
import structlog

from biibaa.adapters._http import make_client

log = structlog.get_logger(__name__)

NPM_DOWNLOADS_URL = "https://api.npmjs.org/downloads/point/last-week"
BULK_LIMIT = 128


class NpmDownloadsSource:
    name = "npm_downloads"

    def __init__(self, *, client: httpx.Client | None = None) -> None:
        self._client = client or make_client(timeout=30.0)

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

    def weekly_downloads_bulk(self, *, packages: Iterable[str]) -> dict[str, int | None]:
        """Fetch downloads for many packages, batching the unscoped ones."""
        out: dict[str, int | None] = {}
        unscoped: list[str] = []
        for p in packages:
            if p.startswith("@"):
                # Scoped — bulk endpoint rejects these.
                out[p] = self.weekly_downloads(package=p)
            else:
                unscoped.append(p)

        for batch in _batched(unscoped, BULK_LIMIT):
            body = self._bulk_with_retry(batch)
            if body is None:
                # Final fallback: individual lookups (rate-limited but accurate).
                for p in batch:
                    out[p] = self.weekly_downloads(package=p)
                    time.sleep(0.05)
                continue
            for p in batch:
                rec = body.get(p)
                if rec is None:
                    out[p] = None
                else:
                    dl = rec.get("downloads")
                    out[p] = int(dl) if dl is not None else None
            time.sleep(0.5)  # gentle pacing between batches
        return out

    def _bulk_with_retry(
        self, batch: list[str], *, max_attempts: int = 3
    ) -> dict[str, dict] | None:
        url = f"{NPM_DOWNLOADS_URL}/{','.join(batch)}"
        for attempt in range(max_attempts):
            try:
                r = self._client.get(url)
            except httpx.HTTPError as e:
                log.warning("npm_downloads.bulk_error", error=str(e), attempt=attempt)
                time.sleep(2 ** attempt)
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = 2 ** (attempt + 1)
                log.warning(
                    "npm_downloads.bulk_429",
                    batch_size=len(batch),
                    wait_s=wait,
                    attempt=attempt,
                )
                time.sleep(wait)
                continue
            log.warning(
                "npm_downloads.bulk_bad_status",
                status=r.status_code,
                batch_size=len(batch),
            )
            return None
        return None

    def close(self) -> None:
        self._client.close()


def _batched(seq: list[str], n: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), n):
        yield seq[i : i + n]
