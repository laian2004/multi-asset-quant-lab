import json
from datetime import date
from typing import Dict, List

from ..models import QuoteRow
from ..utils import (
    extract_alpha_prefix,
    format_trade_date,
    infer_czce_delivery_month,
    iso_timestamp,
    normalize_contract_code,
    normalize_number,
    normalize_text,
    parse_pipe_table,
)


def parse_czce_daily_quotes(
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
    product_name_map: Dict[str, str],
) -> List[QuoteRow]:
    parsed_rows = _parse_rows(raw_text)
    rows: List[QuoteRow] = []
    retrieved_at = iso_timestamp()
    for item in parsed_rows:
        contract_raw = normalize_text(item.get("合约代码") or item.get("symbol") or item.get("contract"))
        if not contract_raw or contract_raw in {"小计", "合计", "总计"}:
            continue
        variety_code = normalize_text(item.get("variety")).upper() or extract_alpha_prefix(contract_raw)
        delivery_month = infer_czce_delivery_month(contract_raw, trade_date)
        contract = normalize_contract_code(f"{variety_code}{delivery_month}")
        rows.append(
            QuoteRow(
                trade_date=format_trade_date(trade_date),
                exchange="CZCE",
                variety_code=variety_code,
                variety_name=product_name_map.get(variety_code, normalize_text(item.get("variety_name")) or variety_code),
                contract=contract,
                delivery_month=delivery_month,
                open=normalize_number(item.get("今开盘") or item.get("open")),
                high=normalize_number(item.get("最高价") or item.get("high")),
                low=normalize_number(item.get("最低价") or item.get("low")),
                close=normalize_number(item.get("今收盘") or item.get("close")),
                prev_settlement=normalize_number(item.get("昨结算") or item.get("pre_settle")),
                settlement=normalize_number(item.get("今结算") or item.get("settle")),
                change_close=normalize_number(item.get("涨跌1") or item.get("change_close")),
                change_settlement=normalize_number(item.get("涨跌2") or item.get("change_settlement")),
                volume=normalize_number(item.get("成交量(手)") or item.get("volume")),
                open_interest=normalize_number(item.get("持仓量") or item.get("open_interest")),
                open_interest_change=normalize_number(item.get("增减量") or item.get("open_interest_change")),
                turnover=normalize_number(item.get("成交额(万元)") or item.get("turnover")),
                source_url=source_url,
                source_type=source_type,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
            )
        )
    return rows


def _parse_rows(raw_text: str) -> List[Dict[str, str]]:
    stripped = raw_text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        parsed_json = json.loads(stripped)
        data = parsed_json.get("data", []) if isinstance(parsed_json, dict) else parsed_json
        rows: List[Dict[str, str]] = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    rows.append({str(key).strip(): normalize_text(value) for key, value in item.items()})
        return rows
    return parse_pipe_table(raw_text)
