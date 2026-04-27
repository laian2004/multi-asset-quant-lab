import json
from datetime import date
from typing import List, Optional

from ..config import PROJECT_ROOT
from ..exceptions import PendingRetryError, SourceNoDataError
from ..models import RawPayload, QuoteRow
from ..parsers.czce import parse_czce_daily_quotes
from ..utils import compact_trade_date, decode_bytes, relative_to_project
from .base import ExchangeSource


class CZCESource(ExchangeSource):
    exchange = "CZCE"

    def fetch_raw(self, trade_date: date) -> RawPayload:
        exchange_settings = self.settings["exchanges"]["CZCE"]
        trade_date_compact = compact_trade_date(trade_date)
        url = exchange_settings["daily_url"].format(year=trade_date_compact[:4], trade_date=trade_date_compact)
        official_error: Optional[Exception] = None
        online_error: Optional[Exception] = None

        try:
            response = self._request(
                "GET",
                url,
                headers=self._headers({"Accept": "text/plain,*/*"}),
            )
            text = decode_bytes(response.content)
            if "每日行情表" in text:
                return RawPayload(content=text, url=url, extension="txt", source_type="official")
            raise SourceNoDataError(f"CZCE response for {trade_date_compact} does not look like a daily quote file.")
        except SourceNoDataError as exc:
            official_error = exc
        except Exception as exc:
            official_error = exc

        try:
            fallback_payload = self._fetch_akshare_fallback(trade_date)
        except SourceNoDataError as exc:
            online_error = exc
        except Exception as exc:
            online_error = exc
        else:
            if official_error is not None:
                self.logger.warning("CZCE official fetch failed for %s, switching to AkShare fallback: %s", trade_date.isoformat(), official_error)
            return fallback_payload

        if isinstance(official_error, SourceNoDataError) and isinstance(online_error, SourceNoDataError):
            raise official_error

        message = f"CZCE official fetch failed and fallback chain exhausted for {trade_date.isoformat()}"
        if official_error is not None or online_error is not None:
            message = f"{message}: official={official_error}; online={online_error}"
        raise PendingRetryError(message)

    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path) -> List[QuoteRow]:
        return parse_czce_daily_quotes(
            raw_text=payload.content,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=payload.url,
            source_type=payload.source_type,
            product_name_map=self.settings["product_name_map"]["CZCE"],
        )

    def _fetch_akshare_fallback(self, trade_date: date) -> RawPayload:
        import akshare as ak

        trade_date_compact = compact_trade_date(trade_date)
        frame = ak.get_futures_daily(start_date=trade_date_compact, end_date=trade_date_compact, market="CZCE")
        if frame.empty:
            raise SourceNoDataError(f"AkShare CZCE fallback returned no rows for {trade_date.isoformat()}.")

        records = []
        for item in frame.to_dict(orient="records"):
            normalized = {}
            for key, value in item.items():
                if value is None:
                    normalized[str(key)] = ""
                else:
                    text = str(value)
                    normalized[str(key)] = "" if text.lower() == "nan" else text
            records.append(normalized)
        payload = {"data": records}
        return RawPayload(
            content=json.dumps(payload, ensure_ascii=False),
            url="akshare://get_futures_daily/CZCE",
            extension="json",
            source_type="fallback_online",
        )
