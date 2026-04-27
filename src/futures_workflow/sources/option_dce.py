import json
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import akshare as ak

from ..config import PROJECT_ROOT, RAW_DIR
from ..constants import OPTIONS_DATASET
from ..exceptions import PendingRetryError, SourceNoDataError
from ..models import OptionQuoteRow, RawPayload
from ..parsers.options_dce import parse_dce_option_daily_quotes
from ..utils import compact_trade_date, ensure_directory, normalize_number, now_shanghai, relative_to_project
from .base import ExchangeSource
from .browser import bootstrap_browser_cookies


OFFICIAL_OPTION_URL = "http://www.dce.com.cn/dcereport/publicweb/dailystat/dayQuotes"
SINA_OPTIONS_URL = "https://stock2.finance.sina.com.cn/futures/api/openapi.php/OptionService.getOptionData"
SINA_HISTORY_URL = "https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_x=/FutureOptionAllService.getOptionDayline"
OPTION_ENDPOINT_ATTEMPTS = (
    ("json", "all"),
    ("json", ""),
    ("form", "all"),
    ("form", ""),
)
SINA_SUPPORTED_PRODUCTS = {
    "A": "黄大豆1号期权",
    "B": "黄大豆2号期权",
    "C": "玉米期权",
    "CS": "玉米淀粉期权",
    "EB": "苯乙烯期权",
    "EG": "乙二醇期权",
    "I": "铁矿石期权",
    "JD": "鸡蛋期权",
    "L": "塑料期权",
    "LG": "原木期权",
    "LH": "生猪期权",
    "M": "豆粕期权",
    "P": "棕榈油期权",
    "PG": "液化石油气期权",
    "PP": "PP期权",
    "V": "PVC期权",
    "Y": "豆油期权",
}


