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
from biibaa.warehouse import (  # noqa: E402
    OpportunityTransition,
    land_advisories,
    land_dependents,
    land_opportunity_transitions,
    land_projects,
    land_replacements,
)

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
    # backfills *complete* intervals. Use UTC since sqlmesh evaluates interval
    # boundaries against UTC; ``date.today()`` returns local date and can be
    # one day ahead of UTC in non-zero timezones (e.g. +08 just past midnight),
    # making "yesterday" land in an interval that hasn't closed yet.
    return (datetime.now(UTC) - timedelta(days=1)).date()


def _land_empty_aux(raw_root: Path, ingest_date: date) -> None:
    """Land empty replacements/dependents so the staging globs match.

    DuckDB ``READ_PARQUET('.../dt=*/*.parquet')`` errors when no files match;
    the new ``staging.replacements`` and ``staging.dependents`` models would
    fail without these even though the test only exercises advisories+projects.
    """
    land_replacements([], raw_root=raw_root, ingest_date=ingest_date)
    land_dependents({}, raw_root=raw_root, ingest_date=ingest_date)
    land_opportunity_transitions([], raw_root=raw_root, ingest_date=ingest_date)


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

    _land_empty_aux(raw, ingest)

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

    _land_empty_aux(raw, ingest)

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


def test_opportunity_state_aggregates_first_last_seen_across_partitions(
    tmp_path: Path,
) -> None:
    """``marts.opportunity_state`` derives ``first_seen_at`` / ``last_seen_at``
    by aggregating over historical staging partitions. Land the same advisory
    on two different ingest_dates and assert the lifecycle row reflects the
    full span — the cross-run signal we need before adding a state machine.
    """
    raw = tmp_path / "raw"
    db = tmp_path / "warehouse.duckdb"
    today_utc = datetime.now(UTC).date()
    older = today_utc - timedelta(days=5)
    newer = today_utc - timedelta(days=1)

    advisory_dict = dict(
        id="GHSA-recurring",
        project_purl="pkg:npm/foo",
        severity="high",
        cvss=7.5,
        summary="patch fix",
        affected_versions="<1.2.3",
        fixed_versions=["1.2.3"],
        refs=[],
        published_at=datetime(2026, 4, 1, tzinfo=UTC),
        repo_url="https://github.com/foo/foo",
    )
    project = Project(
        purl="pkg:npm/foo",
        ecosystem="npm",
        name="foo",
        repo_url="https://github.com/foo/foo",
        downloads_weekly=10_000,
        archived=False,
    )

    for dt in (older, newer):
        land_advisories([Advisory(**advisory_dict)], raw_root=raw, ingest_date=dt)
        land_projects([project], raw_root=raw, ingest_date=dt)
        _land_empty_aux(raw, dt)

    ctx = Context(paths=[str(SQLMESH_DIR)], config=_build_config(raw, db))
    ctx.plan(auto_apply=True, no_prompts=True)

    con = duckdb.connect(str(db))
    rows = con.execute(
        """
        SELECT dedupe_key, kind, project_purl, first_seen_at, last_seen_at,
               partition_count, state
        FROM marts.opportunity_state
        """
    ).fetchall()
    assert len(rows) == 1
    (key, kind, purl, first_seen, last_seen, count, state) = rows[0]
    assert key == "pkg:npm/foo|GHSA-recurring"
    assert kind == "vulnerability-fix"
    assert purl == "pkg:npm/foo"
    assert first_seen.date() == older
    assert last_seen.date() == newer
    assert count == 2
    assert state == "new"


def test_opportunity_state_applies_latest_transition(tmp_path: Path) -> None:
    """``marts.opportunity_state.state`` reflects the latest transition for
    each ``dedupe_key``, defaulting to ``'new'`` when none has been recorded.

    Lands two transitions for the same dedupe_key with different timestamps
    and asserts the later one wins. A second dedupe_key has no transition;
    its state must default to ``'new'``.
    """
    raw = tmp_path / "raw"
    db = tmp_path / "warehouse.duckdb"
    ingest = _yesterday()
    now = datetime.now(UTC)

    land_advisories(
        [
            Advisory(
                id="GHSA-acked",
                project_purl="pkg:npm/foo",
                severity="high",
                cvss=7.5,
                summary="patch fix",
                affected_versions="<1.2.3",
                fixed_versions=["1.2.3"],
                refs=[],
                published_at=datetime(2026, 4, 1, tzinfo=UTC),
                repo_url="https://github.com/foo/foo",
            ),
            Advisory(
                id="GHSA-untouched",
                project_purl="pkg:npm/bar",
                severity="medium",
                cvss=5.0,
                summary="patch fix",
                affected_versions="<2.0.0",
                fixed_versions=["2.0.0"],
                refs=[],
                published_at=datetime(2026, 4, 1, tzinfo=UTC),
                repo_url="https://github.com/bar/bar",
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
                downloads_weekly=10_000,
                archived=False,
            ),
            Project(
                purl="pkg:npm/bar",
                ecosystem="npm",
                name="bar",
                repo_url="https://github.com/bar/bar",
                downloads_weekly=5_000,
                archived=False,
            ),
        ],
        raw_root=raw,
        ingest_date=ingest,
    )
    land_replacements([], raw_root=raw, ingest_date=ingest)
    land_dependents({}, raw_root=raw, ingest_date=ingest)

    # Two transitions for foo: an earlier 'acknowledged' then a later
    # 'resolved'. The later one wins.
    land_opportunity_transitions(
        [
            OpportunityTransition(
                dedupe_key="pkg:npm/foo|GHSA-acked",
                to_state="acknowledged",
                transitioned_at=now - timedelta(hours=2),
                actor="alice",
                reason="triaged",
            ),
            OpportunityTransition(
                dedupe_key="pkg:npm/foo|GHSA-acked",
                to_state="resolved",
                transitioned_at=now - timedelta(hours=1),
                actor="bob",
                reason="patch landed upstream",
            ),
        ],
        raw_root=raw,
        ingest_date=ingest,
    )

    ctx = Context(paths=[str(SQLMESH_DIR)], config=_build_config(raw, db))
    ctx.plan(auto_apply=True, no_prompts=True)

    con = duckdb.connect(str(db))
    rows = {
        key: (state, actor, reason)
        for key, state, actor, reason in con.execute(
            "SELECT dedupe_key, state, state_actor, state_reason "
            "FROM marts.opportunity_state"
        ).fetchall()
    }
    assert rows["pkg:npm/foo|GHSA-acked"] == ("resolved", "bob", "patch landed upstream")
    assert rows["pkg:npm/bar|GHSA-untouched"] == ("new", None, None)
