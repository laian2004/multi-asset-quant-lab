from datetime import date
from typing import List

from ..config import PROJECT_ROOT
from ..constants import OPTIONS_DATASET
from ..models import OptionQuoteRow, RawPayload
from ..parsers.options_cffex import parse_cffex_option_daily_quotes
from ..utils import compact_trade_date, relative_to_project
from .base import ExchangeSource


class CFFEXOptionSource(ExchangeSource):
    exchange = "CFFEX"
    dataset = OPTIONS_DATASET

    def fetch_raw(self, trade_date: date) -> RawPayload:
        trade_date_compact = compact_trade_date(trade_date)
        url = f"http://www.cffex.com.cn/sj/hqsj/rtj/{trade_date_compact[:6]}/{trade_date_compact[6:8]}/index.xml"
        response = self._request(
            "GET",
            url,
            headers=self._headers(
                {
                    "Accept": "application/xml,text/xml,*/*",
                    "Referer": "http://www.cffex.com.cn/cn/lssjxz.html",
                }
            ),
        )
        return RawPayload(content=response.text, url=url, extension="xml", source_type="official")

    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path) -> List[OptionQuoteRow]:
        option_name_map = self.settings.get("option_product_name_map", {}).get("CFFEX", {})
        return parse_cffex_option_daily_quotes(
            raw_text=payload.content,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=payload.url,
            source_type=payload.source_type,
            product_name_map=option_name_map,
        )
