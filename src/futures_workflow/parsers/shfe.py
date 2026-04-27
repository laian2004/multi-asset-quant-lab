import json
from datetime import date
from typing import List

from ..models import QuoteRow
from ..utils import (
    format_trade_date,
    iso_timestamp,
    normalize_contract_code,
    normalize_number,
    normalize_text,
)


def parse_shfe_daily_quotes(
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
) -> List[QuoteRow]:
    payload = json.loads(raw_text)
    rows: List[QuoteRow] = []
    retrieved_at = iso_timestamp()
    for item in payload.get("o_curinstrument", []):
        delivery_month = normalize_text(item.get("DELIVERYMONTH"))
        product_class = normalize_text(item.get("PRODUCTCLASS"))
        raw_product_id = normalize_text(item.get("PRODUCTID"))
        if len(delivery_month) != 4 or not delivery_month.isdigit():
            continue
        if product_class:
            if product_class != "1":
                continue
        elif raw_product_id and not raw_product_id.upper().endswith("_F"):
            continue
        variety_code = normalize_text(item.get("PRODUCTGROUPID")).upper()
        if not variety_code and raw_product_id:
            variety_code = raw_product_id.upper().split("_", 1)[0]
        if not variety_code:
            continue
        contract = normalize_contract_code(f"{variety_code}{delivery_month}")
        rows.append(
            QuoteRow(
                trade_date=format_trade_date(trade_date),
                exchange="SHFE",
                variety_code=variety_code,
                variety_name=normalize_text(item.get("PRODUCTNAME")),
                contract=contract,
                delivery_month=delivery_month,
                open=normalize_number(item.get("OPENPRICE")),
                high=normalize_number(item.get("HIGHESTPRICE")),
                low=normalize_number(item.get("LOWESTPRICE")),
                close=normalize_number(item.get("CLOSEPRICE")),
                prev_settlement=normalize_number(item.get("PRESETTLEMENTPRICE")),
                settlement=normalize_number(item.get("SETTLEMENTPRICE")),
                change_close=normalize_number(item.get("ZD1_CHG")),
                change_settlement=normalize_number(item.get("ZD2_CHG")),
                volume=normalize_number(item.get("VOLUME")),
                open_interest=normalize_number(item.get("OPENINTEREST")),
                open_interest_change=normalize_number(item.get("OPENINTERESTCHG")),
                turnover=normalize_number(item.get("TURNOVER")),
                source_url=source_url,
                source_type=source_type,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
            )
        )
    return rows
