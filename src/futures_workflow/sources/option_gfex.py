from datetime import date
from typing import List

from ..config import PROJECT_ROOT
from ..constants import OPTIONS_DATASET
from ..exceptions import PendingRetryError
from ..models import OptionQuoteRow, RawPayload
from ..parsers.options_gfex import parse_gfex_option_daily_quotes
from ..utils import compact_trade_date, relative_to_project
from .base import ExchangeSource
from .browser import bootstrap_browser_cookies
from .gfex import _parse_gfex_challenge


class GFEXOptionSource(ExchangeSource):
    exchange = "GFEX"
    dataset = OPTIONS_DATASET

    def fetch_raw(self, trade_date: date) -> RawPayload:
        bootstrap_url = self.settings["exchanges"]["GFEX"]["bootstrap_url"]
        url = self.settings["exchanges"]["GFEX"]["daily_url"]
        cookies = {}
        source_type = "official"
        try:
            cookies = self._solve_challenge_cookies(bootstrap_url)
        except Exception as exc:
            self.logger.warning("GFEX option JS challenge parse failed, switching to browser bootstrap: %s", exc)
            cookies, _ = bootstrap_browser_cookies(bootstrap_url, self.settings["user_agent"])
            source_type = "official_browser_bootstrap"

        if not cookies:
            raise PendingRetryError("GFEX option challenge cookies could not be established.")

        response = self._request(
            "POST",
            url,
            data={"trade_date": compact_trade_date(trade_date), "trade_type": "1", "variety": ""},
            headers=self._headers(
                {
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Referer": bootstrap_url,
                }
            ),
            cookies=cookies,
        )
        if response.text.strip().startswith("<!DOCTYPE html"):
            cookies, _ = bootstrap_browser_cookies(bootstrap_url, self.settings["user_agent"])
            response = self._request(
                "POST",
                url,
                data={"trade_date": compact_trade_date(trade_date), "trade_type": "1", "variety": ""},
                headers=self._headers(
                    {
                        "Accept": "application/json, text/javascript, */*; q=0.01",
                        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "Referer": bootstrap_url,
                    }
                ),
                cookies=cookies,
            )
            source_type = "official_browser_bootstrap"
        return RawPayload(content=response.text, url=url, extension="json", source_type=source_type)

    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path) -> List[OptionQuoteRow]:
        return parse_gfex_option_daily_quotes(
            raw_text=payload.content,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=payload.url,
            source_type=payload.source_type,
        )

    def _solve_challenge_cookies(self, bootstrap_url: str):
        response = self._request("GET", bootstrap_url, headers=self._headers({"Accept": "text/html,*/*"}))
        status_cookie, ssid_cookie = _parse_gfex_challenge(response.text)
        return {"__tst_status": status_cookie, "EO_Bot_Ssid": ssid_cookie}
