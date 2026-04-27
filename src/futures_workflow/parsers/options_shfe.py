import json
import re
from datetime import date
from typing import List

from ..models import OptionQuoteRow
from ..utils import format_trade_date, iso_timestamp, normalize_contract_code, normalize_number, normalize_text


OPTION_PATTERN = re.compile(r"^([A-Z]+)(\d{4})([CP])(\d+)$")


def parse_shfe_option_daily_quotes(
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
) -> List[OptionQuoteRow]:
    payload = json.loads(raw_text)
    rows: List[OptionQuoteRow] = []
    retrieved_at = iso_timestamp()
    for item in payload.get("o_curinstrument", []):
        instrument_id = normalize_contract_code(item.get("INSTRUMENTID"))
        match = OPTION_PATTERN.match(instrument_id)
        if not match:
            continue
        product_code, _, option_flag, strike_price = match.groups()
        underlying_contract = normalize_contract_code(item.get("UNDERLYINGINSTRID"))
        rows.append(
            OptionQuoteRow(
                trade_date=format_trade_date(trade_date),
                exchange="SHFE",
                product_code=product_code,
                product_name=normalize_text(item.get("PRODUCTNAME")),
                contract=instrument_id,
                underlying_exchange="SHFE",
                underlying_kind="futures",
                underlying_product_code=product_code,
                underlying_contract=underlying_contract,
                option_type="call" if option_flag == "C" else "put",
                strike_price=normalize_number(strike_price),
                exercise_type="american",
                expire_date="",
                last_trade_date="",
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
                delta=normalize_number(item.get("DELTA")),
                implied_volatility="",
                exercise_volume=normalize_number(item.get("EXECVOLUME")),
                source_url=source_url,
                source_type=source_type,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
            )
        )
    return rows
