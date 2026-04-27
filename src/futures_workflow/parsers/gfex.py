from datetime import date
from typing import List

import json

from ..models import QuoteRow
from ..utils import format_trade_date, iso_timestamp, normalize_contract_code, normalize_number, normalize_text


def parse_gfex_daily_quotes(
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
) -> List[QuoteRow]:
    payload = json.loads(raw_text)
    rows: List[QuoteRow] = []
    retrieved_at = iso_timestamp()
    for item in payload.get("data", []):
        delivery_month = normalize_text(item.get("delivMonth"))
        if len(delivery_month) != 4 or not delivery_month.isdigit():
            continue
        variety_code = normalize_text(item.get("varietyOrder")).upper()
        if not variety_code:
            continue
        rows.append(
            QuoteRow(
                trade_date=format_trade_date(trade_date),
                exchange="GFEX",
                variety_code=variety_code,
                variety_name=normalize_text(item.get("variety")),
                contract=normalize_contract_code(f"{variety_code}{delivery_month}"),
                delivery_month=delivery_month,
                open=normalize_number(item.get("open")),
                high=normalize_number(item.get("high")),
                low=normalize_number(item.get("low")),
                close=normalize_number(item.get("close")),
                prev_settlement=normalize_number(item.get("lastClear")),
                settlement=normalize_number(item.get("clearPrice")),
                change_close=normalize_number(item.get("diff")),
                change_settlement=normalize_number(item.get("diff1")),
                volume=normalize_number(item.get("volumn")),
                open_interest=normalize_number(item.get("openInterest")),
                open_interest_change=normalize_number(item.get("diffI")),
                turnover=normalize_number(item.get("turnover")),
                source_url=source_url,
                source_type=source_type,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
            )
        )
    return rows
