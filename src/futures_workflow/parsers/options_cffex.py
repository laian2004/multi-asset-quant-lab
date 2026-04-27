import re
from datetime import date
from typing import Dict, List

from lxml import etree

from ..models import OptionQuoteRow
from ..utils import format_trade_date, iso_timestamp, normalize_number, normalize_text


OPTION_PATTERN = re.compile(r"^([A-Z]+)(\d{4})-([CP])-(\d+)$")


def parse_cffex_option_daily_quotes(
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
    product_name_map: Dict[str, str],
) -> List[OptionQuoteRow]:
    root = etree.fromstring(_clean_cffex_xml(raw_text).encode("utf-8"))
    rows: List[OptionQuoteRow] = []
    retrieved_at = iso_timestamp()
    for node in root.xpath("//dailydata"):
        instrument_id = normalize_text(node.findtext("instrumentid")).upper()
        match = OPTION_PATTERN.match(instrument_id)
        if not match:
            continue
        product_id, expire_month, option_flag, strike_price = match.groups()
        rows.append(
            OptionQuoteRow(
                trade_date=format_trade_date(trade_date),
                exchange="CFFEX",
                product_code=product_id,
                product_name=product_name_map.get(product_id, product_id),
                contract=instrument_id,
                underlying_exchange="CFFEX",
                underlying_kind="index",
                underlying_product_code=product_id,
                underlying_contract="",
                option_type="call" if option_flag == "C" else "put",
                strike_price=normalize_number(strike_price),
                exercise_type="european",
                expire_date=_normalize_date(node.findtext("expiredate")),
                last_trade_date=_normalize_date(node.findtext("expiredate")),
                open=normalize_number(node.findtext("openprice")),
                high=normalize_number(node.findtext("highestprice")),
                low=normalize_number(node.findtext("lowestprice")),
                close=normalize_number(node.findtext("closeprice")),
                prev_settlement=normalize_number(node.findtext("presettlementprice")),
                settlement=normalize_number(node.findtext("settlementprice")),
                change_close=_diff(node.findtext("closeprice"), node.findtext("presettlementprice")),
                change_settlement=_diff(node.findtext("settlementprice"), node.findtext("presettlementprice")),
                volume=normalize_number(node.findtext("volume")),
                open_interest=normalize_number(node.findtext("openinterest")),
                open_interest_change=_diff(node.findtext("openinterest"), node.findtext("preopeninterest")),
                turnover=normalize_number(node.findtext("turnover")),
                delta=normalize_number(node.findtext("delta")),
                implied_volatility="",
                exercise_volume="",
                source_url=source_url,
                source_type=source_type,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
            )
        )
    return rows


def _normalize_date(value: object) -> str:
    text = normalize_text(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _diff(left: object, right: object) -> str:
    left_text = normalize_number(left)
    right_text = normalize_number(right)
    if not left_text or not right_text:
        return ""
    return normalize_number(str(float(left_text) - float(right_text)))


def _clean_cffex_xml(raw_text: str) -> str:
    return str(raw_text or "").replace("&nbsp;", " ").replace("&NBSP;", " ")
