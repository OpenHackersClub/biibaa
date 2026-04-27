"""npm registry adapter — record the dist-tags.latest contract."""

from __future__ import annotations

import httpx
from pytest_httpx import HTTPXMock

from biibaa.adapters.npm_registry import NpmRegistrySource


def test_latest_version_reads_dist_tag(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://registry.npmjs.org/@openai/codex",
        json={"dist-tags": {"latest": "0.125.0"}},
    )
    src = NpmRegistrySource(client=httpx.Client())
    assert src.latest_version(package="@openai/codex") == "0.125.0"


def test_latest_version_returns_none_on_404(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://registry.npmjs.org/missing-pkg",
        status_code=404,
    )
    src = NpmRegistrySource(client=httpx.Client())
    assert src.latest_version(package="missing-pkg") is None


def test_latest_version_handles_missing_dist_tag(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://registry.npmjs.org/empty",
        json={"versions": {}},
    )
    src = NpmRegistrySource(client=httpx.Client())
    assert src.latest_version(package="empty") is None


def test_latest_versions_iterates(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://registry.npmjs.org/a", json={"dist-tags": {"latest": "1.0.0"}}
    )
    httpx_mock.add_response(
        url="https://registry.npmjs.org/b", json={"dist-tags": {"latest": "2.0.0"}}
    )
    src = NpmRegistrySource(client=httpx.Client())
    assert src.latest_versions(packages=["a", "b"]) == {"a": "1.0.0", "b": "2.0.0"}
