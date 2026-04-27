import logging
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.exceptions import PendingRetryError, SourceNoDataError
from src.futures_workflow.sources.czce import CZCESource


class CZCESourceTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "user_agent": "ua",
            "timeout_seconds": 5,
            "exchanges": {
                "CZCE": {
                    "daily_url": "https://example.com/{year}/{trade_date}/FutureDataDaily.txt",
                }
            },
            "product_name_map": {"CZCE": {"CF": "棉花"}},
        }
        self.source = CZCESource(self.settings, logging.getLogger("test-czce-source"))

    def test_fetch_raw_uses_akshare_fallback_when_official_missing(self):
        frame = pd.DataFrame(
            [
                {
                    "symbol": "CF505",
                    "date": 20150416,
                    "open": 12590.0,
                    "high": 12715.0,
                    "low": 12590.0,
                    "close": 12700.0,
                    "volume": 3036,
                    "open_interest": 23504,
                    "turnover": 19241.07,
                    "settle": 12675.0,
                    "pre_settle": 12630.0,
                    "variety": "CF",
                }
            ]
        )
        with patch.object(self.source, "_request", side_effect=SourceNoDataError("missing")):
            with patch("akshare.get_futures_daily", return_value=frame):
                payload = self.source.fetch_raw(date(2015, 4, 16))
        self.assertEqual(payload.source_type, "fallback_online")
        self.assertEqual(payload.extension, "json")
        self.assertIn("CF505", payload.content)

    def test_fetch_raw_raises_original_no_data_when_fallback_empty(self):
        with patch.object(self.source, "_request", side_effect=SourceNoDataError("missing")):
            with patch("akshare.get_futures_daily", return_value=pd.DataFrame()):
                with self.assertRaises(SourceNoDataError):
                    self.source.fetch_raw(date(2015, 4, 16))

    def test_fetch_raw_raises_pending_retry_when_online_chain_is_exhausted(self):
        with patch.object(self.source, "_request", side_effect=SourceNoDataError("missing")):
            with patch("akshare.get_futures_daily", side_effect=RuntimeError("bad zip")):
                with self.assertRaises(PendingRetryError) as ctx:
                    self.source.fetch_raw(date(2010, 4, 16))
        self.assertIn("fallback chain exhausted", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
