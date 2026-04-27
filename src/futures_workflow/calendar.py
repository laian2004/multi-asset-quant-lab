import json
import re
from datetime import date, timedelta
from typing import List

import requests

from .exceptions import SourceNoDataError
from .utils import parse_trade_date, previous_weekday


class SHFECalendarClient:
    def __init__(self, settings: dict, logger):
        self.settings = settings
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": settings["user_agent"]})

    def get_trading_days(self, year: int) -> List[date]:
        url = self.settings["exchanges"]["SHFE"]["calendar_url"].format(year=year)
        response = self.session.get(url, timeout=int(self.settings.get("timeout_seconds", 30)))
        if response.status_code == 404:
            raise SourceNoDataError(f"SHFE calendar not found for {year}")
        response.raise_for_status()
        payload = json.loads(response.text)
        trading_days = self._extract_days(payload)
        if not trading_days:
            raise SourceNoDataError(f"SHFE calendar did not include parseable trading days for {year}")
        return sorted(set(trading_days))

    def candidate_dates(self, start: date, end: date) -> List[date]:
        dates: List[date] = []
        for year in range(start.year, end.year + 1):
            try:
                dates.extend([item for item in self.get_trading_days(year) if start <= item <= end])
            except Exception as exc:
                self.logger.warning("Falling back to weekday calendar for %s: %s", year, exc)
                dates.extend(_weekday_fallback(max(start, date(year, 1, 1)), min(end, date(year, 12, 31))))
        return sorted(set(dates))

    def previous_trading_day(self, reference: date) -> date:
        start = reference - timedelta(days=15)
        candidates = [item for item in self.candidate_dates(start, reference - timedelta(days=1)) if item < reference]
        if candidates:
            return candidates[-1]
        return previous_weekday(reference)

    def _extract_days(self, payload) -> List[date]:
        records = []
        stack = [payload]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                if current:
                    records.append(current)
                stack.extend(current.values())
            elif isinstance(current, list):
                stack.extend(current)
        days: List[date] = []
        for record in records:
            date_value = None
            trading_flag = None
            for key, value in record.items():
                key_lower = str(key).lower()
                if "date" in key_lower and not date_value:
                    maybe_date = re.search(r"\d{4}-?\d{2}-?\d{2}", str(value))
                    if maybe_date:
                        date_value = parse_trade_date(maybe_date.group(0).replace("-", ""))
                if "trad" in key_lower and trading_flag is None:
                    trading_flag = str(value).strip().lower()
            if date_value and trading_flag in {"1", "true", "y", "yes"}:
                days.append(date_value)
        return days


def _weekday_fallback(start: date, end: date) -> List[date]:
    current = start
    dates: List[date] = []
    while current <= end:
        if current.weekday() < 5:
            dates.append(current)
        current += timedelta(days=1)
    return dates
