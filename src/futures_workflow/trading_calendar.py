from datetime import date, timedelta
from typing import List

from .calendar import SHFECalendarClient
from .utils import previous_weekday


class TradingCalendarRegistry:
    def __init__(self, settings: dict, logger):
        self.logger = logger
        self.futures_client = SHFECalendarClient(settings, logger)

    def candidate_dates(self, calendar_name: str, start: date, end: date) -> List[date]:
        if calendar_name == "futures_cn":
            return self.futures_client.candidate_dates(start, end)
        if calendar_name == "equities_cn":
            return _weekday_dates(start, end)
        if calendar_name == "all":
            return sorted(set(self.futures_client.candidate_dates(start, end) + _weekday_dates(start, end)))
        raise ValueError(f"Unsupported calendar: {calendar_name}")

    def previous_trading_day(self, calendar_name: str, reference: date) -> date:
        if calendar_name == "futures_cn":
            return self.futures_client.previous_trading_day(reference)
        if calendar_name in {"equities_cn", "all"}:
            current = reference - timedelta(days=1)
            while current.weekday() >= 5:
                current -= timedelta(days=1)
            return current
        raise ValueError(f"Unsupported calendar: {calendar_name}")


def _weekday_dates(start: date, end: date) -> List[date]:
    values: List[date] = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            values.append(current)
        current += timedelta(days=1)
    return values
