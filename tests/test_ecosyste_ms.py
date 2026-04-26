"""ecosyste.ms dependents adapter contract test."""

from __future__ import annotations

import httpx
from pytest_httpx import HTTPXMock

from biibaa.adapters.ecosyste_ms import ECOSYSTEMS_BASE, EcosystemsSource


def test_returns_top_dependents_with_repo_url(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{ECOSYSTEMS_BASE}/isarray/dependent_packages?sort=downloads&order=desc&per_page=3",
        json=[
            {
                "name": "readable-stream",
                "downloads": 1_000_000_000,
                "repository_url": "https://github.com/nodejs/readable-stream",
            },
            {
                "name": "buffer",
                "downloads": 500_000_000,
                "repository_url": "https://github.com/feross/buffer",
            },
            {
                # Missing name → skipped
                "downloads": 1,
                "repository_url": None,
            },
        ],
    )
    src = EcosystemsSource(client=httpx.Client())
    out = src.fetch_dependents(package="isarray", top_k=3)
    assert [d.name for d in out] == ["readable-stream", "buffer"]
    assert out[0].repo_url == "https://github.com/nodejs/readable-stream"
    assert out[0].purl == "pkg:npm/readable-stream"
    assert out[0].lifetime_downloads == 1_000_000_000


def test_returns_empty_on_404(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{ECOSYSTEMS_BASE}/missing-pkg/dependent_packages?sort=downloads&order=desc&per_page=10",
        status_code=404,
    )
    src = EcosystemsSource(client=httpx.Client())
    assert src.fetch_dependents(package="missing-pkg", top_k=10) == []
