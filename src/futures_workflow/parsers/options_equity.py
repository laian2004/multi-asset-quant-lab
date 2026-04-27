import json
from datetime import date
from typing import List

from ..models import OptionQuoteRow
from ..utils import format_trade_date, iso_timestamp, normalize_contract_code, normalize_number, normalize_text


def parse_equity_option_daily_quotes(
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
    exchange: str,
) -> List[OptionQuoteRow]:
    payload = json.loads(raw_text)
    rows: List[OptionQuoteRow] = []
    retrieved_at = iso_timestamp()
    for item in payload.get("data", []):
        rows.append(
            OptionQuoteRow(
                trade_date=format_trade_date(trade_date),
                exchange=exchange,
                product_code=normalize_text(item.get("product_code")),
                product_name=normalize_text(item.get("product_name")),
                contract=normalize_contract_code(item.get("contract")),
                underlying_exchange=normalize_text(item.get("underlying_exchange")) or exchange,
                underlying_kind=normalize_text(item.get("underlying_kind")),
                underlying_product_code=normalize_text(item.get("underlying_product_code")),
                underlying_contract=normalize_text(item.get("underlying_contract")),
                option_type=normalize_text(item.get("option_type")).lower(),
                strike_price=normalize_number(item.get("strike_price")),
                exercise_type=normalize_text(item.get("exercise_type")).lower(),
                expire_date=_normalize_date(item.get("expire_date")),
                last_trade_date=_normalize_date(item.get("last_trade_date")),
                open=normalize_number(item.get("open")),
                high=normalize_number(item.get("high")),
                low=normalize_number(item.get("low")),
                close=normalize_number(item.get("close")),
                prev_settlement=normalize_number(item.get("prev_settlement")),
                settlement=normalize_number(item.get("settlement")),
                change_close=normalize_number(item.get("change_close")),
                change_settlement=normalize_number(item.get("change_settlement")),
                volume=normalize_number(item.get("volume")),
                open_interest=normalize_number(item.get("open_interest")),
                open_interest_change=normalize_number(item.get("open_interest_change")),
                turnover=normalize_number(item.get("turnover")),
                delta=normalize_number(item.get("delta")),
                implied_volatility=normalize_number(item.get("implied_volatility")),
                exercise_volume=normalize_number(item.get("exercise_volume")),
                source_url=source_url,
                source_type=source_type,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
                metadata=_normalize_metadata(item.get("metadata")),
            )
        )
    return rows


def _normalize_date(value: object) -> str:
    text = normalize_text(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _normalize_metadata(value: object) -> dict:
    if isinstance(value, dict):
        return {str(key): str(item) if item is not None else "" for key, item in value.items()}
    return {}
