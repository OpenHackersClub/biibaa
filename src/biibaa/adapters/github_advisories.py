"""GHSA REST adapter — pulls security advisories from api.github.com/advisories.

Chosen over OSV bulk for MVP because it's filterable per-request (ecosystem +
severity), structured JSON, and works without auth at low volume.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx
import structlog

from biibaa.adapters._http import make_client
from biibaa.domain import Advisory

log = structlog.get_logger(__name__)

GHSA_URL = "https://api.github.com/advisories"


def _purl_for(package: dict[str, str]) -> str:
    eco = package["ecosystem"].lower()
    name = package["name"]
    return f"pkg:{eco}/{name}"


def _cvss(advisory: dict[str, Any]) -> float | None:
    severities = advisory.get("cvss_severities") or {}
    for key in ("cvss_v4", "cvss_v3"):
        score = (severities.get(key) or {}).get("score")
        if score:
            return float(score)
    score = (advisory.get("cvss") or {}).get("score")
    return float(score) if score else None


def _parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class GithubAdvisorySource:
    """Fan one GHSA record into one Advisory per affected package."""

    name = "github_advisories"

    def __init__(self, *, token: str | None = None, client: httpx.Client | None = None) -> None:
        self._token = token or os.environ.get("GITHUB_TOKEN")
        self._client = client or make_client(timeout=30.0)

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def _page(
        self, *, ecosystem: str, severity: str | None, per_page: int
    ) -> list[dict[str, Any]]:
        params: dict[str, str | int] = {"ecosystem": ecosystem, "per_page": per_page}
        if severity:
            params["severity"] = severity
        r = self._client.get(GHSA_URL, params=params, headers=self._headers())
        r.raise_for_status()
        return r.json()

    def fetch(
        self,
        *,
        ecosystem: str = "npm",
        severities: tuple[str, ...] = ("critical", "high", "medium"),
        per_page: int = 100,
        limit: int = 500,
        only_unpatched: bool = True,
    ) -> Iterator[Advisory]:
        """Yield Advisories. With `only_unpatched=True` (default), keep only
        advisories whose `first_patched_version` is null — i.e. no upstream fix
        exists yet, so the contribution opportunity is to write the patch.
        """
        emitted = 0
        for severity in severities:
            log.info("ghsa.fetch", ecosystem=ecosystem, severity=severity)
            try:
                page = self._page(ecosystem=ecosystem, severity=severity, per_page=per_page)
            except httpx.HTTPStatusError as e:
                log.warning(
                    "ghsa.fetch_failed", severity=severity, status=e.response.status_code
                )
                continue
            for adv in page:
                if adv.get("withdrawn_at"):
                    continue
                for vuln in adv.get("vulnerabilities") or []:
                    pkg = vuln.get("package") or {}
                    if not pkg.get("name") or pkg.get("ecosystem", "").lower() != ecosystem:
                        continue
                    fixed = vuln.get("first_patched_version")
                    if only_unpatched and fixed:
                        continue
                    if not only_unpatched and not fixed:
                        continue
                    yield Advisory(
                        id=adv["ghsa_id"],
                        project_purl=_purl_for(pkg),
                        severity=adv.get("severity"),
                        cvss=_cvss(adv),
                        summary=adv.get("summary") or "",
                        affected_versions=vuln.get("vulnerable_version_range"),
                        fixed_versions=[fixed] if fixed else [],
                        refs=list(adv.get("references") or []),
                        published_at=_parse_published(adv.get("published_at")),
                        repo_url=adv.get("source_code_location") or None,
                    )
                    emitted += 1
                    if emitted >= limit:
                        return

    def close(self) -> None:
        self._client.close()
