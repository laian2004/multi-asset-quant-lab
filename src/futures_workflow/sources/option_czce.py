from datetime import date
from typing import List

from ..config import PROJECT_ROOT
from ..constants import OPTIONS_DATASET
from ..models import OptionQuoteRow, RawPayload
from ..parsers.options_czce import parse_czce_option_daily_quotes
from ..utils import compact_trade_date, decode_bytes, relative_to_project
from .base import ExchangeSource


class CZCEOptionSource(ExchangeSource):
    exchange = "CZCE"
    dataset = OPTIONS_DATASET

    def fetch_raw(self, trade_date: date) -> RawPayload:
        trade_date_compact = compact_trade_date(trade_date)
        url = f"https://www.czce.com.cn/cn/DFSStaticFiles/Option/{trade_date_compact[:4]}/{trade_date_compact}/OptionDataDaily.txt"
        response = self._request(
            "GET",
            url,
            headers=self._headers({"Accept": "text/plain,*/*"}),
        )
        return RawPayload(content=decode_bytes(response.content), url=url, extension="txt", source_type="official")

    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path) -> List[OptionQuoteRow]:
        option_name_map = self.settings.get("option_product_name_map", {}).get("CZCE", {})
        return parse_czce_option_daily_quotes(
            raw_text=payload.content,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=payload.url,
            source_type=payload.source_type,
            product_name_map=option_name_map,
        )
