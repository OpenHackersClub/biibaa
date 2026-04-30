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

from biibaa.domain import Advisory, Project, Replacement  # noqa: E402
from biibaa.ports.dependents import Dependent  # noqa: E402
from biibaa.warehouse import (  # noqa: E402
    land_advisories,
    land_dependents,
    land_projects,
    land_replacements,
)


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


def test_land_replacements_writes_typed_columns(tmp_path: Path) -> None:
    out = land_replacements(
        [
            Replacement(
                id="micro-utilities/is-array",
                from_purl="pkg:npm/is-array",
                to_purls=["pkg:npm/array-isarray"],
                axis="bloat",
                effort="drop-in",
                evidence={"saved_bytes": 1234, "note": "trivial swap"},
            ),
            Replacement(
                id="native/util-promisify",
                from_purl="pkg:npm/util-promisify",
                to_purls=[],
                axis="bloat",
                effort="drop-in",
            ),
        ],
        raw_root=tmp_path,
        ingest_date=date(2026, 4, 28),
    )
    assert out == tmp_path / "replacements" / "dt=2026-04-28" / "replacements.parquet"

    con = duckdb.connect()
    rows = con.execute(
        f"SELECT id, from_purl, to_purls, axis, effort, evidence_json, ingest_date "
        f"FROM read_parquet('{out}') ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    (id1, from1, to1, axis1, eff1, ev1, dt1) = rows[0]
    assert id1 == "micro-utilities/is-array"
    assert from1 == "pkg:npm/is-array"
    assert to1 == ["pkg:npm/array-isarray"]
    assert axis1 == "bloat"
    assert eff1 == "drop-in"
    assert "saved_bytes" in ev1  # JSON-serialized
    assert dt1 == date(2026, 4, 28)
    # Empty evidence → NULL column
    assert rows[1][5] is None


def test_land_replacements_empty_keeps_schema(tmp_path: Path) -> None:
    out = land_replacements([], raw_root=tmp_path, ingest_date=date(2026, 4, 28))
    con = duckdb.connect()
    schema = {
        name: ddl
        for name, ddl, *_ in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{out}')"
        ).fetchall()
    }
    assert schema["id"] == "VARCHAR"
    assert schema["from_purl"] == "VARCHAR"
    assert schema["to_purls"] == "VARCHAR[]"
    assert schema["axis"] == "VARCHAR"
    assert schema["effort"] == "VARCHAR"
    assert schema["ingest_date"] == "DATE"


def test_land_dependents_flattens_fan_out(tmp_path: Path) -> None:
    out = land_dependents(
        {
            "pkg:npm/foo": [
                Dependent(
                    name="alpha",
                    purl="pkg:npm/alpha",
                    repo_url="https://github.com/alpha/alpha",
                    lifetime_downloads=1_000_000,
                ),
                Dependent(
                    name="beta",
                    purl="pkg:npm/beta",
                    repo_url=None,
                    lifetime_downloads=None,
                ),
            ],
            "pkg:npm/bar": [
                Dependent(
                    name="gamma",
                    purl="pkg:npm/gamma",
                    repo_url="https://github.com/gamma/gamma",
                    lifetime_downloads=42,
                ),
            ],
        },
        raw_root=tmp_path,
        ingest_date=date(2026, 4, 28),
    )
    assert out == tmp_path / "dependents" / "dt=2026-04-28" / "dependents.parquet"

    con = duckdb.connect()
    rows = con.execute(
        f"SELECT parent_purl, dependent_purl, dependent_lifetime_downloads "
        f"FROM read_parquet('{out}') ORDER BY parent_purl, dependent_purl"
    ).fetchall()
    assert rows == [
        ("pkg:npm/bar", "pkg:npm/gamma", 42),
        ("pkg:npm/foo", "pkg:npm/alpha", 1_000_000),
        ("pkg:npm/foo", "pkg:npm/beta", None),
    ]


def test_land_dependents_empty_keeps_schema(tmp_path: Path) -> None:
    out = land_dependents({}, raw_root=tmp_path, ingest_date=date(2026, 4, 28))
    con = duckdb.connect()
    schema = {
        name: ddl
        for name, ddl, *_ in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{out}')"
        ).fetchall()
    }
    assert schema["parent_purl"] == "VARCHAR"
    assert schema["dependent_purl"] == "VARCHAR"
    assert schema["dependent_lifetime_downloads"] == "BIGINT"
    assert schema["ingest_date"] == "DATE"


def test_land_opportunity_transitions_writes_event_log(tmp_path: Path) -> None:
    from biibaa.warehouse import OpportunityTransition, land_opportunity_transitions

    out = land_opportunity_transitions(
        [
            OpportunityTransition(
                dedupe_key="pkg:npm/foo|GHSA-aaa",
                to_state="acknowledged",
                transitioned_at=datetime(2026, 4, 28, 10, 0, tzinfo=UTC),
                actor="alice",
                reason="triaged",
            ),
            OpportunityTransition(
                dedupe_key="pkg:npm/foo|GHSA-aaa",
                to_state="resolved",
                transitioned_at=datetime(2026, 4, 28, 12, 0, tzinfo=UTC),
                actor=None,
                reason=None,
            ),
        ],
        raw_root=tmp_path,
        ingest_date=date(2026, 4, 28),
    )
    assert out == tmp_path / "opportunity_transitions" / "dt=2026-04-28" / "transitions.parquet"

    con = duckdb.connect()
    rows = con.execute(
        f"SELECT dedupe_key, to_state, transitioned_at, actor, reason "
        f"FROM read_parquet('{out}') ORDER BY transitioned_at"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0][1] == "acknowledged"
    assert rows[0][3] == "alice"
    assert rows[1][1] == "resolved"
    assert rows[1][3] is None


def test_land_opportunity_transitions_empty_keeps_schema(tmp_path: Path) -> None:
    from biibaa.warehouse import land_opportunity_transitions

    out = land_opportunity_transitions(
        [], raw_root=tmp_path, ingest_date=date(2026, 4, 28)
    )
    con = duckdb.connect()
    schema = {
        name: ddl
        for name, ddl, *_ in con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{out}')"
        ).fetchall()
    }
    assert schema["dedupe_key"] == "VARCHAR"
    assert schema["to_state"] == "VARCHAR"
    assert schema["transitioned_at"] == "TIMESTAMP"
    assert schema["ingest_date"] == "DATE"
