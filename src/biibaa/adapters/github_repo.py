"""GitHub repo activity adapter — fetches the most-recently-merged PR
timestamp and the repo's archived flag via the v4 GraphQL API. Both signals
are pulled in one query and cached together so `last_merged_pr_at` and
`is_archived` callers share a single round-trip per repo.

- `last_merged_pr_at` feeds the confidence axis (a repo whose maintainers
  merged something last week is far more likely to merge a drive-by
  contribution than one frozen for two years).
- `is_archived` is a hard disqualifier — archived repos won't accept PRs."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime

import httpx
import structlog

from biibaa.adapters._http import make_client

log = structlog.get_logger(__name__)

GRAPHQL_URL = "https://api.github.com/graphql"

_QUERY = """
query RepoMeta($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    isArchived
    pullRequests(states: MERGED, orderBy: {field: UPDATED_AT, direction: DESC}, first: 1) {
      nodes { mergedAt }
    }
  }
}
"""


@dataclass(frozen=True)
class RepoMeta:
    last_merged_pr_at: datetime | None
    is_archived: bool

_REPO_RE = re.compile(r"https?://github\.com/([^/]+)/([^/?#]+?)(?:\.git)?/?$")


def _parse_repo_url(url: str) -> tuple[str, str] | None:
    m = _REPO_RE.match(url.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def _resolve_token(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    if env := os.environ.get("GITHUB_TOKEN"):
        return env
    try:
        out = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            check=True,
            timeout=5,
        )
        return out.stdout.strip() or None
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


class GithubRepoSource:
    name = "github_repo"

    def __init__(
        self, *, token: str | None = None, client: httpx.Client | None = None
    ) -> None:
        self._token = _resolve_token(token)
        self._client = client or make_client(timeout=15.0)
        self._cache: dict[tuple[str, str], RepoMeta | None] = {}

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/vnd.github+json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def fetch_meta(self, *, repo_url: str) -> RepoMeta | None:
        parsed = _parse_repo_url(repo_url)
        if not parsed:
            return None
        if parsed in self._cache:
            return self._cache[parsed]
        owner, name = parsed
        try:
            r = self._client.post(
                GRAPHQL_URL,
                json={"query": _QUERY, "variables": {"owner": owner, "name": name}},
                headers=self._headers(),
            )
            r.raise_for_status()
            payload = r.json()
        except httpx.HTTPError as e:
            log.warning("github_repo.fetch_failed", repo=repo_url, error=str(e))
            self._cache[parsed] = None
            return None

        if payload.get("errors"):
            log.warning(
                "github_repo.graphql_errors", repo=repo_url, errors=payload["errors"]
            )
            self._cache[parsed] = None
            return None

        repo = ((payload.get("data") or {}).get("repository")) or {}
        nodes = repo.get("pullRequests", {}).get("nodes") or []
        merged_at: datetime | None = None
        if nodes and nodes[0].get("mergedAt"):
            merged_at = datetime.fromisoformat(
                nodes[0]["mergedAt"].replace("Z", "+00:00")
            )
        meta = RepoMeta(
            last_merged_pr_at=merged_at, is_archived=bool(repo.get("isArchived"))
        )
        self._cache[parsed] = meta
        return meta

    def last_merged_pr_at(self, *, repo_url: str) -> datetime | None:
        meta = self.fetch_meta(repo_url=repo_url)
        return meta.last_merged_pr_at if meta else None

    def is_archived(self, *, repo_url: str) -> bool:
        meta = self.fetch_meta(repo_url=repo_url)
        # Unknown / unreachable repos are NOT treated as archived — better to
        # over-include than silently drop a project on a transient API blip.
        return bool(meta and meta.is_archived)

    def close(self) -> None:
        self._client.close()
