import json
import re
from datetime import date
from typing import List

from ..models import OptionQuoteRow
from ..utils import format_trade_date, iso_timestamp, normalize_number, normalize_text


OPTION_PATTERN = re.compile(r"^([A-Z]+)(\d{4})-([CP])-(\d+)$")


def parse_gfex_option_daily_quotes(
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
) -> List[OptionQuoteRow]:
    payload = json.loads(raw_text)
    rows: List[OptionQuoteRow] = []
    retrieved_at = iso_timestamp()
    for item in payload.get("data", []):
        contract_raw = normalize_text(item.get("delivMonth")).upper()
        match = OPTION_PATTERN.match(contract_raw)
        if not match:
            continue
        product_code, delivery_month, option_flag, strike_price = match.groups()
        rows.append(
            OptionQuoteRow(
                trade_date=format_trade_date(trade_date),
                exchange="GFEX",
                product_code=product_code,
                product_name=normalize_text(item.get("variety")),
                contract=contract_raw,
                underlying_exchange="GFEX",
                underlying_kind="futures",
                underlying_product_code=product_code,
                underlying_contract=f"{product_code}{delivery_month}",
                option_type="call" if option_flag == "C" else "put",
                strike_price=normalize_number(strike_price),
                exercise_type="american",
                expire_date="",
                last_trade_date="",
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
                delta=normalize_number(item.get("delta")),
                implied_volatility=normalize_number(item.get("impliedVolatility")),
                exercise_volume=normalize_number(item.get("matchQtySum")),
                source_url=source_url,
                source_type=source_type,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
            )
        )
    return rows
