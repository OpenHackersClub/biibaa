"""DuckDB / SQLMesh warehouse glue.

The MVP pipeline runs entirely in memory (see `pipeline/run.py`). This
package is the deferred-warehouse slice from SPEC §9.A: raw Parquet
landing today, SQLMesh-driven staging/marts in follow-ups.

Importing this module requires the optional `warehouse` extra
(`uv pip install -e '.[warehouse]'`) which pulls DuckDB.
"""

from biibaa.warehouse.landing import (
    DEFAULT_RAW_ROOT,
    OpportunityTransition,
    land_advisories,
    land_dependents,
    land_opportunity_transitions,
    land_projects,
    land_replacements,
)

__all__ = [
    "DEFAULT_RAW_ROOT",
    "OpportunityTransition",
    "land_advisories",
    "land_dependents",
    "land_opportunity_transitions",
    "land_projects",
    "land_replacements",
]
