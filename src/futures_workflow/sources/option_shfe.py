from datetime import date
from typing import List

from ..config import PROJECT_ROOT
from ..constants import OPTIONS_DATASET
from ..models import OptionQuoteRow, RawPayload
from ..parsers.options_shfe import parse_shfe_option_daily_quotes
from ..utils import compact_trade_date, relative_to_project
from .base import ExchangeSource


class SHFEOptionSource(ExchangeSource):
    exchange = "SHFE"
    dataset = OPTIONS_DATASET

    def fetch_raw(self, trade_date: date) -> RawPayload:
        url = f"https://www.shfe.com.cn/data/tradedata/option/dailydata/kx{compact_trade_date(trade_date)}.dat"
        response = self._request(
            "GET",
            url,
            headers=self._headers(
                {
                    "Accept": "application/json,text/plain,*/*",
                    "Referer": "https://www.shfe.com.cn/reports/tradedata/dailyandweeklydata/",
                }
            ),
        )
        return RawPayload(content=response.text, url=url, extension="json", source_type="official")

    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path) -> List[OptionQuoteRow]:
        return parse_shfe_option_daily_quotes(
            raw_text=payload.content,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=payload.url,
            source_type=payload.source_type,
        )
