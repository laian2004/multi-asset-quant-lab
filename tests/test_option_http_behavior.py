import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.exceptions import PendingRetryError
from src.futures_workflow.sources.option_equity_common import (
    fetch_sina_expire_day,
    fetch_sina_option_daily_row,
    fetch_sina_option_daily_rows,
    fetch_sina_option_metadata,
    iter_cached_sina_option_history_symbols,
    write_sina_option_metadata_cache,
)


class OptionHttpBehaviorTests(unittest.TestCase):
    def test_daily_rows_stop_after_protective_block_with_partial_rows(self):
        calls = []

        def fake_fetch(symbol, trade_date, user_agent, timeout, *, request_settings=None):
            calls.append(symbol)
            if symbol == "1002":
                raise PendingRetryError("blocked")
            return {
                "open": "1",
                "high": "1",
                "low": "1",
                "close": "1",
                "prev_settlement": "1",
                "change_close": "0",
                "volume": "1",
            }

        with mock.patch("src.futures_workflow.sources.option_equity_common.fetch_sina_option_daily_row", side_effect=fake_fetch):
            rows = fetch_sina_option_daily_rows(["1001", "1002", "1003"], date(2026, 4, 16), "ua", 5)

        self.assertEqual(sorted(rows), ["1001"])
        self.assertEqual(calls, ["1001", "1002"])

    def test_daily_rows_raise_when_protective_block_hits_before_any_row(self):
        def fake_fetch(symbol, trade_date, user_agent, timeout, *, request_settings=None):
            raise PendingRetryError("blocked")

        with mock.patch("src.futures_workflow.sources.option_equity_common.fetch_sina_option_daily_row", side_effect=fake_fetch):
            with self.assertRaises(PendingRetryError):
                fetch_sina_option_daily_rows(["1001", "1002"], date(2026, 4, 16), "ua", 5)

    def test_daily_row_prefers_cached_symbol_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_path = root / "equity_options_history" / "90007175.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                '[{"d":"2026-04-15","o":"0.42","h":"0.43","l":"0.41","c":"0.425","v":"100"},{"d":"2026-04-16","o":"0.43","h":"0.44","l":"0.42","c":"0.435","v":"120"}]',
                encoding="utf-8",
            )
            with mock.patch("src.futures_workflow.sources.option_equity_common._daily_cache_path", return_value=cache_path), mock.patch(
                "src.futures_workflow.sources.option_equity_common._sina_get",
                side_effect=AssertionError("cache hit should not issue live request"),
            ):
                row = fetch_sina_option_daily_row("90007175", date(2026, 4, 16), "ua", 5)

        self.assertEqual(row["close"], "0.435")
        self.assertEqual(row["prev_settlement"], "0.425")

    def test_option_metadata_prefers_cached_symbol_metadata(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_path = root / "equity_options_metadata" / "90007175.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                '{"contract_name":"沪深300ETF购4月4500","contract":"159919C2104M004500","strike_price":"4.5000","delta":"0","implied_volatility":"0"}',
                encoding="utf-8",
            )
            with mock.patch("src.futures_workflow.sources.option_equity_common._metadata_cache_path", return_value=cache_path), mock.patch(
                "src.futures_workflow.sources.option_equity_common._sina_get",
                side_effect=AssertionError("metadata cache hit should not issue live request"),
            ):
                metadata = fetch_sina_option_metadata("90007175", "ua", 5)

        self.assertEqual(metadata["contract"], "159919C2104M004500")

    def test_expire_day_prefers_cached_value(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_path = root / "equity_options_expire_days" / "159919_202104.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                '{"underlying_key":"159919","expiry_month":"202104","expire_day":"2021-04-28"}',
                encoding="utf-8",
            )
            with mock.patch("src.futures_workflow.sources.option_equity_common._expire_day_cache_path", return_value=cache_path), mock.patch(
                "src.futures_workflow.sources.option_equity_common._sina_get",
                side_effect=AssertionError("expire day cache hit should not issue live request"),
            ):
                expire_day = fetch_sina_expire_day("202104", "159919", "ua", 5)

        self.assertEqual(expire_day, "2021-04-28")

    def test_write_option_metadata_cache_normalizes_contract(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            cache_path = root / "equity_options_metadata" / "90007175.json"
            with mock.patch("src.futures_workflow.sources.option_equity_common._metadata_cache_path", return_value=cache_path):
                metadata = write_sina_option_metadata_cache(
                    "90007175",
                    {
                        "contract_name": "沪深300ETF购4月4500",
                        "contract": "159919c2104m004500",
                        "strike_price": "4.5000",
                    },
                )
            cache_exists = cache_path.exists()

        self.assertEqual(metadata["contract"], "159919C2104M004500")
        self.assertTrue(cache_exists)

    def test_iter_cached_history_symbols_can_filter_by_trade_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            history_dir = root / "equity_options_history"
            history_dir.mkdir(parents=True, exist_ok=True)
            (history_dir / "90007175.json").write_text(
                '[{"d":"2021-04-16","o":"0.1","h":"0.1","l":"0.1","c":"0.1","v":"1"}]',
                encoding="utf-8",
            )
            (history_dir / "90007176.json").write_text(
                '[{"d":"2021-04-15","o":"0.1","h":"0.1","l":"0.1","c":"0.1","v":"1"}]',
                encoding="utf-8",
            )
            with mock.patch("src.futures_workflow.sources.option_equity_common.RAW_DIR", root):
                symbols = list(iter_cached_sina_option_history_symbols(trade_date=date(2021, 4, 16)))

        self.assertEqual(symbols, ["90007175"])


if __name__ == "__main__":
    unittest.main()
