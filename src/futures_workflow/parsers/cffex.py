import re
from datetime import date
from typing import Dict, List

from lxml import etree

from ..models import QuoteRow
from ..utils import format_trade_date, iso_timestamp, normalize_number, normalize_text


def parse_cffex_daily_quotes(
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
    product_name_map: Dict[str, str],
) -> List[QuoteRow]:
    root = etree.fromstring(_clean_cffex_xml(raw_text).encode("utf-8"))
    rows: List[QuoteRow] = []
    retrieved_at = iso_timestamp()
    for node in root.xpath("//dailydata"):
        instrument_id = normalize_text(node.findtext("instrumentid"))
        if not instrument_id or "-" in instrument_id:
            continue
        delivery_match = re.search(r"(\d{4})$", instrument_id)
        delivery_month = delivery_match.group(1) if delivery_match else ""
        product_id = normalize_text(node.findtext("productid")).upper()
        rows.append(
            QuoteRow(
                trade_date=format_trade_date(trade_date),
                exchange="CFFEX",
                variety_code=product_id,
                variety_name=product_name_map.get(product_id, product_id),
                contract=instrument_id.upper(),
                delivery_month=delivery_month,
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
                source_url=source_url,
                source_type=source_type,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
            )
        )
    return rows


def _diff(left: object, right: object) -> str:
    left_text = normalize_number(left)
    right_text = normalize_number(right)
    if not left_text or not right_text:
        return ""
    return normalize_number(str(float(left_text) - float(right_text)))


def _clean_cffex_xml(raw_text: str) -> str:
    return str(raw_text or "").replace("&nbsp;", " ").replace("&NBSP;", " ")
