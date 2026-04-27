from pathlib import Path
from typing import Dict, Iterable, List

import duckdb


ROOT = Path(__file__).resolve().parents[1]
DUCKDB_PATH = ROOT / "data" / "db" / "market_data.duckdb"
NORMALIZED_ROOT = ROOT / "data" / "normalized"
STATE_ROOT = ROOT / "state"


def connect_database(database_path: Path = DUCKDB_PATH):
    return duckdb.connect(str(database_path), read_only=True)


def list_datasets(database_path: Path = DUCKDB_PATH) -> List[Dict[str, object]]:
    with connect_database(database_path) as connection:
        return [
            {"dataset": row[0], "file_count": row[1], "row_count": row[2], "built_at": row[3]}
            for row in connection.execute("SELECT dataset, file_count, row_count, built_at FROM meta.dataset_manifest ORDER BY dataset").fetchall()
        ]


def preview_dataset(dataset: str, limit: int = 20, database_path: Path = DUCKDB_PATH) -> List[Dict[str, object]]:
    with connect_database(database_path) as connection:
        columns = [item[0] for item in connection.execute(f'SELECT * FROM normalized."{dataset}" LIMIT 0').description]
        rows = connection.execute(f'SELECT * FROM normalized."{dataset}" LIMIT ?', [limit]).fetchall()
    return [dict(zip(columns, row)) for row in rows]


def query(sql: str, params: Iterable[object] = (), database_path: Path = DUCKDB_PATH) -> List[Dict[str, object]]:
    with connect_database(database_path) as connection:
        cursor = connection.execute(sql, list(params))
        columns = [item[0] for item in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]
