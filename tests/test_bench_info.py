"""Bench-presence detection on `GithubRepoSource.bench_info`.

The signal is a low-cost triage hint, not a scoring input — a repo that
maintains benchmarks is the easiest target for a perf-replacement PR
because the change can be falsified against the repo's own harness.

Detection is heuristic and runs against the HEAD `package.json` we
already fetch for direct-dep verification (zero extra HTTP per repo).
"""

from __future__ import annotations

import httpx
from pytest_httpx import HTTPXMock

from biibaa.adapters.github_repo import GithubRepoSource


def test_bench_info_detects_bench_script(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/foo/bar/HEAD/package.json",
        method="GET",
        json={
            "name": "bar",
            "scripts": {"test": "vitest", "bench": "node bench.js"},
        },
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    has_bench, signal = src.bench_info(repo_url="https://github.com/foo/bar")
    assert has_bench is True
    assert signal == "script:bench"


def test_bench_info_detects_namespaced_bench_script(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/foo/bar/HEAD/package.json",
        method="GET",
        json={"scripts": {"benchmark:run": "tinybench bench/*"}},
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    has_bench, signal = src.bench_info(repo_url="https://github.com/foo/bar")
    assert has_bench is True
    assert signal == "script:benchmark:run"


def test_bench_info_detects_known_bench_devdep(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/foo/bar/HEAD/package.json",
        method="GET",
        json={
            "scripts": {"test": "vitest"},
            "devDependencies": {"tinybench": "^2.0.0", "vitest": "^1.0.0"},
        },
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    has_bench, signal = src.bench_info(repo_url="https://github.com/foo/bar")
    assert has_bench is True
    assert signal == "devDep:tinybench"


def test_bench_info_returns_false_when_no_signal(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/foo/bar/HEAD/package.json",
        method="GET",
        json={
            "name": "bar",
            "scripts": {"test": "vitest", "lint": "eslint ."},
            "devDependencies": {"vitest": "^1.0.0", "eslint": "^9.0.0"},
        },
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    has_bench, signal = src.bench_info(repo_url="https://github.com/foo/bar")
    assert has_bench is False
    assert signal is None


def test_bench_info_returns_false_when_pkg_unreachable(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/ghost/missing/HEAD/package.json",
        method="GET",
        status_code=404,
        text="404",
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    has_bench, signal = src.bench_info(repo_url="https://github.com/ghost/missing")
    assert has_bench is False
    assert signal is None


def test_bench_info_shares_cache_with_fetch_direct_deps(httpx_mock: HTTPXMock) -> None:
    """One HTTP call must serve both direct-deps verification and bench_info.

    This is the only reason it's safe to enable bench detection in the
    pipeline — it piggybacks on the package.json fan-out already does.
    """
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/foo/bar/HEAD/package.json",
        method="GET",
        json={
            "dependencies": {"react": "^18.0.0"},
            "devDependencies": {"mitata": "^0.1.0"},
            "scripts": {"build": "tsc"},
        },
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    deps = src.fetch_direct_deps(repo_url="https://github.com/foo/bar")
    has_bench, signal = src.bench_info(repo_url="https://github.com/foo/bar")
    assert deps == {"react", "mitata"}
    assert has_bench is True
    assert signal == "devDep:mitata"
    # No second mock registered — pytest-httpx fails teardown if a 2nd hit fired.


def test_bench_info_script_match_is_case_insensitive(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/foo/bar/HEAD/package.json",
        method="GET",
        json={"scripts": {"Bench": "node bench.js"}},
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    has_bench, signal = src.bench_info(repo_url="https://github.com/foo/bar")
    assert has_bench is True
    assert signal == "script:Bench"
