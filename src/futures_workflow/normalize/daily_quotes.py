from pathlib import Path
from typing import Iterable, List

from ..constants import STANDARD_FIELDS
from ..models import QuoteRow
from .csv_utils import write_typed_rows_csv


def write_daily_quotes_csv(path: Path, rows: Iterable[QuoteRow]) -> Path:
    return write_typed_rows_csv(
        path=path,
        rows=list(rows),
        fieldnames=STANDARD_FIELDS,
        sort_keys=["trade_date", "exchange", "variety_code", "contract"],
    )
