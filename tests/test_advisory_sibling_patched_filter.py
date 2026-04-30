"""Drop unpatched advisories when a sibling package in the same GHSA is patched."""

from __future__ import annotations

from biibaa.domain import Advisory
from biibaa.pipeline.run import _drop_when_sibling_patched


def _adv(*, ghsa: str, name: str, has_patched_sibling: bool) -> Advisory:
    return Advisory(
        id=ghsa,
        project_purl=f"pkg:npm/{name}",
        summary="t",
        has_patched_sibling=has_patched_sibling,
    )


def test_drops_when_sibling_patched() -> None:
    advisories = [_adv(ghsa="GHSA-xmldom", name="xmldom", has_patched_sibling=True)]
    assert _drop_when_sibling_patched(advisories) == []


def test_keeps_when_no_sibling_patched() -> None:
    advisories = [_adv(ghsa="GHSA-lonely", name="lonely", has_patched_sibling=False)]
    out = _drop_when_sibling_patched(advisories)
    assert [a.id for a in out] == ["GHSA-lonely"]


def test_mixed_keeps_only_unpatched_siblings() -> None:
    advisories = [
        _adv(ghsa="GHSA-a", name="abandoned", has_patched_sibling=True),
        _adv(ghsa="GHSA-b", name="standalone", has_patched_sibling=False),
    ]
    out = _drop_when_sibling_patched(advisories)
    assert [a.id for a in out] == ["GHSA-b"]
