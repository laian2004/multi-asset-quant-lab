import json
import re
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Mapping, Optional

import requests

from ..config import RAW_DIR
from ..exceptions import PendingRetryError
from ..utils import ensure_directory, normalize_text
from .request_control import pace_request, raise_for_protective_block

SINA_DAILY_URL = "https://stock.finance.sina.com.cn/futures/api/jsonp_v2.php//StockOptionDaylineService.getSymbolInfo"
SINA_HQ_URL = "http://hq.sinajs.cn/list={query}"
SINA_REMAINDER_DAY_URL = "https://stock.finance.sina.com.cn/futures/api/openapi.php/StockOptionService.getRemainderDay"
SINA_OPTION_CODE_PATTERN = re.compile(r"CON_OP_(\d+)")
PAREN_CODE_PATTERN = re.compile(r"\((\d{6})\)")


def fetch_sina_option_codes(
    underlying_code: str,
    expiry_month: str,
    option_type: str,
    user_agent: str,
    timeout: int,
    *,
    request_settings: Optional[Mapping[str, object]] = None,
) -> List[str]:
    query_prefix = "OP_UP" if option_type == "call" else "OP_DOWN"
    query = f"{query_prefix}_{underlying_code}{expiry_month[2:]}"
    response = _sina_get(
        SINA_HQ_URL.format(query=query),
        headers=_hq_headers(user_agent, "https://stock.finance.sina.com.cn/"),
        timeout=timeout,
        request_settings=request_settings,
    )
    return sorted(set(SINA_OPTION_CODE_PATTERN.findall(response.text)))


def fetch_sina_option_metadata(
    symbol: str,
    user_agent: str,
    timeout: int,
    *,
    request_settings: Optional[Mapping[str, object]] = None,
) -> Dict[str, str]:
    cached = load_cached_sina_option_metadata(symbol)
    if cached:
        return cached
    response = _sina_get(
        SINA_HQ_URL.format(query=f"CON_SO_{symbol}"),
        headers=_hq_headers(user_agent, "https://vip.stock.finance.sina.com.cn/"),
        timeout=timeout,
        request_settings=request_settings,
    )
    text = _between_quotes(response.text)
    if not text:
        return {}
    values = text.split(",")
    if len(values) < 16:
        return {}
    metadata = {
        "contract_name": values[0].strip(),
        "delta": values[5].strip(),
        "implied_volatility": values[9].strip(),
        "high": values[10].strip(),
        "low": values[11].strip(),
        "contract": values[12].strip(),
        "strike_price": values[13].strip(),
        "close": values[14].strip(),
    }
    return write_sina_option_metadata_cache(symbol, metadata)


def fetch_sina_option_daily_rows(
    symbols: Iterable[str],
    trade_date: date,
    user_agent: str,
    timeout: int,
    *,
    max_workers: int = 8,
    request_settings: Optional[Mapping[str, object]] = None,
) -> Dict[str, Dict[str, str]]:
    symbol_list = [str(symbol).strip() for symbol in symbols if str(symbol).strip()]
    if not symbol_list:
        return {}

    rows: Dict[str, Dict[str, str]] = {}
    blocked_error: Optional[PendingRetryError] = None
    for symbol in symbol_list:
        try:
            row = fetch_sina_option_daily_row(
                symbol,
                trade_date,
                user_agent,
                timeout,
                request_settings=request_settings,
            )
        except PendingRetryError as exc:
            blocked_error = exc
            break
        except Exception:
            continue
        if row:
            rows[symbol] = row
    if blocked_error and not rows:
        raise blocked_error
    return rows


def fetch_sina_option_daily_row(
    symbol: str,
    trade_date: date,
    user_agent: str,
    timeout: int,
    *,
    request_settings: Optional[Mapping[str, object]] = None,
) -> Dict[str, str]:
    rows = _load_sina_option_daily_series(
        symbol,
        user_agent,
        timeout,
        request_settings=request_settings,
    )
    for index, item in enumerate(rows):
        row_date = item.get("date", "")
        if row_date != trade_date.isoformat():
            continue
        previous_close = rows[index - 1].get("close", "") if index > 0 else ""
        return {
            "open": item.get("open", ""),
            "high": item.get("high", ""),
            "low": item.get("low", ""),
            "close": item.get("close", ""),
            "prev_settlement": previous_close,
            "change_close": _diff(item.get("close", ""), previous_close),
            "volume": item.get("volume", ""),
        }
    return {}


