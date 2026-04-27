import csv
import json
import re
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from lxml import etree

from .config import PROJECT_ROOT, RAW_DIR
from .constants import FUTURES_RESULTS_DATASET, NO_DATA_STATUS, NOT_APPLICABLE_STATUS, PENDING_RETRY_STATUS, SUCCESS_STATUS
from .models import SourceRunResult
from .utils import compact_trade_date, ensure_directory, extract_digits_suffix, format_trade_date, iso_timestamp, normalize_number, normalize_text, parse_pipe_table, parse_trade_date, relative_to_project


DELIVERY_RECORD_ALIASES = {
    "contract": ["contract", "contractid", "合约", "合约代码", "instrumentid", "合约月份"],
    "delivery_month": ["delivery_month", "deliverymonth", "交割月份", "deliverymonth"],
    "expire_date": ["expire_date", "expiredate", "到期日", "最后交易日"],
    "final_settlement_price": ["final_settlement_price", "finalsettlementprice", "交割结算价", "finalsettlementprice"],
    "delivery_volume": ["delivery_volume", "deliveryvolume", "交割量", "交割手数"],
    "delivery_amount": ["delivery_amount", "deliveryamount", "交割金额"],
    "warehouse_delivery_quantity": ["warehouse_delivery_quantity", "warehousequantity", "仓单交割量", "仓单数量"],
    "result_status": ["result_status", "status", "状态"],
}


