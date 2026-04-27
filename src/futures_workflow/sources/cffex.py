from datetime import date
from typing import List

from ..config import PROJECT_ROOT
from ..models import RawPayload, QuoteRow
from ..parsers.cffex import parse_cffex_daily_quotes
from ..utils import compact_trade_date, relative_to_project
from .base import ExchangeSource


class CFFEXSource(ExchangeSource):
    exchange = "CFFEX"

    def fetch_raw(self, trade_date: date) -> RawPayload:
        exchange_settings = self.settings["exchanges"]["CFFEX"]
        trade_date_compact = compact_trade_date(trade_date)
        url = exchange_settings["daily_url"].format(
            year_month=trade_date_compact[:6],
            day=trade_date_compact[6:8],
        )
        response = self._request(
            "GET",
            url,
            headers=self._headers(
                {
                    "Accept": "application/xml,text/xml,*/*",
                    "Referer": exchange_settings["referer"],
                }
            ),
        )
        return RawPayload(content=response.text, url=url, extension="xml", source_type="official")

    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path) -> List[QuoteRow]:
        return parse_cffex_daily_quotes(
            raw_text=payload.content,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=payload.url,
            source_type=payload.source_type,
            product_name_map=self.settings["product_name_map"]["CFFEX"],
        )
