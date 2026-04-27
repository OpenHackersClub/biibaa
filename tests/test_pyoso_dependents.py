"""PyosoSource contract — sboms_v0 + repositories_v0 join.

Skipped if the optional [pyoso] extra isn't installed."""

from __future__ import annotations

import pytest

pytest.importorskip("pyoso")

import pandas as pd  # noqa: E402

from biibaa.adapters.pyoso_dependents import (  # noqa: E402
    PyosoSource,
    build_query,
)
from biibaa.ports.dependents import Dependent  # noqa: E402


def test_query_filters_npm_github_with_min_stars() -> None:
    q = build_query(package="debug", min_stars=100, top_k=20)
    assert "package_artifact_source = 'NPM'" in q
    assert "package_artifact_name = 'debug'" in q
    assert "dependent_artifact_source = 'GITHUB'" in q
    assert "star_count >= 100" in q
    assert "ORDER BY r.star_count DESC" in q
    assert "LIMIT 20" in q


def test_query_joins_sboms_with_repositories() -> None:
    q = build_query(package="lodash", min_stars=10, top_k=5)
    assert "FROM sboms_v0 s" in q
    assert "LEFT JOIN repositories_v0 r" in q
    assert "ON s.dependent_artifact_id = r.artifact_id" in q


class _StubClient:
    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df
        self.last_sql: str | None = None

    def to_pandas(self, sql: str) -> pd.DataFrame:
        self.last_sql = sql
        return self.df


def test_maps_rows_to_github_dependents() -> None:
    df = pd.DataFrame(
        [
            {
                "owner": "facebook",
                "repo": "react",
                "star_count": 244574,
                "repo_url": "https://github.com/facebook/react",
            },
            {
                "owner": "vuejs",
                "repo": "vue",
                "star_count": 209840,
                "repo_url": "https://github.com/vuejs/vue",
            },
        ]
    )
    src = PyosoSource(client=_StubClient(df))
    out = src.fetch_dependents(package="debug", top_k=10)
    assert out == [
        Dependent(
            name="facebook/react",
            purl="pkg:github/facebook/react",
            repo_url="https://github.com/facebook/react",
            lifetime_downloads=None,
        ),
        Dependent(
            name="vuejs/vue",
            purl="pkg:github/vuejs/vue",
            repo_url="https://github.com/vuejs/vue",
            lifetime_downloads=None,
        ),
    ]


def test_rejects_invalid_package_name() -> None:
    """Defends raw-SQL splicing — non-npm-spec names are dropped, not run."""
    src = PyosoSource(client=_StubClient(pd.DataFrame()))
    assert src.fetch_dependents(package="debug'; DROP TABLE x;--", top_k=10) == []
    assert src.fetch_dependents(package="@scope/pkg", top_k=10) == []  # this IS valid
    # Verify no SQL fired for the bad name
    bad = PyosoSource(client=_StubClient(pd.DataFrame()))
    bad.fetch_dependents(package="../etc/passwd", top_k=10)
    assert bad._client.last_sql is None  # type: ignore[attr-defined]


def test_query_error_returns_empty() -> None:
    class _Boom:
        def to_pandas(self, sql: str) -> pd.DataFrame:
            raise RuntimeError("500 Internal Server Error")

    src = PyosoSource(client=_Boom())
    assert src.fetch_dependents(package="debug", top_k=10) == []