class FuturesDeliveryCollector:
    exchanges = ("SHFE", "INE", "CFFEX", "CZCE", "GFEX", "DCE")

    def __init__(self, settings: Dict[str, object], logger):
        self.settings = settings
        self.logger = logger
        self.timeout = int(settings.get("timeout_seconds", 30))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": str(settings.get("user_agent", "Mozilla/5.0"))})
        self._current_futures_rows: List[object] = []

    def collect(
        self,
        trade_date: date,
        futures_rows: Optional[List[object]] = None,
    ) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, object]]]:
        self._current_futures_rows = list(futures_rows or [])
        rows: List[Dict[str, str]] = []
        summaries: Dict[str, Dict[str, object]] = {}
        for exchange in self.exchanges:
            summary, parsed_rows = self._collect_exchange(exchange, trade_date)
            summaries[exchange] = summary
            rows.extend(parsed_rows)
        return rows, summaries

    def summarize_without_fetch(
        self,
        exchange: str,
        trade_date: date,
        *,
        futures_rows: Optional[List[object]] = None,
    ) -> Optional[Dict[str, object]]:
        if futures_rows is not None:
            self._current_futures_rows = list(futures_rows)
        exchange_settings = self.settings.get("exchanges", {}).get(exchange, {})
        if exchange == "INE" and not exchange_settings:
            exchange_settings = self.settings.get("exchanges", {}).get("SHFE", {})
        launch_date = self._launch_date(exchange)
        if launch_date and trade_date < launch_date:
            return self._summary(
                exchange,
                trade_date,
                NOT_APPLICABLE_STATUS,
                "",
                "official",
                0,
                f"{exchange} futures delivery results are not applicable before launch date {launch_date.isoformat()}.",
            )
        if not self._has_exchange_futures_rows(exchange):
            return None
        if not self._load_exchange_expiring_contracts(exchange, trade_date):
            return self._summary(
                exchange,
                trade_date,
                NO_DATA_STATUS,
                self._default_source_url(exchange, exchange_settings, trade_date),
                "official",
                0,
                f"No expiring {exchange} futures contracts found for this trade date.",
            )
        return None

    def _collect_exchange(self, exchange: str, trade_date: date) -> Tuple[Dict[str, object], List[Dict[str, str]]]:
        exchange_settings = self.settings.get("exchanges", {}).get(exchange, {})
        if exchange == "INE" and not exchange_settings:
            exchange_settings = self.settings.get("exchanges", {}).get("SHFE", {})
        launch_date = self._launch_date(exchange)
        if launch_date and trade_date < launch_date:
            return self._summary(
                exchange,
                trade_date,
                NOT_APPLICABLE_STATUS,
                "",
                "official",
                0,
                f"{exchange} futures delivery results are not applicable before launch date {launch_date.isoformat()}.",
            ), []
        local_summary = self.summarize_without_fetch(exchange, trade_date)
        if local_summary is not None:
            return local_summary, []
        if exchange in {"SHFE", "INE"}:
            return self._collect_shfe(exchange, exchange_settings, trade_date)
        if exchange == "GFEX":
            return self._collect_gfex(exchange_settings, trade_date)
        if exchange == "DCE":
            summary, rows = self._collect_dce_monthly_report(exchange_settings, trade_date)
            if summary is not None:
                return summary, rows
        template = str(exchange_settings.get("delivery_results_url", "")).strip()
        source_url = template or str(exchange_settings.get("referer") or exchange_settings.get("daily_url") or "")
        if not template:
            return self._summary(exchange, trade_date, NO_DATA_STATUS, source_url, "official", 0, "No official delivery result endpoint configured."), []

        url = template.format(
            trade_date=compact_trade_date(trade_date),
            year=trade_date.year,
            month=f"{trade_date.month:02d}",
            day=f"{trade_date.day:02d}",
            year_month=f"{trade_date.year}{trade_date.month:02d}",
        )
        try:
            response = self.session.get(url, timeout=self.timeout, headers={"Accept": "*/*", "User-Agent": self.session.headers["User-Agent"]})
            if response.status_code == 404:
                return self._summary(exchange, trade_date, NO_DATA_STATUS, url, "official", 0, "Official delivery result is not published for this trade date."), []
            response.raise_for_status()
        except requests.RequestException as exc:
            return self._summary(exchange, trade_date, PENDING_RETRY_STATUS, url, "official", 0, f"Official delivery result unavailable: {exc}"), []

        raw_text = response.text
        if not raw_text.strip():
            return self._summary(exchange, trade_date, PENDING_RETRY_STATUS, url, "official", 0, "Official delivery result returned empty content."), []

        extension = _infer_extension(raw_text, response.headers.get("Content-Type", ""))
        raw_path = self._write_raw(exchange, trade_date, raw_text, extension)
        rows = _parse_delivery_payload(
            exchange=exchange,
            raw_text=raw_text,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=url,
            source_type="official",
        )
        status = SUCCESS_STATUS if rows else NO_DATA_STATUS
        message = "" if rows else "Official delivery result contained no rows."
        return self._summary(exchange, trade_date, status, url, "official", len(rows), message, raw_path=raw_path), rows

    def _collect_shfe(self, exchange: str, exchange_settings: Dict[str, object], trade_date: date) -> Tuple[Dict[str, object], List[Dict[str, str]]]:
        daily_template = str(
            exchange_settings.get(
                "delivery_param_url",
                "https://www.shfe.com.cn/data/busiparamdata/future/Delivery{trade_date}.dat",
            )
        ).strip()
        monthly_template = str(
            exchange_settings.get(
                "monthly_delivery_results_url",
                "https://www.shfe.com.cn/data/tradedata/future/monthdata/ExchangeDelivery{year_month}.dat",
            )
        ).strip()
        daily_url = daily_template.format(
            trade_date=compact_trade_date(trade_date),
            year=trade_date.year,
            month=f"{trade_date.month:02d}",
            day=f"{trade_date.day:02d}",
            year_month=f"{trade_date.year}{trade_date.month:02d}",
        )
        monthly_url = monthly_template.format(
            trade_date=compact_trade_date(trade_date),
            year=trade_date.year,
            month=f"{trade_date.month:02d}",
            day=f"{trade_date.day:02d}",
            year_month=f"{trade_date.year}{trade_date.month:02d}",
        )
        headers = {"Accept": "application/json,text/plain,*/*", "User-Agent": self.session.headers["User-Agent"]}
        try:
            daily_response = self.session.get(daily_url, timeout=self.timeout, headers=headers)
            if daily_response.status_code == 404:
                return self._summary(exchange, trade_date, NO_DATA_STATUS, daily_url, "official", 0, f"{exchange} delivery parameter data is not published for this trade date."), []
            daily_response.raise_for_status()
            monthly_response = self.session.get(monthly_url, timeout=self.timeout, headers=headers)
            if monthly_response.status_code == 404:
                return self._summary(exchange, trade_date, NO_DATA_STATUS, monthly_url, "official", 0, f"{exchange} monthly delivery result is not published for this month."), []
            monthly_response.raise_for_status()
        except requests.RequestException as exc:
            return self._summary(exchange, trade_date, PENDING_RETRY_STATUS, monthly_url, "official", 0, f"{exchange} official delivery result unavailable: {exc}"), []

        daily_payload = daily_response.json()
        monthly_payload = monthly_response.json()
        rows = _build_shfe_delivery_rows(
            exchange=exchange,
            trade_date=trade_date,
            daily_payload=daily_payload,
            monthly_payload=monthly_payload,
            raw_path="",
            source_url=monthly_url,
            source_type="official",
        )
        raw_path = self._write_raw_json(
            "SHFE",
            trade_date,
            {
                "delivery_param_url": daily_url,
                "monthly_delivery_results_url": monthly_url,
                "delivery_params": daily_payload,
                "monthly_delivery_results": monthly_payload,
            },
        )
        relative_raw = relative_to_project(raw_path, PROJECT_ROOT)
        for row in rows:
            row["raw_path"] = relative_raw
        status = SUCCESS_STATUS if rows else NO_DATA_STATUS
        message = "" if rows else f"{exchange} official delivery result contained no rows for this trade date."
        return self._summary(exchange, trade_date, status, monthly_url, "official", len(rows), message, raw_path=raw_path), rows

    def _collect_gfex(self, exchange_settings: Dict[str, object], trade_date: date) -> Tuple[Dict[str, object], List[Dict[str, str]]]:
        endpoint = str(
            exchange_settings.get(
                "monthly_delivery_results_url",
                "http://www.gfex.com.cn/u/interfacesWebTcDeliveryQuotes/loadList",
            )
        ).strip()
        referer = str(
            exchange_settings.get(
                "delivery_results_referer",
                "http://www.gfex.com.cn/gfex/jgsj/jgtj_tjsj.shtml",
            )
        ).strip()
        payload = {
            "begin_month": f"{trade_date.year}{trade_date.month:02d}",
            "end_month": f"{trade_date.year}{trade_date.month:02d}",
            "variety": "",
        }
        headers = {
            "Accept": "application/json,text/javascript,*/*;q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": referer,
            "User-Agent": self.session.headers["User-Agent"],
        }
        try:
            response = self.session.post(endpoint, data=payload, timeout=self.timeout, headers=headers)
            if response.status_code == 404:
                return self._summary("GFEX", trade_date, NO_DATA_STATUS, endpoint, "official", 0, "GFEX monthly delivery result is not published for this month."), []
            response.raise_for_status()
        except requests.RequestException as exc:
            return self._summary("GFEX", trade_date, PENDING_RETRY_STATUS, endpoint, "official", 0, f"GFEX official delivery result unavailable: {exc}"), []

        response_payload = response.json()
        rows = _build_gfex_delivery_rows(
            trade_date=trade_date,
            payload=response_payload,
            raw_path="",
            source_url=endpoint,
            source_type="official",
        )
        raw_path = self._write_raw_json(
            "GFEX",
            trade_date,
            {
                "source_url": endpoint,
                "request_payload": payload,
                "response_payload": response_payload,
            },
        )
        relative_raw = relative_to_project(raw_path, PROJECT_ROOT)
        for row in rows:
            row["raw_path"] = relative_raw
        status = SUCCESS_STATUS if rows else NO_DATA_STATUS
        message = "" if rows else "GFEX official delivery result contained no rows for this trade date."
        return self._summary("GFEX", trade_date, status, endpoint, "official", len(rows), message, raw_path=raw_path), rows

    def _collect_dce_monthly_report(
        self,
        exchange_settings: Dict[str, object],
        trade_date: date,
    ) -> Tuple[Optional[Dict[str, object]], List[Dict[str, str]]]:
        expiring_contracts = self._load_dce_expiring_contracts(trade_date)
        if not expiring_contracts:
            return self._summary(
                "DCE",
                trade_date,
                NO_DATA_STATUS,
                "",
                "official",
                0,
                "No expiring DCE futures contracts found for this trade date.",
            ), []
        url = self._resolve_dce_monthly_report_url(exchange_settings, trade_date)
        if not url:
            return self._summary(
                "DCE",
                trade_date,
                PENDING_RETRY_STATUS,
                "",
                "official",
                0,
                "Official DCE monthly market report URL is not yet published for this month.",
            ), []
        try:
            response = self.session.get(
                url,
                timeout=self.timeout,
                headers={"Accept": "application/pdf,*/*", "User-Agent": self.session.headers["User-Agent"]},
            )
            if response.status_code == 404:
                return self._summary(
                    "DCE",
                    trade_date,
                    PENDING_RETRY_STATUS,
                    url,
                    "official",
                    0,
                    "Official DCE monthly market report is not yet published for this month.",
                ), []
            response.raise_for_status()
        except requests.RequestException as exc:
            return self._summary(
                "DCE",
                trade_date,
                PENDING_RETRY_STATUS,
                url,
                "official",
                0,
                f"Official DCE monthly market report unavailable: {exc}",
            ), []
        pdf_bytes = response.content
        if not pdf_bytes:
            return self._summary(
                "DCE",
                trade_date,
                PENDING_RETRY_STATUS,
                url,
                "official",
                0,
                "Official DCE monthly market report returned empty content.",
            ), []
        if _looks_like_html_document(pdf_bytes):
            raw_path = self._write_raw_bytes("dce", trade_date, pdf_bytes, "html")
            return self._summary(
                "DCE",
                trade_date,
                PENDING_RETRY_STATUS,
                url,
                "official",
                0,
                "Official DCE monthly market report returned an HTML error page instead of a PDF.",
                raw_path=raw_path,
            ), []
        raw_path = self._write_raw_bytes("dce", trade_date, pdf_bytes, "pdf")
        rows = _parse_dce_monthly_delivery_report(
            pdf_bytes=pdf_bytes,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=url,
            source_type="official",
            expiring_contracts=expiring_contracts,
            product_name_map=self.settings.get("product_name_map", {}).get("DCE", {}),
        )
        if rows:
            return self._summary("DCE", trade_date, SUCCESS_STATUS, url, "official", len(rows), "", raw_path=raw_path), rows
        return self._summary(
            "DCE",
            trade_date,
            PENDING_RETRY_STATUS,
            url,
            "official",
            0,
            "Official DCE monthly market report did not contain recognizable rows for expiring futures contracts.",
            raw_path=raw_path,
        ), []

    def _load_dce_expiring_contracts(self, trade_date: date) -> List[Dict[str, str]]:
        trade_date_str = format_trade_date(trade_date)
        contracts: List[Dict[str, str]] = []
        for row in self._current_futures_rows:
            exchange = normalize_text(getattr(row, "exchange", "") if not isinstance(row, dict) else row.get("exchange", "")).upper()
            if exchange != "DCE":
                continue
            expire_date = normalize_text(getattr(row, "delivery_month", "") if not isinstance(row, dict) else row.get("delivery_month", ""))
            maybe_dates = {
                normalize_text(getattr(row, "metadata", {}).get("expire_date", "") if not isinstance(row, dict) else (row.get("metadata", {}) or {}).get("expire_date", "")),
                normalize_text(getattr(row, "metadata", {}).get("last_trade_date", "") if not isinstance(row, dict) else (row.get("metadata", {}) or {}).get("last_trade_date", "")),
            }
            if trade_date_str not in maybe_dates:
                continue
            contract = normalize_text(getattr(row, "contract", "") if not isinstance(row, dict) else row.get("contract", "")).upper()
            product_code = normalize_text(getattr(row, "variety_code", "") if not isinstance(row, dict) else row.get("variety_code", "")).upper()
            if contract and product_code:
                contracts.append({"contract": contract, "product_code": product_code})
        return contracts

    def _resolve_dce_monthly_report_url(self, exchange_settings: Dict[str, object], trade_date: date) -> str:
        year_month = f"{trade_date.year}{trade_date.month:02d}"
        override_map = exchange_settings.get("monthly_market_report_overrides", {}) or {}
        override_url = normalize_text(override_map.get(year_month))
        if override_url:
            return override_url
        template = normalize_text(exchange_settings.get("monthly_market_report_url", ""))
        if not template:
            return ""
        return template.format(
            trade_date=compact_trade_date(trade_date),
            year=trade_date.year,
            month=f"{trade_date.month:02d}",
            day=f"{trade_date.day:02d}",
            year_month=year_month,
        )

    def _write_raw(self, exchange: str, trade_date: date, raw_text: str, extension: str) -> Path:
        target_dir = ensure_directory(RAW_DIR / exchange.lower() / FUTURES_RESULTS_DATASET)
        self._prune_stale_raw_variants(target_dir, compact_trade_date(trade_date), extension)
        path = target_dir / f"{compact_trade_date(trade_date)}.{extension}"
        path.write_text(raw_text, encoding="utf-8")
        return path

    def _write_raw_bytes(self, exchange: str, trade_date: date, raw_bytes: bytes, extension: str) -> Path:
        target_dir = ensure_directory(RAW_DIR / exchange.lower() / FUTURES_RESULTS_DATASET)
        self._prune_stale_raw_variants(target_dir, compact_trade_date(trade_date), extension)
        path = target_dir / f"{compact_trade_date(trade_date)}.{extension}"
        path.write_bytes(raw_bytes)
        return path

    def _write_raw_json(self, exchange: str, trade_date: date, payload: Dict[str, object]) -> Path:
        target_dir = ensure_directory(RAW_DIR / exchange.lower() / FUTURES_RESULTS_DATASET)
        self._prune_stale_raw_variants(target_dir, compact_trade_date(trade_date), "json")
        path = target_dir / f"{compact_trade_date(trade_date)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        return path

    @staticmethod
    def _prune_stale_raw_variants(target_dir: Path, stem: str, keep_extension: str) -> None:
        for candidate in target_dir.glob(f"{stem}.*"):
            if candidate.suffix.lstrip(".").lower() == keep_extension.lower():
                continue
            if candidate.is_file():
                candidate.unlink()

    def _summary(
        self,
        exchange: str,
        trade_date: date,
        status: str,
        source_url: str,
        source_type: str,
        row_count: int,
        message: str,
        *,
        raw_path: Optional[Path] = None,
    ) -> Dict[str, object]:
        return {
            "dataset": FUTURES_RESULTS_DATASET,
            "exchange": exchange,
            "trade_date": format_trade_date(trade_date),
            "status": status,
            "source_url": source_url,
            "source_type": source_type,
            "raw_path": str(raw_path) if raw_path else "",
            "row_count": row_count,
            "message": message,
            "error": "",
        }

    def _launch_date(self, exchange: str):
        metadata = self.settings.get("exchange_metadata", {}).get(exchange, {})
        value = metadata.get("futures_launch_date") or metadata.get("launch_date")
        if not value:
            return None
        return parse_trade_date(str(value))

    def _has_exchange_futures_rows(self, exchange: str) -> bool:
        normalized_exchange = normalize_text(exchange).upper()
        for row in self._current_futures_rows:
            row_exchange = normalize_text(
                getattr(row, "exchange", "") if not isinstance(row, dict) else row.get("exchange", "")
            ).upper()
            if row_exchange == normalized_exchange:
                return True
        return False

    def _load_exchange_expiring_contracts(self, exchange: str, trade_date: date) -> List[str]:
        if exchange == "DCE":
            return [item.get("contract", "") for item in self._load_dce_expiring_contracts(trade_date) if item.get("contract")]
        trade_date_str = format_trade_date(trade_date)
        contracts: List[str] = []
        normalized_exchange = normalize_text(exchange).upper()
        for row in self._current_futures_rows:
            row_exchange = normalize_text(
                getattr(row, "exchange", "") if not isinstance(row, dict) else row.get("exchange", "")
            ).upper()
            if row_exchange != normalized_exchange:
                continue
            metadata = getattr(row, "metadata", {}) if not isinstance(row, dict) else (row.get("metadata", {}) or {})
            maybe_dates = {
                normalize_text(getattr(row, "expire_date", "") if not isinstance(row, dict) else row.get("expire_date", "")),
                normalize_text(getattr(row, "last_trade_date", "") if not isinstance(row, dict) else row.get("last_trade_date", "")),
                normalize_text(metadata.get("expire_date", "")),
                normalize_text(metadata.get("last_trade_date", "")),
            }
            if trade_date_str not in maybe_dates:
                continue
            contract = normalize_text(getattr(row, "contract", "") if not isinstance(row, dict) else row.get("contract", "")).upper()
            if contract:
                contracts.append(contract)
        return contracts

    def _default_source_url(self, exchange: str, exchange_settings: Dict[str, object], trade_date: date) -> str:
        template = ""
        if exchange in {"SHFE", "INE"}:
            template = str(exchange_settings.get("monthly_delivery_results_url") or exchange_settings.get("delivery_param_url") or "")
        elif exchange == "GFEX":
            template = str(exchange_settings.get("monthly_delivery_results_url") or exchange_settings.get("delivery_results_referer") or "")
        else:
            template = str(
                exchange_settings.get("monthly_delivery_results_url")
                or exchange_settings.get("monthly_market_report_url")
                or exchange_settings.get("delivery_results_url")
                or exchange_settings.get("referer")
                or exchange_settings.get("daily_url")
                or ""
            )
        template = normalize_text(template)
        if not template:
            return ""
        return template.format(
            trade_date=compact_trade_date(trade_date),
            year=trade_date.year,
            month=f"{trade_date.month:02d}",
            day=f"{trade_date.day:02d}",
            year_month=f"{trade_date.year}{trade_date.month:02d}",
        )


