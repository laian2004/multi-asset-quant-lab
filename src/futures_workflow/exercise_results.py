import csv
import json
import re
from datetime import date
from io import BytesIO
from pathlib import Path
from urllib.parse import urlencode
from typing import Dict, List, Optional, Tuple

import requests
from lxml import etree

from .config import PROJECT_ROOT, RAW_DIR
from .constants import NO_DATA_STATUS, NOT_APPLICABLE_STATUS, OPTION_RESULTS_DATASET, PENDING_RETRY_STATUS, SUCCESS_STATUS
from .parsers.options_cffex import parse_cffex_option_daily_quotes
from .utils import compact_trade_date, ensure_directory, format_trade_date, iso_timestamp, normalize_number, normalize_text, parse_pipe_table, relative_to_project
from .utils import parse_trade_date


SSE_OPTION_EXERCISE_URL = "https://query.sse.com.cn/commonQuery.do"
SSE_OPTION_EXERCISE_SQL_ID = "SSE_ZQPZ_YSP_GGQQZSXT_TJSJ_XQJGXX_SEARCH_L"
SZSE_OPTION_EXERCISE_URL = "https://www.szse.cn/api/report/ShowReport/data"
SZSE_OPTION_EXERCISE_CATALOG_ID = "option_jstj"


EXERCISE_RECORD_ALIASES = {
    "contract": ["contract", "contractid", "合约", "合约代码", "instrumentid"],
    "underlying_contract": ["underlying_contract", "underlyingcontract", "标的合约", "underlying"],
    "option_type": ["option_type", "optiontype", "期权类型"],
    "strike_price": ["strike_price", "strikeprice", "行权价"],
    "expire_date": ["expire_date", "expiredate", "到期日", "最后交易日"],
    "exercise_volume": ["exercise_volume", "exercisevolume", "行权量"],
    "assignment_volume": ["assignment_volume", "assignmentvolume", "配对量", "履约量"],
    "cash_settlement_amount": ["cash_settlement_amount", "cashsettlementamount", "现金结算金额"],
    "delivery_quantity": ["delivery_quantity", "deliveryquantity", "交割数量", "实物交割量"],
    "result_status": ["result_status", "status", "状态"],
}


