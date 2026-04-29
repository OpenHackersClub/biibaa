from __future__ import annotations

from sqlmesh import macro
from sqlmesh.core.macros import MacroEvaluator
from sqlglot import exp


@macro()
def score_opportunity(
    evaluator: MacroEvaluator,
    cvss: exp.Expression,
    dependents: exp.Expression,
) -> exp.Expression:
    """Stub heuristic — port of `scoring.py` lands in a follow-up.

    Score in [0, 1]: half from CVSS (0–10 → 0–0.5), half from a log-scaled
    dependents fan-out (cap 100k → 0.5). Real heuristic is in `src/biibaa/scoring.py`.
    """
    return exp.maybe_parse(
        f"LEAST(1.0, "
        f"  COALESCE(({cvss.sql()}) / 20.0, 0) + "
        f"  COALESCE(LN(GREATEST(({dependents.sql()}), 1)) / LN(100000) * 0.5, 0)"
        f")",
        dialect="duckdb",
    )
