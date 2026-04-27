import csv
from pathlib import Path
from typing import Any, Dict, Iterable, List

from ..utils import ensure_directory


def write_typed_rows_csv(path: Path, rows: Iterable[Any], fieldnames: List[str], sort_keys: List[str]) -> Path:
    ensure_directory(path.parent)
    ordered = _sort_dict_rows([_row_to_dict(row) for row in rows], sort_keys)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in ordered:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return path


def write_dict_rows_csv(path: Path, rows: Iterable[Dict[str, Any]], fieldnames: List[str], sort_keys: List[str]) -> Path:
    ensure_directory(path.parent)
    ordered = _sort_dict_rows(list(rows), sort_keys)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in ordered:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return path


def _row_to_dict(row: Any) -> Dict[str, Any]:
    if hasattr(row, "to_dict"):
        return dict(row.to_dict())
    if isinstance(row, dict):
        return dict(row)
    raise TypeError(f"Unsupported row type: {type(row)!r}")


def _sort_dict_rows(rows: List[Dict[str, Any]], sort_keys: List[str]) -> List[Dict[str, Any]]:
    def sort_value(row: Dict[str, Any]):
        return tuple(str(row.get(key, "")) for key in sort_keys)

    return sorted(rows, key=sort_value)
