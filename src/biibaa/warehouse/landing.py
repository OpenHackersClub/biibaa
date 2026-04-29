"""Land domain entities as Parquet under ``data/raw/<source>/dt=YYYY-MM-DD/``.

The SQLMesh staging models (``sqlmesh/models/staging/stg_*.sql``) read these
partitions via DuckDB ``READ_PARQUET`` and select on ``ingest_date BETWEEN
@start_date AND @end_date``, so the partition column **must** be present in
each row — partition discovery from the path alone isn't enough.

Schemas mirror the column lists declared in the staging models. Extra fields
on the Pydantic domain types (``last_pr_merged_at``, ``bench_signal``) are
written too so downstream marts can pick them up without re-landing; the
current staging models simply don't project them yet.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from biibaa.domain import Advisory, Project

if TYPE_CHECKING:
    import duckdb

log = structlog.get_logger(__name__)

DEFAULT_RAW_ROOT = Path("data/raw")


_ADVISORY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("id", "TEXT"),
    ("project_purl", "TEXT"),
    ("severity", "TEXT"),
    ("cvss", "DOUBLE"),
    ("summary", "TEXT"),
    ("affected_versions", "TEXT"),
    ("fixed_versions", "TEXT[]"),
    ("refs", "TEXT[]"),
    ("published_at", "TIMESTAMP"),
    ("repo_url", "TEXT"),
    ("ingest_date", "DATE"),
)

_PROJECT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("purl", "TEXT"),
    ("ecosystem", "TEXT"),
    ("name", "TEXT"),
    ("repo_url", "TEXT"),
    ("homepage", "TEXT"),
    ("stars", "BIGINT"),
    ("downloads_weekly", "BIGINT"),
    ("dependents", "BIGINT"),
    ("last_release_at", "TIMESTAMP"),
    ("last_commit_at", "TIMESTAMP"),
    ("last_pr_merged_at", "TIMESTAMP"),
    ("archived", "BOOLEAN"),
    ("has_benchmarks", "BOOLEAN"),
    ("bench_signal", "TEXT"),
    ("ingest_date", "DATE"),
)


def _connect() -> duckdb.DuckDBPyConnection:
    try:
        import duckdb
    except ImportError as exc:  # pragma: no cover - exercised via extras
        raise RuntimeError(
            "biibaa.warehouse requires the 'warehouse' extra. "
            "Install with: uv pip install -e '.[warehouse]'"
        ) from exc
    return duckdb.connect()


def _strip_tz(value: datetime | None) -> datetime | None:
    """DuckDB ``TIMESTAMP`` is naive; drop tzinfo before binding.

    Domain datetimes are tz-aware UTC by convention (``datetime.now(UTC)``),
    so dropping tzinfo preserves the wall-clock UTC instant.
    """
    if value is None or value.tzinfo is None:
        return value
    return value.replace(tzinfo=None)


def _advisory_row(adv: Advisory, ingest_date: date) -> tuple[Any, ...]:
    return (
        adv.id,
        adv.project_purl,
        adv.severity,
        adv.cvss,
        adv.summary,
        adv.affected_versions,
        list(adv.fixed_versions),
        list(adv.refs),
        _strip_tz(adv.published_at),
        adv.repo_url,
        ingest_date,
    )


def _project_row(proj: Project, ingest_date: date) -> tuple[Any, ...]:
    return (
        proj.purl,
        proj.ecosystem,
        proj.name,
        proj.repo_url,
        proj.homepage,
        proj.stars,
        proj.downloads_weekly,
        proj.dependents,
        _strip_tz(proj.last_release_at),
        _strip_tz(proj.last_commit_at),
        _strip_tz(proj.last_pr_merged_at),
        proj.archived,
        proj.has_benchmarks,
        proj.bench_signal,
        ingest_date,
    )


def _partition_path(root: Path, source: str, ingest_date: date, filename: str) -> Path:
    return root / source / f"dt={ingest_date.isoformat()}" / filename


def _write(
    *,
    table_name: str,
    columns: Sequence[tuple[str, str]],
    rows: Sequence[tuple[Any, ...]],
    out_path: Path,
) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    con = _connect()
    try:
        col_defs = ", ".join(f"{name} {ddl_type}" for name, ddl_type in columns)
        con.execute(f"CREATE TEMP TABLE {table_name} ({col_defs})")
        if rows:
            placeholders = ", ".join(["?"] * len(columns))
            con.executemany(
                f"INSERT INTO {table_name} VALUES ({placeholders})", rows
            )
        # Quote the path so colons / spaces don't trip DuckDB's parser.
        con.execute(
            f"COPY {table_name} TO '{out_path.as_posix()}' (FORMAT PARQUET)"
        )
    finally:
        con.close()
    return out_path


def land_advisories(
    advisories: Iterable[Advisory],
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
    ingest_date: date | None = None,
    filename: str = "advisories.parquet",
) -> Path:
    """Land advisories at ``<raw_root>/advisories/dt=<ingest_date>/<filename>``.

    Idempotent per ``(ingest_date, filename)`` — re-landing overwrites in place.
    Returns the absolute output path. Empty input still produces an empty
    Parquet file with the declared schema so downstream incremental models
    don't fail on a missing partition.
    """
    ingest_date = ingest_date or date.today()
    advisories = list(advisories)
    rows = [_advisory_row(a, ingest_date) for a in advisories]
    out_path = _partition_path(raw_root, "advisories", ingest_date, filename)
    _write(
        table_name="advisories",
        columns=_ADVISORY_COLUMNS,
        rows=rows,
        out_path=out_path,
    )
    log.info(
        "warehouse.advisories_landed",
        path=str(out_path),
        rows=len(rows),
        ingest_date=ingest_date.isoformat(),
    )
    return out_path


def land_projects(
    projects: Iterable[Project],
    *,
    raw_root: Path = DEFAULT_RAW_ROOT,
    ingest_date: date | None = None,
    filename: str = "projects.parquet",
) -> Path:
    """Land projects at ``<raw_root>/projects/dt=<ingest_date>/<filename>``.

    See :func:`land_advisories` for semantics.
    """
    ingest_date = ingest_date or date.today()
    projects = list(projects)
    rows = [_project_row(p, ingest_date) for p in projects]
    out_path = _partition_path(raw_root, "projects", ingest_date, filename)
    _write(
        table_name="projects",
        columns=_PROJECT_COLUMNS,
        rows=rows,
        out_path=out_path,
    )
    log.info(
        "warehouse.projects_landed",
        path=str(out_path),
        rows=len(rows),
        ingest_date=ingest_date.isoformat(),
    )
    return out_path
