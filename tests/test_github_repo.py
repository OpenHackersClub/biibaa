"""Adapter unit tests for GithubRepoSource (latest-merged-PR signal)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
from pytest_httpx import HTTPXMock

from biibaa.adapters.github_repo import GithubRepoSource


def test_returns_merged_at_for_known_repo(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.github.com/graphql",
        method="POST",
        json={
            "data": {
                "repository": {
                    "pullRequests": {
                        "nodes": [{"mergedAt": "2026-04-20T12:34:56Z"}],
                    }
                }
            }
        },
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    got = src.last_merged_pr_at(repo_url="https://github.com/facebook/react")
    assert got == datetime(2026, 4, 20, 12, 34, 56, tzinfo=UTC)


def test_returns_none_when_no_merged_prs(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.github.com/graphql",
        method="POST",
        json={"data": {"repository": {"pullRequests": {"nodes": []}}}},
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    assert src.last_merged_pr_at(repo_url="https://github.com/example/empty") is None


def test_returns_none_on_graphql_errors(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.github.com/graphql",
        method="POST",
        json={"errors": [{"message": "Could not resolve to a Repository"}]},
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    assert src.last_merged_pr_at(repo_url="https://github.com/ghost/missing") is None


def test_returns_none_on_http_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.github.com/graphql", method="POST", status_code=502
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    assert src.last_merged_pr_at(repo_url="https://github.com/example/repo") is None


def test_results_are_cached_per_repo(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.github.com/graphql",
        method="POST",
        json={
            "data": {
                "repository": {
                    "pullRequests": {"nodes": [{"mergedAt": "2026-04-01T00:00:00Z"}]}
                }
            }
        },
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    a = src.last_merged_pr_at(repo_url="https://github.com/foo/bar")
    b = src.last_merged_pr_at(repo_url="https://github.com/foo/bar")
    assert a == b
    # Only one request despite two calls — pytest-httpx asserts this on teardown
    # if no further mocks are registered.


def test_unparseable_repo_url_returns_none() -> None:
    src = GithubRepoSource(token="x", client=httpx.Client())
    assert src.last_merged_pr_at(repo_url="not-a-url") is None
    assert src.last_merged_pr_at(repo_url="https://gitlab.com/x/y") is None
