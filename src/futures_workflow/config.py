import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict


def _path_from_env(env_name: str, default: Path) -> Path:
    value = str(os.environ.get(env_name, "") or "").strip()
    if not value:
        return default
    return Path(value).expanduser()


PROJECT_ROOT = _path_from_env("FUTURES_WORKFLOW_PROJECT_ROOT", Path(__file__).resolve().parents[2])
CONFIG_PATH = _path_from_env("FUTURES_WORKFLOW_CONFIG_PATH", PROJECT_ROOT / "config" / "sources.yaml")
DATA_DIR = _path_from_env("FUTURES_WORKFLOW_DATA_DIR", PROJECT_ROOT / "data")
ARCHIVE_DIR = DATA_DIR / "archives"
RAW_DIR = DATA_DIR / "raw"
NORMALIZED_ROOT = DATA_DIR / "normalized"
NORMALIZED_DIR = DATA_DIR / "normalized" / "daily_quotes"
PUBLIC_ASSETS_NORMALIZED_DIR = NORMALIZED_ROOT / "public_assets"
PUBLIC_REFERENCES_NORMALIZED_DIR = NORMALIZED_ROOT / "public_references"
PUBLIC_BONDS_NORMALIZED_DIR = NORMALIZED_ROOT / "public_bonds"
CRYPTO_NORMALIZED_DIR = NORMALIZED_ROOT / "crypto_global"
PLATFORM_NORMALIZED_DIR = NORMALIZED_ROOT / "platform"
QUERY_NORMALIZED_DIR = NORMALIZED_ROOT / "queries"
DB_DIR = _path_from_env("FUTURES_WORKFLOW_DB_DIR", DATA_DIR / "db")
DUCKDB_PATH = _path_from_env("FUTURES_WORKFLOW_DUCKDB_PATH", DB_DIR / "market_data.duckdb")
EXPORTS_DIR = _path_from_env("FUTURES_WORKFLOW_EXPORTS_DIR", DATA_DIR / "exports")
EXPORT_CSV_DIR = EXPORTS_DIR / "csv"
EXPORT_JSON_DIR = EXPORTS_DIR / "json"
EXPORT_PARQUET_DIR = EXPORTS_DIR / "parquet"
LOG_DIR = DATA_DIR / "logs"
STATE_DIR = _path_from_env("FUTURES_WORKFLOW_STATE_DIR", PROJECT_ROOT / "state")
CHECKPOINT_PATH = _path_from_env("FUTURES_WORKFLOW_CHECKPOINT_PATH", STATE_DIR / "checkpoints.json")
QUERY_STATE_DIR = _path_from_env("FUTURES_WORKFLOW_QUERY_STATE_DIR", STATE_DIR / "query_runs")
PUBLIC_ASSET_STATE_PATH = _path_from_env("FUTURES_WORKFLOW_PUBLIC_ASSET_STATE_PATH", STATE_DIR / "public_assets.json")
PUBLIC_REFERENCE_STATE_PATH = _path_from_env("FUTURES_WORKFLOW_PUBLIC_REFERENCE_STATE_PATH", STATE_DIR / "public_references.json")
PUBLIC_BOND_STATE_PATH = _path_from_env("FUTURES_WORKFLOW_PUBLIC_BOND_STATE_PATH", STATE_DIR / "public_bonds.json")
CRYPTO_STATE_PATH = _path_from_env("FUTURES_WORKFLOW_CRYPTO_STATE_PATH", STATE_DIR / "crypto_global.json")
PLATFORM_METADATA_STATE_PATH = _path_from_env("FUTURES_WORKFLOW_PLATFORM_METADATA_STATE_PATH", STATE_DIR / "platform_metadata.json")
REGRESSION_SMOKE_STATE_PATH = _path_from_env("FUTURES_WORKFLOW_REGRESSION_SMOKE_STATE_PATH", STATE_DIR / "regression_smoke.json")
PREGRAB_STATE_PATH = _path_from_env("FUTURES_WORKFLOW_PREGRAB_STATE_PATH", STATE_DIR / "pregrab_runs.json")
WINDOW_RUNS_STATE_PATH = _path_from_env("FUTURES_WORKFLOW_WINDOW_RUNS_STATE_PATH", STATE_DIR / "window_runs.json")
SCHEDULES_STATE_PATH = _path_from_env("FUTURES_WORKFLOW_SCHEDULES_STATE_PATH", STATE_DIR / "schedules.json")
SCHEDULER_RUNS_STATE_PATH = _path_from_env("FUTURES_WORKFLOW_SCHEDULER_RUNS_STATE_PATH", STATE_DIR / "scheduler_runs.json")
REPORTS_DIR = _path_from_env("FUTURES_WORKFLOW_REPORTS_DIR", PROJECT_ROOT / "reports")


@lru_cache(maxsize=1)
def load_sources_config() -> Dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
