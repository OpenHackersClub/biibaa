"""DependentsSource port — fan-out from a package to its top dependents.

Implementations live in `biibaa.adapters` (ecosyste.ms, deps.dev BigQuery,
SQLite cache, tiered composite). Pipeline depends only on this protocol so
backends can be swapped per-deployment without touching scoring or rendering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Dependent:
    name: str
    purl: str
    repo_url: str | None
    lifetime_downloads: int | None


class DependentsSource(Protocol):
    name: str

    def fetch_dependents(self, *, package: str, top_k: int = 10) -> list[Dependent]: ...

    def close(self) -> None: ...
