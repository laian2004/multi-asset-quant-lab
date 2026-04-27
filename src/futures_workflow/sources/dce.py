import csv
import io
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode

import requests

from ..config import PROJECT_ROOT, RAW_DIR
from ..exceptions import PendingRetryError, SourceNoDataError
from ..models import RawPayload, QuoteRow
from ..parsers.dce import parse_dce_daily_quotes
from ..utils import compact_trade_date, decode_bytes, ensure_directory, iso_timestamp, now_shanghai, parse_trade_date, relative_to_project
from .base import ExchangeSource
from .browser import bootstrap_browser_cookies


SINA_NODE_SCRIPT_URL = "http://vip.stock.finance.sina.com.cn/quotes_service/view/js/qihuohangqing.js"
SINA_CONTRACT_LIST_URL = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQFuturesData"
SINA_DAILY_URL = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_x=/InnerFuturesNewService.getDailyKLine"
SINA_DAILY_TYPE = "2021_04_12"
SINA_CONTRACT_PATTERN = re.compile(r"([A-Z]{1,2})(\d{4})$")
SINA_FALLBACK_MIN_ROWS = 150
SINA_RECENT_WINDOW_DAYS = 500
EDB_DAILY_URL = "https://edb.shinnytech.com/md/kline"
EDB_FALLBACK_START_DATE = date(2021, 1, 1)


