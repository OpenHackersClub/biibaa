from pathlib import Path

from sqlmesh.core.config import Config, DuckDBConnectionConfig, GatewayConfig, ModelDefaultsConfig

REPO_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_PATH = REPO_ROOT / "data" / "warehouse.duckdb"

config = Config(
    gateways={
        "local": GatewayConfig(
            connection=DuckDBConnectionConfig(database=str(WAREHOUSE_PATH)),
        ),
    },
    default_gateway="local",
    model_defaults=ModelDefaultsConfig(dialect="duckdb"),
    variables={"raw_root": str(REPO_ROOT / "data" / "raw")},
)
