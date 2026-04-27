from datetime import date
from typing import List

from ..config import PROJECT_ROOT
from ..models import RawPayload, QuoteRow
from ..parsers.shfe import parse_shfe_daily_quotes
from ..utils import compact_trade_date, relative_to_project
from .base import ExchangeSource


class SHFESource(ExchangeSource):
    exchange = "SHFE"

    def fetch_raw(self, trade_date: date) -> RawPayload:
        exchange_settings = self.settings["exchanges"]["SHFE"]
        url = exchange_settings["daily_url"].format(trade_date=compact_trade_date(trade_date))
        response = self._request(
            "GET",
            url,
            headers=self._headers(
                {
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": exchange_settings["referer"],
                }
            ),
        )
        return RawPayload(content=response.text, url=url, extension="json", source_type="official")

    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path) -> List[QuoteRow]:
        return parse_shfe_daily_quotes(
            raw_text=payload.content,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=payload.url,
            source_type=payload.source_type,
        )
