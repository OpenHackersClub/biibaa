"""Direct-dep verification — drop fan-out candidates whose package.json
doesn't list the from-package as a direct dependency.

Root cause: OSO `sboms_v0` is lockfile-derived and includes the full
transitive tree, so unverified fan-outs end up recommending packages
to repos that only pull them in via dev tooling (jest, release-please,
etc.). This filter compares against the repo's HEAD `package.json`.
"""

from __future__ import annotations

import httpx
from pytest_httpx import HTTPXMock

from biibaa.adapters.github_repo import MONOREPO_SENTINEL, GithubRepoSource
from biibaa.domain import Replacement
from biibaa.pipeline.run import _fan_out_dependents
from biibaa.ports.dependents import Dependent

# ---------- GithubRepoSource.fetch_direct_deps ----------


def test_fetch_direct_deps_merges_dependencies_and_dev_dependencies(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/foo/bar/HEAD/package.json",
        method="GET",
        json={
            "name": "bar",
            "dependencies": {"lodash": "^4.0.0", "react": "^18.0.0"},
            "devDependencies": {"jest": "^29.0.0"},
        },
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    got = src.fetch_direct_deps(repo_url="https://github.com/foo/bar")
    assert got == {"lodash", "react", "jest"}


def test_fetch_direct_deps_returns_empty_set_when_manifest_has_no_deps(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/foo/bar/HEAD/package.json",
        method="GET",
        json={"name": "bar", "version": "1.0.0"},
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    got = src.fetch_direct_deps(repo_url="https://github.com/foo/bar")
    assert got == set()


def test_fetch_direct_deps_returns_monorepo_sentinel_for_array_workspaces_without_lockfile(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/mono/repo/HEAD/package.json",
        method="GET",
        json={
            "name": "mono",
            "private": True,
            "workspaces": ["packages/*", "apps/*"],
            "dependencies": {"lodash": "^4.0.0"},
        },
    )
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/mono/repo/HEAD/pnpm-lock.yaml",
        method="GET",
        status_code=404,
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    got = src.fetch_direct_deps(repo_url="https://github.com/mono/repo")
    assert got == {MONOREPO_SENTINEL}


def test_fetch_direct_deps_returns_monorepo_sentinel_for_object_workspaces_without_lockfile(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/mono/repo/HEAD/package.json",
        method="GET",
        json={
            "name": "mono",
            "workspaces": {
                "packages": ["packages/*"],
                "nohoist": ["**/foo"],
            },
        },
    )
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/mono/repo/HEAD/pnpm-lock.yaml",
        method="GET",
        status_code=404,
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    got = src.fetch_direct_deps(repo_url="https://github.com/mono/repo")
    assert got == {MONOREPO_SENTINEL}


def test_fetch_direct_deps_uses_pnpm_lockfile_for_monorepo(
    httpx_mock: HTTPXMock,
) -> None:
    """Monorepo + pnpm-lock.yaml present → returns union of importer direct
    deps so transitive-only matches (e.g. stream-buffers under expo) are
    filtered out instead of letting the sentinel bypass the check."""
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/mono/repo/HEAD/package.json",
        method="GET",
        json={
            "name": "mono",
            "private": True,
            "workspaces": {"packages": ["packages/*"]},
        },
    )
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/mono/repo/HEAD/pnpm-lock.yaml",
        method="GET",
        text=(
            "lockfileVersion: '6.0'\n"
            "importers:\n"
            "  .:\n"
            "    devDependencies:\n"
            "      eslint:\n"
            "        specifier: ^8\n"
            "        version: 8.57.0\n"
            "  packages/oauth-client-expo:\n"
            "    peerDependencies:\n"
            "      expo:\n"
            "        specifier: '*'\n"
            "        version: 50.0.0\n"
            "    dependencies:\n"
            "      jose:\n"
            "        specifier: ^5\n"
            "        version: 5.2.0\n"
            "packages:\n"
            "  /stream-buffers@3.0.2:\n"
            "    resolution: {integrity: sha512-fake}\n"
        ),
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    got = src.fetch_direct_deps(repo_url="https://github.com/mono/repo")
    assert got == {"eslint", "expo", "jose"}
    assert got is not None and "stream-buffers" not in got


def test_fetch_pnpm_lockfile_falls_back_when_yaml_invalid(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/mono/repo/HEAD/package.json",
        method="GET",
        json={"name": "mono", "workspaces": ["packages/*"]},
    )
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/mono/repo/HEAD/pnpm-lock.yaml",
        method="GET",
        text="not: valid: yaml: : :",
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    got = src.fetch_direct_deps(repo_url="https://github.com/mono/repo")
    assert got == {MONOREPO_SENTINEL}


def test_fetch_pnpm_lockfile_falls_back_when_no_importers(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/mono/repo/HEAD/package.json",
        method="GET",
        json={"name": "mono", "workspaces": ["packages/*"]},
    )
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/mono/repo/HEAD/pnpm-lock.yaml",
        method="GET",
        text="lockfileVersion: '6.0'\n",
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    got = src.fetch_direct_deps(repo_url="https://github.com/mono/repo")
    assert got == {MONOREPO_SENTINEL}


def test_fetch_direct_deps_returns_none_on_404(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/ghost/missing/HEAD/package.json",
        method="GET",
        status_code=404,
        text="404: Not Found",
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    assert src.fetch_direct_deps(repo_url="https://github.com/ghost/missing") is None


def test_fetch_direct_deps_returns_none_on_invalid_json(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/foo/bar/HEAD/package.json",
        method="GET",
        text="<!DOCTYPE html>not json",
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    assert src.fetch_direct_deps(repo_url="https://github.com/foo/bar") is None


def test_fetch_direct_deps_caches_per_repo(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/foo/bar/HEAD/package.json",
        method="GET",
        json={"dependencies": {"x": "1"}},
    )
    src = GithubRepoSource(token="x", client=httpx.Client())
    a = src.fetch_direct_deps(repo_url="https://github.com/foo/bar")
    b = src.fetch_direct_deps(repo_url="https://github.com/foo/bar")
    assert a == b == {"x"}
    # Only one mock registered — pytest-httpx fails teardown if a 2nd hit fired.


# ---------- pipeline-level filter ----------


class _StubEcoSrc:
    name = "stub"

    def __init__(self, dependents: list[Dependent]) -> None:
        self._dependents = dependents

    def fetch_dependents(self, *, package: str, top_k: int = 10) -> list[Dependent]:
        return self._dependents

    def close(self) -> None:
        pass


class _StubDownloadsSrc:
    """Returns fixed weekly download counts. Avoids real npm calls."""

    def __init__(self, counts: dict[str, int]) -> None:
        self._counts = counts

    def weekly_downloads_bulk(
        self, *, packages: list[str]
    ) -> dict[str, int | None]:
        return {p: self._counts.get(p) for p in packages}

    def close(self) -> None:
        pass


def _replacement(from_name: str) -> Replacement:
    return Replacement(
        id=f"e18e:{from_name}",
        from_purl=f"pkg:npm/{from_name}",
        to_purls=["pkg:npm/<native>"],
        axis="bloat",
        effort="drop-in",
    )


def _dep(name: str, repo_url: str | None) -> Dependent:
    return Dependent(
        name=name,
        purl=f"pkg:npm/{name}",
        repo_url=repo_url,
        lifetime_downloads=None,
    )


def _make_repo_src(client: httpx.Client) -> GithubRepoSource:
    return GithubRepoSource(token="x", client=client)


def test_filter_drops_candidate_without_direct_dep(
    httpx_mock: HTTPXMock,
) -> None:
    """uuid-style case: lodash.snakecase only present transitively."""
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/uuidjs/uuid/HEAD/package.json",
        method="GET",
        json={
            "name": "uuid",
            "dependencies": {},
            "devDependencies": {"jest": "^29", "release-please": "^16"},
        },
    )
    eco = _StubEcoSrc(
        [_dep("uuid", "https://github.com/uuidjs/uuid")]
    )
    downloads = _StubDownloadsSrc({"lodash.snakecase": 5_000_000})
    repo_src = _make_repo_src(httpx.Client())
    out = _fan_out_dependents(
        replacements=[_replacement("lodash.snakecase")],
        eco_src=eco,  # type: ignore[arg-type]
        downloads_src=downloads,  # type: ignore[arg-type]
        fanout_top_n=10,
        dependents_per_replacement=5,
        repo_src=repo_src,
    )
    assert out == []


def test_filter_keeps_candidate_with_direct_dep(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/some/consumer/HEAD/package.json",
        method="GET",
        json={"dependencies": {"lodash.snakecase": "^4.0.0"}},
    )
    eco = _StubEcoSrc(
        [_dep("consumer", "https://github.com/some/consumer")]
    )
    downloads = _StubDownloadsSrc({"lodash.snakecase": 5_000_000})
    repo_src = _make_repo_src(httpx.Client())
    out = _fan_out_dependents(
        replacements=[_replacement("lodash.snakecase")],
        eco_src=eco,  # type: ignore[arg-type]
        downloads_src=downloads,  # type: ignore[arg-type]
        fanout_top_n=10,
        dependents_per_replacement=5,
        repo_src=repo_src,
    )
    assert [d.name for _, d in out] == ["consumer"]


def test_filter_keeps_candidate_when_verification_returns_none(
    httpx_mock: HTTPXMock,
) -> None:
    """404 / parse error → unknown, don't filter."""
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/some/private/HEAD/package.json",
        method="GET",
        status_code=404,
    )
    eco = _StubEcoSrc(
        [_dep("private-pkg", "https://github.com/some/private")]
    )
    downloads = _StubDownloadsSrc({"lodash.snakecase": 5_000_000})
    repo_src = _make_repo_src(httpx.Client())
    out = _fan_out_dependents(
        replacements=[_replacement("lodash.snakecase")],
        eco_src=eco,  # type: ignore[arg-type]
        downloads_src=downloads,  # type: ignore[arg-type]
        fanout_top_n=10,
        dependents_per_replacement=5,
        repo_src=repo_src,
    )
    assert [d.name for _, d in out] == ["private-pkg"]


def test_filter_keeps_candidate_for_monorepo_root_without_lockfile(
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/big/mono/HEAD/package.json",
        method="GET",
        json={
            "name": "mono",
            "private": True,
            "workspaces": ["packages/*"],
            "devDependencies": {"jest": "^29"},
        },
    )
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/big/mono/HEAD/pnpm-lock.yaml",
        method="GET",
        status_code=404,
    )
    eco = _StubEcoSrc(
        [_dep("mono", "https://github.com/big/mono")]
    )
    downloads = _StubDownloadsSrc({"lodash.snakecase": 5_000_000})
    repo_src = _make_repo_src(httpx.Client())
    out = _fan_out_dependents(
        replacements=[_replacement("lodash.snakecase")],
        eco_src=eco,  # type: ignore[arg-type]
        downloads_src=downloads,  # type: ignore[arg-type]
        fanout_top_n=10,
        dependents_per_replacement=5,
        repo_src=repo_src,
    )
    assert [d.name for _, d in out] == ["mono"]


