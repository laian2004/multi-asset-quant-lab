import logging
import tempfile
import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.exceptions import PendingRetryError
from src.futures_workflow.sources.dce import (
    DCESource,
    _history_covers_trade_date,
    _load_cached_history,
    _parse_edb_daily_bar,
    _parse_sina_daily_history,
    _parse_sina_dce_nodes,
)


class _DummyResponse:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")


class DCESourceTests(unittest.TestCase):
    def setUp(self):
        self.settings = {
            "user_agent": "ua",
            "timeout_seconds": 5,
            "exchanges": {
                "DCE": {
                    "bootstrap_url": "http://bootstrap.example.com",
                    "legacy_export_url": "http://legacy.example.com/export",
                    "daily_json_url": "http://json.example.com/dayQuotes",
                    "referer": "http://referer.example.com",
                }
            },
            "fallbacks": {"DCE": {"enabled": False, "provider": "akshare_sina"}},
            "contract_catalog": {
                "DCE": {
                    "A": {
                        "variety_code": "A",
                        "contract_prefix": "A",
                        "first_listed_month": "200001",
                        "last_listed_month": "",
                        "typical_cycle_months": [1, 5, 9],
                    },
                    "J": {
                        "variety_code": "J",
                        "contract_prefix": "J",
                        "first_listed_month": "201104",
                        "last_listed_month": "",
                        "typical_cycle_months": [1, 5, 9],
                    },
                }
            },
            "product_name_map": {"DCE": {"A": "豆一"}},
        }
        self.source = DCESource(self.settings, logging.getLogger("test-dce-source"))

    def test_fetch_raw_prefers_json_endpoint(self):
        json_text = """{"data":[{"contractId":"a2605","variety":"豆一","varietyOrder":"a","deliveryMonth":"2605"}]}"""
        with patch("src.futures_workflow.sources.dce.bootstrap_browser_cookies", return_value=({"k": "v"}, "<html></html>")):
            with patch.object(self.source.session, "post", return_value=_DummyResponse(200, json_text)) as post_mock:
                with patch.object(self.source.session, "get") as get_mock:
                    payload = self.source.fetch_raw(date(2026, 4, 16))
        self.assertEqual(payload.extension, "json")
        self.assertEqual(payload.source_type, "official_browser_bootstrap")
        post_mock.assert_called_once()
        get_mock.assert_not_called()

    def test_fetch_raw_falls_back_to_legacy_export(self):
        legacy_text = "合约|开盘价|最高价|最低价|收盘价\nA2605|1|2|0.5|1.5\n"
        with patch("src.futures_workflow.sources.dce.bootstrap_browser_cookies", return_value=({"k": "v"}, "<html></html>")):
            with patch.object(self.source.session, "post", return_value=_DummyResponse(400, "")):
                with patch.object(self.source.session, "get", return_value=_DummyResponse(200, legacy_text)) as get_mock:
                    payload = self.source.fetch_raw(date(2026, 4, 16))
        self.assertEqual(payload.extension, "txt")
        self.assertIn("legacy.example.com", payload.url)
        get_mock.assert_called_once()

    def test_fetch_raw_raises_pending_retry_when_all_official_paths_fail(self):
        with patch("src.futures_workflow.sources.dce.bootstrap_browser_cookies", return_value=({"k": "v"}, "<html></html>")):
            with patch.object(self.source.session, "post", return_value=_DummyResponse(412, "Precondition Failed")):
                with patch.object(self.source.session, "get", return_value=_DummyResponse(400, "")):
                    with self.assertRaises(PendingRetryError):
                        self.source.fetch_raw(date(2026, 4, 16))

    def test_fetch_raw_uses_fallback_when_enabled(self):
        self.source.settings["fallbacks"]["DCE"]["enabled"] = True
        fallback_rows = [
            {
                "contractId": "A2605",
                "varietyOrder": "A",
                "variety": "豆一",
                "deliveryMonth": "2605",
                "open": "1",
                "high": "2",
                "low": "0.5",
                "close": "1.5",
                "lastClear": "1.2",
                "clearPrice": "1.4",
                "diff": "0.3",
                "diff1": "0.2",
                "volumn": "10",
                "openInterest": "20",
                "diffI": "2",
                    "turnover": "",
            }
        ]
        with patch("src.futures_workflow.sources.dce.bootstrap_browser_cookies", return_value=({"k": "v"}, "<html></html>")):
            with patch.object(self.source.session, "post", return_value=_DummyResponse(400, "")):
                with patch.object(self.source.session, "get", return_value=_DummyResponse(400, "")):
                    with patch.object(
                        self.source,
                        "_collect_fallback_rows",
                        return_value=(fallback_rows, "fallback_online", "https://stock2.finance.sina.com.cn/futures/api/jsonp.php"),
                    ):
                        payload = self.source.fetch_raw(date(2026, 4, 16))
        self.assertEqual(payload.source_type, "fallback_online")
        self.assertEqual(payload.extension, "json")
        self.assertIn("A2605", payload.content)

    def test_fetch_raw_raises_pending_retry_when_online_fallback_has_no_rows(self):
        self.source.settings["fallbacks"]["DCE"]["enabled"] = True
        with patch("src.futures_workflow.sources.dce.bootstrap_browser_cookies", return_value=({"k": "v"}, "<html></html>")):
            with patch.object(self.source.session, "post", return_value=_DummyResponse(400, "")):
                with patch.object(self.source.session, "get", return_value=_DummyResponse(400, "")):
                    with patch.object(self.source, "_rows_for_sina_symbols", return_value={}):
                        with patch.object(self.source, "_rows_for_edb_symbols", return_value={}):
                            with self.assertRaises(PendingRetryError) as ctx:
                                self.source.fetch_raw(date(2010, 4, 16))
        self.assertIn("returned no rows", str(ctx.exception))

    def test_parse_sina_nodes_extracts_dce_node_ids(self):
        script = "ARRFUTURESNODES = { dce : ['x', ['PVC', 'pvc_qh', '24'], ['豆一', 'dd_qh', '8']], shfe : ['y'] }"
        self.assertEqual(_parse_sina_dce_nodes(script), ["pvc_qh", "dd_qh"])

    def test_parse_sina_daily_history_handles_jsonp(self):
        text = "/*comment*/\\nvar _x=([{\"d\":\"2026-04-16\",\"o\":\"1\",\"h\":\"2\",\"l\":\"0.5\",\"c\":\"1.5\",\"v\":\"10\",\"p\":\"20\",\"s\":\"1.4\"}]);"
        rows = _parse_sina_daily_history(text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["d"], "2026-04-16")
        self.assertEqual(rows[0]["s"], "1.4")

    def test_parse_sina_daily_history_handles_null_payload(self):
        rows = _parse_sina_daily_history("var _x=(null);")
        self.assertEqual(rows, [])

    def test_history_covers_trade_date_requires_real_window(self):
        self.assertFalse(_history_covers_trade_date([], "2019-04-16"))
        self.assertFalse(_history_covers_trade_date([{"d": "2025-09-15"}], "2019-04-16"))
        self.assertTrue(_history_covers_trade_date([{"d": "2025-09-15"}, {"d": "2026-04-17"}], "2026-04-16"))

    def test_parse_edb_daily_bar(self):
        text = "datetime_nano,open,high,low,close,volume,open_oi,close_oi\n1618502400000000000,3479,3528,3462,3515,1125763,1568754,1528665\n"
        row = _parse_edb_daily_bar(text)
        self.assertIsNotNone(row)
        self.assertEqual(row["close"], "3515")
        self.assertEqual(row["close_oi"], "1528665")

    def test_load_cached_history_handles_null_data(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "A2605.json"
            path.write_text('{"symbol":"A2605","data":null}', encoding="utf-8")
            self.assertEqual(_load_cached_history(path), [])

    def test_generate_candidate_contracts_uses_contract_catalog(self):
        symbols = self.source._generate_candidate_contracts(date(2010, 4, 16))
        self.assertIn("A1005", symbols)
        self.assertIn("A1009", symbols)
        self.assertIn("A1101", symbols)
        self.assertNotIn("A1004", symbols)
        self.assertNotIn("J1005", symbols)

if __name__ == "__main__":
    unittest.main()