class OptionExerciseCollector:
    exchanges = ("SHFE", "CFFEX", "CZCE", "GFEX", "DCE", "SSE", "SZSE")

    def __init__(self, settings: Dict[str, object], logger):
        self.settings = settings
        self.logger = logger
        self.timeout = int(settings.get("timeout_seconds", 30))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": str(settings.get("user_agent", "Mozilla/5.0"))})
        self._current_option_rows: List[object] = []

    def collect(
        self,
        trade_date: date,
        option_rows: Optional[List[object]] = None,
    ) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, object]]]:
        self._current_option_rows = list(option_rows or [])
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
        option_rows: Optional[List[object]] = None,
    ) -> Optional[Dict[str, object]]:
        if option_rows is not None:
            self._current_option_rows = list(option_rows)
        exchange_settings = self.settings.get("exchanges", {}).get(exchange, {})
        launch_date = self._launch_date(exchange)
        if launch_date and trade_date < launch_date:
            return self._summary(
                exchange,
                trade_date,
                NOT_APPLICABLE_STATUS,
                "",
                "official",
                0,
                f"{exchange} option exercise results are not applicable before launch date {launch_date.isoformat()}.",
            )
        if not self._has_exchange_option_rows(exchange):
            return None
        if not self._load_exchange_expiring_contracts(exchange, trade_date):
            return self._summary(
                exchange,
                trade_date,
                NO_DATA_STATUS,
                self._default_source_url(exchange, exchange_settings, trade_date),
                "official",
                0,
                f"No expiring {exchange} option contracts found for this trade date.",
            )
        return None

    def _collect_exchange(self, exchange: str, trade_date: date) -> Tuple[Dict[str, object], List[Dict[str, str]]]:
        exchange_settings = self.settings.get("exchanges", {}).get(exchange, {})
        launch_date = self._launch_date(exchange)
        if launch_date and trade_date < launch_date:
            return self._summary(
                exchange,
                trade_date,
                NOT_APPLICABLE_STATUS,
                "",
                "official",
                0,
                f"{exchange} option exercise results are not applicable before launch date {launch_date.isoformat()}.",
            ), []
        local_summary = self.summarize_without_fetch(exchange, trade_date)
        if local_summary is not None:
            return local_summary, []
        if exchange == "CFFEX":
            summary, rows = self._collect_cffex_monthly_report(exchange_settings, trade_date)
            if summary is not None:
                return summary, rows
        if exchange == "DCE":
            summary, rows = self._collect_dce_monthly_report(exchange_settings, trade_date)
            if summary is not None:
                return summary, rows
        if exchange == "SSE":
            summary, rows = self._collect_sse_official_summary(trade_date)
            if summary is not None:
                return summary, rows
        if exchange == "SZSE":
            summary, rows = self._collect_szse_official_summary(trade_date)
            if summary is not None:
                return summary, rows
        template = str(exchange_settings.get("exercise_results_url", "")).strip()
        source_url = template or str(exchange_settings.get("referer") or exchange_settings.get("daily_url") or "")
        if not template:
            return self._summary(exchange, trade_date, NO_DATA_STATUS, source_url, "official", 0, "No official exercise result endpoint configured."), []

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
                return self._summary(exchange, trade_date, NO_DATA_STATUS, url, "official", 0, "Official exercise result is not published for this trade date."), []
            response.raise_for_status()
        except requests.RequestException as exc:
            return self._summary(exchange, trade_date, PENDING_RETRY_STATUS, url, "official", 0, f"Official exercise result unavailable: {exc}"), []

        raw_text = response.text
        if not raw_text.strip():
            return self._summary(exchange, trade_date, PENDING_RETRY_STATUS, url, "official", 0, "Official exercise result returned empty content."), []

        extension = _infer_extension(raw_text, response.headers.get("Content-Type", ""))
        raw_path = self._write_raw(exchange, trade_date, raw_text, extension, source_url=url, source_type="official")
        rows = _parse_exercise_payload(
            exchange=exchange,
            raw_text=raw_text,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=url,
            source_type="official",
        )
        status = SUCCESS_STATUS if rows else NO_DATA_STATUS
        message = "" if rows else "Official exercise result contained no rows."
        return self._summary(exchange, trade_date, status, url, "official", len(rows), message, raw_path=raw_path), rows

    def _collect_cffex_monthly_report(
        self,
        exchange_settings: Dict[str, object],
        trade_date: date,
    ) -> Tuple[Optional[Dict[str, object]], List[Dict[str, str]]]:
        template = str(exchange_settings.get("monthly_exercise_report_url", "")).strip()
        if not template:
            return None, []
        expiring_products = self._load_cffex_expiring_products(trade_date)
        if not expiring_products:
            return self._summary(
                "CFFEX",
                trade_date,
                NO_DATA_STATUS,
                template,
                "official",
                0,
                "No expiring CFFEX option products found for this trade date.",
            ), []
        url = template.format(
            trade_date=compact_trade_date(trade_date),
            year=trade_date.year,
            month=f"{trade_date.month:02d}",
            day=f"{trade_date.day:02d}",
            year_month=f"{trade_date.year}{trade_date.month:02d}",
        )
        try:
            response = self.session.get(url, timeout=self.timeout, headers={"Accept": "application/pdf,*/*", "User-Agent": self.session.headers["User-Agent"]})
            if response.status_code == 404:
                return self._summary(
                    "CFFEX",
                    trade_date,
                    PENDING_RETRY_STATUS,
                    url,
                    "official",
                    0,
                    "Official CFFEX monthly exercise report is not yet published for this trade date.",
                ), []
            response.raise_for_status()
        except requests.RequestException as exc:
            return self._summary(
                "CFFEX",
                trade_date,
                PENDING_RETRY_STATUS,
                url,
                "official",
                0,
                f"Official CFFEX monthly exercise report unavailable: {exc}",
            ), []
        pdf_bytes = response.content
        if not pdf_bytes:
            return self._summary(
                "CFFEX",
                trade_date,
                PENDING_RETRY_STATUS,
                url,
                "official",
                0,
                "Official CFFEX monthly exercise report returned empty content.",
            ), []
        if _looks_like_html_document(pdf_bytes):
            raw_path = self._write_raw_bytes(
                "cffex",
                OPTION_RESULTS_DATASET,
                trade_date,
                pdf_bytes,
                "html",
                source_url=url,
                source_type="official",
            )
            return self._summary(
                "CFFEX",
                trade_date,
                PENDING_RETRY_STATUS,
                url,
                "official",
                0,
                "Official CFFEX monthly exercise report returned an HTML error page instead of a PDF.",
                raw_path=raw_path,
            ), []
        raw_path = self._write_raw_bytes("cffex", OPTION_RESULTS_DATASET, trade_date, pdf_bytes, "pdf", source_url=url, source_type="official")
        report_rows = _parse_cffex_monthly_exercise_report(
            pdf_bytes=pdf_bytes,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=url,
            source_type="official",
            expiring_products=expiring_products,
        )
        if report_rows:
            return self._summary("CFFEX", trade_date, SUCCESS_STATUS, url, "official", len(report_rows), "", raw_path=raw_path), report_rows
        return self._summary(
            "CFFEX",
            trade_date,
            PENDING_RETRY_STATUS,
            url,
            "official",
            0,
            "Official CFFEX monthly exercise report did not contain recognizable rows for expiring products.",
            raw_path=raw_path,
        ), []

    def _collect_sse_official_summary(self, trade_date: date) -> Tuple[Optional[Dict[str, object]], List[Dict[str, str]]]:
        params = {
            "isPagination": "false",
            "sqlId": SSE_OPTION_EXERCISE_SQL_ID,
            "tradeDate": compact_trade_date(trade_date),
        }
        url = f"{SSE_OPTION_EXERCISE_URL}?{urlencode(params)}"
        headers = {
            "Accept": "application/json,*/*",
            "Host": "query.sse.com.cn",
            "Referer": "https://www.sse.com.cn/",
            "User-Agent": self.session.headers["User-Agent"],
        }
        try:
            response = self.session.get(SSE_OPTION_EXERCISE_URL, params=params, timeout=self.timeout, headers=headers)
            if response.status_code == 404:
                return self._summary(
                    "SSE",
                    trade_date,
                    NO_DATA_STATUS,
                    url,
                    "official",
                    0,
                    "SSE official option exercise settlement summary is not published for this trade date.",
                ), []
            response.raise_for_status()
        except requests.RequestException as exc:
            return self._summary(
                "SSE",
                trade_date,
                PENDING_RETRY_STATUS,
                url,
                "official",
                0,
                f"SSE official option exercise settlement summary unavailable: {exc}",
            ), []

        try:
            payload = response.json()
        except ValueError as exc:
            return self._summary(
                "SSE",
                trade_date,
                PENDING_RETRY_STATUS,
                url,
                "official",
                0,
                f"SSE official option exercise settlement summary returned invalid JSON: {exc}",
            ), []

        raw_path = self._write_raw_json(
            "sse",
            OPTION_RESULTS_DATASET,
            trade_date,
            {
                "source_url": url,
                "request_params": params,
                "response_payload": payload,
            },
            source_url=url,
            source_type="official",
        )
        rows = _parse_exercise_payload(
            exchange="SSE",
            raw_text=json.dumps(payload, ensure_ascii=False),
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=url,
            source_type="official",
        )
        status = SUCCESS_STATUS if rows else NO_DATA_STATUS
        message = "" if rows else "SSE official option exercise settlement summary contained no rows."
        return self._summary("SSE", trade_date, status, url, "official", len(rows), message, raw_path=raw_path), rows

    def _collect_szse_official_summary(self, trade_date: date) -> Tuple[Optional[Dict[str, object]], List[Dict[str, str]]]:
        params = {
            "SHOWTYPE": "JSON",
            "CATALOGID": SZSE_OPTION_EXERCISE_CATALOG_ID,
            "TABKEY": "tab1",
            "txtKsrq": format_trade_date(trade_date),
            "txtZzrq": format_trade_date(trade_date),
            "tab1PAGENO": "1",
        }
        url = f"{SZSE_OPTION_EXERCISE_URL}?{urlencode(params)}"
        headers = {
            "Accept": "application/json,*/*",
            "Referer": "https://www.szse.cn/option/quotation/statistical/traffic/index.html",
            "User-Agent": self.session.headers["User-Agent"],
        }
        try:
            response = self.session.get(SZSE_OPTION_EXERCISE_URL, params=params, timeout=self.timeout, headers=headers)
            if response.status_code == 404:
                return self._summary(
                    "SZSE",
                    trade_date,
                    NO_DATA_STATUS,
                    url,
                    "official",
                    0,
                    "SZSE official option exercise settlement summary is not published for this trade date.",
                ), []
            response.raise_for_status()
        except requests.RequestException as exc:
            return self._summary(
                "SZSE",
                trade_date,
                PENDING_RETRY_STATUS,
                url,
                "official",
                0,
                f"SZSE official option exercise settlement summary unavailable: {exc}",
            ), []
        try:
            payload = response.json()
        except ValueError as exc:
            return self._summary(
                "SZSE",
                trade_date,
                PENDING_RETRY_STATUS,
                url,
                "official",
                0,
                f"SZSE official option exercise settlement summary returned invalid JSON: {exc}",
            ), []
        records: List[Dict[str, object]] = []
        if isinstance(payload, list) and payload:
            root = payload[0] if isinstance(payload[0], dict) else {}
            records.extend(root.get("data", []) or [])
            metadata = root.get("metadata", {}) or {}
            page_count = int(metadata.get("pagecount") or 0)
            for page_no in range(2, page_count + 1):
                page_params = dict(params)
                page_params["tab1PAGENO"] = str(page_no)
                page_response = self.session.get(SZSE_OPTION_EXERCISE_URL, params=page_params, timeout=self.timeout, headers=headers)
                page_response.raise_for_status()
                page_payload = page_response.json()
                if isinstance(page_payload, list) and page_payload and isinstance(page_payload[0], dict):
                    records.extend(page_payload[0].get("data", []) or [])
        raw_path = self._write_raw_json(
            "szse",
            OPTION_RESULTS_DATASET,
            trade_date,
            {
                "source_url": url,
                "request_params": params,
                "response_payload": payload,
            },
            source_url=url,
            source_type="official",
        )
        rows = _parse_szse_official_exercise_rows(
            records=records,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=url,
            source_type="official",
        )
        status = SUCCESS_STATUS if rows else NO_DATA_STATUS
        message = "" if rows else "SZSE official option exercise settlement summary contained no rows."
        return self._summary("SZSE", trade_date, status, url, "official", len(rows), message, raw_path=raw_path), rows

    def _collect_dce_monthly_report(
        self,
        exchange_settings: Dict[str, object],
        trade_date: date,
    ) -> Tuple[Optional[Dict[str, object]], List[Dict[str, str]]]:
        expiring_series = self._load_dce_expiring_series(trade_date)
        if not expiring_series:
            return self._summary(
                "DCE",
                trade_date,
                NO_DATA_STATUS,
                "",
                "official",
                0,
                "No expiring DCE option series found for this trade date.",
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
            raw_path = self._write_raw_bytes(
                "dce",
                OPTION_RESULTS_DATASET,
                trade_date,
                pdf_bytes,
                "html",
                source_url=url,
                source_type="official",
            )
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
        raw_path = self._write_raw_bytes(
            "dce",
            OPTION_RESULTS_DATASET,
            trade_date,
            pdf_bytes,
            "pdf",
            source_url=url,
            source_type="official",
        )
        rows = _parse_dce_monthly_exercise_report(
            pdf_bytes=pdf_bytes,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=url,
            source_type="official",
            expiring_series=expiring_series,
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
            "Official DCE monthly market report did not contain recognizable rows for expiring option series.",
            raw_path=raw_path,
        ), []

    def _load_cffex_expiring_products(self, trade_date: date) -> List[str]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = RAW_DIR / "cffex" / "options_daily_quotes" / f"{compact_trade_date(trade_date)}.xml"
        if not raw_path.exists():
            exchange_settings = self.settings.get("exchanges", {}).get("CFFEX", {})
            daily_url = str(exchange_settings.get("daily_url", "")).strip()
            if not daily_url:
                return []
            url = daily_url.format(
                trade_date=compact_trade_date(trade_date),
                year=trade_date.year,
                month=f"{trade_date.month:02d}",
                day=f"{trade_date.day:02d}",
                year_month=f"{trade_date.year}{trade_date.month:02d}",
            )
            try:
                response = self.session.get(url, timeout=self.timeout, headers={"Accept": "application/xml,text/xml,*/*", "User-Agent": self.session.headers["User-Agent"]})
                response.raise_for_status()
            except requests.RequestException:
                return []
            raw_text = response.text
        else:
            raw_text = raw_path.read_text(encoding="utf-8")
        try:
            option_rows = parse_cffex_option_daily_quotes(
                raw_text=raw_text,
                trade_date=trade_date,
                raw_path=relative_to_project(raw_path, PROJECT_ROOT),
                source_url="",
                source_type="official",
                product_name_map=self.settings.get("option_product_name_map", {}).get("CFFEX", {}),
            )
        except Exception:
            return []
        expiring_products = sorted(
            {
                row.product_code
                for row in option_rows
                if (row.expire_date or row.last_trade_date) == trade_date_str and row.product_code
            }
        )
        return expiring_products

    def _load_dce_expiring_series(self, trade_date: date) -> List[str]:
        trade_date_str = format_trade_date(trade_date)
        series = {
            normalize_text(
                getattr(row, "underlying_contract", "")
                if not isinstance(row, dict)
                else row.get("underlying_contract", "")
            ).lower()
            for row in self._current_option_rows
            if normalize_text(
                getattr(row, "exchange", "")
                if not isinstance(row, dict)
                else row.get("exchange", "")
            ).upper()
            == "DCE"
            and trade_date_str
            in {
                normalize_text(getattr(row, "expire_date", "") if not isinstance(row, dict) else row.get("expire_date", "")),
                normalize_text(
                    getattr(row, "last_trade_date", "") if not isinstance(row, dict) else row.get("last_trade_date", "")
                ),
            }
        }
        return sorted(item for item in series if item)

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

    def _write_raw(self, exchange: str, trade_date: date, raw_text: str, extension: str, *, source_url: str, source_type: str) -> Path:
        target_dir = ensure_directory(RAW_DIR / exchange.lower() / OPTION_RESULTS_DATASET)
        self._prune_stale_raw_variants(target_dir, compact_trade_date(trade_date), extension)
        path = target_dir / f"{compact_trade_date(trade_date)}.{extension}"
        path.write_text(raw_text, encoding="utf-8")
        self._write_raw_meta(path, source_url=source_url, source_type=source_type, extension=extension)
        return path

    def _write_raw_bytes(self, exchange: str, dataset: str, trade_date: date, raw_bytes: bytes, extension: str, *, source_url: str, source_type: str) -> Path:
        target_dir = ensure_directory(RAW_DIR / exchange.lower() / dataset)
        self._prune_stale_raw_variants(target_dir, compact_trade_date(trade_date), extension)
        path = target_dir / f"{compact_trade_date(trade_date)}.{extension}"
        path.write_bytes(raw_bytes)
        self._write_raw_meta(path, source_url=source_url, source_type=source_type, extension=extension)
        return path

    def _write_raw_json(self, exchange: str, dataset: str, trade_date: date, payload: Dict[str, object], *, source_url: str, source_type: str) -> Path:
        target_dir = ensure_directory(RAW_DIR / exchange.lower() / dataset)
        self._prune_stale_raw_variants(target_dir, compact_trade_date(trade_date), "json")
        path = target_dir / f"{compact_trade_date(trade_date)}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        self._write_raw_meta(path, source_url=source_url, source_type=source_type, extension="json")
        return path

    def _write_raw_meta(self, raw_path: Path, *, source_url: str, source_type: str, extension: str) -> None:
        meta_path = raw_path.with_name(f"{raw_path.stem}.meta.json")
        meta_path.write_text(
            json.dumps(
                {
                    "source_url": source_url,
                    "source_type": source_type,
                    "extension": extension,
                    "meta": {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @staticmethod
    def _prune_stale_raw_variants(target_dir: Path, stem: str, keep_extension: str) -> None:
        for candidate in target_dir.glob(f"{stem}.*"):
            if candidate.name == f"{stem}.meta.json":
                continue
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
            "dataset": OPTION_RESULTS_DATASET,
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
        value = metadata.get("options_launch_date") or metadata.get("launch_date")
        if not value:
            return None
        return parse_trade_date(str(value))

    def _has_exchange_option_rows(self, exchange: str) -> bool:
        normalized_exchange = normalize_text(exchange).upper()
        for row in self._current_option_rows:
            row_exchange = normalize_text(
                getattr(row, "exchange", "") if not isinstance(row, dict) else row.get("exchange", "")
            ).upper()
            if row_exchange == normalized_exchange:
                return True
        return False

    def _load_exchange_expiring_contracts(self, exchange: str, trade_date: date) -> List[str]:
        if exchange == "CFFEX":
            return self._load_cffex_expiring_products(trade_date)
        if exchange == "DCE":
            return self._load_dce_expiring_series(trade_date)
        trade_date_str = format_trade_date(trade_date)
        contracts: List[str] = []
        normalized_exchange = normalize_text(exchange).upper()
        for row in self._current_option_rows:
            row_exchange = normalize_text(
                getattr(row, "exchange", "") if not isinstance(row, dict) else row.get("exchange", "")
            ).upper()
            if row_exchange != normalized_exchange:
                continue
            maybe_dates = {
                normalize_text(getattr(row, "expire_date", "") if not isinstance(row, dict) else row.get("expire_date", "")),
                normalize_text(getattr(row, "last_trade_date", "") if not isinstance(row, dict) else row.get("last_trade_date", "")),
            }
            if trade_date_str not in maybe_dates:
                continue
            contract = normalize_text(getattr(row, "contract", "") if not isinstance(row, dict) else row.get("contract", "")).upper()
            if contract:
                contracts.append(contract)
        return contracts

    def _default_source_url(self, exchange: str, exchange_settings: Dict[str, object], trade_date: date) -> str:
        if exchange == "SSE":
            params = {
                "isPagination": "false",
                "sqlId": SSE_OPTION_EXERCISE_SQL_ID,
                "tradeDate": compact_trade_date(trade_date),
            }
            return f"{SSE_OPTION_EXERCISE_URL}?{urlencode(params)}"
        if exchange == "SZSE":
            params = {
                "SHOWTYPE": "JSON",
                "CATALOGID": SZSE_OPTION_EXERCISE_CATALOG_ID,
                "TABKEY": "tab1",
                "txtKsrq": format_trade_date(trade_date),
                "txtZzrq": format_trade_date(trade_date),
                "tab1PAGENO": "1",
            }
            return f"{SZSE_OPTION_EXERCISE_URL}?{urlencode(params)}"
        template = normalize_text(
            exchange_settings.get("monthly_exercise_report_url")
            or exchange_settings.get("monthly_market_report_url")
            or exchange_settings.get("exercise_results_url")
            or exchange_settings.get("referer")
            or exchange_settings.get("daily_url")
            or ""
        )
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


def _parse_cffex_monthly_exercise_report(
    *,
    pdf_bytes: bytes,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
    expiring_products: List[str],
) -> List[Dict[str, str]]:
    text = _extract_pdf_text(pdf_bytes)
    if not text.strip():
        return []
    start = text.find("期权各产品行权数据统计")
    if start == -1:
        return []
    section = text[start:]
    note_index = section.find("注：")
    if note_index != -1:
        section = section[:note_index]
    matches = re.findall(r"\b([A-Z]{2})\s+(\d+)\s+(\d+)\s+(\d+)\s+\d+\s+\d+\s+\d+\b", section)
    allowed = set(expiring_products)
    filter_products = bool(allowed)
    rows: List[Dict[str, str]] = []
    for product_code, _, unexercised, exercise_volume in matches:
        if filter_products and product_code not in allowed:
            continue
        rows.append(
            {
                "trade_date": format_trade_date(trade_date),
                "exchange": "CFFEX",
                "contract": product_code,
                "underlying_contract": "",
                "option_type": "",
                "strike_price": "",
                "expire_date": format_trade_date(trade_date),
                "exercise_volume": normalize_number(exercise_volume),
                "assignment_volume": "",
                "cash_settlement_amount": "",
                "delivery_quantity": "",
                "result_status": "reported_product_aggregate",
                "source_url": source_url,
                "source_type": source_type,
                "retrieved_at": iso_timestamp(),
                "raw_path": raw_path,
            }
        )
        if filter_products:
            allowed.remove(product_code)
    return rows


def _parse_dce_monthly_exercise_report(
    *,
    pdf_bytes: bytes,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
    expiring_series: List[str],
) -> List[Dict[str, str]]:
    text = _extract_pdf_text(pdf_bytes)
    if not text.strip():
        return []
    start = text.rfind("DCE期权行权情况")
    if start == -1:
        start = text.rfind("期权行权情况")
    if start == -1:
        start = text.rfind("期权行权")
    if start == -1:
        return []
    end = text.find("二、实物交割", start)
    section = text[start:end] if end != -1 else text[start:]
    lines = [normalize_text(line) for line in section.splitlines()]
    allowed = {normalize_text(item).lower() for item in expiring_series if normalize_text(item)}
    rows: List[Dict[str, str]] = []
    current_product = ""
    retrieved_at = iso_timestamp()
    pattern = re.compile(
        r"^(?:(?P<product>[\u4e00-\u9fffA-Za-z0-9（）()]+?期权))?"
        r"(?P<series>[a-z]{1,2}\d{4})\s+"
        r"(?P<month_total>[\d,]+)\s+(?P<year_total>[\d,]+)\s+"
        r"(?P<call_month>[\d,]+)\s+[\d.]+%\s+"
        r"(?P<put_month>[\d,]+)\s+[\d.]+%\s+"
        r"(?P<call_year>[\d,]+)\s+[\d.]+%\s+"
        r"(?P<put_year>[\d,]+)\s+[\d.]+%$"
    )
    for line in lines:
        if not line or any(marker in line for marker in ("单位：", "期权系列", "总计", "小计")):
            continue
        match = pattern.match(line)
        if not match:
            continue
        product_label = normalize_text(match.group("product"))
        if product_label:
            current_product = product_label
        series = normalize_text(match.group("series")).lower()
        if allowed and series not in allowed:
            continue
        base_contract = series.upper()
        aggregates = (
            ("call", match.group("call_month"), "CALL"),
            ("put", match.group("put_month"), "PUT"),
        )
        for option_type, volume, suffix in aggregates:
            normalized_volume = normalize_number(volume)
            if not normalized_volume or normalized_volume in {"0", "0.0", "0.00"}:
                continue
            rows.append(
                {
                    "trade_date": format_trade_date(trade_date),
                    "exchange": "DCE",
                    "contract": f"{base_contract}-{suffix}-AGG",
                    "underlying_contract": base_contract,
                    "option_type": option_type,
                    "strike_price": "",
                    "expire_date": format_trade_date(trade_date),
                    "exercise_volume": normalized_volume,
                    "assignment_volume": "",
                    "cash_settlement_amount": "",
                    "delivery_quantity": "",
                    "result_status": "reported_series_aggregate",
                    "source_url": source_url,
                    "source_type": source_type,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                }
            )
            if current_product:
                rows[-1]["underlying_contract"] = base_contract
    return rows


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


def _parse_exercise_payload(
    *,
    exchange: str,
    raw_text: str,
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
) -> List[Dict[str, str]]:
    if exchange == "CFFEX" and raw_path.endswith(".pdf"):
        return _parse_cffex_monthly_exercise_report(
            pdf_bytes=raw_text.encode("latin1"),
            trade_date=trade_date,
            raw_path=raw_path,
            source_url=source_url,
            source_type=source_type,
            expiring_products=[],
        )
    stripped = raw_text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return _parse_json_exercise(exchange, raw_text, trade_date, raw_path, source_url, source_type)
    if stripped.startswith("<"):
        return _parse_xml_exercise(exchange, raw_text, trade_date, raw_path, source_url, source_type)
    if "|" in raw_text:
        return _normalize_exercise_rows(exchange, parse_pipe_table(raw_text), trade_date, raw_path, source_url, source_type)
    return _parse_csv_exercise(exchange, raw_text, trade_date, raw_path, source_url, source_type)


def _parse_json_exercise(exchange: str, raw_text: str, trade_date: date, raw_path: str, source_url: str, source_type: str) -> List[Dict[str, str]]:
    payload = json.loads(raw_text)
    if exchange == "SSE":
        if isinstance(payload, dict):
            if isinstance(payload.get("response_payload"), dict):
                return _parse_sse_official_exercise_rows(
                    payload.get("response_payload", {}).get("result", []),
                    trade_date,
                    raw_path,
                    source_url,
                    source_type,
                )
            if isinstance(payload.get("result"), list):
                return _parse_sse_official_exercise_rows(payload.get("result", []), trade_date, raw_path, source_url, source_type)
        if isinstance(payload, list):
            return _parse_sse_official_exercise_rows(payload, trade_date, raw_path, source_url, source_type)
    if isinstance(payload, dict):
        for key in ("data", "result", "rows"):
            candidate = payload.get(key)
            if isinstance(candidate, list):
                return _normalize_exercise_rows(exchange, candidate, trade_date, raw_path, source_url, source_type)
    if isinstance(payload, list):
        return _normalize_exercise_rows(exchange, payload, trade_date, raw_path, source_url, source_type)
    return []


def _parse_xml_exercise(exchange: str, raw_text: str, trade_date: date, raw_path: str, source_url: str, source_type: str) -> List[Dict[str, str]]:
    cleaned_text = raw_text.replace("&nbsp;", " ").replace("&NBSP;", " ")
    root = etree.fromstring(cleaned_text.encode("utf-8"))
    records: List[Dict[str, str]] = []
    for node in root.xpath("//*[local-name()='dailydata' or local-name()='row' or local-name()='record']"):
        record: Dict[str, str] = {}
        for child in node.iterchildren():
            record[child.tag.split('}')[-1]] = normalize_text(child.text)
        records.append(record)
    return _normalize_exercise_rows(exchange, records, trade_date, raw_path, source_url, source_type)


def _parse_csv_exercise(exchange: str, raw_text: str, trade_date: date, raw_path: str, source_url: str, source_type: str) -> List[Dict[str, str]]:
    reader = csv.DictReader(raw_text.splitlines())
    return _normalize_exercise_rows(exchange, list(reader), trade_date, raw_path, source_url, source_type)


def _normalize_exercise_rows(
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
        rows.append(
            {
                "trade_date": format_trade_date(trade_date),
                "exchange": exchange,
                "contract": contract.upper(),
                "underlying_contract": _pick_field(normalized_record, "underlying_contract"),
                "option_type": _pick_field(normalized_record, "option_type"),
                "strike_price": normalize_number(_pick_field(normalized_record, "strike_price")),
                "expire_date": _pick_field(normalized_record, "expire_date"),
                "exercise_volume": normalize_number(_pick_field(normalized_record, "exercise_volume")),
                "assignment_volume": normalize_number(_pick_field(normalized_record, "assignment_volume")),
                "cash_settlement_amount": normalize_number(_pick_field(normalized_record, "cash_settlement_amount")),
                "delivery_quantity": normalize_number(_pick_field(normalized_record, "delivery_quantity")),
                "result_status": _pick_field(normalized_record, "result_status") or "reported",
                "source_url": source_url,
                "source_type": source_type,
                "retrieved_at": retrieved_at,
                "raw_path": raw_path,
            }
        )
    return rows


def _parse_sse_official_exercise_rows(
    records: List[Dict[str, object]],
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    retrieved_at = iso_timestamp()
    for record in records:
        underlying = normalize_text(record.get("UNDERLYING_SECURITY_ID")).upper()
        underlying_name = normalize_text(record.get("UNDERLYING_SECURITY_ABBR"))
        if not underlying:
            continue
        aggregates = (
            ("call", "CALL_EXE_VALUE", "CALL"),
            ("put", "PUT_EXE_VALUE", "PUT"),
        )
        for option_type, field_name, suffix in aggregates:
            volume = normalize_number(record.get(field_name))
            if not volume or volume in {"0", "0.0", "0.00"}:
                continue
            rows.append(
                {
                    "trade_date": format_trade_date(trade_date),
                    "exchange": "SSE",
                    "contract": f"{underlying}-{suffix}-AGG",
                    "underlying_contract": underlying,
                    "option_type": option_type,
                    "strike_price": "",
                    "expire_date": format_trade_date(trade_date),
                    "exercise_volume": volume,
                    "assignment_volume": "",
                    "cash_settlement_amount": "",
                    "delivery_quantity": "",
                    "result_status": "reported_underlying_aggregate",
                    "source_url": source_url,
                    "source_type": source_type,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                }
            )
            if underlying_name:
                rows[-1]["underlying_contract"] = underlying
    return rows


def _parse_szse_official_exercise_rows(
    records: List[Dict[str, object]],
    trade_date: date,
    raw_path: str,
    source_url: str,
    source_type: str,
) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    retrieved_at = iso_timestamp()
    for record in records:
        underlying_label = normalize_text(record.get("bdzqdm"))
        if not underlying_label:
            continue
        code_match = re.search(r"\((\d{6})\)", underlying_label)
        underlying = code_match.group(1) if code_match else ""
        for option_type, field_name, suffix in (
            ("call", "cxqhysl", "CALL"),
            ("put", "pxqhysl", "PUT"),
        ):
            volume = normalize_number(record.get(field_name))
            if not volume or volume in {"0", "0.0", "0.00"}:
                continue
            contract = f"{underlying}-{suffix}-AGG" if underlying else f"SZSE-{suffix}-AGG"
            rows.append(
                {
                    "trade_date": format_trade_date(trade_date),
                    "exchange": "SZSE",
                    "contract": contract,
                    "underlying_contract": underlying,
                    "option_type": option_type,
                    "strike_price": "",
                    "expire_date": format_trade_date(trade_date),
                    "exercise_volume": volume,
                    "assignment_volume": "",
                    "cash_settlement_amount": "",
                    "delivery_quantity": "",
                    "result_status": "reported_underlying_aggregate",
                    "source_url": source_url,
                    "source_type": source_type,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                }
            )
    return rows


def _pick_field(record: Dict[str, str], logical_name: str) -> str:
    for key in EXERCISE_RECORD_ALIASES[logical_name]:
        value = record.get(key.lower(), "")
        if value:
            return value
    return ""
