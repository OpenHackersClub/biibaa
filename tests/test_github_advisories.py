"""Adapter unit test using pytest-httpx to record the GHSA contract."""

from __future__ import annotations

import httpx
from pytest_httpx import HTTPXMock

from biibaa.adapters.github_advisories import GithubAdvisorySource

_FIXTURE = [
    {
        "ghsa_id": "GHSA-test-1111-aaaa",
        "summary": "Test vuln across two packages",
        "severity": "critical",
        "cvss_severities": {"cvss_v3": {"score": 9.1}, "cvss_v4": {"score": 0.0}},
        "references": ["https://example.com/advisory"],
        "published_at": "2026-04-01T00:00:00Z",
        "source_code_location": "https://github.com/example/thingy",
        "vulnerabilities": [
            {
                "package": {"ecosystem": "npm", "name": "widget"},
                "vulnerable_version_range": ">= 1.0.0, < 1.2.3",
                "first_patched_version": "1.2.3",
            },
            {
                "package": {"ecosystem": "npm", "name": "thingy"},
                "vulnerable_version_range": ">= 0.0.1",
                "first_patched_version": None,
            },
        ],
    },
    {
        "ghsa_id": "GHSA-test-2222-bbbb",
        "summary": "Withdrawn advisory should be skipped",
        "severity": "high",
        "cvss_severities": {"cvss_v3": {"score": 8.0}, "cvss_v4": {"score": 0.0}},
        "withdrawn_at": "2026-04-15T00:00:00Z",
        "vulnerabilities": [
            {
                "package": {"ecosystem": "npm", "name": "widget"},
                "vulnerable_version_range": "< 2.0.0",
                "first_patched_version": None,
            }
        ],
    },
]


def _mock(httpx_mock: HTTPXMock) -> None:
    for sev in ("critical", "high", "medium"):
        httpx_mock.add_response(
            url=f"https://api.github.com/advisories?ecosystem=npm&per_page=100&severity={sev}",
            json=_FIXTURE if sev == "critical" else [],
        )


def test_only_unpatched_emits_packages_without_fix(httpx_mock: HTTPXMock) -> None:
    _mock(httpx_mock)
    src = GithubAdvisorySource(client=httpx.Client())
    out = list(src.fetch())
    assert len(out) == 1
    a = out[0]
    assert a.id == "GHSA-test-1111-aaaa"
    assert a.project_purl == "pkg:npm/thingy"
    assert a.fixed_versions == []
    assert a.repo_url == "https://github.com/example/thingy"
    # Sibling `widget` in the same GHSA is patched — flag for downstream filtering.
    assert a.has_patched_sibling is True


def test_has_patched_sibling_false_when_all_unpatched(httpx_mock: HTTPXMock) -> None:
    fixture = [
        {
            "ghsa_id": "GHSA-test-3333-cccc",
            "summary": "All packages still unpatched",
            "severity": "high",
            "cvss_severities": {"cvss_v3": {"score": 7.5}},
            "vulnerabilities": [
                {
                    "package": {"ecosystem": "npm", "name": "lonely"},
                    "vulnerable_version_range": "<= 0.1.0",
                    "first_patched_version": None,
                }
            ],
        }
    ]
    for sev in ("critical", "high", "medium"):
        httpx_mock.add_response(
            url=f"https://api.github.com/advisories?ecosystem=npm&per_page=100&severity={sev}",
            json=fixture if sev == "high" else [],
        )
    src = GithubAdvisorySource(client=httpx.Client())
    out = list(src.fetch())
    assert len(out) == 1
    assert out[0].has_patched_sibling is False


def test_legacy_only_unpatched_false_emits_patched(httpx_mock: HTTPXMock) -> None:
    """When inverted, the adapter still works for the original "fix-available" mode."""
    _mock(httpx_mock)
    src = GithubAdvisorySource(client=httpx.Client())
    out = list(src.fetch(only_unpatched=False))
    assert len(out) == 1
    assert out[0].project_purl == "pkg:npm/widget"
    assert out[0].fixed_versions == ["1.2.3"]


def test_withdrawn_advisories_are_skipped(httpx_mock: HTTPXMock) -> None:
    _mock(httpx_mock)
    src = GithubAdvisorySource(client=httpx.Client())
    out = list(src.fetch())
    # GHSA-test-2222 is withdrawn — its (unpatched) vulnerability must not appear.
    assert all(a.id != "GHSA-test-2222-bbbb" for a in out)
