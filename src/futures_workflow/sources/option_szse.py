import json
import random
import re
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from ..config import PROJECT_ROOT
from ..constants import OPTIONS_DATASET
from ..exceptions import PendingRetryError, SourceNoDataError
from ..models import OptionQuoteRow, RawPayload
from ..parsers.options_equity import parse_equity_option_daily_quotes
from ..utils import normalize_number, normalize_text, relative_to_project
from .base import ExchangeSource
from .option_equity_common import (
    fetch_sina_expire_day,
    fetch_sina_option_codes,
    fetch_sina_option_daily_rows,
    fetch_sina_option_metadata,
    generate_expiry_months,
    iter_cached_sina_option_history_symbols,
    iter_cached_sina_option_metadata,
    load_cached_sina_option_metadata,
    _normalize_daily_payload,
    write_sina_option_metadata_cache,
)


SZSE_REPORT_URL = "https://investor.szse.cn/api/report/ShowReport/data"
SZSE_CONTRACT_PATTERN = re.compile(r"^(\d{6})([CP])(\d{4})([A-Z])(\d{5,6})([A-Z]?)$")


class SZSEOptionSource(ExchangeSource):
    exchange = "SZSE"
    dataset = OPTIONS_DATASET

    def __init__(self, settings, logger):
        super().__init__(settings, logger)
        self._historical_contract_map_cache: Dict[str, Dict[str, Dict[str, str]]] = {}
        self._recent_underlying_rows_cache: Dict[str, List[Dict[str, str]]] = {}
        self._resolved_symbol_metadata_cache: Dict[str, Dict[str, str]] = {}
        self._history_probe_cache: Dict[Tuple[str, str, str, str, bool], List[str]] = {}

    def fetch_raw(self, trade_date: date) -> RawPayload:
        source_url = f"{SZSE_REPORT_URL}|{self._sina_daily_url()}"
        cached = self._load_cached_payload_if_historical(trade_date, source_url, "fallback_online")
        if cached is not None:
            refresh_min_rows = int(self.settings.get("equity_option_historical_refresh_min_rows", 24) or 24)
            if self._treat_historical_gap_as_no_data(trade_date) and _payload_row_count(cached.content) < refresh_min_rows:
                self.logger.info(
                    "SZSE option refreshing undersized historical cached raw payload for %s (rows=%s, min=%s).",
                    trade_date.isoformat(),
                    _payload_row_count(cached.content),
                    refresh_min_rows,
                )
            else:
                self.logger.info("SZSE option reusing cached raw payload for %s.", trade_date.isoformat())
                return cached
        try:
            trade_date_text = trade_date.isoformat()
            offline_only = self._treat_historical_gap_as_no_data(trade_date)
            allow_historical_live_metadata_probe = self._allow_historical_live_metadata_probe(trade_date)
            underlying_rows: List[Dict[str, str]] = []
            if not offline_only:
                try:
                    underlying_rows = self._fetch_underlying_rows(trade_date_text)
                except Exception as exc:
                    self.logger.warning(
                        "SZSE official underlying summary fetch failed for %s, trying cached payloads: %s",
                        trade_date_text,
                        exc,
                    )
                    underlying_rows = self._load_recent_cached_underlying_rows(trade_date)
            if not underlying_rows:
                underlying_rows = self._load_recent_cached_underlying_rows(trade_date)
            if not underlying_rows:
                underlying_rows = self._fallback_underlying_rows_from_config()
            if not underlying_rows:
                raise SourceNoDataError(f"SZSE has no published option summary for {trade_date_text}.")

            candidate_symbols, candidate_metadata = self._discover_historical_symbols(
                underlying_rows,
                trade_date,
                offline_only=offline_only,
                allow_historical_live_metadata_probe=allow_historical_live_metadata_probe,
            )
            if not candidate_symbols:
                if offline_only:
                    raise SourceNoDataError(
                        f"SZSE historical public contract source unavailable for {trade_date_text}."
                    )
                raise PendingRetryError(f"SZSE option contract discovery returned no symbols for {trade_date_text}.")

            daily_rows = fetch_sina_option_daily_rows(
                candidate_symbols,
                trade_date,
                self.settings["user_agent"],
                self.timeout,
                max_workers=int(self.settings.get("request_behavior", {}).get("sina_daily_max_workers", 1) or 1),
                request_settings=self.settings,
            )
            if not daily_rows:
                if offline_only:
                    raise SourceNoDataError(
                        f"SZSE historical public option quotes unavailable for {trade_date_text}."
                    )
                raise PendingRetryError(f"SZSE option history returned no rows for {trade_date_text}.")

            underlyings_by_code = {
                normalize_text(item.get("bddm") or item.get("合约标的代码")): normalize_text(item.get("bdmc") or item.get("合约标的名称"))
                for item in underlying_rows
            }
            product_name_map = self.settings.get("option_product_name_map", {}).get("SZSE", {})
            records: List[Dict[str, str]] = []
            expire_cache: Dict[tuple, str] = {}

            for symbol, price_row in sorted(daily_rows.items()):
                metadata = candidate_metadata.get(symbol, {})
                if not metadata:
                    continue
                contract_metadata = self._resolve_symbol_metadata(symbol, metadata, allow_live_lookup=not offline_only)
                contract = normalize_text(contract_metadata.get("contract")).upper()
                if not contract:
                    contract = normalize_text(symbol).upper()
                if not contract:
                    continue
                match = SZSE_CONTRACT_PATTERN.match(contract)
                option_type = normalize_text(contract_metadata.get("option_type"))
                if option_type not in {"call", "put"} and match:
                    option_type = "call" if match.group(2) == "C" else "put"
                if option_type not in {"call", "put"}:
                    continue
                underlying_code = normalize_text(
                    contract_metadata.get("underlying_product_code")
                    or contract_metadata.get("underlying_code")
                    or metadata.get("underlying_code")
                )
                expiry_month = ""
                if match:
                    underlying_code = underlying_code or match.group(1)
                    expiry_month = f"20{match.group(3)}"
                if not underlying_code:
                    continue
                expire_date = normalize_text(contract_metadata.get("expire_date"))
                if not expire_date and expiry_month:
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
                    expire_date = expire_cache.get(cache_key, "")
                exercise_type = normalize_text(contract_metadata.get("exercise_type")) or "european"
                underlying_kind = normalize_text(contract_metadata.get("underlying_kind")) or "etf"
                contract_multiplier = normalize_text(contract_metadata.get("contract_multiplier"))
                prev_settlement = price_row.get("prev_settlement", "")
                underlying_label = underlyings_by_code.get(underlying_code, normalize_text(metadata.get("underlying_name")) or underlying_code)
                records.append(
                    {
                        "product_code": underlying_code,
                        "product_name": product_name_map.get(underlying_code, f"{underlying_label}期权"),
                        "contract": contract,
                        "underlying_exchange": "SZSE",
                        "underlying_kind": underlying_kind,
                        "underlying_product_code": underlying_code,
                        "underlying_contract": underlying_code,
                        "option_type": option_type,
                        "strike_price": normalize_text(contract_metadata.get("strike_price")),
                        "exercise_type": exercise_type,
                        "expire_date": expire_date,
                        "last_trade_date": normalize_text(contract_metadata.get("last_trade_date")) or expire_date,
                        "open": price_row.get("open", ""),
                        "high": price_row.get("high", ""),
                        "low": price_row.get("low", ""),
                        "close": price_row.get("close", ""),
                        "prev_settlement": prev_settlement,
                        "settlement": "",
                        "change_close": normalize_number(price_row.get("change_close", "")),
                        "change_settlement": "",
                        "volume": price_row.get("volume", ""),
                        "open_interest": "",
                        "open_interest_change": "",
                        "turnover": "",
                        "delta": normalize_text(contract_metadata.get("delta")),
                        "implied_volatility": normalize_text(contract_metadata.get("implied_volatility")),
                        "exercise_volume": "",
                        "metadata": {
                            "contract_multiplier": contract_multiplier,
                            "quote_unit": "元",
                            "price_tick": "",
                            "delivery_type": "cash",
                            "exercise_type": exercise_type,
                            "option_type": option_type,
                            "strike_price": normalize_text(contract_metadata.get("strike_price")),
                            "expire_date": expire_date,
                            "last_trade_date": normalize_text(contract_metadata.get("last_trade_date")) or expire_date,
                            "underlying_exchange": "SZSE",
                            "underlying_kind": underlying_kind,
                            "underlying_product_code": underlying_code,
                            "underlying_contract": underlying_code,
                            "contract_id_kind": normalize_text(contract_metadata.get("contract_id_kind")),
                            "formal_contract_unavailable": normalize_text(contract_metadata.get("formal_contract_unavailable")),
                            "reconstruction_method": normalize_text(contract_metadata.get("reconstruction_method")),
                        },
                    }
                )

            if not records and offline_only:
                raise SourceNoDataError(f"SZSE historical public contract source unavailable for {trade_date_text}.")
            if not records:
                raise PendingRetryError(f"SZSE option records were discovered but not materialized for {trade_date_text}.")

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
            self.logger.warning("SZSE option live fetch failed for %s, reusing cached raw payload.", trade_date.isoformat())
            return cached
        except SourceNoDataError as exc:
            try:
                cached = self._load_cached_payload(trade_date, source_url, "fallback_online")
            except FileNotFoundError:
                raise exc
            self.logger.warning("SZSE option live fetch failed for %s, reusing cached raw payload.", trade_date.isoformat())
            return cached
        except Exception:
            try:
                cached = self._load_cached_payload(trade_date, source_url, "fallback_online")
            except FileNotFoundError:
                raise
            self.logger.warning("SZSE option live fetch failed for %s, reusing cached raw payload.", trade_date.isoformat())
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

    def _fetch_underlying_rows(self, trade_date_text: str) -> List[Dict[str, str]]:
        response = self._request(
            "GET",
            SZSE_REPORT_URL,
            params={
                "SHOWTYPE": "JSON",
                "CATALOGID": "ysprdzb",
                "TABKEY": "tab1",
                "txtQueryDate": trade_date_text,
                "random": str(random.random()),
            },
            headers=self._headers({"Accept": "application/json,text/plain,*/*"}),
        )
        payload = response.json()
        if not payload:
            return []
        return payload[0].get("data", [])

    def _fetch_current_contract_map(self) -> Dict[str, Dict[str, str]]:
        return self._fetch_contract_map()

    def _fetch_historical_contract_map(self, trade_date_text: str) -> Dict[str, Dict[str, str]]:
        if trade_date_text in self._historical_contract_map_cache:
            return self._historical_contract_map_cache[trade_date_text]
        cached = self._load_cached_historical_contract_map(trade_date_text)
        if cached:
            self._historical_contract_map_cache[trade_date_text] = cached
            return cached
        contract_map = self._fetch_contract_map(trade_date_text=trade_date_text)
        if contract_map:
            self._write_historical_contract_cache(trade_date_text, contract_map)
        self._historical_contract_map_cache[trade_date_text] = contract_map
        return contract_map

    def _fetch_contract_map(self, trade_date_text: str = "") -> Dict[str, Dict[str, str]]:
        current_map: Dict[str, Dict[str, str]] = {}
        page_no = 1
        page_count = 1
        validated_history_page = False
        while page_no <= page_count:
            params = {
                "SHOWTYPE": "JSON",
                "CATALOGID": "option_drhy",
                "TABKEY": "tab1",
                "PAGENO": str(page_no),
            }
            if trade_date_text:
                params["txtQueryDate"] = trade_date_text
            response = self._request(
                "GET",
                SZSE_REPORT_URL,
                params=params,
                headers=self._headers({"Accept": "application/json,text/plain,*/*"}),
            )
            payload = response.json()
            if not payload:
                break
            metadata = payload[0].get("metadata", {})
            if trade_date_text and not validated_history_page:
                source_trade_date = normalize_text(metadata.get("subname"))
                if source_trade_date and source_trade_date != trade_date_text:
                    self.logger.warning(
                        "SZSE historical contract lookup ignored payload for %s because source trade date %s does not match requested date.",
                        trade_date_text,
                        source_trade_date,
                    )
                    return {}
                validated_history_page = True
            try:
                page_count = int(metadata.get("pagecount") or 1)
            except (TypeError, ValueError):
                page_count = 1
            current_map.update(self._build_contract_map_rows(payload[0].get("data", [])))
            page_no += 1
        return current_map

    def _build_contract_map_rows(self, rows: List[Dict[str, str]]) -> Dict[str, Dict[str, str]]:
        contract_map: Dict[str, Dict[str, str]] = {}
        for row in rows:
            symbol = normalize_text(row.get("hybm") or row.get("合约编码"))
            if not symbol:
                continue
            contract_map[symbol] = {
                "contract": normalize_text(row.get("hydm") or row.get("合约代码")).upper(),
                "strike_price": normalize_text(row.get("xqjg") or row.get("行权价")),
                "expire_date": normalize_text(row.get("dqrq") or row.get("到期日")),
                "last_trade_date": normalize_text(row.get("hzjyrq") or row.get("最后交易日")),
                "open_interest": normalize_text(row.get("hyzcc") or row.get("合约总持仓")),
                "underlying": extract_code_from_text(row.get("bdzqdm") or row.get("标的证券简称(代码)")),
                "contract_multiplier": normalize_text(row.get("hydw") or row.get("合约单位")),
                "prev_settlement": normalize_text(row.get("qjsjg") or row.get("前结算价")),
            }
        return contract_map

    def _historical_contract_cache_path(self, trade_date_text: str) -> Path:
        return PROJECT_ROOT / "data" / "raw" / "szse" / "historical_contract_lookup" / f"{trade_date_text.replace('-', '')}.json"

    def _load_cached_historical_contract_map(self, trade_date_text: str) -> Dict[str, Dict[str, str]]:
        cache_path = self._historical_contract_cache_path(trade_date_text)
        if not cache_path.exists():
            return {}
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        source_trade_date = normalize_text(payload.get("source_trade_date"))
        if source_trade_date and source_trade_date != trade_date_text:
            return {}
        data = payload.get("data")
        if not isinstance(data, dict):
            return {}
        contract_map: Dict[str, Dict[str, str]] = {}
        for symbol, item in data.items():
            if not isinstance(item, dict):
                continue
            normalized_symbol = normalize_text(symbol)
            contract = normalize_text(item.get("contract")).upper()
            if not normalized_symbol or not contract:
                continue
            contract_map[normalized_symbol] = {
                "contract": contract,
                "strike_price": normalize_text(item.get("strike_price")),
                "expire_date": normalize_text(item.get("expire_date")),
                "last_trade_date": normalize_text(item.get("last_trade_date")),
                "open_interest": normalize_text(item.get("open_interest")),
                "underlying": normalize_text(item.get("underlying")),
                "contract_multiplier": normalize_text(item.get("contract_multiplier")),
                "prev_settlement": normalize_text(item.get("prev_settlement")),
            }
        return contract_map

    def _write_historical_contract_cache(self, trade_date_text: str, contract_map: Dict[str, Dict[str, str]]) -> None:
        if not contract_map:
            return
        cache_path = self._historical_contract_cache_path(trade_date_text)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps({"trade_date": trade_date_text, "source_trade_date": trade_date_text, "data": contract_map}, ensure_ascii=False),
            encoding="utf-8",
        )

    def _official_contracts_url(self) -> str:
        return SZSE_REPORT_URL

    def _official_underlying_url(self) -> str:
        return SZSE_REPORT_URL

    def _sina_daily_url(self) -> str:
        return "https://stock.finance.sina.com.cn/futures/api/jsonp_v2.php//StockOptionDaylineService.getSymbolInfo"

    def _prefer_cached_payload(self, trade_date: date, live_payload: RawPayload, min_row_count: int) -> RawPayload:
        try:
            cached = self._load_cached_payload(trade_date, live_payload.url, live_payload.source_type)
        except FileNotFoundError:
            return live_payload
        cached_count = _payload_row_count(cached.content)
        if cached_count > max(min_row_count, _payload_row_count(live_payload.content)):
            self.logger.warning("SZSE option live fetch returned fewer rows than cached raw for %s, keeping cached payload.", trade_date.isoformat())
            return cached
        return live_payload

    def _discover_historical_symbols(
        self,
        underlying_rows: List[Dict[str, str]],
        trade_date: date,
        *,
        offline_only: bool,
        allow_historical_live_metadata_probe: bool,
    ) -> tuple[Set[str], Dict[str, Dict[str, str]]]:
        metadata: Dict[str, Dict[str, str]] = {}
        candidate_symbols: Set[str] = set()
        self._seed_metadata_cache_from_contract_dir(trade_date)
        months_ahead = int(self.settings.get("equity_option_months_ahead", 4) or 4)
        expiry_months = generate_expiry_months(trade_date, months_ahead=months_ahead)
        for item in underlying_rows:
            underlying_code = normalize_text(item.get("bddm") or item.get("合约标的代码"))
            underlying_name = normalize_text(item.get("bdmc") or item.get("合约标的名称"))
            if not underlying_code:
                continue
            underlying_has_symbols = False
            historical_contract_map: Dict[str, Dict[str, str]] = {}
            if offline_only:
                try:
                    historical_contract_map = self._fetch_historical_contract_map(trade_date.isoformat())
                except Exception as exc:
                    self.logger.warning(
                        "SZSE historical contract lookup failed for %s, falling back to cache/probe: %s",
                        trade_date.isoformat(),
                        exc,
                    )
            for expiry_month in expiry_months:
                for option_type in ("call", "put"):
                    discovered: List[str] = []
                    if historical_contract_map:
                        discovered = self._load_symbols_from_contract_map(
                            contract_map=historical_contract_map,
                            underlying_code=underlying_code,
                            expiry_month=expiry_month,
                            option_type=option_type,
                        )
                    if not offline_only:
                        try:
                            discovered = fetch_sina_option_codes(
                                underlying_code,
                                expiry_month,
                                option_type,
                                self.settings["user_agent"],
                                self.timeout,
                                request_settings=self.settings,
                            )
                        except Exception:
                            discovered = []
                    if not discovered:
                        discovered = self._load_recent_cached_symbols_from_contract_dir(
                            trade_date=trade_date,
                            underlying_code=underlying_code,
                            expiry_month=expiry_month,
                            option_type=option_type,
                        )
                    if not discovered:
                        discovered = self._load_cached_symbols_from_metadata(
                            underlying_code=underlying_code,
                            expiry_month=expiry_month,
                            option_type=option_type,
                        )
                    if not discovered:
                        discovered = self._probe_history_cached_symbols(
                            trade_date=trade_date,
                            underlying_code=underlying_code,
                            expiry_month=expiry_month,
                            option_type=option_type,
                            allow_live_metadata_probe=(not offline_only) or allow_historical_live_metadata_probe,
                        )
                    for symbol in discovered:
                        candidate_symbols.add(symbol)
                        underlying_has_symbols = True
                        symbol_metadata = metadata.setdefault(
                            symbol,
                            {
                                "underlying_code": underlying_code,
                                "underlying_name": underlying_name,
                                "expiry_month": expiry_month,
                            },
                        )
                        cached_symbol_metadata = {
                            key: value
                            for key, value in load_cached_sina_option_metadata(symbol).items()
                            if normalize_text(value)
                        }
                        if cached_symbol_metadata:
                            symbol_metadata.update(cached_symbol_metadata)
                        contract_item = historical_contract_map.get(symbol, {})
                        if contract_item:
                            symbol_metadata.update(
                                {
                                    "contract": normalize_text(contract_item.get("contract")).upper(),
                                    "strike_price": normalize_text(contract_item.get("strike_price")),
                                    "expire_date": normalize_text(contract_item.get("expire_date")),
                                    "last_trade_date": normalize_text(contract_item.get("last_trade_date")),
                                    "underlying_product_code": normalize_text(contract_item.get("underlying")),
                                    "contract_multiplier": normalize_text(contract_item.get("contract_multiplier")),
                                    "prev_settlement": normalize_text(contract_item.get("prev_settlement")),
                                }
                            )
            if offline_only and not underlying_has_symbols:
                reconstructed_symbols, reconstructed_metadata = self._reconstruct_historical_symbols_from_history_cache(
                    trade_date=trade_date,
                    underlying_code=underlying_code,
                    underlying_name=underlying_name,
                    single_underlying=(
                        len(
                            [
                                row
                                for row in underlying_rows
                                if normalize_text(row.get("bddm") or row.get("合约标的代码"))
                            ]
                        )
                        == 1
                    ),
                )
                if reconstructed_symbols:
                    self.logger.info(
                        "SZSE option reconstructed %s historical symbols from local history cache for %s on %s.",
                        len(reconstructed_symbols),
                        underlying_code,
                        trade_date.isoformat(),
                    )
                    candidate_symbols.update(reconstructed_symbols)
                    metadata.update(reconstructed_metadata)
        return candidate_symbols, metadata

    def _load_symbols_from_contract_map(
        self,
        *,
        contract_map: Dict[str, Dict[str, str]],
        underlying_code: str,
        expiry_month: str,
        option_type: str,
    ) -> List[str]:
        matched: List[str] = []
        option_flag = "C" if option_type == "call" else "P"
        expiry_token = normalize_text(expiry_month)[2:6]
        for symbol, item in contract_map.items():
            contract = normalize_text(item.get("contract")).upper()
            cached_underlying = normalize_text(item.get("underlying"))
            if not contract or cached_underlying != underlying_code:
                continue
            match = SZSE_CONTRACT_PATTERN.match(contract)
            if not match:
                continue
            _, cached_option_flag, cached_expiry_token, _, _, _ = match.groups()
            if cached_option_flag != option_flag or cached_expiry_token != expiry_token:
                continue
            normalized_symbol = normalize_text(symbol)
            if not normalized_symbol:
                continue
            write_sina_option_metadata_cache(
                normalized_symbol,
                {
                    "contract": contract,
                    "strike_price": normalize_text(item.get("strike_price")),
                    "expire_date": normalize_text(item.get("expire_date")),
                    "last_trade_date": normalize_text(item.get("last_trade_date")),
                    "underlying_product_code": cached_underlying,
                    "contract_multiplier": normalize_text(item.get("contract_multiplier")),
                    "prev_settlement": normalize_text(item.get("prev_settlement")),
                },
            )
            matched.append(normalized_symbol)
        if matched:
            self.logger.info(
                "SZSE option using official historical contract table for %s %s %s.",
                underlying_code,
                expiry_month,
                option_type,
            )
        return sorted(set(item for item in matched if item))

    def _seed_metadata_cache_from_contract_dir(self, trade_date: date) -> None:
        payload_dir = PROJECT_ROOT / "data" / "raw" / "szse" / "contracts_snapshot"
        if not payload_dir.exists():
            return
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
        seeded = 0
        for _, path in sorted(candidates, key=lambda item: (item[0], item[1].name)):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            contract_map = payload.get("data")
            if not isinstance(contract_map, dict):
                continue
            current_seeded = 0
            for symbol, item in contract_map.items():
                if not isinstance(item, dict):
                    continue
                normalized_symbol = normalize_text(symbol)
                contract = normalize_text(item.get("contract")).upper()
                if not normalized_symbol or not contract:
                    continue
                metadata = {
                    "contract": contract,
                    "strike_price": normalize_text(item.get("strike_price")),
                    "expire_date": normalize_text(item.get("expire_date")),
                    "last_trade_date": normalize_text(item.get("last_trade_date")),
                    "underlying_product_code": normalize_text(item.get("underlying")),
                    "contract_multiplier": normalize_text(item.get("contract_multiplier")),
                    "prev_settlement": normalize_text(item.get("prev_settlement")),
                }
                cached_before = load_cached_sina_option_metadata(normalized_symbol)
                written = write_sina_option_metadata_cache(normalized_symbol, metadata)
                if written and written != cached_before:
                    current_seeded += 1
            if current_seeded:
                seeded += current_seeded
                self.logger.info(
                    "SZSE option seeded %s symbol metadata rows from nearby contracts_snapshot %s for %s.",
                    current_seeded,
                    path.name,
                    trade_date.isoformat(),
                )
        if seeded:
            self.logger.info("SZSE option seeded %s metadata rows before historical discovery for %s.", seeded, trade_date.isoformat())

    def _load_recent_cached_underlying_rows(self, trade_date: date) -> List[Dict[str, str]]:
        cache_key = trade_date.isoformat()
        if cache_key in self._recent_underlying_rows_cache:
            return list(self._recent_underlying_rows_cache[cache_key])
        payload_dir = PROJECT_ROOT / "data" / "raw" / "szse" / "options_daily_quotes"
        if not payload_dir.exists():
            option_rows: List[Dict[str, str]] = []
        else:
            option_rows = self._load_recent_underlyings_from_payload_dir(payload_dir, trade_date)
            if option_rows:
                self._recent_underlying_rows_cache[cache_key] = list(option_rows)
                return option_rows
        contract_payload_dir = PROJECT_ROOT / "data" / "raw" / "szse" / "contracts_snapshot"
        if contract_payload_dir.exists():
            contract_rows = self._load_recent_underlyings_from_contract_dir(contract_payload_dir, trade_date)
            if contract_rows:
                self._recent_underlying_rows_cache[cache_key] = list(contract_rows)
                return contract_rows
        self._recent_underlying_rows_cache[cache_key] = []
        return []

    def _load_recent_underlyings_from_payload_dir(self, payload_dir: Path, trade_date: date) -> List[Dict[str, str]]:
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
            rows = payload.get("data")
            if not isinstance(rows, list):
                continue
            underlyings: Dict[str, Dict[str, str]] = {}
            for item in rows:
                underlying_code = normalize_text(item.get("underlying_product_code") or item.get("product_code"))
                if not underlying_code:
                    continue
                product_name = normalize_text(item.get("product_name")).replace("期权", "")
                underlyings.setdefault(
                    underlying_code,
                    {
                        "bddm": underlying_code,
                        "bdmc": product_name or underlying_code,
                    },
                )
            if underlyings:
                self.logger.info(
                    "SZSE option using nearby cached underlyings from %s for %s.",
                    path.name,
                    trade_date.isoformat(),
                )
                return list(underlyings.values())
        return []

    def _load_recent_underlyings_from_contract_dir(self, payload_dir: Path, trade_date: date) -> List[Dict[str, str]]:
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
            contract_map = payload.get("data")
            if not isinstance(contract_map, dict):
                continue
            underlyings: Dict[str, Dict[str, str]] = {}
            for item in contract_map.values():
                if not isinstance(item, dict):
                    continue
                underlying_code = normalize_text(item.get("underlying"))
                if not underlying_code:
                    continue
                product_name = normalize_text(item.get("contract_name") or item.get("product_name")).replace("期权", "")
                underlyings.setdefault(
                    underlying_code,
                    {
                        "bddm": underlying_code,
                        "bdmc": product_name or underlying_code,
                    },
                )
            if underlyings:
                self.logger.info(
                    "SZSE option using nearby cached contracts_snapshot underlyings from %s for %s.",
                    path.name,
                    trade_date.isoformat(),
                )
                return list(underlyings.values())
        return []

    def _load_cached_symbols_from_metadata(self, *, underlying_code: str, expiry_month: str, option_type: str) -> List[str]:
        matched: List[str] = []
        option_flag = "C" if option_type == "call" else "P"
        expiry_token = normalize_text(expiry_month)[2:6]
        for item in iter_cached_sina_option_metadata():
            contract = normalize_text(item.get("contract")).upper()
            symbol = normalize_text(item.get("symbol"))
            if not contract or not symbol:
                continue
            match = SZSE_CONTRACT_PATTERN.match(contract)
            if not match:
                continue
            cached_underlying_code, cached_option_flag, cached_expiry_token, _, _, _ = match.groups()
            if (
                cached_underlying_code == underlying_code
                and cached_option_flag == option_flag
                and cached_expiry_token == expiry_token
            ):
                matched.append(symbol)
        return sorted(set(matched))

    def _load_recent_cached_symbols_from_contract_dir(
        self,
        *,
        trade_date: date,
        underlying_code: str,
        expiry_month: str,
        option_type: str,
    ) -> List[str]:
        payload_dir = PROJECT_ROOT / "data" / "raw" / "szse" / "contracts_snapshot"
        if not payload_dir.exists():
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
        option_flag = "C" if option_type == "call" else "P"
        expiry_token = normalize_text(expiry_month)[2:6]
        for _, path in sorted(candidates, key=lambda item: (item[0], item[1].name)):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            contract_map = payload.get("data")
            if not isinstance(contract_map, dict):
                continue
            matched: List[str] = []
            for symbol, item in contract_map.items():
                if not isinstance(item, dict):
                    continue
                contract = normalize_text(item.get("contract")).upper()
                cached_underlying = normalize_text(item.get("underlying"))
                if not contract or cached_underlying != underlying_code:
                    continue
                match = SZSE_CONTRACT_PATTERN.match(contract)
                if not match:
                    continue
                _, cached_option_flag, cached_expiry_token, _, _, _ = match.groups()
                if cached_option_flag == option_flag and cached_expiry_token == expiry_token:
                    normalized_symbol = normalize_text(symbol)
                    if not normalized_symbol:
                        continue
                    write_sina_option_metadata_cache(
                        normalized_symbol,
                        {
                            "contract": contract,
                            "strike_price": normalize_text(item.get("strike_price")),
                            "expire_date": normalize_text(item.get("expire_date")),
                            "last_trade_date": normalize_text(item.get("last_trade_date")),
                            "underlying_product_code": cached_underlying,
                        },
                    )
                    matched.append(normalized_symbol)
            if matched:
                self.logger.info(
                    "SZSE option using nearby cached contracts_snapshot symbols from %s for %s.",
                    path.name,
                    trade_date.isoformat(),
                )
                return sorted(set(item for item in matched if item))
        return []

    def _fallback_underlying_rows_from_config(self) -> List[Dict[str, str]]:
        product_name_map = self.settings.get("option_product_name_map", {}).get("SZSE", {})
        rows = []
        for underlying_code, product_name in sorted(product_name_map.items()):
            code = normalize_text(underlying_code)
            if not code:
                continue
            rows.append(
                {
                    "bddm": code,
                    "bdmc": normalize_text(str(product_name)).replace("期权", "") or code,
                }
            )
        if rows:
            self.logger.info("SZSE option using configured underlying fallback for historical discovery.")
        return rows

    def _resolve_symbol_metadata(
        self,
        symbol: str,
        discovery_metadata: Dict[str, str],
        *,
        allow_live_lookup: bool,
    ) -> Dict[str, str]:
        contract = normalize_text(discovery_metadata.get("contract")).upper()
        if contract or not allow_live_lookup:
            return discovery_metadata
        normalized_symbol = normalize_text(symbol)
        if normalized_symbol in self._resolved_symbol_metadata_cache:
            cached = dict(self._resolved_symbol_metadata_cache[normalized_symbol])
            cached.update({key: value for key, value in discovery_metadata.items() if normalize_text(value)})
            return cached
        metadata = fetch_sina_option_metadata(
            symbol,
            self.settings["user_agent"],
            self.timeout,
            request_settings=self.settings,
        )
        merged = dict(discovery_metadata)
        merged.update({key: value for key, value in metadata.items() if normalize_text(value)})
        self._resolved_symbol_metadata_cache[normalized_symbol] = dict(merged)
        return merged

    def _probe_history_cached_symbols(
        self,
        *,
        trade_date: date,
        underlying_code: str,
        expiry_month: str,
        option_type: str,
        allow_live_metadata_probe: bool,
    ) -> List[str]:
        cache_key = (trade_date.isoformat(), underlying_code, expiry_month, option_type, bool(allow_live_metadata_probe))
        if cache_key in self._history_probe_cache:
            return list(self._history_probe_cache[cache_key])
        option_flag = "C" if option_type == "call" else "P"
        expiry_token = normalize_text(expiry_month)[2:6]
        matched: List[str] = []
        probe_started_at = time.monotonic()
        if self._treat_historical_gap_as_no_data(trade_date) and allow_live_metadata_probe:
            probe_limit = int(self.settings.get("equity_option_historical_probe_limit", 120) or 120)
            probe_budget_seconds = float(self.settings.get("equity_option_historical_probe_budget_seconds", 45) or 45)
            probe_timeout_seconds = int(self.settings.get("equity_option_historical_probe_timeout_seconds", min(self.timeout, 3)) or min(self.timeout, 3))
        else:
            probe_limit = int(self.settings.get("equity_option_history_probe_limit", 24) or 24)
            probe_budget_seconds = 0.0
            probe_timeout_seconds = self.timeout
        matched_limit = int(self.settings.get("equity_option_history_match_limit", 12) or 12)
        probe_count = 0
        for symbol in iter_cached_sina_option_history_symbols(trade_date=trade_date):
            if probe_budget_seconds and (time.monotonic() - probe_started_at) >= probe_budget_seconds:
                self.logger.warning(
                    "SZSE option history metadata probing exceeded %.1fs budget for %s; stopping early.",
                    probe_budget_seconds,
                    trade_date.isoformat(),
                )
                break
            metadata = load_cached_sina_option_metadata(symbol)
            if not metadata:
                if not allow_live_metadata_probe:
                    continue
                if probe_count >= probe_limit:
                    break
                probe_count += 1
                try:
                    metadata = fetch_sina_option_metadata(
                        symbol,
                        self.settings["user_agent"],
                        probe_timeout_seconds,
                        request_settings=self.settings,
                    )
                    self._resolved_symbol_metadata_cache[normalize_text(symbol)] = dict(metadata)
                except Exception:
                    continue
            contract = normalize_text(metadata.get("contract")).upper()
            if not contract:
                continue
            match = SZSE_CONTRACT_PATTERN.match(contract)
            if not match:
                continue
            cached_underlying_code, cached_option_flag, cached_expiry_token, _, _, _ = match.groups()
            if (
                cached_underlying_code == underlying_code
                and cached_option_flag == option_flag
                and cached_expiry_token == expiry_token
            ):
                matched.append(symbol)
                if len(matched) >= matched_limit:
                    break
        self._history_probe_cache[cache_key] = sorted(set(matched))
        if matched:
            self.logger.info(
                "SZSE option using history-cache symbol probing for %s %s %s on %s.",
                underlying_code,
                expiry_month,
                option_type,
                trade_date.isoformat(),
            )
        return sorted(set(item for item in matched if item))

    def _reconstruct_historical_symbols_from_history_cache(
        self,
        *,
        trade_date: date,
        underlying_code: str,
        underlying_name: str,
        single_underlying: bool,
    ) -> Tuple[Set[str], Dict[str, Dict[str, str]]]:
        history_dir = PROJECT_ROOT / "data" / "raw" / "equity_options_history"
        if not history_dir.exists():
            return set(), {}

        grouped: Dict[Tuple[str, str], List[Dict[str, object]]] = defaultdict(list)
        for symbol in iter_cached_sina_option_history_symbols(trade_date=trade_date):
            rows = self._load_history_rows(history_dir / f"{symbol}.json")
            if not rows:
                continue
            cached_metadata = load_cached_sina_option_metadata(symbol)
            cached_underlying = normalize_text(cached_metadata.get("underlying_product_code"))
            if cached_underlying and cached_underlying != underlying_code:
                continue
            if not cached_underlying and not single_underlying:
                continue
            expire_date = max((item.get("date", "") for item in rows if item.get("date")), default="")
            if not expire_date:
                continue
            first_trade_date = min((item.get("date", "") for item in rows if item.get("date")), default="")
            close_text = ""
            for item in rows:
                if item.get("date") == trade_date.isoformat():
                    close_text = normalize_text(item.get("close"))
                    break
            if not close_text:
                continue
            grouped[(expire_date, first_trade_date)].append(
                {
                    "symbol": symbol,
                    "close": close_text,
                    "cached_metadata": cached_metadata,
                }
            )

        discovered: Set[str] = set()
        metadata: Dict[str, Dict[str, str]] = {}
        for (expire_date, _), items in grouped.items():
            inferred_types = self._infer_option_types_from_history_group(items)
            for item in items:
                symbol = normalize_text(item.get("symbol"))
                if not symbol:
                    continue
                cached_metadata = item.get("cached_metadata") or {}
                if not isinstance(cached_metadata, dict):
                    cached_metadata = {}
                discovered.add(symbol)
                metadata[symbol] = {
                    "contract": symbol,
                    "strike_price": normalize_text(cached_metadata.get("strike_price")),
                    "expire_date": expire_date,
                    "last_trade_date": expire_date,
                    "underlying_product_code": underlying_code,
                    "underlying_code": underlying_code,
                    "underlying_name": underlying_name,
                    "underlying_kind": "etf",
                    "exercise_type": "european",
                    "option_type": inferred_types.get(symbol, "call"),
                    "contract_multiplier": normalize_text(cached_metadata.get("contract_multiplier")),
                    "contract_id_kind": "exchange_numeric_symbol",
                    "formal_contract_unavailable": "true",
                    "reconstruction_method": "history_expire_cluster",
                }
        return discovered, metadata

    def _infer_option_types_from_history_group(self, items: List[Dict[str, object]]) -> Dict[str, str]:
        ordered = sorted(items, key=lambda item: normalize_text(item.get("symbol")))
        if not ordered:
            return {}
        closes = [self._safe_float(item.get("close")) for item in ordered]
        runs: List[Tuple[int, int, int]] = []
        start = 0
        current_direction = 0
        for index in range(1, len(ordered)):
            diff = closes[index] - closes[index - 1]
            direction = 1 if diff > 1e-9 else -1 if diff < -1e-9 else 0
            if current_direction == 0 and direction != 0:
                current_direction = direction
                continue
            if direction == 0 or current_direction == 0 or direction == current_direction:
                continue
            runs.append((start, index - 1, current_direction))
            start = max(index - 1, 0)
            current_direction = direction
        runs.append((start, len(ordered) - 1, current_direction))

        inferred: Dict[str, str] = {}
        previous_type = "put"
        for start_index, end_index, direction in runs:
            if direction < 0:
                option_type = "call"
            elif direction > 0:
                option_type = "put"
            else:
                option_type = "call" if previous_type == "put" else "put"
            previous_type = option_type
            for item in ordered[start_index : end_index + 1]:
                symbol = normalize_text(item.get("symbol"))
                if symbol:
                    inferred[symbol] = option_type
        return inferred

    def _load_history_rows(self, path: Path) -> List[Dict[str, str]]:
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return _normalize_daily_payload(payload)

    @staticmethod
    def _safe_float(value: object) -> float:
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return 0.0

    def _treat_historical_gap_as_no_data(self, trade_date: date) -> bool:
        return (date.today() - trade_date).days > 30

    def _allow_historical_live_metadata_probe(self, trade_date: date) -> bool:
        if not self._treat_historical_gap_as_no_data(trade_date):
            return False
        return bool(self.settings.get("equity_option_allow_historical_live_metadata_probe", True))


def extract_code_from_text(text: object) -> str:
    value = normalize_text(text)
    match = re.search(r"\((\d{6})\)", value)
    if match:
        return match.group(1)
    return ""


def _payload_row_count(raw_text: str) -> int:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return 0
    data = payload.get("data")
    return len(data) if isinstance(data, list) else 0
