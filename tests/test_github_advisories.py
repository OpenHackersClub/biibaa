"""Adapter unit test using pytest-httpx to record the GHSA contract."""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

from biibaa.adapters.github_advisories import GithubAdvisorySource

_FIXTURE = [
    {
        "ghsa_id": "GHSA-test-1111-aaaa",
        "summary": "Test vuln in widget",
        "severity": "critical",
        "cvss_severities": {"cvss_v3": {"score": 9.1}, "cvss_v4": {"score": 0.0}},
        "references": ["https://example.com/advisory"],
        "published_at": "2026-04-01T00:00:00Z",
        "vulnerabilities": [
            {
                "package": {"ecosystem": "npm", "name": "widget"},
                "vulnerable_version_range": ">= 1.0.0, < 1.2.3",
                "first_patched_version": "1.2.3",
            },
            {
                # missing fix → must be skipped
                "package": {"ecosystem": "npm", "name": "thingy"},
                "vulnerable_version_range": ">= 0.0.1",
                "first_patched_version": None,
            },
        ],
    }
]


@pytest.fixture
def adv_client(httpx_mock: HTTPXMock) -> GithubAdvisorySource:
    httpx_mock.add_response(
        url="https://api.github.com/advisories?ecosystem=npm&per_page=100&severity=critical",
        json=_FIXTURE,
    )
    httpx_mock.add_response(
        url="https://api.github.com/advisories?ecosystem=npm&per_page=100&severity=high",
        json=[],
    )
    return GithubAdvisorySource(client=httpx.Client())


def test_emits_one_advisory_per_fixed_package(adv_client: GithubAdvisorySource) -> None:
    out = list(adv_client.fetch())
    assert len(out) == 1
    a = out[0]
    assert a.id == "GHSA-test-1111-aaaa"
    assert a.project_purl == "pkg:npm/widget"
    assert a.fixed_versions == ["1.2.3"]
    assert a.cvss == 9.1
    assert a.severity == "critical"
