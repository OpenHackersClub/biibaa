from __future__ import annotations

from sqlglot import exp
from sqlmesh.core.macros import MacroEvaluator

from sqlmesh import macro


@macro()
def score_opportunity(
    evaluator: MacroEvaluator,
    cvss: exp.Expression,
    downloads_weekly: exp.Expression,
    stars: exp.Expression,
    fixed_versions: exp.Expression,
    advisory_summary: exp.Expression,
    last_pr_merged_at: exp.Expression,
) -> exp.Expression:
    """SQL port of ``biibaa.scoring.final_score`` for vulnerability-fix opportunities.

    Returns a value in ``[0, 1]`` = ``(0.6*impact + 0.25*effort + 0.15*confidence) / 100``,
    where each sub-score is on the [0, 100] scale per SPEC §6. The canonical Python
    implementation lives in ``src/biibaa/scoring.py``; ``tests/test_sqlmesh_plan.py``
    asserts SQL ↔ Python parity on rich fixtures.

    Constants kept inline (rather than `@VAR`) so the macro is self-contained:
    DOWNLOADS_REF_NPM=1e8, STARS_REF=1e5, blend weights 0.7/0.3 and 0.6/0.25/0.15,
    confidence window 14d→365d, unknown=30.
    """
    cvss_sql = cvss.sql()
    dw_sql = downloads_weekly.sql()
    stars_sql = stars.sql()
    fv_sql = fixed_versions.sql()
    summary_sql = advisory_summary.sql()
    pr_sql = last_pr_merged_at.sql()

    sql = f"""
    (
      (
        0.6 * (
          GREATEST(0.0, LEAST(100.0,
            100.0 * (
              0.7 * COALESCE(LOG10(1.0 + ({dw_sql})) / LOG10(1.0 + 100000000.0), 0.0)
              + 0.3 * COALESCE(LOG10(1.0 + ({stars_sql})) / LOG10(1.0 + 100000.0), 0.0)
            )
          )) / 100.0
          * GREATEST(0.0, LEAST(100.0, COALESCE(({cvss_sql}), 5.0) * 10.0))
        )
        + 0.25 * (
          CASE
            WHEN ({fv_sql}) IS NULL OR LEN({fv_sql}) = 0 THEN 20.0
            WHEN LOWER(COALESCE(({summary_sql}), '')) LIKE '%breaking%'
              OR LOWER(COALESCE(({summary_sql}), '')) LIKE '%rewrite%'
              OR LOWER(COALESCE(({summary_sql}), '')) LIKE '%rearchitect%'
              OR LOWER(COALESCE(({summary_sql}), '')) LIKE '%removed api%'
              THEN 60.0
            WHEN REGEXP_MATCHES(({fv_sql})[1], '^[vV]*[0-9]+([.].*)?$') THEN 95.0
            ELSE 70.0
          END
        )
        + 0.15 * (
          CASE
            WHEN ({pr_sql}) IS NULL THEN 30.0
            WHEN (EPOCH(NOW()) - EPOCH(({pr_sql}))) / 86400.0 <= 14.0 THEN 100.0
            WHEN (EPOCH(NOW()) - EPOCH(({pr_sql}))) / 86400.0 >= 365.0 THEN 0.0
            ELSE 100.0 * (
              1.0 - ((EPOCH(NOW()) - EPOCH(({pr_sql}))) / 86400.0 - 14.0) / 351.0
            )
          END
        )
      ) / 100.0
    )
    """
    return exp.maybe_parse(sql, dialect="duckdb")