def fetch_sina_expire_day(
    expiry_month: str,
    underlying_key: str,
    user_agent: str,
    timeout: int,
    *,
    request_settings: Optional[Mapping[str, object]] = None,
) -> str:
    normalized_month = str(expiry_month).strip()
    if len(normalized_month) == 4 and normalized_month.isdigit():
        normalized_month = f"20{normalized_month}"
    expire_cache_path = _expire_day_cache_path(underlying_key, normalized_month)
    if expire_cache_path.exists():
        try:
            payload = json.loads(expire_cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
        cached_day = str(payload.get("expire_day", "")).strip()
        if len(cached_day) == 10:
            return cached_day
    response = _sina_get(
        SINA_REMAINDER_DAY_URL,
        params={
            "exchange": "null",
            "cate": underlying_key,
            "date": f"{normalized_month[:4]}-{normalized_month[4:6]}",
        },
        headers={"User-Agent": user_agent},
        timeout=timeout,
        request_settings=request_settings,
    )
    payload = response.json()
    data = payload.get("result", {}).get("data", {})
    expire_day = str(data.get("expireDay", "")).strip()
    if len(expire_day) == 10:
        ensure_directory(expire_cache_path.parent)
        expire_cache_path.write_text(
            json.dumps(
                {
                    "underlying_key": str(underlying_key).strip(),
                    "expiry_month": normalized_month,
                    "expire_day": expire_day,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return expire_day
    return ""


def generate_expiry_months(trade_date: date, months_ahead: int = 12) -> List[str]:
    current_index = trade_date.year * 12 + (trade_date.month - 1)
    values: List[str] = []
    for offset in range(months_ahead):
        month_index = current_index + offset
        year = month_index // 12
        month = month_index % 12 + 1
        values.append(f"{year:04d}{month:02d}")
    return values


def extract_code_from_text(text: str) -> str:
    match = PAREN_CODE_PATTERN.search(str(text))
    return match.group(1) if match else ""


def load_cached_sina_option_metadata(symbol: str) -> Dict[str, str]:
    cache_path = _metadata_cache_path(symbol)
    if not cache_path.exists():
        return {}
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    normalized = {str(key): str(value).strip() for key, value in payload.items() if value is not None}
    return normalized if normalize_text(normalized.get("contract")) else {}


def iter_cached_sina_option_metadata() -> Iterator[Dict[str, str]]:
    cache_dir = RAW_DIR / "equity_options_metadata"
    if not cache_dir.exists():
        return
    for path in sorted(cache_dir.glob("*.json")):
        symbol = path.stem.strip()
        if not symbol:
            continue
        metadata = load_cached_sina_option_metadata(symbol)
        if not metadata:
            continue
        enriched = dict(metadata)
        enriched.setdefault("symbol", symbol)
        yield enriched


def iter_cached_sina_option_history_symbols(*, trade_date: Optional[date] = None) -> Iterator[str]:
    history_dir = RAW_DIR / "equity_options_history"
    if not history_dir.exists():
        return
    target_date = trade_date.isoformat() if trade_date else ""
    for path in sorted(history_dir.glob("*.json")):
        symbol = path.stem.strip()
        if not symbol:
            continue
        if not target_date:
            yield symbol
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        normalized_rows = _normalize_daily_payload(rows)
        if any(item.get("date") == target_date for item in normalized_rows):
            yield symbol


def write_sina_option_metadata_cache(symbol: str, metadata: Mapping[str, object]) -> Dict[str, str]:
    normalized_symbol = normalize_text(symbol)
    if not normalized_symbol:
        return {}
    normalized: Dict[str, str] = {
        str(key): str(value).strip()
        for key, value in dict(metadata).items()
        if value is not None and str(value).strip()
    }
    contract = normalize_text(normalized.get("contract"))
    if not contract:
        return {}
    normalized["contract"] = contract.upper()
    cache_path = _metadata_cache_path(normalized_symbol)
    ensure_directory(cache_path.parent)
    cache_path.write_text(json.dumps(normalized, ensure_ascii=False), encoding="utf-8")
    return normalized


def _normalize_daily_payload(payload) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for item in payload or []:
        if isinstance(item, dict):
            normalized.append(
                {
                    "date": str(item.get("d", "")).strip(),
                    "open": str(item.get("o", "")).strip(),
                    "high": str(item.get("h", "")).strip(),
                    "low": str(item.get("l", "")).strip(),
                    "close": str(item.get("c", "")).strip(),
                    "volume": str(item.get("v", "")).strip(),
                }
            )
        elif isinstance(item, list) and len(item) >= 6:
            normalized.append(
                {
                    "date": str(item[0]).strip(),
                    "open": str(item[1]).strip(),
                    "high": str(item[2]).strip(),
                    "low": str(item[3]).strip(),
                    "close": str(item[4]).strip(),
                    "volume": str(item[5]).strip(),
                }
            )
    return normalized


def _hq_headers(user_agent: str, referer: str) -> Dict[str, str]:
    return {
        "Accept": "*/*",
        "Referer": referer,
        "User-Agent": user_agent,
    }


def _daily_headers(user_agent: str) -> Dict[str, str]:
    return {
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Referer": "https://stock.finance.sina.com.cn/option/quotes.html",
        "Sec-Fetch-Dest": "script",
        "Sec-Fetch-Mode": "no-cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": user_agent,
    }


def _between_quotes(text: str) -> str:
    start = text.find('"')
    end = text.rfind('"')
    if start < 0 or end <= start:
        return ""
    return text[start + 1 : end]


def _diff(left: str, right: str) -> str:
    try:
        if left == "" or right == "":
            return ""
        return str(float(left) - float(right))
    except ValueError:
        return ""


def _sina_get(
    url: str,
    *,
    timeout: int,
    headers: Optional[Dict[str, str]] = None,
    params: Optional[Dict[str, str]] = None,
    request_settings: Optional[Mapping[str, object]] = None,
) -> requests.Response:
    pace_request(url, request_settings)
    response = requests.get(url, headers=headers, params=params, timeout=timeout)
    raise_for_protective_block(url, response, request_settings)
    response.raise_for_status()
    return response


def _load_sina_option_daily_series(
    symbol: str,
    user_agent: str,
    timeout: int,
    *,
    request_settings: Optional[Mapping[str, object]] = None,
) -> List[Dict[str, str]]:
    cache_path = _daily_cache_path(symbol)
    if cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            return _normalize_daily_payload(cached)
        except json.JSONDecodeError:
            pass
    response = _sina_get(
        SINA_DAILY_URL,
        params={"symbol": f"CON_OP_{symbol}"},
        headers=_daily_headers(user_agent),
        timeout=timeout,
        request_settings=request_settings,
    )
    text = response.text
    start = text.find("(")
    end = text.rfind(")")
    if start < 0 or end <= start:
        return []
    payload = json.loads(text[start + 1 : end])
    ensure_directory(cache_path.parent)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return _normalize_daily_payload(payload)


def _daily_cache_path(symbol: str) -> Path:
    return RAW_DIR / "equity_options_history" / f"{str(symbol).strip()}.json"


def _metadata_cache_path(symbol: str) -> Path:
    return RAW_DIR / "equity_options_metadata" / f"{str(symbol).strip()}.json"


def _expire_day_cache_path(underlying_key: str, expiry_month: str) -> Path:
    normalized_underlying = normalize_text(underlying_key) or "unknown"
    normalized_month = normalize_text(expiry_month).replace("-", "")
    return RAW_DIR / "equity_options_expire_days" / f"{normalized_underlying}_{normalized_month}.json"
