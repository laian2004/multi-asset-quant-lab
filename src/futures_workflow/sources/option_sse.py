import json
import re
from datetime import date
from pathlib import Path
from typing import Dict, List

from ..config import PROJECT_ROOT
from ..constants import OPTIONS_DATASET
from ..exceptions import PendingRetryError, SourceNoDataError
from ..models import OptionQuoteRow, RawPayload
from ..parsers.options_equity import parse_equity_option_daily_quotes
from ..utils import normalize_number, normalize_text, now_shanghai, relative_to_project
from .base import ExchangeSource
from .option_equity_common import fetch_sina_expire_day, fetch_sina_option_daily_rows


SSE_RISK_URL = "https://query.sse.com.cn/commonQuery.do"
SSE_QUOTE_BASE_URL = "https://yunhq.sse.com.cn:32042"
SSE_CONTRACT_PATTERN = re.compile(r"^(\d{6})([CP])(\d{4})([A-Z])(\d{5,6})([A-Z]?)$")


class SSEOptionSource(ExchangeSource):
    exchange = "SSE"
    dataset = OPTIONS_DATASET

    def __init__(self, settings, logger):
        super().__init__(settings, logger)
        self._risk_rows_cache: Dict[str, List[Dict[str, object]]] = {}
        self._nearby_risk_rows_cache: Dict[str, List[Dict[str, object]]] = {}
        self._current_underlyings_cache: List[str] = []
        self._current_expiry_map_cache: Dict[str, List[str]] = {}
        self._month_chain_cache: Dict[tuple[str, str], List[Dict[str, str]]] = {}
        self._expire_day_cache: Dict[tuple[str, str], str] = {}

    def fetch_raw(self, trade_date: date) -> RawPayload:
        source_url = f"{self._official_risk_url()}|{self._sina_daily_url()}"
        cached = self._load_cached_payload_if_historical(trade_date, source_url, "fallback_online")
        if cached is not None:
            self.logger.info("SSE option reusing cached raw payload for %s.", trade_date.isoformat())
            return cached
        if self._should_try_official_current(trade_date):
            try:
                records = self._fetch_official_current_records(trade_date)
                if records:
                    return RawPayload(
                        content=json.dumps({"data": records}, ensure_ascii=False),
                        url=self._official_quote_source_url(),
                        extension="json",
                        source_type="official",
                    )
            except Exception as exc:
                self.logger.warning("SSE official current quote fetch failed for %s: %s", trade_date.isoformat(), exc)
        try:
            try:
                risk_rows = self._fetch_risk_rows(trade_date)
            except Exception as exc:
                self.logger.warning(
                    "SSE official risk rows fetch failed for %s, trying cached contracts_snapshot payloads: %s",
                    trade_date.isoformat(),
                    exc,
                )
                risk_rows = self._load_recent_cached_risk_rows(trade_date)
            if not risk_rows:
                risk_rows = self._load_recent_cached_risk_rows(trade_date)
            if not risk_rows:
                raise SourceNoDataError(f"SSE has no published option risk data for {trade_date.isoformat()}.")

            symbols = [normalize_text(item.get("SECURITY_ID")) for item in risk_rows if normalize_text(item.get("SECURITY_ID"))]
            daily_rows = fetch_sina_option_daily_rows(
                symbols,
                trade_date,
                self.settings["user_agent"],
                self.timeout,
                max_workers=int(self.settings.get("request_behavior", {}).get("sina_daily_max_workers", 1) or 1),
                request_settings=self.settings,
            )
            if not daily_rows:
                raise PendingRetryError(f"SSE option history returned no rows for {trade_date.isoformat()}.")

            expire_cache = self._expire_day_cache
            product_name_map = self.settings.get("option_product_name_map", {}).get("SSE", {})

            records: List[Dict[str, str]] = []
            for item in risk_rows:
                security_id = normalize_text(item.get("SECURITY_ID"))
                contract = normalize_text(item.get("CONTRACT_ID")).upper()
                match = SSE_CONTRACT_PATTERN.match(contract)
                if not security_id or not match:
                    continue
                price_row = daily_rows.get(security_id)
                if not price_row:
                    continue
                underlying_code, option_flag, expiry_month, _, strike_digits, _ = match.groups()
                cache_key = (underlying_code, expiry_month)
                if cache_key not in expire_cache:
                    try:
                        expire_cache[cache_key] = fetch_sina_expire_day(
                            expiry_month,
                            underlying_code,
                            self.settings["user_agent"],
                            self.timeout,
                            request_settings=self.settings,
                        )
                    except Exception:
                        expire_cache[cache_key] = ""
                records.append(
                    {
                        "product_code": underlying_code,
                        "product_name": product_name_map.get(underlying_code, f"{underlying_code}期权"),
                        "contract": contract,
                        "underlying_exchange": "SSE",
                        "underlying_kind": "etf",
                        "underlying_product_code": underlying_code,
                        "underlying_contract": underlying_code,
                        "option_type": "call" if option_flag == "C" else "put",
                        "strike_price": normalize_number(str(int(strike_digits) / 1000)),
                        "exercise_type": "european",
                        "expire_date": expire_cache.get(cache_key, ""),
                        "last_trade_date": expire_cache.get(cache_key, ""),
                        "open": price_row.get("open", ""),
                        "high": price_row.get("high", ""),
                        "low": price_row.get("low", ""),
                        "close": price_row.get("close", ""),
                        "prev_settlement": price_row.get("prev_settlement", ""),
                        "settlement": "",
                        "change_close": price_row.get("change_close", ""),
                        "change_settlement": "",
                        "volume": price_row.get("volume", ""),
                        "open_interest": "",
                        "open_interest_change": "",
                        "turnover": "",
                        "delta": normalize_number(item.get("DELTA_VALUE")),
                        "implied_volatility": normalize_number(item.get("IMPLC_VOLATLTY")),
                        "exercise_volume": "",
                    }
                )

            if not records:
                raise PendingRetryError(f"SSE option contracts were discovered but no priced rows materialized for {trade_date.isoformat()}.")

            live_payload = RawPayload(
                content=json.dumps({"data": records}, ensure_ascii=False),
                url=source_url,
                extension="json",
                source_type="fallback_online",
            )
            return self._prefer_cached_payload(trade_date, live_payload, min_row_count=len(records))
        except PendingRetryError as exc:
            try:
                cached = self._load_cached_payload(trade_date, source_url, "fallback_online")
            except FileNotFoundError:
                raise exc
            self.logger.warning("SSE option live fetch failed for %s, reusing cached raw payload.", trade_date.isoformat())
            return cached
        except (SourceNoDataError, Exception):
            try:
                cached = self._load_cached_payload(trade_date, source_url, "fallback_online")
            except FileNotFoundError:
                raise
            self.logger.warning("SSE option live fetch failed for %s, reusing cached raw payload.", trade_date.isoformat())
            return cached

    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path) -> List[OptionQuoteRow]:
        return parse_equity_option_daily_quotes(
            raw_text=payload.content,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=payload.url,
            source_type=payload.source_type,
            exchange=self.exchange,
        )

    def _fetch_risk_rows(self, trade_date: date) -> List[Dict[str, object]]:
        cache_key = trade_date.isoformat()
        if cache_key in self._risk_rows_cache:
            return self._risk_rows_cache[cache_key]
        response = self._request(
            "GET",
            SSE_RISK_URL,
            params={
                "isPagination": "false",
                "trade_date": trade_date.strftime("%Y%m%d"),
                "sqlId": "SSE_ZQPZ_YSP_GGQQZSXT_YSHQ_QQFXZB_DATE_L",
                "contractSymbol": "",
            },
            headers=self._headers(
                {
                    "Accept": "*/*",
                    "Host": "query.sse.com.cn",
                    "Referer": "http://www.sse.com.cn/",
                }
            ),
        )
        payload = response.json()
        rows = payload.get("result", [])
        self._risk_rows_cache[cache_key] = rows
        return rows

    def _official_risk_url(self) -> str:
        return SSE_RISK_URL

    def _official_quote_source_url(self) -> str:
        return (
            f"{SSE_RISK_URL}|"
            f"{SSE_QUOTE_BASE_URL}/v1/sho/list/exchange/underlyingstock|"
            f"{SSE_QUOTE_BASE_URL}/v1/sho/list/exchange/stockexpire|"
            f"{SSE_QUOTE_BASE_URL}/v1/sho/list/tstyle"
        )

    def _sina_daily_url(self) -> str:
        return "https://stock.finance.sina.com.cn/futures/api/jsonp_v2.php//StockOptionDaylineService.getSymbolInfo"

    def _prefer_cached_payload(self, trade_date: date, live_payload: RawPayload, min_row_count: int) -> RawPayload:
        try:
            cached = self._load_cached_payload(trade_date, live_payload.url, live_payload.source_type)
        except FileNotFoundError:
            return live_payload
        cached_count = _payload_row_count(cached.content)
        live_count = _payload_row_count(live_payload.content)
        if cached_count > max(min_row_count, live_count):
            self.logger.warning("SSE option live fetch returned fewer rows than cached raw for %s, keeping cached payload.", trade_date.isoformat())
            return cached
        return live_payload

    def _should_try_official_current(self, trade_date: date) -> bool:
        delta_days = (now_shanghai().date() - trade_date).days
        return 0 <= delta_days <= 7

    def _fetch_official_current_records(self, trade_date: date) -> List[Dict[str, str]]:
        risk_rows = self._fetch_risk_rows(trade_date)
        if not risk_rows:
            raise SourceNoDataError(f"SSE has no published option risk data for {trade_date.isoformat()}.")
        risk_map = {
            normalize_text(item.get("CONTRACT_ID")).upper(): item
            for item in risk_rows
            if normalize_text(item.get("CONTRACT_ID"))
        }
        if not risk_map:
            raise SourceNoDataError(f"SSE risk feed returned no contract ids for {trade_date.isoformat()}.")

        price_map = self._fetch_official_current_price_map(trade_date)
        if not price_map:
            raise SourceNoDataError(f"SSE official current quote feed returned no rows for {trade_date.isoformat()}.")

        product_name_map = self.settings.get("option_product_name_map", {}).get("SSE", {})
        records: List[Dict[str, str]] = []
        for contract, risk_item in risk_map.items():
            match = SSE_CONTRACT_PATTERN.match(contract)
            if not match:
                continue
            price_item = price_map.get(contract)
            if not price_item:
                continue
            underlying_code, option_flag, _, _, strike_digits, _ = match.groups()
            close_value = normalize_number(price_item.get("close"))
            prev_settlement = normalize_number(price_item.get("prev_settlement"))
            records.append(
                {
                    "product_code": underlying_code,
                    "product_name": product_name_map.get(underlying_code, f"{underlying_code}期权"),
                    "contract": contract,
                    "underlying_exchange": "SSE",
                    "underlying_kind": "etf",
                    "underlying_product_code": underlying_code,
                    "underlying_contract": underlying_code,
                    "option_type": "call" if option_flag == "C" else "put",
                    "strike_price": normalize_number(str(int(strike_digits) / 1000)),
                    "exercise_type": "european",
                    "expire_date": "",
                    "last_trade_date": "",
                    "open": "",
                    "high": "",
                    "low": "",
                    "close": close_value,
                    "prev_settlement": prev_settlement,
                    "settlement": "",
                    "change_close": _diff(close_value, prev_settlement),
                    "change_settlement": "",
                    "volume": "",
                    "open_interest": "",
                    "open_interest_change": "",
                    "turnover": "",
                    "delta": normalize_number(risk_item.get("DELTA_VALUE")),
                    "implied_volatility": normalize_number(risk_item.get("IMPLC_VOLATLTY")),
                    "exercise_volume": "",
                    "metadata": {
                        "official_quote_date": price_item.get("quote_date", ""),
                    },
                }
            )
        if not records:
            raise SourceNoDataError(f"SSE official current quotes discovered no priced contract rows for {trade_date.isoformat()}.")
        return records

    def _fetch_official_current_price_map(self, trade_date: date) -> Dict[str, Dict[str, str]]:
        underlyings = self._fetch_current_underlyings()
        if not underlyings:
            return {}
        expiry_map = self._fetch_current_expiry_map()
        price_map: Dict[str, Dict[str, str]] = {}
        for underlying_code in underlyings:
            for expiry_month in expiry_map.get(underlying_code, []):
                for item in self._fetch_month_chain(underlying_code, expiry_month):
                    if item.get("quote_date") != trade_date.isoformat():
                        continue
                    contract = normalize_text(item.get("contract")).upper()
                    if contract:
                        price_map[contract] = item
        return price_map

    def _fetch_current_underlyings(self) -> List[str]:
        if self._current_underlyings_cache:
            return list(self._current_underlyings_cache)
        response = self._request(
            "GET",
            f"{SSE_QUOTE_BASE_URL}/v1/sho/list/exchange/underlyingstock",
            params={"select": "stockid"},
            headers=self._headers(
                {
                    "Accept": "*/*",
                    "Referer": "https://www.sse.com.cn/assortment/options/price/",
                }
            ),
        )
        payload = response.json()
        self._current_underlyings_cache = [normalize_text(item[0]) for item in payload.get("list", []) if item and normalize_text(item[0])]
        return list(self._current_underlyings_cache)

    def _load_recent_cached_risk_rows(self, trade_date: date) -> List[Dict[str, object]]:
        cache_key = trade_date.isoformat()
        if cache_key in self._nearby_risk_rows_cache:
            return self._nearby_risk_rows_cache[cache_key]
        payload_dir = PROJECT_ROOT / "data" / "raw" / "sse" / "contracts_snapshot"
        if not payload_dir.exists():
            self._nearby_risk_rows_cache[cache_key] = []
            return []
        candidates: List[tuple[int, Path]] = []
        target_value = int(trade_date.strftime("%Y%m%d"))
        for path in payload_dir.glob("*.json"):
            if path.name.endswith(".meta.json"):
                continue
            stem = path.stem
            if len(stem) != 8 or not stem.isdigit():
                continue
            if stem == trade_date.strftime("%Y%m%d"):
                continue
            candidates.append((abs(int(stem) - target_value), path))
        for _, path in sorted(candidates, key=lambda item: (item[0], item[1].name)):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            rows = payload.get("result")
            if isinstance(rows, list) and rows:
                self.logger.info(
                    "SSE option using nearby cached contracts_snapshot risk rows from %s for %s.",
                    path.name,
                    trade_date.isoformat(),
                )
                self._nearby_risk_rows_cache[cache_key] = rows
                return rows
        self._nearby_risk_rows_cache[cache_key] = []
        return []

    def _fetch_current_expiry_map(self) -> Dict[str, List[str]]:
        if self._current_expiry_map_cache:
            return {key: list(value) for key, value in self._current_expiry_map_cache.items()}
        response = self._request(
            "GET",
            f"{SSE_QUOTE_BASE_URL}/v1/sho/list/exchange/stockexpire",
            params={"select": "stockid,expiremonth"},
            headers=self._headers(
                {
                    "Accept": "*/*",
                    "Referer": "https://www.sse.com.cn/assortment/options/price/",
                }
            ),
        )
        payload = response.json()
        expiry_map: Dict[str, List[str]] = {}
        for item in payload.get("list", []):
            if not isinstance(item, list) or len(item) < 2:
                continue
            underlying_code = normalize_text(item[0])
            expiry_month = normalize_text(item[1])
            if not underlying_code or not expiry_month:
                continue
            expiry_map.setdefault(underlying_code, []).append(expiry_month)
        self._current_expiry_map_cache = {key: list(value) for key, value in expiry_map.items()}
        return expiry_map

    def _fetch_month_chain(self, underlying_code: str, expiry_month: str) -> List[Dict[str, str]]:
        cache_key = (underlying_code, expiry_month)
        if cache_key in self._month_chain_cache:
            return list(self._month_chain_cache[cache_key])
        month_token = normalize_text(expiry_month)[-2:]
        response = self._request(
            "GET",
            f"{SSE_QUOTE_BASE_URL}/v1/sho/list/tstyle/{underlying_code}_{month_token}",
            params={
                "select": "contractid,last,chg_rate,presetpx,exepx",
                "order": "contractid,ase",
            },
            headers=self._headers(
                {
                    "Accept": "*/*",
                    "Referer": "https://www.sse.com.cn/assortment/options/price/",
                }
            ),
        )
        payload = response.json()
        quote_date = _normalize_ymd(payload.get("date"))
        rows: List[Dict[str, str]] = []
        for item in payload.get("list", []):
            if not isinstance(item, list) or len(item) < 5:
                continue
            rows.append(
                {
                    "quote_date": quote_date,
                    "contract": normalize_text(item[0]).upper(),
                    "close": normalize_number(item[1]),
                    "prev_settlement": normalize_number(item[3]),
                    "strike_price": normalize_number(item[4]),
                }
            )
        self._month_chain_cache[cache_key] = list(rows)
        return rows


def _payload_row_count(raw_text: str) -> int:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return 0
    data = payload.get("data")
    return len(data) if isinstance(data, list) else 0


def _normalize_ymd(value: object) -> str:
    text = normalize_text(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _diff(left: str, right: str) -> str:
    try:
        if left == "" or right == "":
            return ""
        return str(float(left) - float(right))
    except ValueError:
        return ""
