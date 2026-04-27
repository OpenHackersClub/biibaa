"""Cover the GHSA range strings the pipeline relies on."""

from __future__ import annotations

from biibaa.adapters._semver import is_version_in_range


def test_lte_matches_within_range() -> None:
    assert is_version_in_range("0.23.0", "<= 0.23.0") is True
    assert is_version_in_range("0.22.5", "<= 0.23.0") is True


def test_lte_excludes_newer_version() -> None:
    # The motivating case: @openai/codex affected `<= 0.23.0`, latest 0.125.0.
    assert is_version_in_range("0.125.0", "<= 0.23.0") is False


def test_compound_range_and_semantics() -> None:
    assert is_version_in_range("1.1.0", ">= 1.0.0, < 1.2.3") is True
    assert is_version_in_range("1.2.3", ">= 1.0.0, < 1.2.3") is False
    assert is_version_in_range("0.9.9", ">= 1.0.0, < 1.2.3") is False


def test_open_range_matches_everything() -> None:
    assert is_version_in_range("9.9.9", ">= 0.0.1") is True


def test_unparseable_range_returns_none() -> None:
    assert is_version_in_range("1.0.0", "garbage") is None


def test_unparseable_version_returns_none() -> None:
    assert is_version_in_range("not-a-version", "<= 1.0.0") is None


def test_v_prefix_and_minor_only() -> None:
    assert is_version_in_range("v1.2", "<= 1.2.0") is True
    assert is_version_in_range("1.2", "< 1.2.0") is False


def test_prerelease_metadata_stripped() -> None:
    # Pre-release tags are dropped before comparison; advisories nearly
    # always pin to released versions, so this trade-off is acceptable.
    assert is_version_in_range("1.0.0-beta.1", "<= 1.0.0") is True
