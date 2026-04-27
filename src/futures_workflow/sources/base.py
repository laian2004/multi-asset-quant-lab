import json
from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path
from typing import Dict, List

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..config import RAW_DIR
from ..constants import ERROR_STATUS, FUTURES_DATASET, NO_DATA_STATUS, NOT_APPLICABLE_STATUS, PENDING_RETRY_STATUS, SUCCESS_STATUS
from ..exceptions import PendingRetryError, SourceNoDataError
from ..models import RawPayload, QuoteRow, SourceRunResult
from ..utils import compact_trade_date, ensure_directory, now_shanghai, parse_trade_date
from .request_control import pace_request, raise_for_protective_block


class ExchangeSource(ABC):
    exchange: str = ""
    dataset: str = FUTURES_DATASET

    def __init__(self, settings: Dict[str, object], logger):
        self.settings = settings
        self.logger = logger
        self.timeout = int(settings.get("timeout_seconds", 30))
        self.retry_attempts = int(settings.get("retry_attempts", 3))
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": str(settings.get("user_agent", "Mozilla/5.0"))})

    def run(self, trade_date: date) -> SourceRunResult:
        trade_date_str = trade_date.strftime("%Y-%m-%d")
        if not self.is_applicable(trade_date):
            return SourceRunResult(
                exchange=self.exchange,
                trade_date=trade_date_str,
                status=NOT_APPLICABLE_STATUS,
                dataset=self.dataset,
                message=self._not_applicable_message(),
            )
        try:
            payload = self.fetch_raw(trade_date)
            raw_path = self._write_raw_file(trade_date, payload)
            rows = self.parse_raw(trade_date, payload, raw_path)
            status = SUCCESS_STATUS if rows else NO_DATA_STATUS
            message = "" if rows else "Source returned no futures rows."
            return SourceRunResult(
                exchange=self.exchange,
                trade_date=trade_date_str,
                status=status,
                dataset=self.dataset,
                source_url=payload.url,
                source_type=payload.source_type,
                raw_path=raw_path,
                row_count=len(rows),
                rows=rows,
                message=message,
            )
        except SourceNoDataError as exc:
            return SourceRunResult(
                exchange=self.exchange,
                trade_date=trade_date_str,
                status=NO_DATA_STATUS,
                dataset=self.dataset,
                message=str(exc),
                error=str(exc),
            )
        except PendingRetryError as exc:
            return SourceRunResult(
                exchange=self.exchange,
                trade_date=trade_date_str,
                status=PENDING_RETRY_STATUS,
                dataset=self.dataset,
                message=str(exc),
                error=str(exc),
            )
        except Exception as exc:  # pragma: no cover - exercised in integration flow
            self.logger.exception("%s fetch failed for %s", self.exchange, trade_date_str)
            return SourceRunResult(
                exchange=self.exchange,
                trade_date=trade_date_str,
                status=ERROR_STATUS,
                dataset=self.dataset,
                message=str(exc),
                error=str(exc),
            )

    @abstractmethod
    def fetch_raw(self, trade_date: date) -> RawPayload:
        raise NotImplementedError

    @abstractmethod
    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path: Path) -> List[QuoteRow]:
        raise NotImplementedError

    def _write_raw_file(self, trade_date: date, payload: RawPayload) -> Path:
        target_dir = ensure_directory(self._raw_directory())
        stem = compact_trade_date(trade_date)
        target_path = target_dir / f"{stem}.{payload.extension}"
        target_path.write_text(payload.content, encoding="utf-8")
        meta_path = target_dir / f"{stem}.meta.json"
        meta_payload = {
            "source_url": payload.url,
            "source_type": payload.source_type,
            "extension": payload.extension,
            "meta": payload.meta,
        }
        meta_path.write_text(json.dumps(meta_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target_path

    def _load_cached_payload(self, trade_date: date, source_url: str, source_type: str) -> RawPayload:
        stem = compact_trade_date(trade_date)
        meta_path = self._raw_directory() / f"{stem}.meta.json"
        cached_meta: Dict[str, object] = {}
        cached_url = source_url
        cached_source_type = source_type
        if meta_path.exists():
            try:
                cached_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                cached_meta = {}
            cached_url = str(cached_meta.get("source_url") or source_url)
            cached_source_type = str(cached_meta.get("source_type") or source_type)
        for extension in ("json", "xml", "txt", "html"):
            candidate = self._raw_directory() / f"{stem}.{extension}"
            if candidate.exists():
                return RawPayload(
                    content=candidate.read_text(encoding="utf-8"),
                    url=cached_url,
                    extension=extension,
                    source_type=cached_source_type,
                    meta=dict(cached_meta.get("meta", {}) or {}),
                )
        raise FileNotFoundError(f"No cached raw payload found for {self.exchange} {self.dataset} {trade_date.isoformat()}.")

    def _load_cached_payload_if_historical(self, trade_date: date, source_url: str, source_type: str):
        if trade_date >= now_shanghai().date():
            return None
        try:
            return self._load_cached_payload(trade_date, source_url, source_type)
        except FileNotFoundError:
            return None

    def _headers(self, extra: Dict[str, str] = None) -> Dict[str, str]:
        headers = dict(self.session.headers)
        if extra:
            headers.update(extra)
        return headers

    def _raw_directory(self) -> Path:
        dataset_dir = "daily_quotes" if self.dataset == FUTURES_DATASET else self.dataset
        return RAW_DIR / self.exchange.lower() / dataset_dir

    def is_applicable(self, trade_date: date) -> bool:
        launch_date = self._launch_date()
        if launch_date and trade_date < launch_date:
            return False
        return True

    def _launch_date(self):
        metadata = self.settings.get("exchange_metadata", {}).get(self.exchange, {})
        if self.dataset == "options_daily_quotes":
            launch_date_value = metadata.get("options_launch_date") or metadata.get("launch_date")
        else:
            launch_date_value = metadata.get("futures_launch_date") or metadata.get("launch_date")
        if not launch_date_value:
            return None
        return parse_trade_date(str(launch_date_value))

    def _not_applicable_message(self) -> str:
        launch_date = self._launch_date()
        if launch_date is None:
            return f"{self.exchange} is not applicable for this trade date."
        return f"{self.exchange} is not applicable before launch date {launch_date.isoformat()}."

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        return self._request_with_retry(method, url, **kwargs)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(requests.RequestException),
        reraise=True,
    )
    def _request_with_retry(self, method: str, url: str, **kwargs) -> requests.Response:
        timeout = kwargs.pop("timeout", self.timeout)
        pace_request(url, self.settings)
        response = self.session.request(method=method, url=url, timeout=timeout, **kwargs)
        if response.status_code == 404:
            raise SourceNoDataError(f"{self.exchange} has no published file at {url}")
        raise_for_protective_block(url, response, self.settings)
        response.raise_for_status()
        return response
