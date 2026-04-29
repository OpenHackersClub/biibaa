"""Round-trip tests for ``biibaa.warehouse.landing``.

These exist to lock the on-disk contract with SQLMesh: the staging models
under ``sqlmesh/models/staging/`` ``READ_PARQUET`` the partitions written
here, and they project a fixed column list and types. If the writer drifts
from that schema, the staging models silently start emitting NULLs.

Skipped when the optional ``warehouse`` extra (DuckDB) isn't installed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb")

from biibaa.domain import Advisory, Project  # noqa: E402
from biibaa.warehouse import land_advisories, land_projects  # noqa: E402


def _advisory(**overrides) -> Advisory:
    base = dict(
        id="GHSA-aaaa-bbbb-cccc",
        project_purl="pkg:npm/foo",
        severity="high",
        cvss=7.5,
        summary="boom",
        affected_versions="<1.2.3",
        fixed_versions=["1.2.3", "2.0.0"],
        refs=["https://github.com/advisories/GHSA-aaaa-bbbb-cccc"],
        published_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        repo_url="https://github.com/foo/foo",
    )
    base.update(overrides)
    return Advisory(**base)


def _project(**overrides) -> Project:
    base = dict(
        purl="pkg:npm/foo",
        ecosystem="npm",
        name="foo",
        repo_url="https://github.com/foo/foo",
        downloads_weekly=12_345,
        archived=False,
    )
    base.update(overrides)
    return Project(**base)


def test_land_advisories_writes_partitioned_parquet(tmp_path: Path) -> None:
    out = land_advisories(
        [_advisory(), _advisory(id="GHSA-zzz", fixed_versions=[])],
        raw_root=tmp_path,
        ingest_date=date(2026, 4, 29),
    )
    assert out == tmp_path / "advisories" / "dt=2026-04-29" / "advisories.parquet"
    assert out.exists()

    con = duckdb.connect()
    rows = con.execute(
        f"SELECT id, fixed_versions, ingest_date FROM read_parquet('{out}') ORDER BY id"
    ).fetchall()
    assert rows == [
        ("GHSA-aaaa-bbbb-cccc", ["1.2.3", "2.0.0"], date(2026, 4, 29)),
        ("GHSA-zzz", [], date(2026, 4, 29)),
    ]


def test_land_advisories_glob_matches_sqlmesh_pattern(tmp_path: Path) -> None:
    """The staging model reads `<raw_root>/advisories/dt=*/*.parquet`."""
    land_advisories([_advisory()], raw_root=tmp_path, ingest_date=date(2026, 4, 28))
    land_advisories([_advisory()], raw_root=tmp_path, ingest_date=date(2026, 4, 29))

    con = duckdb.connect()
    (count,) = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{tmp_path}/advisories/dt=*/*.parquet')"
    ).fetchone()
    assert count == 2


def test_land_advisories_empty_keeps_schema(tmp_path: Path) -> None:
    out = land_advisories([], raw_root=tmp_path, ingest_date=date(2026, 4, 29))
    con = duckdb.connect()
    schema = {
        name: ddl
        for name, ddl, *_ in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{out}')"
        ).fetchall()
    }
    # Spot-check the columns that staging projects out.
    assert schema["id"] == "VARCHAR"
    assert schema["cvss"] == "DOUBLE"
    assert schema["fixed_versions"] == "VARCHAR[]"
    assert schema["refs"] == "VARCHAR[]"
    assert schema["published_at"] == "TIMESTAMP"
    assert schema["ingest_date"] == "DATE"


def test_land_projects_writes_typed_columns(tmp_path: Path) -> None:
    out = land_projects(
        [
            _project(),
            _project(
                purl="pkg:npm/bar",
                name="bar",
                downloads_weekly=None,
                archived=True,
                last_pr_merged_at=datetime(2026, 4, 1, tzinfo=UTC),
            ),
        ],
        raw_root=tmp_path,
        ingest_date=date(2026, 4, 29),
    )
    assert out == tmp_path / "projects" / "dt=2026-04-29" / "projects.parquet"

    con = duckdb.connect()
    rows = con.execute(
        f"SELECT purl, downloads_weekly, archived, ingest_date "
        f"FROM read_parquet('{out}') ORDER BY purl"
    ).fetchall()
    assert rows == [
        ("pkg:npm/bar", None, True, date(2026, 4, 29)),
        ("pkg:npm/foo", 12_345, False, date(2026, 4, 29)),
    ]


def test_land_advisories_idempotent_overwrite(tmp_path: Path) -> None:
    """Re-landing the same partition replaces the file, not appends."""
    land_advisories(
        [_advisory(), _advisory(id="GHSA-old")],
        raw_root=tmp_path,
        ingest_date=date(2026, 4, 29),
    )
    out = land_advisories(
        [_advisory()],
        raw_root=tmp_path,
        ingest_date=date(2026, 4, 29),
    )
    con = duckdb.connect()
    (count,) = con.execute(
        f"SELECT COUNT(*) FROM read_parquet('{out}')"
    ).fetchone()
    assert count == 1
