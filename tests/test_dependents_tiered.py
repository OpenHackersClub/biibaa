"""TieredDependentsSource fallback ordering."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from biibaa.adapters.dependents_cache import DependentsCache
from biibaa.adapters.dependents_tiered import TieredDependentsSource
from biibaa.ports.dependents import Dependent


def _now() -> datetime:
    return datetime(2026, 4, 26, tzinfo=UTC)


class _Stub:
    def __init__(self, name: str, result: list[Dependent]) -> None:
        self.name = name
        self.result = result
        self.calls = 0

    def fetch_dependents(self, *, package: str, top_k: int = 10) -> list[Dependent]:
        self.calls += 1
        return self.result

    def close(self) -> None:
        pass


def _dep(name: str) -> Dependent:
    return Dependent(name=name, purl=f"pkg:npm/{name}", repo_url=None, lifetime_downloads=None)


def test_primary_hit_skips_fallback(tmp_path: Path) -> None:
    cache = DependentsCache(path=tmp_path / "c.sqlite", clock=_now)
    primary = _Stub("primary", [_dep("a")])
    fallback = _Stub("fallback", [_dep("b")])
    src = TieredDependentsSource(cache=cache, primary=primary, fallback=fallback)

    out = src.fetch_dependents(package="lodash", top_k=5)
    assert [d.name for d in out] == ["a"]
    assert primary.calls == 1
    assert fallback.calls == 0


def test_primary_empty_falls_back(tmp_path: Path) -> None:
    cache = DependentsCache(path=tmp_path / "c.sqlite", clock=_now)
    primary = _Stub("primary", [])
    fallback = _Stub("fallback", [_dep("b")])
    src = TieredDependentsSource(cache=cache, primary=primary, fallback=fallback)

    out = src.fetch_dependents(package="lodash", top_k=5)
    assert [d.name for d in out] == ["b"]
    assert primary.calls == 1
    assert fallback.calls == 1


def test_cache_hit_skips_both(tmp_path: Path) -> None:
    cache = DependentsCache(path=tmp_path / "c.sqlite", clock=_now)
    cache.put(system="npm", name="lodash", dependents=[_dep("cached")])
    primary = _Stub("primary", [_dep("a")])
    fallback = _Stub("fallback", [_dep("b")])
    src = TieredDependentsSource(cache=cache, primary=primary, fallback=fallback)

    out = src.fetch_dependents(package="lodash", top_k=5)
    assert [d.name for d in out] == ["cached"]
    assert primary.calls == 0
    assert fallback.calls == 0


def test_no_primary_uses_fallback_directly(tmp_path: Path) -> None:
    cache = DependentsCache(path=tmp_path / "c.sqlite", clock=_now)
    fallback = _Stub("fallback", [_dep("b")])
    src = TieredDependentsSource(cache=cache, primary=None, fallback=fallback)

    out = src.fetch_dependents(package="lodash", top_k=5)
    assert [d.name for d in out] == ["b"]
    assert fallback.calls == 1


def test_empty_results_are_not_cached(tmp_path: Path) -> None:
    cache = DependentsCache(path=tmp_path / "c.sqlite", clock=_now)
    primary = _Stub("primary", [])
    fallback = _Stub("fallback", [])
    src = TieredDependentsSource(cache=cache, primary=primary, fallback=fallback)

    src.fetch_dependents(package="lodash", top_k=5)
    # If empty had been cached we'd see a hit (empty list), not None.
    assert cache.get(system="npm", name="lodash") is None
