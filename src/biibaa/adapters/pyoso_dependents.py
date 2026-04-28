"""Pyoso (Open Source Observer) dependents adapter.

Joins `sboms_v0` (the dependents-fan-out edge list) with `repositories_v0`
to rank by GitHub star count. Returns GitHub repos directly — which is more
useful than npm package names for biibaa's "where do I PR" question.

The `pyoso` library is optional — installed via the `[pyoso]` extra.
Auth is via the OSO_API_KEY env var (or explicit api_key= to the Client).

We sanitize the package name with a strict regex before splicing into SQL
because pyoso's `to_pandas` takes raw SQL with no parameterization.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

import structlog

from biibaa.adapters._circuit import CircuitBreaker
from biibaa.ports.dependents import Dependent

log = structlog.get_logger(__name__)

try:
    from pyoso import Client  # type: ignore[import-not-found]
except ImportError as e:  # pragma: no cover - exercised only when extra missing
    raise ImportError(
        "pyoso adapter requires the 'pyoso' extra: pip install 'biibaa[pyoso]'"
    ) from e


# npm package name spec: lowercase, digits, dot, hyphen, underscore, optional
# scoped form `@scope/name`. Reject anything else to keep raw-SQL splicing safe.
_NPM_NAME_RE = re.compile(r"^(@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*$")

_QUERY_TEMPLATE = """
SELECT
  s.dependent_artifact_namespace AS owner,
  s.dependent_artifact_name AS repo,
  r.star_count AS star_count,
  r.artifact_url AS repo_url
FROM sboms_v0 s
LEFT JOIN repositories_v0 r
  ON s.dependent_artifact_id = r.artifact_id
WHERE s.package_artifact_source = 'NPM'
  AND s.package_artifact_name = '{package}'
  AND s.dependent_artifact_source = 'GITHUB'
  AND r.star_count >= {min_stars}
ORDER BY r.star_count DESC NULLS LAST
LIMIT {top_k}
"""


class PyosoSource:
    """Dependents source backed by OSO's sboms_v0 mart."""

    name = "pyoso_dependents"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: Client | None = None,
        min_stars: int = 10,
        breaker: CircuitBreaker[list[Dependent]] | None = None,
        query_timeout_seconds: float = 30.0,
    ) -> None:
        self._client = client or Client(api_key=api_key)
        self._min_stars = min_stars
        self._timeout = query_timeout_seconds
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="pyoso")
        self._breaker = breaker or CircuitBreaker[list[Dependent]](
            name="pyoso",
            failure_threshold=3,
            reset_after_seconds=300.0,
        )

    def fetch_dependents(self, *, package: str, top_k: int = 10) -> list[Dependent]:
        if not _NPM_NAME_RE.match(package):
            log.warning("pyoso.invalid_package_name", package=package)
            return []
        return self._breaker.call(
            lambda: self._fetch(package=package, top_k=top_k),
            fallback=[],
        )

    def _fetch(self, *, package: str, top_k: int) -> list[Dependent]:
        sql = _QUERY_TEMPLATE.format(
            package=package, min_stars=self._min_stars, top_k=top_k
        )
        future = self._executor.submit(self._client.to_pandas, sql)
        try:
            df = future.result(timeout=self._timeout)
        except FuturesTimeoutError:
            log.warning("pyoso.query_timeout", package=package, timeout=self._timeout)
            return []
        except Exception as e:
            log.warning("pyoso.query_error", package=package, error=str(e))
            return []
        out: list[Dependent] = []
        for row in df.itertuples(index=False):
            owner = row.owner
            repo = row.repo
            if not owner or not repo:
                continue
            full = f"{owner}/{repo}"
            out.append(
                Dependent(
                    name=full,
                    purl=f"pkg:github/{full}",
                    repo_url=row.repo_url or f"https://github.com/{full}",
                    lifetime_downloads=None,
                )
            )
        return out

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def build_query(*, package: str, min_stars: int, top_k: int) -> str:
    """Exposed for tests + dry-run inspection."""
    return _QUERY_TEMPLATE.format(package=package, min_stars=min_stars, top_k=top_k)
