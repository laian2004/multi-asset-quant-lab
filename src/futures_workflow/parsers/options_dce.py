import json
import re
from datetime import date
from typing import Dict, List

from ..models import OptionQuoteRow
from ..utils import format_trade_date, iso_timestamp, normalize_number, normalize_text


OPTION_PATTERN = re.compile(r"^([A-Z]+)(\d{4})-?([CP])?-?(\d+)?$", re.IGNORECASE)


def parse_dce_option_daily_quotes(
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
    product_name_map: Dict[str, str],
) -> List[OptionQuoteRow]:
    payload = json.loads(raw_text)
    rows: List[OptionQuoteRow] = []
    retrieved_at = iso_timestamp()
    for item in payload.get("data", []):
        contract_raw = normalize_text(item.get("contractId") or item.get("合约") or item.get("合约代码")).upper()
        if not contract_raw or any(marker in contract_raw for marker in {"小计", "总计"}):
            continue
        option_type = _option_type(item.get("optionType") or item.get("类型") or contract_raw)
        strike_price = normalize_number(item.get("strikePrice") or item.get("行权价") or _extract_strike(contract_raw))
        product_code = normalize_text(item.get("varietyOrder") or item.get("品种代码")).upper() or _extract_prefix(contract_raw)
        underlying_contract = normalize_text(item.get("underlyingContract") or item.get("标的合约"))
        if not underlying_contract:
            delivery = _extract_delivery(contract_raw)
            underlying_contract = f"{product_code}{delivery}" if delivery else ""
        rows.append(
            OptionQuoteRow(
                trade_date=format_trade_date(trade_date),
                exchange="DCE",
                product_code=product_code,
                product_name=product_name_map.get(product_code, normalize_text(item.get("variety")) or product_code),
                contract=contract_raw,
                underlying_exchange="DCE",
                underlying_kind="futures",
                underlying_product_code=product_code,
                underlying_contract=underlying_contract,
                option_type=option_type,
                strike_price=strike_price,
                exercise_type="american",
                expire_date="",
                last_trade_date="",
                open=normalize_number(item.get("open") or item.get("开盘价")),
                high=normalize_number(item.get("high") or item.get("最高价")),
                low=normalize_number(item.get("low") or item.get("最低价")),
                close=normalize_number(item.get("close") or item.get("收盘价")),
                prev_settlement=normalize_number(item.get("lastClear") or item.get("前结算价")),
                settlement=normalize_number(item.get("clearPrice") or item.get("结算价")),
                change_close=normalize_number(item.get("diff") or item.get("涨跌")),
                change_settlement=normalize_number(item.get("diff1") or item.get("涨跌1")),
                volume=normalize_number(item.get("volumn") or item.get("成交量")),
                open_interest=normalize_number(item.get("openInterest") or item.get("持仓量")),
                open_interest_change=normalize_number(item.get("diffI") or item.get("持仓量变化")),
                turnover=normalize_number(item.get("turnover") or item.get("成交额")),
                delta=normalize_number(item.get("delta") or item.get("Delta")),
                implied_volatility=normalize_number(item.get("impliedVolatility") or item.get("隐含波动率(%)")),
                exercise_volume=normalize_number(item.get("matchQtySum") or item.get("行权量")),
                source_url=source_url,
                source_type=source_type,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
                metadata=_normalize_metadata(item.get("metadata")),
            )
        )
    return rows


def _extract_prefix(contract: str) -> str:
    match = re.match(r"([A-Z]+)", contract)
    return match.group(1) if match else ""


def _extract_delivery(contract: str) -> str:
    match = re.search(r"([0-9]{4})", contract)
    return match.group(1) if match else ""


def _extract_strike(contract: str) -> str:
    match = re.search(r"([CP])-?(\d+)$", contract)
    return match.group(2) if match else ""


def _option_type(value: object) -> str:
    text = normalize_text(value).upper()
    if "认购" in text or text.startswith("C") or "-C-" in text:
        return "call"
    if "认沽" in text or text.startswith("P") or "-P-" in text:
        return "put"
    return ""


def _normalize_metadata(value: object) -> dict:
    if isinstance(value, dict):
        return {str(key): str(item) if item is not None else "" for key, item in value.items()}
    return {}