class DCEOptionSource(ExchangeSource):
    exchange = "DCE"
    dataset = OPTIONS_DATASET

    def __init__(self, settings, logger):
        super().__init__(settings, logger)
        self._history_series_cache: Dict[str, List[Tuple[str, Dict[str, str]]]] = {}
        self._history_row_cache: Dict[Tuple[str, str], Optional[Dict[str, str]]] = {}

    def fetch_raw(self, trade_date: date) -> RawPayload:
        cached = self._load_cached_payload_if_historical(
            trade_date,
            f"{OFFICIAL_OPTION_URL}|{SINA_OPTIONS_URL}|{SINA_HISTORY_URL}",
            "fallback_online",
        )
        if cached is not None:
            self.logger.info("DCE option reusing cached raw payload for %s.", trade_date.isoformat())
            return cached
        errors: List[str] = []
        try:
            return self._fetch_official_raw(trade_date)
        except SourceNoDataError:
            raise
        except Exception as exc:
            errors.append(str(exc))

        try:
            if self._is_latest_completed_market_date(trade_date):
                return self._fetch_recent_snapshot_fallback_raw(trade_date)
        except SourceNoDataError:
            raise
        except Exception as exc:
            errors.append(str(exc))

        try:
            return self._fetch_sina_contract_table_fallback_raw(trade_date)
        except SourceNoDataError:
            raise
        except Exception as exc:
            errors.append(str(exc))

        try:
            return self._fetch_stock2_fallback_raw(trade_date)
        except SourceNoDataError:
            raise
        except Exception as exc:
            errors.append(str(exc))

        try:
            cached = self._load_cached_payload(
                trade_date,
                f"{SINA_OPTIONS_URL}|{SINA_HISTORY_URL}",
                "fallback_online",
            )
        except FileNotFoundError:
            cached = None
        if cached is not None:
            self.logger.warning("DCE option live fetch failed for %s, reusing cached raw payload.", trade_date.isoformat())
            return cached

        joined = "; ".join(error for error in errors if error) or "no supported DCE option source returned rows"
        raise PendingRetryError(f"DCE option daily quotes unavailable: {joined}")

    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path) -> List[OptionQuoteRow]:
        return parse_dce_option_daily_quotes(
            raw_text=payload.content,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=payload.url,
            source_type=payload.source_type,
            product_name_map=self.settings.get("option_product_name_map", {}).get("DCE", {}),
        )

    def _fetch_official_raw(self, trade_date: date) -> RawPayload:
        exchange_settings = self.settings["exchanges"]["DCE"]
        bootstrap_url = exchange_settings["bootstrap_url"]
        referer = exchange_settings.get("referer", bootstrap_url)
        try:
            cookies, _ = bootstrap_browser_cookies(bootstrap_url, self.settings["user_agent"], wait_ms=7000)
        except Exception as exc:
            raise PendingRetryError(f"DCE option browser bootstrap failed: {exc}") from exc
        if not cookies:
            raise PendingRetryError("DCE option browser bootstrap returned no cookies.")

        errors: List[str] = []
        for mode, variety_id in OPTION_ENDPOINT_ATTEMPTS:
            try:
                return self._fetch_official_daily_quotes(trade_date, cookies, referer, mode=mode, variety_id=variety_id)
            except SourceNoDataError:
                raise
            except Exception as exc:
                errors.append(f"{mode}:{variety_id or 'blank'} -> {exc}")
        raise PendingRetryError("; ".join(errors) or "official option endpoint rejected all request shapes")

    def _fetch_official_daily_quotes(
        self,
        trade_date: date,
        cookies: Dict[str, str],
        referer: str,
        *,
        mode: str,
        variety_id: str,
    ) -> RawPayload:
        payload = {
            "contractId": "",
            "lang": "zh",
            "optionSeries": "",
            "statisticsType": "0",
            "tradeDate": compact_trade_date(trade_date),
            "tradeType": "2",
            "varietyId": variety_id,
        }
        headers = self._headers(
            {
                "Accept": "application/json, text/plain, */*",
                "Origin": "http://www.dce.com.cn",
                "Referer": referer,
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        if mode == "json":
            response = self._request(
                "POST",
                OFFICIAL_OPTION_URL,
                json=payload,
                headers={**headers, "Content-Type": "application/json;charset=UTF-8"},
                cookies=cookies,
            )
        else:
            response = self._request(
                "POST",
                OFFICIAL_OPTION_URL,
                data=payload,
                headers={**headers, "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
                cookies=cookies,
            )
        text = response.text
        if response.status_code in {403, 412} or "Precondition Failed" in text:
            raise PendingRetryError(f"DCE option official endpoint returned anti-bot response for {trade_date.isoformat()}")
        if response.status_code == 404:
            raise SourceNoDataError(f"DCE option official endpoint has no published file for {trade_date.isoformat()}.")
        if response.status_code >= 400:
            raise ValueError(f"DCE option official endpoint returned HTTP {response.status_code}")
        if text.lstrip().startswith("<"):
            raise ValueError("DCE option official endpoint returned HTML instead of JSON.")
        parsed = json.loads(text)
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if not data:
            raise SourceNoDataError(f"DCE option official endpoint returned no rows for {trade_date.isoformat()}.")
        return RawPayload(content=json.dumps(parsed, ensure_ascii=False), url=OFFICIAL_OPTION_URL, extension="json", source_type="official_browser_bootstrap")

    def _fetch_stock2_fallback_raw(self, trade_date: date) -> RawPayload:
        supported_products = self._supported_products()
        candidate_contracts = self._generate_candidate_underlying_contracts(trade_date, supported_products)
        contract_rows: List[Dict[str, str]] = []
        for attempt in range(2):
            contract_rows = self._fetch_contract_tables(candidate_contracts, supported_products)
            if contract_rows:
                break
            self.logger.warning(
                "DCE option fallback contract discovery returned no rows for %s on attempt %s.",
                trade_date.isoformat(),
                attempt + 1,
            )
        if not contract_rows:
            raise PendingRetryError(f"DCE option fallback contract discovery returned no rows for {trade_date.isoformat()}.")

        option_rows = self._build_fallback_records(trade_date, contract_rows, supported_products)
        if not option_rows:
            raise PendingRetryError(f"DCE option fallback history returned no rows for {trade_date.isoformat()}.")

        live_payload = RawPayload(
            content=json.dumps({"data": option_rows}, ensure_ascii=False),
            url=f"{SINA_OPTIONS_URL}|{SINA_HISTORY_URL}",
            extension="json",
            source_type="fallback_online",
        )
        return self._prefer_cached_payload(trade_date, live_payload, len(option_rows))

    def _fetch_sina_contract_table_fallback_raw(self, trade_date: date) -> RawPayload:
        supported_products = self._supported_products()
        contract_rows = self._fetch_contract_tables_from_available_contracts(trade_date, supported_products)
        if not contract_rows:
            raise PendingRetryError(f"DCE option Sina contract-table discovery returned no rows for {trade_date.isoformat()}.")

        option_rows = self._build_fallback_records(trade_date, contract_rows, supported_products)
        if not option_rows:
            raise PendingRetryError(f"DCE option Sina contract-table history returned no rows for {trade_date.isoformat()}.")

        live_payload = RawPayload(
            content=json.dumps({"data": option_rows}, ensure_ascii=False),
            url=f"https://stock.finance.sina.com.cn/futures/view/optionsDP.php|{SINA_OPTIONS_URL}|{SINA_HISTORY_URL}",
            extension="json",
            source_type="fallback_online",
        )
        return self._prefer_cached_payload(trade_date, live_payload, len(option_rows))

    def _fetch_recent_snapshot_fallback_raw(self, trade_date: date) -> RawPayload:
        supported_products = self._supported_products()
        contract_rows = self._fetch_contract_tables_from_available_contracts(trade_date, supported_products)
        if not contract_rows:
            raise PendingRetryError(f"DCE option recent snapshot discovery returned no rows for {trade_date.isoformat()}.")

        option_rows = self._build_recent_snapshot_records(contract_rows, supported_products)
        if not option_rows:
            raise PendingRetryError(f"DCE option recent snapshot returned no rows for {trade_date.isoformat()}.")

        live_payload = RawPayload(
            content=json.dumps({"data": option_rows}, ensure_ascii=False),
            url="https://stock.finance.sina.com.cn/futures/view/optionsDP.php",
            extension="json",
            source_type="fallback_online",
            meta={"quote_date_assumption": trade_date.isoformat()},
        )
        return self._prefer_cached_payload(trade_date, live_payload, len(option_rows))

    def _supported_products(self) -> Dict[str, str]:
        configured = self.settings.get("option_product_name_map", {}).get("DCE", {})
        supported = dict(SINA_SUPPORTED_PRODUCTS)
        for product_code, product_name in configured.items():
            supported.setdefault(str(product_code).upper(), str(product_name))
        return supported

    def _generate_candidate_underlying_contracts(self, trade_date: date, supported_products: Dict[str, str]) -> Dict[str, List[str]]:
        catalog = self.settings.get("contract_catalog", {}).get("DCE", {})
        month_index = trade_date.year * 12 + (trade_date.month - 1)
        results: Dict[str, List[str]] = {}
        for product_code in supported_products:
            metadata = catalog.get(product_code, {})
            prefix = str(metadata.get("contract_prefix") or product_code).lower()
            allowed_months = {int(month) for month in metadata.get("typical_cycle_months", list(range(1, 13)))}
            first_index = _contract_month_to_index(str(metadata.get("first_listed_month", "")))
            last_index = _contract_month_to_index(str(metadata.get("last_listed_month", "")))
            contracts: List[str] = []
            for month_offset in range(0, 7):
                current_index = month_index + month_offset
                if first_index is not None and current_index < first_index:
                    continue
                if last_index is not None and current_index > last_index:
                    continue
                year = current_index // 12
                month = current_index % 12 + 1
                if month not in allowed_months:
                    continue
                contracts.append(f"{prefix}{year % 100:02d}{month:02d}")
            if contracts:
                results[product_code] = contracts
        return results

    def _fetch_contract_tables(self, candidate_contracts: Dict[str, List[str]], supported_products: Dict[str, str]) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for product_code, contracts in candidate_contracts.items():
            product_token = f"{product_code.lower()}_o"
            for underlying_contract in contracts:
                try:
                    response = self._request(
                        "GET",
                        SINA_OPTIONS_URL,
                        params={
                            "type": "futures",
                            "product": product_token,
                            "exchange": "dce",
                            "pinzhong": underlying_contract,
                        },
                        headers=self._headers({"Accept": "application/json,text/plain,*/*", "Referer": "https://www.iweiai.com/"}),
                    )
                    payload = response.json()
                except Exception:
                    continue
                if payload.get("result", {}).get("status", {}).get("code") != 0:
                    continue
                up_rows = payload.get("result", {}).get("data", {}).get("up") or []
                down_rows = payload.get("result", {}).get("data", {}).get("down") or []
                if not up_rows and not down_rows:
                    continue
                for record in _merge_option_table_rows(up_rows, down_rows):
                    record["underlying_contract"] = underlying_contract.upper()
                    record["product_code"] = product_code
                    record["product_name"] = supported_products.get(product_code, product_code)
                    rows.append(record)
        return rows

    def _fetch_contract_tables_from_available_contracts(self, trade_date: date, supported_products: Dict[str, str]) -> List[Dict[str, str]]:
        current_month_index = trade_date.year * 12 + (trade_date.month - 1)
        rows: List[Dict[str, str]] = []
        for product_code, product_name in supported_products.items():
            try:
                contract_frame = ak.option_commodity_contract_sina(symbol=product_name)
            except Exception:
                continue
            for underlying_contract in [str(value).strip() for value in contract_frame.get("合约", []).tolist()]:
                if not underlying_contract:
                    continue
                month_index = _extract_underlying_contract_month_index(underlying_contract)
                if month_index is not None and abs(month_index - current_month_index) > 8:
                    continue
                try:
                    table = ak.option_commodity_contract_table_sina(symbol=product_name, contract=underlying_contract)
                except Exception:
                    continue
                for record in table.to_dict("records"):
                    normalized = {str(key): value for key, value in record.items()}
                    normalized["underlying_contract"] = underlying_contract.upper()
                    normalized["product_code"] = product_code
                    normalized["product_name"] = product_name
                    rows.append(normalized)
        return rows

    def _build_fallback_records(
        self,
        trade_date: date,
        contract_rows: List[Dict[str, str]],
        supported_products: Dict[str, str],
    ) -> List[Dict[str, str]]:
        contract_map: Dict[str, Dict[str, str]] = {}
        for item in contract_rows:
            underlying_contract = str(item.get("underlying_contract", "")).upper()
            product_code = str(item.get("product_code", "")).upper()
            product_name = supported_products.get(product_code, str(item.get("product_name", "")).strip())
            strike_price = normalize_number(item.get("行权价"))
            for option_type, contract_field, oi_field in (
                ("call", "看涨合约-看涨期权合约", "看涨合约-持仓量"),
                ("put", "看跌合约-看跌期权合约", "看跌合约-持仓量"),
            ):
                contract = str(item.get(contract_field, "")).strip().upper()
                if not contract:
                    continue
                latest_field = "看涨合约-最新价" if option_type == "call" else "看跌合约-最新价"
                latest_quote = normalize_number(item.get(latest_field))
                open_interest = normalize_number(item.get(oi_field))
                if latest_quote == "" and open_interest == "":
                    continue
                contract_map[contract] = {
                    "product_code": product_code,
                    "product_name": product_name,
                    "underlying_contract": underlying_contract,
                    "option_type": option_type,
                    "strike_price": strike_price,
                    "open_interest": open_interest,
                }

        history_rows = self._fetch_history_rows(trade_date, list(contract_map))
        records: List[Dict[str, str]] = []
        for contract, metadata in sorted(contract_map.items()):
            history = history_rows.get(contract)
            if history is None:
                continue
            close = history.get("close", "")
            prev_close = history.get("prev_close", "")
            records.append(
                {
                    "contractId": contract,
                    "varietyOrder": metadata["product_code"],
                    "variety": metadata["product_name"],
                    "underlyingContract": metadata["underlying_contract"],
                    "optionType": metadata["option_type"],
                    "strikePrice": metadata["strike_price"],
                    "open": history.get("open", ""),
                    "high": history.get("high", ""),
                    "low": history.get("low", ""),
                    "close": close,
                    "lastClear": prev_close,
                    "clearPrice": "",
                    "diff": normalize_number(_diff_numbers(close, prev_close)),
                    "diff1": "",
                    "volumn": history.get("volume", ""),
                    "openInterest": metadata.get("open_interest", ""),
                    "diffI": "",
                    "turnover": "",
                    "delta": "",
                    "impliedVolatility": "",
                    "matchQtySum": "",
                    "metadata": {
                        "contract_multiplier": "",
                        "quote_unit": "元",
                        "price_tick": "",
                        "delivery_type": "physical",
                        "exercise_type": "american",
                        "option_type": metadata["option_type"],
                        "strike_price": metadata["strike_price"],
                        "underlying_exchange": "DCE",
                        "underlying_kind": "futures",
                        "underlying_product_code": metadata["product_code"],
                        "underlying_contract": metadata["underlying_contract"],
                    },
                }
            )
        return records

    def _build_recent_snapshot_records(
        self,
        contract_rows: List[Dict[str, str]],
        supported_products: Dict[str, str],
    ) -> List[Dict[str, str]]:
        records: List[Dict[str, str]] = []
        for item in contract_rows:
            underlying_contract = str(item.get("underlying_contract", "")).upper()
            product_code = str(item.get("product_code", "")).upper()
            product_name = supported_products.get(product_code, str(item.get("product_name", "")).strip())
            strike_price = normalize_number(item.get("行权价"))
            for option_type, contract_field, latest_field, diff_field, oi_field in (
                ("call", "看涨合约-看涨期权合约", "看涨合约-最新价", "看涨合约-涨跌", "看涨合约-持仓量"),
                ("put", "看跌合约-看跌期权合约", "看跌合约-最新价", "看跌合约-涨跌", "看跌合约-持仓量"),
            ):
                contract = str(item.get(contract_field, "")).strip().upper()
                if not contract:
                    continue
                close = normalize_number(item.get(latest_field))
                open_interest = normalize_number(item.get(oi_field))
                change_close = normalize_number(item.get(diff_field))
                if close == "" and open_interest == "":
                    continue
                records.append(
                    {
                        "contractId": contract,
                        "varietyOrder": product_code,
                        "variety": product_name,
                        "underlyingContract": underlying_contract,
                        "optionType": option_type,
                        "strikePrice": strike_price,
                        "open": "",
                        "high": "",
                        "low": "",
                        "close": close,
                        "lastClear": "",
                        "clearPrice": "",
                        "diff": change_close,
                        "diff1": "",
                        "volumn": "",
                        "openInterest": open_interest,
                        "diffI": "",
                        "turnover": "",
                        "delta": "",
                        "impliedVolatility": "",
                        "matchQtySum": "",
                        "metadata": {
                            "contract_multiplier": "",
                            "quote_unit": "元",
                            "price_tick": "",
                            "delivery_type": "physical",
                            "exercise_type": "american",
                            "option_type": option_type,
                            "strike_price": strike_price,
                            "underlying_exchange": "DCE",
                            "underlying_kind": "futures",
                            "underlying_product_code": product_code,
                            "underlying_contract": underlying_contract,
                            "quote_mode": "recent_snapshot",
                        },
                    }
                )
        return records

    def _fetch_history_rows(self, trade_date: date, contracts: List[str]) -> Dict[str, Dict[str, str]]:
        results: Dict[str, Dict[str, str]] = {}
        for index, contract in enumerate(contracts, start=1):
            if index % 100 == 0:
                self.logger.info("DCE option history progress for %s: %s/%s contracts", trade_date.isoformat(), index, len(contracts))
            try:
                row = self._load_history_row(contract, trade_date)
            except PendingRetryError as exc:
                self.logger.warning(
                    "DCE option stock2 history hit protective block for %s on %s: %s",
                    contract,
                    trade_date.isoformat(),
                    exc,
                )
                break
            except Exception as exc:
                self.logger.debug("DCE option stock2 history skipped %s for %s: %s", contract, trade_date.isoformat(), exc)
                continue
            if row:
                results[contract] = row
        return results

    def _load_history_row(self, contract: str, trade_date: date) -> Optional[Dict[str, str]]:
        cache_key = (str(contract).upper(), trade_date.isoformat())
        if cache_key in self._history_row_cache:
            return self._history_row_cache[cache_key]
        normalized_rows = self._load_history_series(contract)
        trade_date_text = trade_date.isoformat()
        matched_row: Optional[Dict[str, str]] = None
        for index, (row_date, row) in enumerate(normalized_rows):
            if row_date != trade_date_text:
                continue
            previous_close = normalized_rows[index - 1][1].get("close", "") if index > 0 else ""
            matched_row = {
                "open": row.get("open", ""),
                "high": row.get("high", ""),
                "low": row.get("low", ""),
                "close": row.get("close", ""),
                "prev_close": previous_close,
                "volume": row.get("volume", ""),
            }
            break
        self._history_row_cache[cache_key] = matched_row
        return matched_row

    def _load_history_series(self, contract: str) -> List[Tuple[str, Dict[str, str]]]:
        normalized_contract = str(contract).upper()
        if normalized_contract in self._history_series_cache:
            return self._history_series_cache[normalized_contract]
        cache_path = self._history_cache_path(contract)
        if cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                normalized = _normalize_history_payload(cached)
                self._history_series_cache[normalized_contract] = normalized
                return normalized
            except json.JSONDecodeError:
                pass
        response = self._request(
            "GET",
            SINA_HISTORY_URL,
            params={"symbol": contract.lower()},
            headers=self._headers({"Accept": "*/*", "Referer": "https://www.iweiai.com/"}),
        )
        text = response.text
        start = text.find("[")
        end = text.rfind("]")
        if start < 0 or end <= start:
            self._history_series_cache[normalized_contract] = []
            return []
        payload = json.loads(text[start : end + 1])
        ensure_directory(cache_path.parent)
        cache_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        normalized = _normalize_history_payload(payload)
        self._history_series_cache[normalized_contract] = normalized
        return normalized

    def _prefer_cached_payload(self, trade_date: date, live_payload: RawPayload, live_row_count: int) -> RawPayload:
        try:
            cached = self._load_cached_payload(trade_date, live_payload.url, live_payload.source_type)
        except FileNotFoundError:
            return live_payload
        cached_count = _payload_row_count(cached.content)
        if cached_count > live_row_count:
            self.logger.warning("DCE option live fetch returned fewer rows than cached raw for %s, keeping cached payload.", trade_date.isoformat())
            return cached
        return live_payload

    def _history_cache_path(self, contract: str) -> Path:
        return RAW_DIR / "dce" / "options_history_contracts" / f"{str(contract).upper()}.json"

    def _is_latest_completed_market_date(self, trade_date: date) -> bool:
        return trade_date == _latest_completed_market_date()


def _contract_month_to_index(value: str) -> Optional[int]:
    if len(value) != 6 or not value.isdigit():
        return None
    year = int(value[:4])
    month = int(value[4:6])
    if month < 1 or month > 12:
        return None
    return year * 12 + (month - 1)


def _extract_underlying_contract_month_index(contract: str) -> Optional[int]:
    text = str(contract).strip().lower()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 4:
        return None
    value = digits[-4:]
    year = 2000 + int(value[:2])
    month = int(value[2:])
    if month < 1 or month > 12:
        return None
    return year * 12 + (month - 1)


def _diff_numbers(left: str, right: str) -> str:
    if not left or not right:
        return ""
    try:
        return str(float(left) - float(right))
    except ValueError:
        return ""


def _merge_option_table_rows(up_rows: List[List[object]], down_rows: List[List[object]]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    size = max(len(up_rows), len(down_rows))
    for index in range(size):
        up = up_rows[index] if index < len(up_rows) else []
        down = down_rows[index] if index < len(down_rows) else []
        rows.append(
            {
                "看涨合约-买量": up[0] if len(up) > 0 else "",
                "看涨合约-买价": up[1] if len(up) > 1 else "",
                "看涨合约-最新价": up[2] if len(up) > 2 else "",
                "看涨合约-卖价": up[3] if len(up) > 3 else "",
                "看涨合约-卖量": up[4] if len(up) > 4 else "",
                "看涨合约-持仓量": up[5] if len(up) > 5 else "",
                "看涨合约-涨跌": up[6] if len(up) > 6 else "",
                "行权价": up[7] if len(up) > 7 else (down[7] if len(down) > 7 else ""),
                "看涨合约-看涨期权合约": up[8] if len(up) > 8 else "",
                "看跌合约-买量": down[0] if len(down) > 0 else "",
                "看跌合约-买价": down[1] if len(down) > 1 else "",
                "看跌合约-最新价": down[2] if len(down) > 2 else "",
                "看跌合约-卖价": down[3] if len(down) > 3 else "",
                "看跌合约-卖量": down[4] if len(down) > 4 else "",
                "看跌合约-持仓量": down[5] if len(down) > 5 else "",
                "看跌合约-涨跌": down[6] if len(down) > 6 else "",
                "看跌合约-看跌期权合约": down[8] if len(down) > 8 else "",
            }
        )
    return rows


def _payload_row_count(raw_text: str) -> int:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return 0
    data = payload.get("data")
    return len(data) if isinstance(data, list) else 0


def _normalize_history_payload(payload: List[Dict[str, object]]) -> List[Tuple[str, Dict[str, str]]]:
    normalized_rows: List[Tuple[str, Dict[str, str]]] = []
    for item in payload or []:
        normalized_rows.append(
            (
                str(item.get("d", "")).strip(),
                {
                    "open": normalize_number(item.get("o")),
                    "high": normalize_number(item.get("h")),
                    "low": normalize_number(item.get("l")),
                    "close": normalize_number(item.get("c")),
                    "volume": normalize_number(item.get("v")),
                },
            )
        )
    return normalized_rows


def _latest_completed_market_date(today: Optional[date] = None) -> date:
    current = today or now_shanghai().date()
    if current.weekday() >= 5:
        offset = current.weekday() - 4
        return current.fromordinal(current.toordinal() - offset)
    current_time = now_shanghai().time() if today is None else None
    if current_time is not None and current_time.hour < 16:
        if current.weekday() == 0:
            return current.fromordinal(current.toordinal() - 3)
        return current.fromordinal(current.toordinal() - 1)
    return current
