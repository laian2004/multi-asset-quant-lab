import json
from datetime import date
from typing import Dict, List

from ..models import QuoteRow
from ..utils import (
    extract_alpha_prefix,
    extract_digits_suffix,
    format_trade_date,
    iso_timestamp,
    normalize_contract_code,
    normalize_number,
    normalize_text,
    parse_pipe_table,
    read_html_tables,
)


def parse_dce_daily_quotes(
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
    product_name_map: Dict[str, str],
) -> List[QuoteRow]:
    rows = _parse_rows(raw_text)
    normalized_rows: List[QuoteRow] = []
    retrieved_at = iso_timestamp()
    for item in rows:
        contract_raw = normalize_text(
            item.get("contractId")
            or item.get("合约")
            or item.get("合约代码")
            or item.get("合约名称")
            or item.get("Contract")
        )
        variety_name = normalize_text(item.get("variety") or item.get("品种"))
        if (
            not contract_raw
            or contract_raw in {"小计", "合计", "总计"}
            or any(marker in contract_raw for marker in {"小计", "总计"})
            or any(marker in variety_name for marker in {"小计", "总计"})
        ):
            continue
        contract = normalize_contract_code(contract_raw)
        variety_code = normalize_text(item.get("varietyOrder")).upper() or extract_alpha_prefix(contract)
        delivery_month = normalize_text(item.get("deliveryMonth")) or extract_digits_suffix(contract)
        normalized_rows.append(
            QuoteRow(
                trade_date=format_trade_date(trade_date),
                exchange="DCE",
                variety_code=variety_code,
                variety_name=product_name_map.get(variety_code, variety_name or variety_code),
                contract=contract,
                delivery_month=delivery_month,
                open=normalize_number(_pick(item, "open", "开盘价", "今开盘", "开盘")),
                high=normalize_number(_pick(item, "high", "最高价", "最高")),
                low=normalize_number(_pick(item, "low", "最低价", "最低")),
                close=normalize_number(_pick(item, "close", "收盘价", "今收盘", "最新价", "收盘")),
                prev_settlement=normalize_number(_pick(item, "lastClear", "前结算价", "昨结算", "前结算")),
                settlement=normalize_number(_pick(item, "clearPrice", "结算价", "今结算", "结算")),
                change_close=normalize_number(_pick(item, "diff", "涨跌", "涨跌1")),
                change_settlement=normalize_number(_pick(item, "diff1", "涨跌1", "涨跌2", "结算价涨跌")),
                volume=normalize_number(_pick(item, "volumn", "成交量", "成交量(手)")),
                open_interest=normalize_number(_pick(item, "openInterest", "持仓量")),
                open_interest_change=normalize_number(_pick(item, "diffI", "持仓量变化", "持仓量增减", "增减量")),
                turnover=normalize_number(_pick(item, "turnover", "成交额", "成交额(万元)")),
                source_url=source_url,
                source_type=source_type,
                retrieved_at=retrieved_at,
                raw_path=raw_path,
            )
        )
    return normalized_rows


def _parse_rows(raw_text: str) -> List[Dict[str, str]]:
    stripped = raw_text.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        parsed_json = json.loads(stripped)
        if isinstance(parsed_json, dict):
            data = parsed_json.get("data", [])
            if isinstance(data, list):
                return [_stringify_row(item) for item in data if isinstance(item, dict)]
        if isinstance(parsed_json, list):
            return [_stringify_row(item) for item in parsed_json if isinstance(item, dict)]
    if "<table" in raw_text.lower():
        return [_stringify_row(row) for row in read_html_tables(raw_text)]
    parsed = parse_pipe_table(raw_text)
    if parsed:
        return parsed
    lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
    if len(lines) < 2:
        return []
    header = [part.strip() for part in lines[0].split()]
    rows: List[Dict[str, str]] = []
    for line in lines[1:]:
        parts = line.split()
        if len(parts) >= len(header):
            rows.append(dict(zip(header, parts)))
    return rows


def _pick(row: Dict[str, str], *keys: str) -> str:
    for key in keys:
        if key in row:
            return row[key]
    return ""


def _stringify_row(row: Dict[str, object]) -> Dict[str, str]:
    return {str(key).strip(): normalize_text(value) for key, value in row.items()}
