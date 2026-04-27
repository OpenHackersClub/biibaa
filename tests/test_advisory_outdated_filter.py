"""Drop unpatched advisories whose affected range no longer covers `latest`."""

from __future__ import annotations

from biibaa.domain import Advisory
from biibaa.pipeline.run import _drop_outdated_unpatched


class _FakeRegistry:
    def __init__(self, mapping: dict[str, str | None]) -> None:
        self._mapping = mapping

    def latest_versions(self, *, packages: list[str]) -> dict[str, str | None]:
        return {p: self._mapping.get(p) for p in packages}


def _adv(*, ghsa: str, name: str, affected: str | None) -> Advisory:
    return Advisory(
        id=ghsa,
        project_purl=f"pkg:npm/{name}",
        summary="t",
        affected_versions=affected,
    )


def test_drops_when_latest_outside_affected_range() -> None:
    advisories = [_adv(ghsa="GHSA-codex", name="@openai/codex", affected="<= 0.23.0")]
    registry = _FakeRegistry({"@openai/codex": "0.125.0"})
    out = _drop_outdated_unpatched(advisories, registry)  # type: ignore[arg-type]
    assert out == []


def test_keeps_when_latest_still_in_range() -> None:
    advisories = [_adv(ghsa="GHSA-x", name="widget", affected=">= 0.0.1")]
    registry = _FakeRegistry({"widget": "1.5.0"})
    out = _drop_outdated_unpatched(advisories, registry)  # type: ignore[arg-type]
    assert [a.id for a in out] == ["GHSA-x"]


def test_keeps_when_latest_unknown() -> None:
    """Don't drop on a registry blip."""
    advisories = [_adv(ghsa="GHSA-y", name="ghost", affected="<= 0.1.0")]
    registry = _FakeRegistry({"ghost": None})
    out = _drop_outdated_unpatched(advisories, registry)  # type: ignore[arg-type]
    assert [a.id for a in out] == ["GHSA-y"]


def test_keeps_when_range_unparseable() -> None:
    advisories = [_adv(ghsa="GHSA-z", name="weird", affected="completely-malformed")]
    registry = _FakeRegistry({"weird": "1.0.0"})
    out = _drop_outdated_unpatched(advisories, registry)  # type: ignore[arg-type]
    assert [a.id for a in out] == ["GHSA-z"]


def test_keeps_when_no_affected_range() -> None:
    advisories = [_adv(ghsa="GHSA-w", name="unbounded", affected=None)]
    registry = _FakeRegistry({"unbounded": "2.0.0"})
    out = _drop_outdated_unpatched(advisories, registry)  # type: ignore[arg-type]
    assert [a.id for a in out] == ["GHSA-w"]