def _infer_extension(raw_text: str, content_type: str) -> str:
    lowered_type = content_type.lower()
    stripped = raw_text.lstrip()
    if "xml" in lowered_type or stripped.startswith("<"):
        return "xml"
    if "json" in lowered_type or stripped.startswith("{") or stripped.startswith("["):
        return "json"
    if "|" in raw_text:
        return "txt"
    return "csv"


def _parse_delivery_payload(
    *,
    exchange: str,
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
) -> List[Dict[str, str]]:
    stripped = raw_text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _parse_json_delivery(exchange, raw_text, trade_date, raw_path, source_url, source_type)
    if stripped.startswith("<"):
        return _parse_xml_delivery(exchange, raw_text, trade_date, raw_path, source_url, source_type)
    if "|" in raw_text:
        return _normalize_delivery_rows(exchange, parse_pipe_table(raw_text), trade_date, raw_path, source_url, source_type)
    return _parse_csv_delivery(exchange, raw_text, trade_date, raw_path, source_url, source_type)


def _parse_json_delivery(exchange: str, raw_text: str, trade_date: date, raw_path: str, source_url: str, source_type: str) -> List[Dict[str, str]]:
    payload = json.loads(raw_text)
    if isinstance(payload, dict):
        for key in ("data", "result", "rows"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return _normalize_delivery_rows(exchange, candidate, trade_date, raw_path, source_url, source_type)
    if isinstance(payload, list):
        return _normalize_delivery_rows(exchange, payload, trade_date, raw_path, source_url, source_type)
    return []


def _parse_xml_delivery(exchange: str, raw_text: str, trade_date: date, raw_path: str, source_url: str, source_type: str) -> List[Dict[str, str]]:
    root = etree.fromstring(raw_text.encode("utf-8"))
    records: List[Dict[str, str]] = []
    for node in root.xpath("//*[local-name()='dailydata' or local-name()='row' or local-name()='record']"):
        record: Dict[str, str] = {}
        for child in node.iterchildren():
            record[child.tag.split("}")[-1]] = normalize_text(child.text)
        records.append(record)
    return _normalize_delivery_rows(exchange, records, trade_date, raw_path, source_url, source_type)


def _parse_csv_delivery(exchange: str, raw_text: str, trade_date: date, raw_path: str, source_url: str, source_type: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(raw_text.splitlines())
    return _normalize_delivery_rows(exchange, list(reader), trade_date, raw_path, source_url, source_type)


def _normalize_delivery_rows(
    exchange: str,
    records: List[Dict[str, object]],
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    retrieved_at = iso_timestamp()
    for record in records:
        normalized_record = {str(key).lower(): normalize_text(value) for key, value in record.items()}
        contract = _pick_field(normalized_record, "contract")
        if not contract or any(marker in contract for marker in ("小计", "合计", "总计")):
            continue
        delivery_month = _pick_field(normalized_record, "delivery_month") or extract_digits_suffix(contract)
        rows.append(
            {
                "trade_date": format_trade_date(trade_date),
                "exchange": exchange,
                "contract": contract.upper(),
                "delivery_month": delivery_month,
                "expire_date": _pick_field(normalized_record, "expire_date"),
                "final_settlement_price": normalize_number(_pick_field(normalized_record, "final_settlement_price")),
                "delivery_volume": normalize_number(_pick_field(normalized_record, "delivery_volume")),
                "delivery_amount": normalize_number(_pick_field(normalized_record, "delivery_amount")),
                "warehouse_delivery_quantity": normalize_number(_pick_field(normalized_record, "warehouse_delivery_quantity")),
                "result_status": _pick_field(normalized_record, "result_status") or "reported",
                "source_url": source_url,
                "source_type": source_type,
                "retrieved_at": retrieved_at,
                "raw_path": raw_path,
            }
        )
    return rows


def _build_shfe_delivery_rows(
    *,
    exchange: str = "SHFE",
    trade_date: date,
    daily_payload: Dict[str, object],
    monthly_payload: Dict[str, object],
    raw_path: str,
    source_url: str,
    source_type: str,
) -> List[Dict[str, str]]:
    daily_records = _extract_json_records(daily_payload, ("Delivery", "data", "rows"))
    monthly_records = _extract_json_records(monthly_payload, ("ExchangeDelivery", "data", "rows"))
    daily_by_contract: Dict[str, Dict[str, str]] = {}
    for record in daily_records:
        contract = normalize_text(record.get("INSTRUMENTID") or record.get("contract")).upper()
        if contract:
            daily_by_contract[contract] = record

    rows: List[Dict[str, str]] = []
    retrieved_at = iso_timestamp()
    for record in monthly_records:
        if not _matches_trade_date(record.get("DELIVERYDAY"), trade_date):
            continue
        contract = normalize_text(record.get("INSTRUMENTID") or record.get("contract")).upper()
        if not contract:
            continue
        if _infer_shfe_delivery_exchange(contract) != exchange:
            continue
        daily_record = daily_by_contract.get(contract, {})
        rows.append(
            {
                "trade_date": format_trade_date(trade_date),
                "exchange": exchange,
                "contract": contract,
                "delivery_month": extract_digits_suffix(contract),
                "expire_date": _normalize_date_value(daily_record.get("ENDDELIVERYDATE")),
                "final_settlement_price": normalize_number(daily_record.get("DELIVERYPRICE")),
                "delivery_volume": normalize_number(record.get("DELIVERYVOLUME")),
                "delivery_amount": normalize_number(record.get("DELIVERYAMOUNT")),
                "warehouse_delivery_quantity": normalize_number(record.get("EXCHANGE_DELIVERYVOLUME")),
                "result_status": "reported",
                "source_url": source_url,
                "source_type": source_type,
                "retrieved_at": retrieved_at,
                "raw_path": raw_path,
            }
        )
    return rows


INE_DELIVERY_PREFIXES = {"SC", "LU", "NR", "BC", "EC"}


def _infer_shfe_delivery_exchange(contract: str) -> str:
    upper_contract = normalize_text(contract).upper()
    if not upper_contract:
        return "SHFE"
    prefix = re.sub(r"[0-9].*$", "", upper_contract)
    return "INE" if prefix in INE_DELIVERY_PREFIXES else "SHFE"


def _build_gfex_delivery_rows(
    *,
    trade_date: date,
    payload: Dict[str, object],
    raw_path: str,
    source_url: str,
    source_type: str,
) -> List[Dict[str, str]]:
    records = _extract_json_records(payload, ("data", "rows"))
    rows: List[Dict[str, str]] = []
    retrieved_at = iso_timestamp()
    for record in records:
        if not _matches_trade_date(record.get("deliveryDate"), trade_date):
            continue
        contract = normalize_text(record.get("contractId") or record.get("contract")).upper()
        if not contract:
            continue
        rows.append(
            {
                "trade_date": format_trade_date(trade_date),
                "exchange": "GFEX",
                "contract": contract,
                "delivery_month": extract_digits_suffix(contract),
                "expire_date": "",
                "final_settlement_price": normalize_number(record.get("deliveryPrice")),
                "delivery_volume": normalize_number(record.get("deliveryQty")),
                "delivery_amount": normalize_number(record.get("deliveryAmt")),
                "warehouse_delivery_quantity": "",
                "result_status": "reported",
                "source_url": source_url,
                "source_type": source_type,
                "retrieved_at": retrieved_at,
                "raw_path": raw_path,
            }
        )
    return rows


def _parse_dce_monthly_delivery_report(
    *,
    pdf_bytes: bytes,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
    expiring_contracts: List[Dict[str, str]],
    product_name_map: Dict[str, str],
) -> List[Dict[str, str]]:
    text = _extract_pdf_text(pdf_bytes)
    if not text.strip():
        return []
    start = text.find("DCE交割情况")
    if start == -1:
        start = text.find("交割情况")
    if start == -1:
        return []
    end = text.find("2、仓单信息", start)
    section = text[start:end] if end != -1 else text[start:]
    code_by_name = {normalize_text(name): code for code, name in product_name_map.items()}
    contracts_by_product: Dict[str, List[str]] = {}
    for item in expiring_contracts:
        contracts_by_product.setdefault(normalize_text(item.get("product_code")).upper(), []).append(
            normalize_text(item.get("contract")).upper()
        )
    rows: List[Dict[str, str]] = []
    current_product = ""
    retrieved_at = iso_timestamp()
    pattern = re.compile(
        r"^(?P<product>[\u4e00-\u9fffA-Za-z0-9（）()\-]*)\s*"
        r"(?P<delivery_volume>[\d,\-]+)\s+"
        r"(?P<delivery_amount>[\d.\-]+)\s+"
        r"(?P<year_volume>[\d,]+)\s+"
        r"(?P<year_amount>[\d.]+)\s+"
        r"(?P<delivery_type>.+)$"
    )
    for raw_line in section.splitlines():
        line = normalize_text(raw_line)
        if not line or any(marker in line for marker in ("单位：", "交割方式", "总计", "第13页", "品种")):
            continue
        compact_line = re.sub(r"\s+", " ", line)
        match = pattern.match(compact_line)
        if not match:
            continue
        product_label = normalize_text(match.group("product")).rstrip("-") or current_product
        if not product_label:
            continue
        current_product = product_label
        product_code = code_by_name.get(product_label)
        if not product_code:
            continue
        contracts = contracts_by_product.get(product_code.upper(), [])
        if not contracts:
            continue
        delivery_volume = normalize_number(match.group("delivery_volume"))
        delivery_amount = normalize_number(match.group("delivery_amount"))
        if not delivery_volume or delivery_volume in {"0", "0.0", "0.00"}:
            continue
        for contract in contracts:
            rows.append(
                {
                    "trade_date": format_trade_date(trade_date),
                    "exchange": "DCE",
                    "contract": contract,
                    "delivery_month": extract_digits_suffix(contract),
                    "expire_date": format_trade_date(trade_date),
                    "final_settlement_price": "",
                    "delivery_volume": delivery_volume,
                    "delivery_amount": delivery_amount,
                    "warehouse_delivery_quantity": "",
                    "result_status": normalize_text(match.group("delivery_type")) or "reported_product_aggregate",
                    "source_url": source_url,
                    "source_type": source_type,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                }
            )
    return rows


def _extract_json_records(payload: object, list_keys: Tuple[str, ...]) -> List[Dict[str, object]]:
    if isinstance(payload, list):
        return [record for record in payload if isinstance(record, dict)]
    if isinstance(payload, dict):
        for key in list_keys:
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return [record for record in candidate if isinstance(record, dict)]
    return []


def _matches_trade_date(value: object, trade_date: date) -> bool:
    normalized = _normalize_date_value(value)
    return bool(normalized) and normalized == format_trade_date(trade_date)


def _normalize_date_value(value: object) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) >= 8:
        digits = digits[:8]
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return ""


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        from PyPDF2 import PdfReader
    except Exception:
        return ""
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
    except Exception:
        return ""
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _looks_like_html_document(content: bytes) -> bool:
    prefix = content[:512].lstrip().lower()
    if prefix.startswith(b"<!doctype html") or prefix.startswith(b"<html"):
        return True
    try:
        decoded = prefix.decode("latin1", errors="ignore")
    except Exception:
        return False
    return "<html" in decoded or "doctype html" in decoded


def _pick_field(record: Dict[str, str], logical_name: str) -> str:
    for key in DELIVERY_RECORD_ALIASES[logical_name]:
        value = record.get(key.lower(), "")
        if value:
            return value
    return ""
