"""End-to-end smoke: land fixture → ``sqlmesh plan`` → assert the mart materializes.

Catches the wiring bugs that the per-file unit tests can't: model graph
resolution, macro evaluation against real data, audit assertions on the
landed Parquet, and DuckDB type compatibility between writer and staging
SELECT lists.

Skipped when the optional ``warehouse`` extra (sqlmesh + duckdb) isn't
installed, and on Python 3.14+ until upstream sqlmesh stops referencing
``ast.Str`` (removed from the stdlib in 3.14).
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

# sqlmesh 0.234.x calls ast.Str during model load; that attribute is gone in 3.14.
# Track upstream — once a release supports 3.14, drop this guard.
if sys.version_info >= (3, 14):
    pytest.skip(
        "sqlmesh 0.234.x incompatible with Python 3.14 (ast.Str removed)",
        allow_module_level=True,
    )

duckdb = pytest.importorskip("duckdb")
pytest.importorskip("sqlmesh")

from sqlmesh.core.config import (  # noqa: E402
    Config,
    DuckDBConnectionConfig,
    GatewayConfig,
    ModelDefaultsConfig,
)
from sqlmesh.core.context import Context  # noqa: E402

from biibaa.domain import Advisory, Project  # noqa: E402
from biibaa.warehouse import land_advisories, land_projects  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SQLMESH_DIR = REPO_ROOT / "sqlmesh"


def _build_config(raw_root: Path, db_path: Path) -> Config:
    return Config(
        gateways={
            "local": GatewayConfig(
                connection=DuckDBConnectionConfig(database=str(db_path)),
            ),
        },
        default_gateway="local",
        model_defaults=ModelDefaultsConfig(dialect="duckdb"),
        variables={"raw_root": str(raw_root)},
    )


def _yesterday() -> date:
    # The staging models are INCREMENTAL_BY_TIME_RANGE @daily — sqlmesh only
    # backfills *complete* intervals, so today's partition wouldn't be picked up.
    return date.today() - timedelta(days=1)


def test_sqlmesh_plan_materializes_marts_opportunities(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    db = tmp_path / "warehouse.duckdb"
    ingest = _yesterday()

    land_advisories(
        [
            Advisory(
                id="GHSA-aaa",
                project_purl="pkg:npm/foo",
                severity="high",
                cvss=8.0,
                summary="boom",
                affected_versions="<1.2.3",
                fixed_versions=["1.2.3"],
                refs=[],
                published_at=datetime(2026, 4, 1, tzinfo=UTC),
                repo_url="https://github.com/foo/foo",
            ),
            # Pairs with an archived project below — must drop out of the mart.
            Advisory(
                id="GHSA-archived",
                project_purl="pkg:npm/dead",
                severity="critical",
                cvss=9.0,
                summary="ignored",
                affected_versions="<1.0.0",
                fixed_versions=["1.0.0"],
                refs=[],
                published_at=datetime(2026, 4, 1, tzinfo=UTC),
                repo_url="https://github.com/dead/dead",
            ),
        ],
        raw_root=raw,
        ingest_date=ingest,
    )
    land_projects(
        [
            Project(
                purl="pkg:npm/foo",
                ecosystem="npm",
                name="foo",
                repo_url="https://github.com/foo/foo",
                stars=1234,
                downloads_weekly=10_000,
                dependents=500,
                archived=False,
            ),
            Project(
                purl="pkg:npm/dead",
                ecosystem="npm",
                name="dead",
                repo_url="https://github.com/dead/dead",
                archived=True,
            ),
        ],
        raw_root=raw,
        ingest_date=ingest,
    )

    ctx = Context(paths=[str(SQLMESH_DIR)], config=_build_config(raw, db))
    ctx.plan(auto_apply=True, no_prompts=True)

    con = duckdb.connect(str(db))
    rows = con.execute(
        """
        SELECT id, kind, project_purl, ecosystem, project_name,
               advisory_severity, project_dependents, score
        FROM marts.opportunities
        ORDER BY id
        """
    ).fetchall()

    assert len(rows) == 1, f"archived project should drop out; got {rows}"
    (oid, kind, purl, eco, name, sev, deps, score) = rows[0]
    assert oid == "GHSA-aaa"
    assert kind == "vulnerability-fix"
    assert purl == "pkg:npm/foo"
    assert eco == "npm"
    assert name == "foo"
    assert sev == "high"
    assert deps == 500
    assert 0.0 <= score <= 1.0
