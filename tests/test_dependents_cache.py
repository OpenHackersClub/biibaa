"""DependentsCache contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from biibaa.adapters.dependents_cache import DependentsCache
from biibaa.ports.dependents import Dependent


def _now() -> datetime:
    return datetime(2026, 4, 26, tzinfo=UTC)


def test_round_trip(tmp_path: Path) -> None:
    cache = DependentsCache(path=tmp_path / "c.sqlite", clock=_now)
    deps = [
        Dependent(name="a", purl="pkg:npm/a", repo_url="https://x/a", lifetime_downloads=1),
        Dependent(name="b", purl="pkg:npm/b", repo_url=None, lifetime_downloads=None),
    ]
    cache.put(system="npm", name="lodash", dependents=deps)
    got = cache.get(system="npm", name="lodash")
    assert got == deps


def test_miss_returns_none(tmp_path: Path) -> None:
    cache = DependentsCache(path=tmp_path / "c.sqlite", clock=_now)
    assert cache.get(system="npm", name="never-cached") is None


def test_unopenable_path_degrades_to_no_op(tmp_path: Path) -> None:
    """Disk full / unwritable path: cache must not crash the pipeline."""
    bad = tmp_path / "does" / "not" / "exist"
    bad.parent.mkdir(parents=True)
    bad.parent.chmod(0o400)  # parent dir read-only -> sqlite open fails
    try:
        cache = DependentsCache(path=bad / "c.sqlite", clock=_now)
        assert cache.get(system="npm", name="x") is None
        dep = Dependent(name="a", purl="p", repo_url=None, lifetime_downloads=None)
        cache.put(system="npm", name="x", dependents=[dep])
        assert cache.get(system="npm", name="x") is None  # no-op
        cache.close()
    finally:
        bad.parent.chmod(0o700)


def test_different_week_is_a_miss(tmp_path: Path) -> None:
    t = {"now": datetime(2026, 4, 26, tzinfo=UTC)}
    cache = DependentsCache(path=tmp_path / "c.sqlite", clock=lambda: t["now"])
    cache.put(system="npm", name="x", dependents=[])
    # Same week -> hit (empty list, but not None)
    assert cache.get(system="npm", name="x") == []
    # Jump weeks
    t["now"] = datetime(2026, 5, 12, tzinfo=UTC)
    assert cache.get(system="npm", name="x") is None
