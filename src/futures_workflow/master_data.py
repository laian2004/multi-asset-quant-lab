import json
import re
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from .config import PROJECT_ROOT, RAW_DIR
from .models import OptionQuoteRow, QuoteRow
from .sources.option_sse import SSEOptionSource
from .sources.option_szse import SZSEOptionSource
from .utils import compact_trade_date, ensure_directory, iso_timestamp, normalize_number, normalize_text, now_shanghai, relative_to_project


OFFICIAL_MASTER_SOURCE_TYPES = {"official", "official_browser_bootstrap"}
SSE_CONTRACT_PATTERN = re.compile(r"^(\d{6})([CP])(\d{4})([A-Z])(\d{5,6})([A-Z]?)$")
CFFEX_UNDERLYING_PRODUCT_MAP = {
    "HO": "IH",
    "IO": "IF",
    "MO": "IM",
}


class ContractMasterCollector:
    def __init__(self, settings: Dict[str, object], logger):
        self.settings = settings
        self.logger = logger
        self._sse_source = SSEOptionSource(settings, logger)
        self._szse_source = SZSEOptionSource(settings, logger)

    def collect(
        self,
        trade_date: date,
        *,
        futures_rows: Iterable[QuoteRow],
        options_rows: Iterable[OptionQuoteRow],
    ) -> Dict[Tuple[str, str, str], Dict[str, str]]:
        metadata: Dict[Tuple[str, str, str], Dict[str, str]] = {}
        futures_rows = list(futures_rows)
        options_rows = list(options_rows)

        metadata.update(self._collect_official_futures_metadata(futures_rows))
        metadata.update(self._collect_official_option_metadata(options_rows))
        metadata.update(self._collect_fallback_option_metadata(options_rows))
        metadata.update(self._collect_sse_metadata(trade_date, options_rows))
        metadata.update(self._collect_szse_metadata(trade_date, options_rows))
        return metadata

    def _collect_official_futures_metadata(self, rows: List[QuoteRow]) -> Dict[Tuple[str, str, str], Dict[str, str]]:
        collected: Dict[Tuple[str, str, str], Dict[str, str]] = {}
        for row in rows:
            if row.source_type not in OFFICIAL_MASTER_SOURCE_TYPES:
                continue
            collected[("future", row.exchange, row.contract)] = {
                "trade_date": row.trade_date,
                "instrument_type": "future",
                "exchange": row.exchange,
                "product_code": row.variety_code,
                "product_name": row.variety_name,
                "contract": row.contract,
                "contract_status": "trading",
                "list_date": "",
                "expire_date": "",
                "last_trade_date": "",
                "contract_multiplier": "",
                "quote_unit": "",
                "price_tick": "",
                "delivery_type": "",
                "exercise_type": "",
                "option_type": "",
                "strike_price": "",
                "underlying_exchange": row.exchange,
                "underlying_kind": "",
                "underlying_product_code": row.variety_code,
                "underlying_contract": row.contract,
                "source_url": row.source_url,
                "source_type": row.source_type,
                "retrieved_at": row.retrieved_at,
                "raw_path": row.raw_path,
            }
        return collected

    def _collect_official_option_metadata(self, rows: List[OptionQuoteRow]) -> Dict[Tuple[str, str, str], Dict[str, str]]:
        collected: Dict[Tuple[str, str, str], Dict[str, str]] = {}
        for row in rows:
            if row.exchange in {"SSE", "SZSE"}:
                continue
            if row.source_type not in OFFICIAL_MASTER_SOURCE_TYPES:
                continue
            collected[("option", row.exchange, row.contract)] = {
                "trade_date": row.trade_date,
                "instrument_type": "option",
                "exchange": row.exchange,
                "product_code": row.product_code,
                "product_name": row.product_name,
                "contract": row.contract,
                "contract_status": "trading",
                "list_date": "",
                "expire_date": row.expire_date,
                "last_trade_date": row.last_trade_date,
                "contract_multiplier": "",
                "quote_unit": "",
                "price_tick": "",
                "delivery_type": "",
                "exercise_type": row.exercise_type,
                "option_type": row.option_type,
                "strike_price": row.strike_price,
                "underlying_exchange": row.underlying_exchange,
                "underlying_kind": row.underlying_kind,
                "underlying_product_code": self._resolved_underlying_product_code(row),
                "underlying_contract": self._resolved_underlying_contract(row),
                "source_url": row.source_url,
                "source_type": row.source_type,
                "retrieved_at": row.retrieved_at,
                "raw_path": row.raw_path,
            }
        return collected

    def _collect_fallback_option_metadata(self, rows: List[OptionQuoteRow]) -> Dict[Tuple[str, str, str], Dict[str, str]]:
        collected: Dict[Tuple[str, str, str], Dict[str, str]] = {}
        for row in rows:
            if row.source_type != "fallback_online":
                continue
            option_type = normalize_text(row.option_type)
            underlying_contract = normalize_text(self._resolved_underlying_contract(row))
            if not option_type or not underlying_contract:
                continue
            collected[("option", row.exchange, row.contract)] = {
                "trade_date": row.trade_date,
                "instrument_type": "option",
                "exchange": row.exchange,
                "product_code": row.product_code,
                "product_name": row.product_name,
                "contract": row.contract,
                "contract_status": "trading",
                "list_date": "",
                "expire_date": row.expire_date,
                "last_trade_date": row.last_trade_date,
                "contract_multiplier": "",
                "quote_unit": "",
                "price_tick": "",
                "delivery_type": "",
                "exercise_type": row.exercise_type,
                "option_type": option_type,
                "strike_price": row.strike_price,
                "underlying_exchange": row.underlying_exchange,
                "underlying_kind": row.underlying_kind,
                "underlying_product_code": self._resolved_underlying_product_code(row),
                "underlying_contract": underlying_contract,
                "source_url": row.source_url,
                "source_type": row.source_type,
                "retrieved_at": row.retrieved_at,
                "raw_path": row.raw_path,
            }
        return collected

    def _resolved_underlying_product_code(self, row: OptionQuoteRow) -> str:
        if row.exchange == "CFFEX":
            return CFFEX_UNDERLYING_PRODUCT_MAP.get(row.product_code, row.underlying_product_code or row.product_code)
        return row.underlying_product_code or row.product_code

    def _resolved_underlying_contract(self, row: OptionQuoteRow) -> str:
        if normalize_text(row.underlying_contract):
            return normalize_text(row.underlying_contract)
        if row.exchange == "CFFEX":
            match = re.match(r"^[A-Z]+(\d{4})-[CP]-\d+$", row.contract.upper())
            underlying_product = self._resolved_underlying_product_code(row)
            if match and underlying_product:
                return f"{underlying_product}{match.group(1)}"
        return ""

    def _collect_sse_metadata(
        self,
        trade_date: date,
        option_rows: List[OptionQuoteRow],
    ) -> Dict[Tuple[str, str, str], Dict[str, str]]:
        contracts = {row.contract.upper() for row in option_rows if row.exchange == "SSE"}
        if not contracts:
            return {}
        cached = self._load_cached_if_historical("sse", trade_date)
        if cached is not None:
            risk_rows = cached.get("result", [])
            raw_path = self._raw_path("sse", trade_date)
        else:
            try:
                risk_rows = self._sse_source._fetch_risk_rows(trade_date)
                raw_path = self._write_raw(
                    exchange="sse",
                    trade_date=trade_date,
                    payload={"result": risk_rows},
                )
            except Exception as exc:
                cached = self._load_cached("sse", trade_date)
                if cached is None:
                    self.logger.warning("SSE official contract metadata fetch failed for %s: %s", trade_date.isoformat(), exc)
                    return {}
                self.logger.warning("SSE official contract metadata fetch failed for %s, reusing cached master payload.", trade_date.isoformat())
                risk_rows = cached.get("result", [])
                raw_path = self._raw_path("sse", trade_date)

        retrieved_at = iso_timestamp()
        product_name_map = self.settings.get("option_product_name_map", {}).get("SSE", {})
        collected: Dict[Tuple[str, str, str], Dict[str, str]] = {}
        for item in risk_rows:
            contract = normalize_text(item.get("CONTRACT_ID")).upper()
            if contract not in contracts:
                continue
            match = SSE_CONTRACT_PATTERN.match(contract)
            if not match:
                continue
            underlying_code, option_flag, _, _, strike_digits, _ = match.groups()
            collected[("option", "SSE", contract)] = {
                "trade_date": trade_date.isoformat(),
                "instrument_type": "option",
                "exchange": "SSE",
                "product_code": underlying_code,
                "product_name": product_name_map.get(underlying_code, f"{underlying_code}期权"),
                "contract": contract,
                "contract_status": "trading",
                "list_date": "",
                "expire_date": "",
                "last_trade_date": "",
                "contract_multiplier": "",
                "quote_unit": "",
                "price_tick": "",
                "delivery_type": "cash",
                "exercise_type": "european",
                "option_type": "call" if option_flag == "C" else "put",
                "strike_price": normalize_number(str(int(strike_digits) / 1000)),
                "underlying_exchange": "SSE",
                "underlying_kind": "etf",
                "underlying_product_code": underlying_code,
                "underlying_contract": underlying_code,
                "source_url": self._sse_source._official_risk_url(),
                "source_type": "official",
                "retrieved_at": retrieved_at,
                "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            }
        return collected

    def _collect_szse_metadata(
        self,
        trade_date: date,
        option_rows: List[OptionQuoteRow],
    ) -> Dict[Tuple[str, str, str], Dict[str, str]]:
        contracts = {row.contract.upper() for row in option_rows if row.exchange == "SZSE"}
        if not contracts:
            return {}
        cached = self._load_cached_if_historical("szse", trade_date)
        if cached is not None:
            contract_map = cached.get("data", {})
            raw_path = self._raw_path("szse", trade_date)
        else:
            try:
                contract_map = self._szse_source._fetch_current_contract_map()
                raw_path = self._write_raw(
                    exchange="szse",
                    trade_date=trade_date,
                    payload={"data": contract_map},
                )
            except Exception as exc:
                cached = self._load_cached("szse", trade_date)
                if cached is None:
                    self.logger.warning("SZSE official contract metadata fetch failed for %s: %s", trade_date.isoformat(), exc)
                    return {}
                self.logger.warning("SZSE official contract metadata fetch failed for %s, reusing cached master payload.", trade_date.isoformat())
                contract_map = cached.get("data", {})
                raw_path = self._raw_path("szse", trade_date)

        retrieved_at = iso_timestamp()
        product_name_map = self.settings.get("option_product_name_map", {}).get("SZSE", {})
        collected: Dict[Tuple[str, str, str], Dict[str, str]] = {}
        for metadata in contract_map.values():
            contract = normalize_text(metadata.get("contract")).upper()
            if contract not in contracts:
                continue
            underlying_code = normalize_text(metadata.get("underlying"))
            option_flag = "C" if "C" in contract else "P"
            collected[("option", "SZSE", contract)] = {
                "trade_date": trade_date.isoformat(),
                "instrument_type": "option",
                "exchange": "SZSE",
                "product_code": underlying_code,
                "product_name": product_name_map.get(underlying_code, f"{underlying_code}期权"),
                "contract": contract,
                "contract_status": "trading",
                "list_date": "",
                "expire_date": normalize_text(metadata.get("expire_date")),
                "last_trade_date": normalize_text(metadata.get("last_trade_date")),
                "contract_multiplier": normalize_text(metadata.get("contract_multiplier")),
                "quote_unit": "",
                "price_tick": "",
                "delivery_type": "cash",
                "exercise_type": "european",
                "option_type": "call" if option_flag == "C" else "put",
                "strike_price": normalize_number(metadata.get("strike_price")),
                "underlying_exchange": "SZSE",
                "underlying_kind": "etf",
                "underlying_product_code": underlying_code,
                "underlying_contract": underlying_code,
                "source_url": self._szse_source._official_contracts_url(),
                "source_type": "official",
                "retrieved_at": retrieved_at,
                "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            }
        return collected

    def _write_raw(self, *, exchange: str, trade_date: date, payload: Dict[str, object]) -> Path:
        path = self._raw_path(exchange, trade_date)
        ensure_directory(path.parent)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path

    def _load_cached(self, exchange: str, trade_date: date):
        path = self._raw_path(exchange, trade_date)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None

    def _load_cached_if_historical(self, exchange: str, trade_date: date):
        if trade_date >= now_shanghai().date():
            return None
        return self._load_cached(exchange, trade_date)

    def _raw_path(self, exchange: str, trade_date: date) -> Path:
        return RAW_DIR / exchange / "contracts_snapshot" / f"{compact_trade_date(trade_date)}.json"
