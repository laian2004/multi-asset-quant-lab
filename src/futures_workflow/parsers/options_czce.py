import re
from datetime import date
from typing import Dict, List

from ..models import OptionQuoteRow
from ..utils import (
    format_trade_date,
    infer_czce_delivery_month,
    iso_timestamp,
    normalize_contract_code,
    normalize_number,
    normalize_text,
    parse_pipe_table,
)


OPTION_PATTERN = re.compile(r"^([A-Z]+)(\d{3,4})([CP])(\d+)$")


def parse_czce_option_daily_quotes(
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
    product_name_map: Dict[str, str],
) -> List[OptionQuoteRow]:
    parsed_rows = parse_pipe_table(raw_text)
    rows: List[OptionQuoteRow] = []
    retrieved_at = iso_timestamp()
    for item in parsed_rows:
        contract_raw = normalize_text(item.get("合约代码"))
        if not contract_raw or contract_raw in {"小计", "合计", "总计"}:
            continue
        match = OPTION_PATTERN.match(contract_raw.upper())
        if not match:
            continue
        product_code, delivery_digits, option_flag, strike_price = match.groups()
        delivery_month = infer_czce_delivery_month(f"{product_code}{delivery_digits}", trade_date)
        rows.append(
            OptionQuoteRow(
                trade_date=format_trade_date(trade_date),
                exchange="CZCE",
                product_code=product_code,
                product_name=product_name_map.get(product_code, product_code),
                contract=normalize_contract_code(f"{product_code}{delivery_month}{option_flag}{strike_price}"),
                underlying_exchange="CZCE",
                underlying_kind="futures",
                underlying_product_code=product_code,
                underlying_contract=normalize_contract_code(f"{product_code}{delivery_month}"),
                option_type="call" if option_flag == "C" else "put",
                strike_price=normalize_number(strike_price),
                exercise_type="american",
                expire_date="",
                last_trade_date="",
                open=normalize_number(item.get("今开盘")),
                high=normalize_number(item.get("最高价")),
                low=normalize_number(item.get("最低价")),
                close=normalize_number(item.get("今收盘")),
                prev_settlement=normalize_number(item.get("昨结算")),
                settlement=normalize_number(item.get("今结算")),
                change_close=normalize_number(item.get("涨跌1")),
                change_settlement=normalize_number(item.get("涨跌2")),
                volume=normalize_number(item.get("成交量(手)")),
                open_interest=normalize_number(item.get("持仓量")),
                open_interest_change=normalize_number(item.get("增减量")),
                turnover=normalize_number(item.get("成交额(万元)")),
                delta=normalize_number(item.get("DELTA")),
                implied_volatility=normalize_number(item.get("隐含波动率")),
                exercise_volume=normalize_number(item.get("行权量")),
                source_url=source_url,
                source_type=source_type,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
            )
        )
    return rows
