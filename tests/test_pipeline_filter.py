"""Eligibility filter — drop archived repos and packages below downloads floor."""

from __future__ import annotations

from biibaa.domain import Project
from biibaa.pipeline.run import _is_eligible


def _project(*, archived: bool = False, downloads: int | None = 100_000) -> Project:
    return Project(
        purl="pkg:npm/x",
        ecosystem="npm",
        name="x",
        archived=archived,
        downloads_weekly=downloads,
    )


def test_eligible_when_active_and_popular() -> None:
    assert _is_eligible(_project(), min_weekly_downloads=50_000) is True


def test_filtered_when_archived() -> None:
    assert _is_eligible(_project(archived=True), min_weekly_downloads=50_000) is False


def test_filtered_when_below_downloads_floor() -> None:
    assert (
        _is_eligible(_project(downloads=49_999), min_weekly_downloads=50_000) is False
    )


def test_unknown_downloads_passes() -> None:
    """A None downloads count means npm-stat blip — don't drop the project."""
    assert _is_eligible(_project(downloads=None), min_weekly_downloads=50_000) is True


def test_at_threshold_is_eligible() -> None:
    assert _is_eligible(_project(downloads=50_000), min_weekly_downloads=50_000) is True
