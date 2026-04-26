from collections.abc import Iterable
from typing import Protocol

from biibaa.domain import Advisory


class AdvisorySource(Protocol):
    name: str

    def fetch(self, *, ecosystem: str, limit: int) -> Iterable[Advisory]: ...


class PopularitySource(Protocol):
    name: str

    def weekly_downloads(self, *, package: str) -> int | None: ...