def test_filter_drops_transitive_only_dep_in_monorepo_with_pnpm_lock(
    httpx_mock: HTTPXMock,
) -> None:
    """The atproto/stream-buffers regression: a pnpm monorepo where the
    flagged package only appears via a 4-deep transitive chain. Lockfile
    parsing surfaces the real direct deps so the candidate is dropped."""
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/bsky/atproto/HEAD/package.json",
        method="GET",
        json={
            "name": "atp",
            "private": True,
            "workspaces": {"packages": ["packages/*"]},
        },
    )
    httpx_mock.add_response(
        url="https://raw.githubusercontent.com/bsky/atproto/HEAD/pnpm-lock.yaml",
        method="GET",
        text=(
            "lockfileVersion: '6.0'\n"
            "importers:\n"
            "  .:\n"
            "    devDependencies:\n"
            "      eslint:\n"
            "        specifier: ^8\n"
            "        version: 8.57.0\n"
            "  packages/oauth-client-expo:\n"
            "    peerDependencies:\n"
            "      expo:\n"
            "        specifier: '*'\n"
            "        version: 50.0.0\n"
        ),
    )
    eco = _StubEcoSrc(
        [_dep("atproto", "https://github.com/bsky/atproto")]
    )
    downloads = _StubDownloadsSrc({"stream-buffers": 12_000_000})
    repo_src = _make_repo_src(httpx.Client())
    out = _fan_out_dependents(
        replacements=[_replacement("stream-buffers")],
        eco_src=eco,  # type: ignore[arg-type]
        downloads_src=downloads,  # type: ignore[arg-type]
        fanout_top_n=10,
        dependents_per_replacement=5,
        repo_src=repo_src,
    )
    assert out == []


def test_filter_disabled_when_repo_src_is_none() -> None:
    """No repo_src kwarg → original behavior, return all candidates."""
    eco = _StubEcoSrc(
        [_dep("transitive-only", "https://github.com/foo/bar")]
    )
    downloads = _StubDownloadsSrc({"lodash.snakecase": 5_000_000})
    out = _fan_out_dependents(
        replacements=[_replacement("lodash.snakecase")],
        eco_src=eco,  # type: ignore[arg-type]
        downloads_src=downloads,  # type: ignore[arg-type]
        fanout_top_n=10,
        dependents_per_replacement=5,
    )
    assert [d.name for _, d in out] == ["transitive-only"]
