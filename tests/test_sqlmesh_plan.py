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
from biibaa.scoring import (  # noqa: E402
    confidence,
    effort_score,
    final_score,
    impact,
    popularity,
    severity_score,
)
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


def test_score_opportunity_macro_matches_python_scoring(tmp_path: Path) -> None:
    """The SQL ``score_opportunity`` macro must produce the same value as
    ``biibaa.scoring.final_score / 100``. This is the load-bearing parity
    check — if the macro and Python drift, briefs and the warehouse rank
    opportunities differently.

    Two fixtures pin determinism around the confidence decay window:
    one is "fresh" (last_pr_merged_at well within 14d ⇒ confidence=100)
    and one is "stale" (>365d ⇒ confidence=0), so neither depends on
    sub-second drift between Python ``datetime.now`` and DuckDB ``NOW()``.
    """
    raw = tmp_path / "raw"
    db = tmp_path / "warehouse.duckdb"
    ingest = _yesterday()
    now = datetime.now(UTC)

    fixtures = [
        # Fresh, drop-in version bump, popular package
        dict(
            id="GHSA-fresh",
            purl="pkg:npm/popular",
            cvss=7.5,
            summary="patch fix",
            fixed_versions=["1.2.3"],
            stars=10_000,
            downloads_weekly=5_000_000,
            last_pr_merged_at=now - timedelta(days=1),
        ),
        # Stale, breaking summary (effort=60), low popularity
        dict(
            id="GHSA-stale",
            purl="pkg:npm/quiet",
            cvss=4.0,
            summary="breaking rewrite required",
            fixed_versions=["2.0.0"],
            stars=10,
            downloads_weekly=100,
            last_pr_merged_at=now - timedelta(days=400),
        ),
        # NULL-heavy: missing CVSS, empty fix versions, no PR signal — exercises
        # every COALESCE / IS NULL branch in the macro.
        dict(
            id="GHSA-nulls",
            purl="pkg:npm/sparse",
            cvss=None,
            summary="",
            fixed_versions=[],
            stars=None,
            downloads_weekly=None,
            last_pr_merged_at=None,
        ),
    ]

    land_advisories(
        [
            Advisory(
                id=f["id"],
                project_purl=f["purl"],
                severity="high",
                cvss=f["cvss"],
                summary=f["summary"],
                affected_versions="<1.0.0",
                fixed_versions=f["fixed_versions"],
                refs=[],
                published_at=datetime(2026, 4, 1, tzinfo=UTC),
                repo_url=f"https://github.com/{f['purl'].split('/')[-1]}/repo",
            )
            for f in fixtures
        ],
        raw_root=raw,
        ingest_date=ingest,
    )
    land_projects(
        [
            Project(
                purl=f["purl"],
                ecosystem="npm",
                name=f["purl"].split("/")[-1],
                repo_url=f"https://github.com/{f['purl'].split('/')[-1]}/repo",
                stars=f["stars"],
                downloads_weekly=f["downloads_weekly"],
                last_pr_merged_at=f["last_pr_merged_at"],
                archived=False,
            )
            for f in fixtures
        ],
        raw_root=raw,
        ingest_date=ingest,
    )

    ctx = Context(paths=[str(SQLMESH_DIR)], config=_build_config(raw, db))
    ctx.plan(auto_apply=True, no_prompts=True)

    con = duckdb.connect(str(db))
    sql_scores = dict(
        con.execute("SELECT id, score FROM marts.opportunities").fetchall()
    )

    for f in fixtures:
        pop = popularity(downloads_weekly=f["downloads_weekly"], stars=f["stars"])
        sev = severity_score(cvss=f["cvss"])
        eff = effort_score(
            fixed_versions=f["fixed_versions"], advisory_summary=f["summary"]
        )
        imp = impact(pop=pop, sev=sev)
        conf = confidence(last_pr_merged_at=f["last_pr_merged_at"], now=now)
        expected = final_score(impact_value=imp, effort_value=eff, confidence_value=conf) / 100.0

        actual = sql_scores[f["id"]]
        assert abs(actual - expected) < 1e-4, (
            f"{f['id']}: SQL={actual:.6f} vs Python={expected:.6f} "
            f"(pop={pop:.2f} sev={sev:.2f} eff={eff:.2f} imp={imp:.2f} conf={conf:.2f})"
        )