class DCESource(ExchangeSource):
    exchange = "DCE"

    def fetch_raw(self, trade_date: date) -> RawPayload:
        exchange_settings = self.settings["exchanges"]["DCE"]
        bootstrap_url = exchange_settings["bootstrap_url"]
        referer = exchange_settings.get("referer", bootstrap_url)
        errors: List[str] = []

        try:
            cookies, _ = bootstrap_browser_cookies(bootstrap_url, self.settings["user_agent"], wait_ms=7000)
        except Exception as exc:
            raise PendingRetryError(f"DCE browser bootstrap failed: {exc}") from exc
        if not cookies:
            raise PendingRetryError("DCE browser bootstrap returned no cookies.")

        for attempt in (self._fetch_json_endpoint, self._fetch_legacy_export):
            try:
                return attempt(trade_date, cookies=cookies, referer=referer, bootstrap_url=bootstrap_url)
            except SourceNoDataError:
                raise
            except Exception as exc:
                errors.append(str(exc))

        try:
            fallback_payload = self._fallback_payload(trade_date)
        except Exception as exc:
            fallback_payload = None
            errors.append(str(exc))
        if fallback_payload is not None:
            self.logger.warning("DCE official fetch failed, switching to fallback: %s", "; ".join(errors))
            return fallback_payload

        joined = "; ".join(error for error in errors if error) or "unknown official fetch failure"
        raise PendingRetryError(f"DCE official endpoints failed after browser bootstrap: {joined}")

    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path) -> List[QuoteRow]:
        return parse_dce_daily_quotes(
            raw_text=payload.content,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=payload.url,
            source_type=payload.source_type,
            product_name_map=self.settings["product_name_map"]["DCE"],
        )

    def _fetch_json_endpoint(
        self,
        trade_date: date,
        *,
        cookies: Dict[str, str],
        referer: str,
        bootstrap_url: str,
    ) -> RawPayload:
        exchange_settings = self.settings["exchanges"]["DCE"]
        url = exchange_settings["daily_json_url"]
        payload = {
            "contractId": "",
            "lang": "zh",
            "optionSeries": "",
            "statisticsType": "0",
            "tradeDate": compact_trade_date(trade_date),
            "tradeType": "1",
            "varietyId": "all",
        }
        response = self.session.post(
            url,
            json=payload,
            timeout=self.timeout,
            headers=self._headers(
                {
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json;charset=UTF-8",
                    "Origin": "http://www.dce.com.cn",
                    "Referer": referer,
                    "X-Requested-With": "XMLHttpRequest",
                }
            ),
            cookies=cookies,
        )
        return self._build_json_payload(
            response=response,
            url=url,
            trade_date=trade_date,
            challenge_hint=f"JSON endpoint returned anti-bot response after bootstrap from {bootstrap_url}",
        )

    def _fetch_legacy_export(
        self,
        trade_date: date,
        *,
        cookies: Dict[str, str],
        referer: str,
        bootstrap_url: str,
    ) -> RawPayload:
        exchange_settings = self.settings["exchanges"]["DCE"]
        query_params = {
            "dayQuotes.variety": "all",
            "dayQuotes.trade_type": "0",
            "year": str(trade_date.year),
            "month": str(trade_date.month - 1),
            "day": str(trade_date.day),
            "exportFlag": "txt",
        }
        url = f"{exchange_settings['legacy_export_url']}?{urlencode(query_params)}"
        response = self.session.get(
            url,
            timeout=self.timeout,
            headers=self._headers(
                {
                    "Accept": "text/plain,text/html,*/*",
                    "Referer": referer,
                }
            ),
            cookies=cookies,
        )
        text = decode_bytes(response.content)
        if response.status_code in {403, 412} or "Precondition Failed" in text:
            raise PendingRetryError(f"Legacy export endpoint still returned anti-bot response after bootstrap from {bootstrap_url}")
        if response.status_code == 404:
            raise SourceNoDataError(f"DCE legacy export has no published file for {trade_date.isoformat()}.")
        if response.status_code >= 400:
            raise ValueError(f"DCE legacy export returned HTTP {response.status_code}")
        if "无数据" in text or "暂无数据" in text:
            raise SourceNoDataError(f"DCE has no published data for {trade_date.isoformat()}.")
        if not text.strip() or text.strip() == "<html><head></head><body></body></html>":
            raise ValueError("DCE legacy export returned blank content.")
        extension = "html" if "<table" in text.lower() or "<html" in text.lower() else "txt"
        return RawPayload(content=text, url=url, extension=extension, source_type="official_browser_bootstrap")

    def _build_json_payload(self, *, response, url: str, trade_date: date, challenge_hint: str) -> RawPayload:
        text = decode_bytes(response.content)
        if response.status_code in {403, 412} or "Precondition Failed" in text:
            raise PendingRetryError(challenge_hint)
        if response.status_code == 404:
            raise SourceNoDataError(f"DCE JSON endpoint has no published file for {trade_date.isoformat()}.")
        if response.status_code >= 400:
            raise ValueError(f"DCE JSON endpoint returned HTTP {response.status_code}")
        if text.lstrip().startswith("<"):
            raise ValueError("DCE JSON endpoint returned HTML instead of JSON.")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("DCE JSON endpoint returned invalid JSON.") from exc
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, list) and not data:
            raise SourceNoDataError(f"DCE JSON endpoint returned no rows for {trade_date.isoformat()}.")
        normalized_text = json.dumps(payload, ensure_ascii=False)
        return RawPayload(content=normalized_text, url=url, extension="json", source_type="official_browser_bootstrap")

    def _fallback_payload(self, trade_date: date) -> Optional[RawPayload]:
        fallback_settings = self.settings.get("fallbacks", {}).get("DCE", {})
        if not fallback_settings.get("enabled"):
            return None

        provider = str(fallback_settings.get("provider", "")).strip().lower()
        if provider not in {"sina_contract_history", "akshare_sina", "sina", "hybrid_history", "edb_sina"}:
            raise PendingRetryError(f"DCE fallback provider '{provider or 'unknown'}' is not supported.")

        rows, source_type, source_url = self._collect_fallback_rows(trade_date)
        if not rows:
            raise PendingRetryError(f"DCE fallback provider '{provider}' returned no rows for {trade_date.isoformat()}.")

        payload = {"data": rows}
        return RawPayload(
            content=json.dumps(payload, ensure_ascii=False),
            url=source_url,
            extension="json",
            source_type=source_type,
        )

    def _collect_fallback_rows(self, trade_date: date):
        recent_cutoff = now_shanghai().date() - timedelta(days=SINA_RECENT_WINDOW_DAYS)
        prefer_sina = trade_date >= recent_cutoff
        generated_symbols = self._generate_candidate_contracts(trade_date)
        candidate_symbols = generated_symbols
        if prefer_sina:
            current_symbols = self._discover_sina_current_contracts()
            candidate_symbols = _dedupe_symbols(current_symbols + generated_symbols)

        row_map: Dict[str, Dict[str, str]] = {}
        source_urls: List[str] = []

        if prefer_sina:
            sina_rows = self._rows_for_sina_symbols(candidate_symbols, trade_date)
            if sina_rows:
                source_urls.append(SINA_DAILY_URL)
            row_map.update(sina_rows)

        if trade_date >= EDB_FALLBACK_START_DATE:
            missing_symbols = [symbol for symbol in candidate_symbols if symbol not in row_map]
            edb_rows = self._rows_for_edb_symbols(missing_symbols, trade_date)
            if edb_rows:
                source_urls.append(EDB_DAILY_URL)
            row_map.update(edb_rows)

        if prefer_sina and len(row_map) < SINA_FALLBACK_MIN_ROWS:
            missing_symbols = [symbol for symbol in candidate_symbols if symbol not in row_map]
            sina_rows = self._rows_for_sina_symbols(missing_symbols, trade_date)
            if sina_rows and SINA_DAILY_URL not in source_urls:
                source_urls.append(SINA_DAILY_URL)
            row_map.update(sina_rows)
        elif not prefer_sina and not row_map:
            sina_rows = self._rows_for_sina_symbols(candidate_symbols, trade_date)
            if sina_rows:
                source_urls.append(SINA_DAILY_URL)
            row_map.update(sina_rows)

        rows = [row_map[contract] for contract in sorted(row_map)]
        return rows, "fallback_online", "|".join(source_urls) if source_urls else "fallback_online://dce/hybrid_history"

    def _rows_for_sina_symbols(self, symbols: List[str], trade_date: date) -> Dict[str, Dict[str, str]]:
        row_map: Dict[str, Dict[str, str]] = {}
        for symbol in symbols:
            try:
                history_rows = self._load_or_fetch_sina_history(symbol, trade_date)
            except Exception as exc:
                self.logger.debug("DCE Sina fallback skipped %s for %s: %s", symbol, trade_date.isoformat(), exc)
                continue
            row = self._build_fallback_row(symbol, trade_date, history_rows)
            if row:
                row_map[symbol] = row
        return row_map

    def _rows_for_edb_symbols(self, symbols: List[str], trade_date: date) -> Dict[str, Dict[str, str]]:
        row_map: Dict[str, Dict[str, str]] = {}
        for symbol in symbols:
            try:
                edb_row = self._load_or_fetch_edb_row(symbol, trade_date)
            except Exception as exc:
                self.logger.debug("DCE EDB fallback skipped %s for %s: %s", symbol, trade_date.isoformat(), exc)
                continue
            row = self._build_edb_fallback_row(symbol, edb_row)
            if row:
                row_map[symbol] = row
        return row_map

    def _discover_sina_current_contracts(self) -> List[str]:
        response = self._request("GET", SINA_NODE_SCRIPT_URL, headers=self._headers({"Accept": "application/javascript,*/*"}))
        text = decode_bytes(response.content)
        node_ids = _parse_sina_dce_nodes(text)
        symbols = set()
        for node_id in node_ids:
            params = {"page": "1", "num": "1000", "sort": "position", "asc": "0", "node": node_id, "base": "futures"}
            response = self._request("GET", SINA_CONTRACT_LIST_URL, params=params, headers=self._headers({"Accept": "application/json,text/plain,*/*"}))
            try:
                payload = json.loads(response.text)
            except json.JSONDecodeError:
                continue
            for item in payload:
                symbol = str(item.get("symbol", "")).upper()
                if SINA_CONTRACT_PATTERN.fullmatch(symbol):
                    symbols.add(symbol)
        return sorted(symbols)

    def _generate_candidate_contracts(self, trade_date: date) -> List[str]:
        catalog = self.settings.get("contract_catalog", {}).get("DCE", {})
        if not isinstance(catalog, dict) or not catalog:
            return self._generate_candidate_contracts_from_product_map(trade_date)

        symbols = set()
        month_index = trade_date.year * 12 + (trade_date.month - 1)
        for variety_code, metadata in catalog.items():
            if not isinstance(metadata, dict):
                continue
            prefix = str(metadata.get("contract_prefix") or variety_code).upper()
            cycle_months = metadata.get("typical_cycle_months") or list(range(1, 13))
            allowed_months = {int(month) for month in cycle_months}
            first_index = _contract_month_to_index(str(metadata.get("first_listed_month", "")))
            last_index = _contract_month_to_index(str(metadata.get("last_listed_month", "")))
            for month_offset in range(-1, 13):
                current_index = month_index + month_offset
                if first_index is not None and current_index < first_index:
                    continue
                if last_index is not None and current_index > last_index:
                    continue
                year = current_index // 12
                month = current_index % 12 + 1
                if month not in allowed_months:
                    continue
                symbols.add(f"{prefix}{year % 100:02d}{month:02d}")
        return sorted(symbols)

    def _generate_candidate_contracts_from_product_map(self, trade_date: date) -> List[str]:
        symbols = set()
        month_index = trade_date.year * 12 + (trade_date.month - 1)
        for variety_code in self.settings["product_name_map"]["DCE"]:
            for month_offset in range(-1, 13):
                current_index = month_index + month_offset
                year = current_index // 12
                month = current_index % 12 + 1
                symbols.add(f"{variety_code}{year % 100:02d}{month:02d}")
        return sorted(symbols)

    def _load_or_fetch_sina_history(self, symbol: str, trade_date: date) -> List[Dict[str, str]]:
        cache_path = self._history_cache_path(symbol)
        trade_date_str = trade_date.isoformat()

        if cache_path.exists():
            try:
                cached_rows = _load_cached_history(cache_path)
                if _history_covers_trade_date(cached_rows, trade_date_str):
                    return cached_rows
            except Exception as exc:
                self.logger.warning("DCE fallback cache read failed for %s: %s", symbol, exc)

        response = self.session.get(
            SINA_DAILY_URL,
            params={"symbol": symbol, "type": SINA_DAILY_TYPE},
            timeout=self.timeout,
            headers=self._headers(
                {
                    "Accept": "*/*",
                    "Referer": "https://finance.sina.com.cn/futuremarket/",
                }
            ),
        )
        if response.status_code >= 400:
            raise ValueError(f"Sina daily history returned HTTP {response.status_code} for {symbol}")

        rows = _parse_sina_daily_history(response.text)
        ensure_directory(cache_path.parent)
        cache_path.write_text(
            json.dumps({"symbol": symbol, "retrieved_at": iso_timestamp(), "data": rows}, ensure_ascii=False),
            encoding="utf-8",
        )
        return rows

    def _load_or_fetch_edb_row(self, symbol: str, trade_date: date) -> Optional[Dict[str, str]]:
        cache_path = self._edb_cache_path(symbol, trade_date)
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            cached_row = payload.get("data")
            if isinstance(cached_row, dict):
                return {str(key): "" if value is None else str(value) for key, value in cached_row.items()}
            if payload.get("data") is None:
                return None

        edb_symbol = _to_edb_symbol(symbol)
        if not edb_symbol:
            return None

        response = requests.get(
            EDB_DAILY_URL,
            params={
                "symbol": edb_symbol,
                "period": "86400",
                "start_time": f"{trade_date.isoformat()} 00:00:00",
                "end_time": f"{trade_date.isoformat()} 23:59:59",
            },
            timeout=min(self.timeout, 5),
            headers=self._headers({"Accept": "text/csv,*/*"}),
        )
        if response.status_code >= 400:
            raise ValueError(f"EDB daily history returned HTTP {response.status_code} for {symbol}")

        row = _parse_edb_daily_bar(response.text)
        ensure_directory(cache_path.parent)
        cache_path.write_text(
            json.dumps(
                {
                    "symbol": symbol,
                    "trade_date": trade_date.isoformat(),
                    "retrieved_at": iso_timestamp(),
                    "data": row,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return row

    def _build_fallback_row(self, symbol: str, trade_date: date, history_rows: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
        trade_date_str = trade_date.isoformat()
        match = SINA_CONTRACT_PATTERN.fullmatch(symbol)
        if not match:
            return None
        variety_code, delivery_month = match.groups()
        variety_name = self.settings["product_name_map"]["DCE"].get(variety_code, variety_code)

        for index, item in enumerate(history_rows):
            if item.get("d") != trade_date_str:
                continue
            previous = history_rows[index - 1] if index > 0 else {}
            prev_settlement = previous.get("s", "")
            close = item.get("c", "")
            settlement = item.get("s", "")
            return {
                "contractId": symbol,
                "varietyOrder": variety_code,
                "variety": variety_name,
                "deliveryMonth": delivery_month,
                "open": item.get("o", ""),
                "high": item.get("h", ""),
                "low": item.get("l", ""),
                "close": close,
                "lastClear": prev_settlement,
                "clearPrice": settlement,
                "diff": _difference(close, prev_settlement),
                "diff1": _difference(settlement, prev_settlement),
                "volumn": item.get("v", ""),
                "openInterest": item.get("p", ""),
                "diffI": _difference(item.get("p", ""), previous.get("p", "")),
                "turnover": "",
            }
        return None

    def _build_edb_fallback_row(self, symbol: str, edb_row: Optional[Dict[str, str]]) -> Optional[Dict[str, str]]:
        if not edb_row:
            return None
        match = SINA_CONTRACT_PATTERN.fullmatch(symbol)
        if not match:
            return None

        variety_code, delivery_month = match.groups()
        variety_name = self.settings["product_name_map"]["DCE"].get(variety_code, variety_code)
        open_interest = edb_row.get("close_oi", "")
        open_interest_change = _difference(edb_row.get("close_oi", ""), edb_row.get("open_oi", ""))
        return {
            "contractId": symbol,
            "varietyOrder": variety_code,
            "variety": variety_name,
            "deliveryMonth": delivery_month,
            "open": edb_row.get("open", ""),
            "high": edb_row.get("high", ""),
            "low": edb_row.get("low", ""),
            "close": edb_row.get("close", ""),
            "lastClear": "",
            "clearPrice": "",
            "diff": "",
            "diff1": "",
            "volumn": edb_row.get("volume", ""),
            "openInterest": open_interest,
            "diffI": open_interest_change,
            "turnover": "",
        }

    def _history_cache_path(self, symbol: str) -> Path:
        return RAW_DIR / "dce" / "fallback_contract_histories" / f"{symbol}.json"

    def _edb_cache_path(self, symbol: str, trade_date: date) -> Path:
        return RAW_DIR / "dce" / "fallback_edb_rows" / f"{symbol}_{trade_date.isoformat()}.json"


def _difference(left: str, right: str) -> str:
    if not left or not right:
        return ""
    try:
        result = Decimal(str(left)) - Decimal(str(right))
    except InvalidOperation:
        return ""
    if result == result.to_integral():
        return str(result.quantize(Decimal("1")))
    return format(result.normalize(), "f")


def _load_cached_history(path: Path) -> List[Dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("data", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []
    normalized_rows: List[Dict[str, str]] = []
    for item in rows:
        if isinstance(item, dict):
            normalized_rows.append({str(key): "" if value is None else str(value) for key, value in item.items()})
    return normalized_rows


def _history_covers_trade_date(rows: List[Dict[str, str]], trade_date_str: str) -> bool:
    if not rows:
        return False
    dates = [row.get("d", "") for row in rows if row.get("d")]
    if not dates:
        return False
    return min(dates) <= trade_date_str <= max(dates)


def _parse_sina_dce_nodes(text: str) -> List[str]:
    block_match = re.search(r"dce\s*:\s*\[(.*?)\]\s*,\s*shfe\s*:", text, re.S)
    if not block_match:
        raise ValueError("Could not locate DCE node block in Sina futures script.")
    return re.findall(r"\[\s*'[^']+'\s*,\s*'([^']+)'\s*,\s*'[^']+'\s*\]", block_match.group(1))


def _parse_sina_daily_history(text: str) -> List[Dict[str, str]]:
    match = re.search(r"var\s+[A-Za-z0-9_]+\s*=\((.*)\);?\s*$", text, re.S)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    rows: List[Dict[str, str]] = []
    for item in payload:
        if isinstance(item, dict):
            rows.append({str(key): "" if value is None else str(value) for key, value in item.items()})
    return rows


def _parse_edb_daily_bar(text: str) -> Optional[Dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    for item in reader:
        if not item.get("datetime_nano"):
            continue
        return {str(key): "" if value is None else str(value) for key, value in item.items()}
    return None


def _to_edb_symbol(symbol: str) -> str:
    match = SINA_CONTRACT_PATTERN.fullmatch(symbol.upper())
    if not match:
        return ""
    variety_code, delivery_month = match.groups()
    return f"DCE.{variety_code.lower()}{delivery_month}"


def _contract_month_to_index(value: str) -> Optional[int]:
    stripped = str(value).strip()
    if not stripped:
        return None
    if not re.fullmatch(r"\d{6}", stripped):
        return None
    year = int(stripped[:4])
    month = int(stripped[4:])
    return year * 12 + (month - 1)


def _dedupe_symbols(symbols: List[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for symbol in symbols:
        normalized = symbol.upper().strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered
