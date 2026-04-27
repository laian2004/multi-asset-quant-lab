import re
from datetime import date
from typing import Dict, List, Tuple

from ..config import PROJECT_ROOT
from ..exceptions import PendingRetryError
from ..models import RawPayload, QuoteRow
from ..parsers.gfex import parse_gfex_daily_quotes
from ..utils import compact_trade_date, relative_to_project
from .base import ExchangeSource
from .browser import bootstrap_browser_cookies


class GFEXSource(ExchangeSource):
    exchange = "GFEX"

    def fetch_raw(self, trade_date: date) -> RawPayload:
        exchange_settings = self.settings["exchanges"]["GFEX"]
        bootstrap_url = exchange_settings["bootstrap_url"]
        cookies = {}
        source_type = "official"
        try:
            cookies = self._solve_challenge_cookies(bootstrap_url)
        except Exception as exc:
            self.logger.warning("GFEX JS challenge parse failed, switching to browser bootstrap: %s", exc)
            cookies, _ = bootstrap_browser_cookies(bootstrap_url, self.settings["user_agent"])
            source_type = "official_browser_bootstrap"

        if not cookies:
            raise PendingRetryError("GFEX challenge cookies could not be established.")

        url = exchange_settings["daily_url"]
        response = self._request(
            "POST",
            url,
            data={"trade_date": compact_trade_date(trade_date), "trade_type": "0", "variety": ""},
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
                data={"trade_date": compact_trade_date(trade_date), "trade_type": "0", "variety": ""},
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

    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path) -> List[QuoteRow]:
        return parse_gfex_daily_quotes(
            raw_text=payload.content,
            trade_date=trade_date,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            source_url=payload.url,
            source_type=payload.source_type,
        )

    def _solve_challenge_cookies(self, bootstrap_url: str) -> Dict[str, str]:
        response = self._request("GET", bootstrap_url, headers=self._headers({"Accept": "text/html,*/*"}))
        html = response.text
        status_cookie, ssid_cookie = _parse_gfex_challenge(html)
        return {"__tst_status": status_cookie, "EO_Bot_Ssid": ssid_cookie}


def _parse_gfex_challenge(html: str) -> Tuple[str, str]:
    sum_match = re.search(r"WTKkN:(\d+).*?bOYDu:(\d+).*?wyeCN:(\d+)", html, re.S)
    if not sum_match:
        raise ValueError("GFEX challenge did not expose expected sum fields.")
    total = sum(int(value) for value in sum_match.groups())
    fragment = html.split("EO_Bot_Ssid=", 1)[1]
    ssid_numbers = re.findall(r"\d{6,}", fragment)
    if not ssid_numbers:
        raise ValueError("GFEX challenge did not expose EO_Bot_Ssid.")
    return f"{total}#", ssid_numbers[0]
