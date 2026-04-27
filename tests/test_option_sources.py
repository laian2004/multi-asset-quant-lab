import logging
import json
import sys
import unittest
from datetime import date
from pathlib import Path
import tempfile
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.sources.option_dce import DCEOptionSource
from src.futures_workflow.sources.option_sse import SSEOptionSource
from src.futures_workflow.sources.option_szse import SZSEOptionSource
from src.futures_workflow.models import RawPayload


class OptionSourceApplicabilityTests(unittest.TestCase):
    def test_shfe_pre_option_launch_is_not_applicable(self):
        from src.futures_workflow.sources.option_shfe import SHFEOptionSource

        source = SHFEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchange_metadata": {"SHFE": {"options_launch_date": "2018-09-21"}},
            },
            logging.getLogger("test-shfe-option-source"),
        )
        result = source.run(date(2018, 9, 1))
        self.assertEqual(result.status, "not_applicable")

    def test_sse_pre_launch_is_not_applicable(self):
        source = SSEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchange_metadata": {"SSE": {"launch_date": "2015-02-09"}},
            },
            logging.getLogger("test-sse-option-source"),
        )
        result = source.run(date(2015, 2, 1))
        self.assertEqual(result.status, "not_applicable")

    def test_szse_pre_launch_is_not_applicable(self):
        source = SZSEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchange_metadata": {"SZSE": {"launch_date": "2019-12-23"}},
            },
            logging.getLogger("test-szse-option-source"),
        )
        result = source.run(date(2019, 12, 1))
        self.assertEqual(result.status, "not_applicable")

    def test_dce_pre_option_launch_is_not_applicable(self):
        source = DCEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchange_metadata": {
                    "DCE": {
                        "launch_date": "1993-03-01",
                        "options_launch_date": "2017-03-31",
                    }
                },
            },
            logging.getLogger("test-dce-option-source-launch"),
        )
        result = source.run(date(2017, 3, 1))
        self.assertEqual(result.status, "not_applicable")

    def test_szse_contract_map_paginates_all_pages(self):
        source = SZSEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
            },
            logging.getLogger("test-szse-option-source-pagination"),
        )

        class FakeResponse:
            def __init__(self, payload):
                self._payload = payload

            def json(self):
                return self._payload

        payloads = {
            "1": [
                {
                    "metadata": {"pagecount": 2},
                    "data": [
                        {
                            "hybm": "90000001",
                            "hydm": "159919C2604M04000A",
                            "xqjg": "4.0000",
                            "dqrq": "2026-04-22",
                            "hzjyrq": "2026-04-22",
                            "bdzqdm": "沪深300ETF嘉实(159919)",
                            "hydw": "10000",
                            "qjsjg": "0.1234",
                        }
                    ],
                }
            ],
            "2": [
                {
                    "metadata": {"pagecount": 2},
                    "data": [
                        {
                            "hybm": "90000002",
                            "hydm": "159919P2604M04000A",
                            "xqjg": "4.0000",
                            "dqrq": "2026-04-22",
                            "hzjyrq": "2026-04-22",
                            "bdzqdm": "沪深300ETF嘉实(159919)",
                            "hydw": "10000",
                            "qjsjg": "0.2234",
                        }
                    ],
                }
            ],
        }

        def fake_request(method, url, **kwargs):
            return FakeResponse(payloads[kwargs["params"]["PAGENO"]])

        source._request = fake_request
        current_map = source._fetch_current_contract_map()
        self.assertEqual(sorted(current_map), ["90000001", "90000002"])
        self.assertEqual(current_map["90000001"]["contract_multiplier"], "10000")

    def test_szse_historical_contract_map_uses_txt_query_date_and_caches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = SZSEOptionSource(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                },
                logging.getLogger("test-szse-historical-contract-map"),
            )

            class FakeResponse:
                def __init__(self, payload):
                    self._payload = payload

                def json(self):
                    return self._payload

            requests_seen = []

            def fake_request(method, url, **kwargs):
                requests_seen.append(kwargs["params"])
                return FakeResponse(
                    [
                        {
                            "metadata": {"pagecount": 1},
                            "data": [
                                {
                                    "hybm": "10002859",
                                    "hydm": "159919C2104M005000",
                                    "xqjg": "5.0000",
                                    "dqrq": "2021-04-28",
                                    "hzjyrq": "2021-04-28",
                                    "bdzqdm": "沪深300ETF嘉实(159919)",
                                    "hydw": "10000",
                                    "qjsjg": "0.1234",
                                }
                            ],
                        }
                    ]
                )

            with mock.patch("src.futures_workflow.sources.option_szse.PROJECT_ROOT", root), mock.patch.object(
                source, "_request", side_effect=fake_request
            ):
                contract_map = source._fetch_historical_contract_map("2021-04-16")
                cached_map = source._fetch_historical_contract_map("2021-04-16")

            self.assertEqual(contract_map["10002859"]["contract"], "159919C2104M005000")
            self.assertEqual(contract_map, cached_map)
            self.assertEqual(len(requests_seen), 1)
            self.assertEqual(requests_seen[0]["txtQueryDate"], "2021-04-16")
            cache_path = root / "data" / "raw" / "szse" / "historical_contract_lookup" / "20210416.json"
            self.assertTrue(cache_path.exists())
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["source_trade_date"], "2021-04-16")

    def test_szse_historical_contract_map_ignores_mismatched_source_trade_date(self):
        source = SZSEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
            },
            logging.getLogger("test-szse-historical-contract-map-mismatch"),
        )

        class FakeResponse:
            def json(self):
                return [
                    {
                        "metadata": {"pagecount": 1, "subname": "2026-04-20"},
                        "data": [
                            {
                                "hybm": "90000001",
                                "hydm": "159919C2604M04000A",
                                "xqjg": "4.0000",
                                "dqrq": "2026-04-22",
                                "hzjyrq": "2026-04-22",
                                "bdzqdm": "沪深300ETF嘉实(159919)",
                                "hydw": "10000",
                                "qjsjg": "0.1234",
                            }
                        ],
                    }
                ]

        with mock.patch.object(source, "_request", return_value=FakeResponse()):
            contract_map = source._fetch_contract_map(trade_date_text="2021-04-16")

        self.assertEqual(contract_map, {})

    def test_szse_historical_discovery_can_use_official_historical_contract_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = SZSEOptionSource(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                },
                logging.getLogger("test-szse-historical-contract-discovery"),
            )
            with mock.patch("src.futures_workflow.sources.option_szse.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.sources.option_equity_common.RAW_DIR",
                root / "data" / "raw",
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.generate_expiry_months",
                return_value=["202104"],
            ), mock.patch.object(
                source,
                "_fetch_historical_contract_map",
                return_value={
                    "10002859": {
                        "contract": "159919C2104M005000",
                        "strike_price": "5.0000",
                        "expire_date": "2021-04-28",
                        "last_trade_date": "2021-04-28",
                        "underlying": "159919",
                        "contract_multiplier": "10000",
                        "prev_settlement": "0.1234",
                    }
                },
            ):
                symbols, metadata = source._discover_historical_symbols(
                    [{"bddm": "159919", "bdmc": "沪深300ETF嘉实"}],
                    date(2021, 4, 16),
                    offline_only=True,
                    allow_historical_live_metadata_probe=False,
                )

            self.assertEqual(symbols, {"10002859"})
            self.assertEqual(metadata["10002859"]["contract"], "159919C2104M005000")
            cache_path = root / "data" / "raw" / "equity_options_metadata" / "10002859.json"
            self.assertTrue(cache_path.exists())
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["contract"], "159919C2104M005000")

    def test_dce_builds_fallback_records_from_contract_table_and_history(self):
        source = DCEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "contract_catalog": {"DCE": {"M": {"contract_prefix": "M", "typical_cycle_months": [1, 3, 5, 7, 8, 9, 11, 12]}}},
            },
            logging.getLogger("test-dce-option-source"),
        )

        contract_rows = [
            {
                "underlying_contract": "M2605",
                "product_code": "M",
                "product_name": "豆粕期权",
                "行权价": "2500",
                "看涨合约-看涨期权合约": "m2605C2500",
                "看涨合约-持仓量": "45",
                "看跌合约-看跌期权合约": "m2605P2500",
                "看跌合约-持仓量": "18236",
            }
        ]

        with mock.patch.object(
            source,
            "_fetch_history_rows",
            return_value={
                "M2605C2500": {"open": "337.5", "high": "350.5", "low": "337.5", "close": "350.5", "prev_close": "340.0", "volume": "5"},
                "M2605P2500": {"open": "0.5", "high": "0.5", "low": "0.5", "close": "0.5", "prev_close": "0.5", "volume": "7"},
            },
        ):
            rows = source._build_fallback_records(date(2026, 4, 16), contract_rows, {"M": "豆粕期权"})

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["underlyingContract"], "M2605")
        self.assertIn(rows[0]["optionType"], {"call", "put"})
        self.assertEqual(rows[0]["metadata"]["underlying_exchange"], "DCE")

    def test_dce_skips_shell_contracts_without_quote_or_open_interest(self):
        source = DCEOptionSource({"user_agent": "ua", "timeout_seconds": 5}, logging.getLogger("test-dce-shell-contracts"))
        contract_rows = [
            {
                "underlying_contract": "M2605",
                "product_code": "M",
                "product_name": "豆粕期权",
                "行权价": "2500",
                "看涨合约-看涨期权合约": "m2605C2500",
                "看涨合约-持仓量": "",
                "看涨合约-最新价": "",
                "看跌合约-看跌期权合约": "m2605P2500",
                "看跌合约-持仓量": "15",
                "看跌合约-最新价": "0.5",
            }
        ]
        with mock.patch.object(
            source,
            "_fetch_history_rows",
            return_value={
                "M2605P2500": {"open": "0.5", "high": "0.5", "low": "0.5", "close": "0.5", "prev_close": "0.5", "volume": "7"}
            },
        ):
            rows = source._build_fallback_records(date(2026, 4, 16), contract_rows, {"M": "豆粕期权"})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["contractId"], "M2605P2500")

    def test_sse_prefers_cached_historical_payload(self):
        source = SSEOptionSource({"user_agent": "ua", "timeout_seconds": 5}, logging.getLogger("test-sse-cache"))
        cached = RawPayload(content='{"data":[]}', url="cached://sse", extension="json", source_type="fallback_online")
        with mock.patch.object(source, "_load_cached_payload_if_historical", return_value=cached), mock.patch.object(
            source, "_fetch_risk_rows", side_effect=AssertionError("should not fetch live SSE data when cached payload exists")
        ):
            payload = source.fetch_raw(date(2026, 4, 16))
        self.assertEqual(payload.url, "cached://sse")

    def test_sse_uses_official_current_quotes_for_recent_trade_date(self):
        source = SSEOptionSource({"user_agent": "ua", "timeout_seconds": 5}, logging.getLogger("test-sse-official-current"))
        records = [
            {
                "product_code": "510050",
                "product_name": "上证50ETF期权",
                "contract": "510050C2604M02650",
                "underlying_exchange": "SSE",
                "underlying_kind": "etf",
                "underlying_product_code": "510050",
                "underlying_contract": "510050",
                "option_type": "call",
                "strike_price": "2.6500",
                "exercise_type": "european",
                "expire_date": "",
                "last_trade_date": "",
                "open": "",
                "high": "",
                "low": "",
                "close": "0.3342",
                "prev_settlement": "0.3652",
                "settlement": "",
                "change_close": "-0.031",
                "change_settlement": "",
                "volume": "",
                "open_interest": "",
                "open_interest_change": "",
                "turnover": "",
                "delta": "0.990",
                "implied_volatility": "0.443",
                "exercise_volume": "",
            }
        ]
        with mock.patch.object(source, "_load_cached_payload_if_historical", return_value=None), mock.patch.object(
            source, "_should_try_official_current", return_value=True
        ), mock.patch.object(source, "_fetch_official_current_records", return_value=records), mock.patch.object(
            source, "_fetch_risk_rows", side_effect=AssertionError("official current branch should short-circuit fallback path")
        ):
            payload = source.fetch_raw(date(2026, 4, 17))

        self.assertEqual(payload.source_type, "official")
        self.assertIn("yunhq.sse.com.cn", payload.url)
        content = json.loads(payload.content)
        self.assertEqual(content["data"][0]["contract"], "510050C2604M02650")

    def test_sse_builds_official_current_records(self):
        source = SSEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "option_product_name_map": {"SSE": {"510050": "上证50ETF期权"}},
            },
            logging.getLogger("test-sse-official-current-records"),
        )
        with mock.patch.object(
            source,
            "_fetch_risk_rows",
            return_value=[
                {
                    "CONTRACT_ID": "510050C2604M02650",
                    "DELTA_VALUE": "0.990",
                    "IMPLC_VOLATLTY": "0.443",
                }
            ],
        ), mock.patch.object(
            source,
            "_fetch_official_current_price_map",
            return_value={
                "510050C2604M02650": {
                    "quote_date": "2026-04-17",
                    "contract": "510050C2604M02650",
                    "close": "0.3342",
                    "prev_settlement": "0.3652",
                }
            },
        ):
            records = source._fetch_official_current_records(date(2026, 4, 17))

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["product_name"], "上证50ETF期权")
        self.assertEqual(records[0]["close"], "0.3342")
        self.assertEqual(records[0]["prev_settlement"], "0.3652")
        self.assertEqual(records[0]["metadata"]["official_quote_date"], "2026-04-17")

    def test_szse_prefers_cached_historical_payload(self):
        source = SZSEOptionSource({"user_agent": "ua", "timeout_seconds": 5}, logging.getLogger("test-szse-cache"))
        cached = RawPayload(content='{"data":[]}', url="cached://szse", extension="json", source_type="fallback_online")
        with mock.patch.object(source, "_load_cached_payload_if_historical", return_value=cached), mock.patch.object(
            source, "_fetch_underlying_rows", side_effect=AssertionError("should not fetch live SZSE data when cached payload exists")
        ):
            payload = source.fetch_raw(date(2026, 4, 16))
        self.assertEqual(payload.url, "cached://szse")

    def test_szse_fetches_historical_symbols_from_target_trade_date(self):
        source = SZSEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "option_product_name_map": {"SZSE": {"159919": "沪深300ETF嘉实期权"}},
            },
            logging.getLogger("test-szse-historical-discovery"),
        )
        with mock.patch.object(source, "_load_cached_payload_if_historical", return_value=None), mock.patch.object(
            source,
            "_fetch_underlying_rows",
            return_value=[{"bddm": "159919", "bdmc": "沪深300ETF嘉实"}],
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.generate_expiry_months",
            return_value=["202604"],
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_option_codes",
            side_effect=[["90007175"], ["90007184"]],
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_option_daily_rows",
            return_value={
                "90007175": {
                    "open": "0.4306",
                    "high": "0.4378",
                    "low": "0.4274",
                    "close": "0.4378",
                    "prev_settlement": "0.4349",
                    "change_close": "0.0029",
                    "volume": "722",
                },
                "90007184": {
                    "open": "0.0007",
                    "high": "0.0007",
                    "low": "0.0003",
                    "close": "0.0005",
                    "prev_settlement": "0.0008",
                    "change_close": "-0.0003",
                    "volume": "120402",
                },
            },
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_option_metadata",
            side_effect=[
                {
                    "contract_name": "沪深300ETF购4月4500",
                    "contract": "159919C2604M004500",
                    "strike_price": "4.5000",
                    "delta": "0",
                    "implied_volatility": "0",
                },
                {
                    "contract_name": "沪深300ETF沽4月4500",
                    "contract": "159919P2604M004500",
                    "strike_price": "4.5000",
                    "delta": "-1",
                    "implied_volatility": "0",
                },
            ],
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_expire_day",
            return_value="2026-04-22",
        ), mock.patch.object(
            source,
            "_prefer_cached_payload",
            side_effect=lambda trade_date, live_payload, min_row_count: live_payload,
        ):
            payload = source.fetch_raw(date(2026, 4, 17))

        content = json.loads(payload.content)
        self.assertEqual(payload.source_type, "fallback_online")
        self.assertEqual(len(content["data"]), 2)
        self.assertEqual(content["data"][0]["contract"], "159919C2604M004500")
        self.assertEqual(content["data"][0]["expire_date"], "2026-04-22")
        self.assertEqual(content["data"][1]["option_type"], "put")

    def test_szse_uses_nearby_cached_underlyings_when_official_summary_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_path = root / "data" / "raw" / "szse" / "options_daily_quotes" / "20260415.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(
                json.dumps(
                    {
                        "data": [
                            {
                                "product_code": "159919",
                                "product_name": "沪深300ETF嘉实期权",
                                "contract": "159919C2604M004500",
                                "underlying_product_code": "159919",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source = SZSEOptionSource(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "option_product_name_map": {"SZSE": {"159919": "沪深300ETF嘉实期权"}},
                },
                logging.getLogger("test-szse-cached-underlyings"),
            )
            with mock.patch("src.futures_workflow.sources.option_szse.PROJECT_ROOT", root), mock.patch.object(
                source, "_load_cached_payload_if_historical", return_value=None
            ), mock.patch.object(
                source, "_fetch_underlying_rows", side_effect=RuntimeError("upstream down")
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.generate_expiry_months",
                return_value=["202604"],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_codes",
                side_effect=[["90007175"], ["90007184"]],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_daily_rows",
                return_value={
                    "90007175": {
                        "open": "0.4306",
                        "high": "0.4378",
                        "low": "0.4274",
                        "close": "0.4378",
                        "prev_settlement": "0.4349",
                        "change_close": "0.0029",
                        "volume": "722",
                    }
                },
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_metadata",
                return_value={
                    "contract_name": "沪深300ETF购4月4500",
                    "contract": "159919C2604M004500",
                    "strike_price": "4.5000",
                    "delta": "0",
                    "implied_volatility": "0",
                },
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_expire_day",
                return_value="2026-04-22",
            ), mock.patch.object(
                source,
                "_prefer_cached_payload",
                side_effect=lambda trade_date, live_payload, min_row_count: live_payload,
            ):
                payload = source.fetch_raw(date(2026, 4, 14))

        content = json.loads(payload.content)
        self.assertEqual(payload.source_type, "fallback_online")
        self.assertEqual(len(content["data"]), 1)
        self.assertEqual(content["data"][0]["underlying_product_code"], "159919")

    def test_szse_uses_configured_underlyings_when_official_and_cached_summary_are_missing(self):
        source = SZSEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "option_product_name_map": {
                    "SZSE": {
                        "159919": "沪深300ETF嘉实期权",
                        "159922": "中证500ETF期权",
                    }
                },
            },
            logging.getLogger("test-szse-config-underlyings"),
        )
        with mock.patch.object(source, "_load_cached_payload_if_historical", return_value=None), mock.patch.object(
            source, "_fetch_underlying_rows", side_effect=RuntimeError("upstream down")
        ), mock.patch.object(
            source, "_load_recent_cached_underlying_rows", return_value=[]
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.generate_expiry_months",
            return_value=["202104"],
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_option_codes",
            side_effect=[["90007175"], [], [], []],
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_option_daily_rows",
            return_value={
                "90007175": {
                    "open": "0.4306",
                    "high": "0.4378",
                    "low": "0.4274",
                    "close": "0.4378",
                    "prev_settlement": "0.4349",
                    "change_close": "0.0029",
                    "volume": "722",
                }
            },
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_option_metadata",
            return_value={
                "contract_name": "沪深300ETF购4月4500",
                "contract": "159919C2604M004500",
                "strike_price": "4.5000",
                "delta": "0",
                "implied_volatility": "0",
            },
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_expire_day",
            return_value="2026-04-22",
        ), mock.patch.object(
            source,
            "_prefer_cached_payload",
            side_effect=lambda trade_date, live_payload, min_row_count: live_payload,
        ):
            payload = source.fetch_raw(date(2026, 4, 17))

        content = json.loads(payload.content)
        self.assertEqual(payload.source_type, "fallback_online")
        self.assertEqual(len(content["data"]), 1)
        self.assertEqual(content["data"][0]["underlying_product_code"], "159919")
        self.assertEqual(content["data"][0]["contract"], "159919C2604M004500")

    def test_szse_uses_cached_symbol_metadata_when_code_discovery_returns_empty(self):
        source = SZSEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "option_product_name_map": {"SZSE": {"159919": "沪深300ETF嘉实期权"}},
            },
            logging.getLogger("test-szse-cached-symbol-metadata"),
        )
        cached_metadata = [
            {
                "symbol": "90007175",
                "contract": "159919C2604M004500",
                "strike_price": "4.5000",
                "delta": "0",
                "implied_volatility": "0",
            }
        ]
        with mock.patch.object(source, "_load_cached_payload_if_historical", return_value=None), mock.patch.object(
            source,
            "_fetch_underlying_rows",
            return_value=[{"bddm": "159919", "bdmc": "沪深300ETF嘉实"}],
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.generate_expiry_months",
            return_value=["202604"],
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_option_codes",
            side_effect=[[], []],
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.iter_cached_sina_option_metadata",
            return_value=iter(cached_metadata),
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_option_daily_rows",
            return_value={
                "90007175": {
                    "open": "0.4306",
                    "high": "0.4378",
                    "low": "0.4274",
                    "close": "0.4378",
                    "prev_settlement": "0.4349",
                    "change_close": "0.0029",
                    "volume": "722",
                }
            },
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_option_metadata",
            return_value={
                "contract_name": "沪深300ETF购4月4500",
                "contract": "159919C2604M004500",
                "strike_price": "4.5000",
                "delta": "0",
                "implied_volatility": "0",
            },
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_expire_day",
            return_value="2026-04-22",
        ), mock.patch.object(
            source,
            "_prefer_cached_payload",
            side_effect=lambda trade_date, live_payload, min_row_count: live_payload,
        ):
            payload = source.fetch_raw(date(2026, 4, 17))

        content = json.loads(payload.content)
        self.assertEqual(len(content["data"]), 1)
        self.assertEqual(content["data"][0]["contract"], "159919C2604M004500")
        self.assertEqual(content["data"][0]["underlying_product_code"], "159919")

    def test_szse_uses_nearby_cached_contract_snapshot_symbols_when_code_discovery_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            contract_cache = root / "data" / "raw" / "szse" / "contracts_snapshot" / "20260416.json"
            contract_cache.parent.mkdir(parents=True, exist_ok=True)
            contract_cache.write_text(
                json.dumps(
                    {
                        "data": {
                            "90007175": {
                                "contract": "159919C2604M004500",
                                "underlying": "159919",
                                "strike_price": "4.5000",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source = SZSEOptionSource(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "option_product_name_map": {"SZSE": {"159919": "沪深300ETF嘉实期权"}},
                },
                logging.getLogger("test-szse-cached-contract-symbols"),
            )
            with mock.patch("src.futures_workflow.sources.option_szse.PROJECT_ROOT", root), mock.patch.object(
                source, "_load_cached_payload_if_historical", return_value=None
            ), mock.patch.object(
                source,
                "_fetch_underlying_rows",
                return_value=[{"bddm": "159919", "bdmc": "沪深300ETF嘉实"}],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.generate_expiry_months",
                return_value=["202604"],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_codes",
                side_effect=[[], []],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_daily_rows",
                return_value={
                    "90007175": {
                        "open": "0.4306",
                        "high": "0.4378",
                        "low": "0.4274",
                        "close": "0.4378",
                        "prev_settlement": "0.4349",
                        "change_close": "0.0029",
                        "volume": "722",
                    }
                },
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_metadata",
                return_value={
                    "contract_name": "沪深300ETF购4月4500",
                    "contract": "159919C2604M004500",
                    "strike_price": "4.5000",
                    "delta": "0",
                    "implied_volatility": "0",
                },
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_expire_day",
                return_value="2026-04-22",
            ), mock.patch.object(
                source,
                "_prefer_cached_payload",
                side_effect=lambda trade_date, live_payload, min_row_count: live_payload,
            ):
                payload = source.fetch_raw(date(2026, 4, 17))

        content = json.loads(payload.content)
        self.assertEqual(len(content["data"]), 1)
        self.assertEqual(content["data"][0]["contract"], "159919C2604M004500")
        self.assertEqual(content["data"][0]["underlying_product_code"], "159919")

    def test_szse_seeds_symbol_metadata_cache_from_nearby_contract_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            contract_cache = root / "data" / "raw" / "szse" / "contracts_snapshot" / "20260416.json"
            contract_cache.parent.mkdir(parents=True, exist_ok=True)
            contract_cache.write_text(
                json.dumps(
                    {
                        "data": {
                            "90007175": {
                                "contract": "159919C2604M004500",
                                "underlying": "159919",
                                "strike_price": "4.5000",
                                "expire_date": "2026-04-22",
                                "last_trade_date": "2026-04-22",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            metadata_root = root / "data" / "raw"
            source = SZSEOptionSource({"user_agent": "ua", "timeout_seconds": 5}, logging.getLogger("test-szse-symbol-cache-seed"))

            with mock.patch("src.futures_workflow.sources.option_szse.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.sources.option_equity_common.RAW_DIR",
                metadata_root,
            ):
                symbols = source._load_recent_cached_symbols_from_contract_dir(
                    trade_date=date(2026, 4, 17),
                    underlying_code="159919",
                    expiry_month="202604",
                    option_type="call",
                )

            cache_path = metadata_root / "equity_options_metadata" / "90007175.json"
            self.assertEqual(symbols, ["90007175"])
            self.assertTrue(cache_path.exists())
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["contract"], "159919C2604M004500")
            self.assertEqual(payload["strike_price"], "4.5000")

    def test_szse_uses_history_cache_symbol_probe_when_other_discovery_paths_are_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            history_root = root / "data" / "raw" / "equity_options_history"
            history_root.mkdir(parents=True, exist_ok=True)
            (history_root / "90007175.json").write_text(
                json.dumps(
                    [{"d": "2026-04-17", "o": "0.4306", "h": "0.4378", "l": "0.4274", "c": "0.4378", "v": "722"}],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source = SZSEOptionSource(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "option_product_name_map": {"SZSE": {"159919": "沪深300ETF嘉实期权"}},
                    "equity_option_history_probe_limit": 5,
                },
                logging.getLogger("test-szse-history-symbol-probe"),
            )
            with mock.patch("src.futures_workflow.sources.option_szse.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.sources.option_equity_common.RAW_DIR",
                root / "data" / "raw",
            ), mock.patch.object(
                source, "_load_cached_payload_if_historical", return_value=None
            ), mock.patch.object(
                source,
                "_fetch_underlying_rows",
                return_value=[{"bddm": "159919", "bdmc": "沪深300ETF嘉实"}],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.generate_expiry_months",
                return_value=["202604"],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_codes",
                side_effect=[[], []],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_metadata",
                return_value={
                    "contract_name": "沪深300ETF购4月4500",
                    "contract": "159919C2604M004500",
                    "strike_price": "4.5000",
                    "delta": "0",
                    "implied_volatility": "0",
                },
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_daily_rows",
                return_value={
                    "90007175": {
                        "open": "0.4306",
                        "high": "0.4378",
                        "low": "0.4274",
                        "close": "0.4378",
                        "prev_settlement": "0.4349",
                        "change_close": "0.0029",
                        "volume": "722",
                    }
                },
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_expire_day",
                return_value="2026-04-22",
            ), mock.patch.object(
                source,
                "_prefer_cached_payload",
                side_effect=lambda trade_date, live_payload, min_row_count: live_payload,
            ):
                payload = source.fetch_raw(date(2026, 4, 17))

        content = json.loads(payload.content)
        self.assertEqual(len(content["data"]), 1)
        self.assertEqual(content["data"][0]["contract"], "159919C2604M004500")

    def test_szse_historical_discovery_seeds_metadata_from_nearby_contract_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            history_root = root / "data" / "raw" / "equity_options_history"
            history_root.mkdir(parents=True, exist_ok=True)
            (history_root / "90007175.json").write_text(
                json.dumps(
                    [{"d": "2026-04-17", "o": "0.4306", "h": "0.4378", "l": "0.4274", "c": "0.4378", "v": "722"}],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            contract_cache = root / "data" / "raw" / "szse" / "contracts_snapshot" / "20260416.json"
            contract_cache.parent.mkdir(parents=True, exist_ok=True)
            contract_cache.write_text(
                json.dumps(
                    {
                        "data": {
                            "90007175": {
                                "contract": "159919C2604M004500",
                                "underlying": "159919",
                                "strike_price": "4.5000",
                                "expire_date": "2026-04-22",
                                "last_trade_date": "2026-04-22",
                            }
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source = SZSEOptionSource(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "option_product_name_map": {"SZSE": {"159919": "沪深300ETF嘉实期权"}},
                    "equity_option_history_probe_limit": 5,
                },
                logging.getLogger("test-szse-history-discovery-seed"),
            )
            with mock.patch("src.futures_workflow.sources.option_szse.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.sources.option_equity_common.RAW_DIR",
                root / "data" / "raw",
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.generate_expiry_months",
                return_value=["202604"],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_codes",
                side_effect=[[], []],
            ):
                symbols, metadata = source._discover_historical_symbols(
                    [{"bddm": "159919", "bdmc": "沪深300ETF嘉实"}],
                    date(2026, 4, 17),
                    offline_only=True,
                    allow_historical_live_metadata_probe=False,
                )

            self.assertEqual(symbols, {"90007175"})
            self.assertEqual(metadata["90007175"]["underlying_code"], "159919")
            self.assertEqual(metadata["90007175"]["contract"], "159919C2604M004500")
            self.assertEqual(metadata["90007175"]["expire_date"], "2026-04-22")
            cache_path = root / "data" / "raw" / "equity_options_metadata" / "90007175.json"
            self.assertTrue(cache_path.exists())
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["contract"], "159919C2604M004500")

    def test_szse_historical_no_symbol_discovery_without_cache_is_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            source = SZSEOptionSource(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "equity_option_allow_historical_live_metadata_probe": False,
                    "option_product_name_map": {"SZSE": {"159919": "沪深300ETF嘉实期权"}},
                },
                logging.getLogger("test-szse-no-symbol-pending"),
            )
            with mock.patch("src.futures_workflow.sources.option_equity_common.RAW_DIR", root / "data" / "raw"), mock.patch.object(
                source,
                "_fetch_historical_contract_map",
                return_value={},
            ), mock.patch.object(
                source,
                "_load_cached_payload_if_historical",
                return_value=None,
            ), mock.patch.object(
                source,
                "_fetch_underlying_rows",
                return_value=[{"bddm": "159919", "bdmc": "沪深300ETF嘉实"}],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.generate_expiry_months",
                return_value=["202104"],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_codes",
                side_effect=[[], []],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.iter_cached_sina_option_metadata",
                return_value=iter([]),
            ), mock.patch.object(
                source,
                "_load_cached_payload",
                side_effect=FileNotFoundError("missing cache"),
            ):
                result = source.run(date(2021, 4, 16))

        self.assertEqual(result.status, "no_data")
        self.assertIn("historical public contract source unavailable", result.message)

    def test_szse_historical_discovery_can_use_limited_live_metadata_probe(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            history_root = root / "data" / "raw" / "equity_options_history"
            history_root.mkdir(parents=True, exist_ok=True)
            (history_root / "10002859.json").write_text(
                json.dumps(
                    [{"d": "2021-04-16", "o": "0.10", "h": "0.12", "l": "0.09", "c": "0.11", "v": "88"}],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source = SZSEOptionSource(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "option_product_name_map": {"SZSE": {"159919": "沪深300ETF嘉实期权"}},
                    "equity_option_history_probe_limit": 5,
                    "equity_option_allow_historical_live_metadata_probe": True,
                    "equity_option_historical_probe_timeout_seconds": 3,
                },
                logging.getLogger("test-szse-historical-live-metadata-probe"),
            )
            metadata_fetch = mock.Mock(
                return_value={
                    "contract_name": "沪深300ETF购4月5000",
                    "contract": "159919C2104M005000",
                    "strike_price": "5.0000",
                    "delta": "0",
                    "implied_volatility": "0",
                }
            )
            with mock.patch("src.futures_workflow.sources.option_szse.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.sources.option_equity_common.RAW_DIR",
                root / "data" / "raw",
            ), mock.patch.object(
                source,
                "_fetch_historical_contract_map",
                return_value={},
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.generate_expiry_months",
                return_value=["202104"],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_codes",
                side_effect=[[], []],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_metadata",
                metadata_fetch,
            ):
                symbols, metadata = source._discover_historical_symbols(
                    [{"bddm": "159919", "bdmc": "沪深300ETF嘉实"}],
                    date(2021, 4, 16),
                    offline_only=True,
                    allow_historical_live_metadata_probe=True,
                )

            self.assertEqual(symbols, {"10002859"})
            self.assertEqual(metadata["10002859"]["underlying_code"], "159919")
            self.assertEqual(metadata_fetch.call_args.args[2], 3)

    def test_szse_historical_discovery_can_reconstruct_symbols_from_history_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            history_root = root / "data" / "raw" / "equity_options_history"
            history_root.mkdir(parents=True, exist_ok=True)
            samples = {
                "10000001": [
                    {"d": "2021-03-25", "o": "0.31", "h": "0.32", "l": "0.30", "c": "0.31", "v": "10"},
                    {"d": "2021-04-16", "o": "0.30", "h": "0.31", "l": "0.29", "c": "0.30", "v": "11"},
                    {"d": "2021-06-23", "o": "0.01", "h": "0.01", "l": "0.01", "c": "0.01", "v": "2"},
                ],
                "10000002": [
                    {"d": "2021-03-25", "o": "0.21", "h": "0.22", "l": "0.20", "c": "0.21", "v": "9"},
                    {"d": "2021-04-16", "o": "0.20", "h": "0.21", "l": "0.19", "c": "0.20", "v": "10"},
                    {"d": "2021-06-23", "o": "0.01", "h": "0.01", "l": "0.01", "c": "0.01", "v": "2"},
                ],
                "10000003": [
                    {"d": "2021-03-25", "o": "0.05", "h": "0.06", "l": "0.04", "c": "0.05", "v": "9"},
                    {"d": "2021-04-16", "o": "0.08", "h": "0.09", "l": "0.07", "c": "0.08", "v": "10"},
                    {"d": "2021-06-23", "o": "0.30", "h": "0.31", "l": "0.29", "c": "0.30", "v": "2"},
                ],
                "10000004": [
                    {"d": "2021-03-25", "o": "0.09", "h": "0.10", "l": "0.08", "c": "0.09", "v": "9"},
                    {"d": "2021-04-16", "o": "0.12", "h": "0.13", "l": "0.11", "c": "0.12", "v": "10"},
                    {"d": "2021-06-23", "o": "0.34", "h": "0.35", "l": "0.33", "c": "0.34", "v": "2"},
                ],
            }
            for symbol, rows in samples.items():
                (history_root / f"{symbol}.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            source = SZSEOptionSource(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "option_product_name_map": {"SZSE": {"159919": "沪深300ETF嘉实期权"}},
                },
                logging.getLogger("test-szse-history-reconstruct"),
            )
            with mock.patch("src.futures_workflow.sources.option_szse.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.sources.option_equity_common.RAW_DIR",
                root / "data" / "raw",
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.generate_expiry_months",
                return_value=["202104"],
            ), mock.patch.object(
                source,
                "_fetch_historical_contract_map",
                return_value={},
            ):
                symbols, metadata = source._discover_historical_symbols(
                    [{"bddm": "159919", "bdmc": "沪深300ETF嘉实"}],
                    date(2021, 4, 16),
                    offline_only=True,
                    allow_historical_live_metadata_probe=False,
                )

            self.assertEqual(symbols, {"10000001", "10000002", "10000003", "10000004"})
            self.assertEqual(metadata["10000001"]["contract"], "10000001")
            self.assertEqual(metadata["10000001"]["expire_date"], "2021-06-23")
            self.assertEqual(metadata["10000001"]["option_type"], "call")
            self.assertEqual(metadata["10000003"]["option_type"], "put")
            self.assertEqual(metadata["10000001"]["formal_contract_unavailable"], "true")

    def test_szse_fetch_raw_can_materialize_reconstructed_historical_metadata(self):
        source = SZSEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "option_product_name_map": {"SZSE": {"159919": "沪深300ETF嘉实期权"}},
            },
            logging.getLogger("test-szse-reconstructed-fetch"),
        )
        cached = RawPayload(
            content=json.dumps({"data": [{"contract": "159919C2104M005000"}]}, ensure_ascii=False),
            url="cached://szse",
            extension="json",
            source_type="fallback_online",
        )
        with mock.patch.object(source, "_load_cached_payload_if_historical", return_value=cached), mock.patch.object(
            source,
            "_fetch_underlying_rows",
            return_value=[{"bddm": "159919", "bdmc": "沪深300ETF嘉实"}],
        ), mock.patch.object(
            source,
            "_discover_historical_symbols",
            return_value=(
                {"10000001"},
                {
                    "10000001": {
                        "contract": "10000001",
                        "underlying_product_code": "159919",
                        "underlying_code": "159919",
                        "underlying_name": "沪深300ETF嘉实",
                        "option_type": "call",
                        "expire_date": "2021-06-23",
                        "last_trade_date": "2021-06-23",
                        "exercise_type": "european",
                        "underlying_kind": "etf",
                        "formal_contract_unavailable": "true",
                        "reconstruction_method": "history_expire_cluster",
                    }
                },
            ),
        ), mock.patch(
            "src.futures_workflow.sources.option_szse.fetch_sina_option_daily_rows",
            return_value={
                "10000001": {
                    "open": "0.30",
                    "high": "0.31",
                    "low": "0.29",
                    "close": "0.30",
                    "prev_settlement": "0.31",
                    "change_close": "-0.01",
                    "volume": "11",
                }
            },
        ), mock.patch.object(
            source,
            "_prefer_cached_payload",
            side_effect=lambda trade_date, live_payload, min_row_count: live_payload,
        ):
            payload = source.fetch_raw(date(2021, 4, 16))

        content = json.loads(payload.content)
        self.assertEqual(payload.source_type, "fallback_online")
        self.assertNotEqual(payload.url, "cached://szse")
        self.assertEqual(content["data"][0]["contract"], "10000001")
        self.assertEqual(content["data"][0]["option_type"], "call")
        self.assertEqual(content["data"][0]["expire_date"], "2021-06-23")
        self.assertEqual(content["data"][0]["metadata"]["formal_contract_unavailable"], "true")

    def test_szse_history_probe_respects_historical_budget(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            history_root = root / "data" / "raw" / "equity_options_history"
            history_root.mkdir(parents=True, exist_ok=True)
            for symbol in ("10002859", "10002860"):
                (history_root / f"{symbol}.json").write_text(
                    json.dumps(
                        [{"d": "2021-04-16", "o": "0.10", "h": "0.12", "l": "0.09", "c": "0.11", "v": "88"}],
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
            source = SZSEOptionSource(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "equity_option_historical_probe_limit": 10,
                    "equity_option_historical_probe_budget_seconds": 0.1,
                },
                logging.getLogger("test-szse-history-budget"),
            )
            with mock.patch("src.futures_workflow.sources.option_equity_common.RAW_DIR", root / "data" / "raw"), mock.patch(
                "src.futures_workflow.sources.option_szse.PROJECT_ROOT",
                root,
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.time.monotonic",
                side_effect=[0.0, 0.11, 0.12],
            ), mock.patch(
                "src.futures_workflow.sources.option_szse.fetch_sina_option_metadata",
                side_effect=AssertionError("budget should stop before live metadata probe"),
            ):
                symbols = source._probe_history_cached_symbols(
                    trade_date=date(2021, 4, 16),
                    underlying_code="159919",
                    expiry_month="202104",
                    option_type="call",
                    allow_live_metadata_probe=True,
                )

            self.assertEqual(symbols, [])

    def test_sse_uses_nearby_cached_contract_snapshot_when_risk_fetch_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_path = root / "data" / "raw" / "sse" / "contracts_snapshot" / "20260416.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(
                json.dumps(
                    {
                        "result": [
                            {
                                "SECURITY_ID": "10000001",
                                "CONTRACT_ID": "510050C2604M02650",
                                "DELTA_VALUE": "0.990",
                                "IMPLC_VOLATLTY": "0.443",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            source = SSEOptionSource(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "option_product_name_map": {"SSE": {"510050": "上证50ETF期权"}},
                },
                logging.getLogger("test-sse-cached-contract-snapshot"),
            )
            with mock.patch("src.futures_workflow.sources.option_sse.PROJECT_ROOT", root), mock.patch.object(
                source, "_load_cached_payload_if_historical", return_value=None
            ), mock.patch.object(
                source, "_should_try_official_current", return_value=False
            ), mock.patch.object(
                source, "_fetch_risk_rows", side_effect=RuntimeError("upstream down")
            ), mock.patch(
                "src.futures_workflow.sources.option_sse.fetch_sina_option_daily_rows",
                return_value={
                    "10000001": {
                        "open": "0.3300",
                        "high": "0.3400",
                        "low": "0.3200",
                        "close": "0.3342",
                        "prev_settlement": "0.3652",
                        "change_close": "-0.031",
                        "volume": "1024",
                    }
                },
            ), mock.patch(
                "src.futures_workflow.sources.option_sse.fetch_sina_expire_day",
                return_value="2026-04-22",
            ), mock.patch.object(
                source,
                "_prefer_cached_payload",
                side_effect=lambda trade_date, live_payload, min_row_count: live_payload,
            ):
                payload = source.fetch_raw(date(2026, 4, 17))

        content = json.loads(payload.content)
        self.assertEqual(len(content["data"]), 1)
        self.assertEqual(content["data"][0]["contract"], "510050C2604M02650")
        self.assertEqual(content["data"][0]["product_code"], "510050")

    def test_sse_discovered_contracts_without_quote_rows_is_pending_retry(self):
        source = SSEOptionSource(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "option_product_name_map": {"SSE": {"510050": "上证50ETF期权"}},
            },
            logging.getLogger("test-sse-no-quote-rows-pending"),
        )
        with mock.patch.object(source, "_load_cached_payload_if_historical", return_value=None), mock.patch.object(
            source, "_should_try_official_current", return_value=False
        ), mock.patch.object(
            source,
            "_fetch_risk_rows",
            return_value=[
                {
                    "SECURITY_ID": "10000001",
                    "CONTRACT_ID": "510050C2604M02650",
                    "DELTA_VALUE": "0.990",
                    "IMPLC_VOLATLTY": "0.443",
                }
            ],
        ), mock.patch(
            "src.futures_workflow.sources.option_sse.fetch_sina_option_daily_rows",
            return_value={},
        ), mock.patch.object(
            source,
            "_load_cached_payload",
            side_effect=FileNotFoundError("missing cache"),
        ):
            result = source.run(date(2026, 4, 17))

        self.assertEqual(result.status, "pending_retry")
        self.assertIn("returned no rows", result.message)

    def test_dce_prefers_cached_historical_payload(self):
        source = DCEOptionSource({"user_agent": "ua", "timeout_seconds": 5}, logging.getLogger("test-dce-cache"))
        cached = RawPayload(content='{"data":[]}', url="cached://dce", extension="json", source_type="fallback_online")
        with mock.patch.object(source, "_load_cached_payload_if_historical", return_value=cached), mock.patch.object(
            source, "_fetch_official_raw", side_effect=AssertionError("should not fetch live DCE data when cached payload exists")
        ):
            payload = source.fetch_raw(date(2026, 4, 16))
        self.assertEqual(payload.url, "cached://dce")

    def test_dce_uses_available_sina_contract_tables_when_needed(self):
        source = DCEOptionSource({"user_agent": "ua", "timeout_seconds": 5}, logging.getLogger("test-dce-sina-contract-table"))
        fake_contracts = mock.Mock()
        fake_contracts.get.return_value.tolist.return_value = ["m2609"]
        fake_table = mock.Mock()
        fake_table.to_dict.return_value = [
            {
                "行权价": "2500",
                "看涨合约-看涨期权合约": "m2609C2500",
                "看涨合约-持仓量": "234",
                "看跌合约-看跌期权合约": "m2609P2500",
                "看跌合约-持仓量": "5367",
            }
        ]

        with mock.patch("src.futures_workflow.sources.option_dce.ak.option_commodity_contract_sina", return_value=fake_contracts), mock.patch(
            "src.futures_workflow.sources.option_dce.ak.option_commodity_contract_table_sina",
            return_value=fake_table,
        ):
            rows = source._fetch_contract_tables_from_available_contracts(date(2026, 4, 17), {"M": "豆粕期权"})

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["underlying_contract"], "M2609")
        self.assertEqual(rows[0]["product_code"], "M")

    def test_dce_recent_snapshot_uses_current_contract_table_without_history_fanout(self):
        source = DCEOptionSource({"user_agent": "ua", "timeout_seconds": 5}, logging.getLogger("test-dce-recent-snapshot"))
        contract_rows = [
            {
                "underlying_contract": "M2609",
                "product_code": "M",
                "product_name": "豆粕期权",
                "行权价": "2500",
                "看涨合约-看涨期权合约": "m2609C2500",
                "看涨合约-最新价": "88.5",
                "看涨合约-涨跌": "1.0",
                "看涨合约-持仓量": "234",
                "看跌合约-看跌期权合约": "m2609P2500",
                "看跌合约-最新价": "12.5",
                "看跌合约-涨跌": "-0.5",
                "看跌合约-持仓量": "5367",
            }
        ]
        with mock.patch.object(source, "_fetch_contract_tables_from_available_contracts", return_value=contract_rows), mock.patch.object(
            source, "_prefer_cached_payload", side_effect=lambda trade_date, live_payload, live_row_count: live_payload
        ):
            payload = source._fetch_recent_snapshot_fallback_raw(date(2026, 4, 17))

        content = json.loads(payload.content)
        self.assertEqual(payload.source_type, "fallback_online")
        self.assertEqual(len(content["data"]), 2)
        self.assertEqual(content["data"][0]["metadata"]["quote_mode"], "recent_snapshot")
        self.assertEqual(content["data"][0]["close"], "88.5")

    def test_dce_history_row_prefers_contract_cache(self):
        source = DCEOptionSource({"user_agent": "ua", "timeout_seconds": 5}, logging.getLogger("test-dce-history-cache"))
        cached_series = [
            {"d": "2026-04-16", "o": "1", "h": "2", "l": "1", "c": "1.5", "v": "5"},
            {"d": "2026-04-17", "o": "2", "h": "3", "l": "2", "c": "2.5", "v": "6"},
        ]
        with mock.patch.object(source, "_history_cache_path") as history_cache_path, mock.patch.object(
            source.session, "request", side_effect=AssertionError("cache hit should not issue live request")
        ):
            fake_path = mock.Mock()
            fake_path.exists.return_value = True
            fake_path.read_text.return_value = json.dumps(cached_series, ensure_ascii=False)
            history_cache_path.return_value = fake_path
            row = source._load_history_row("M2609C2500", date(2026, 4, 17))

        self.assertEqual(row["close"], "2.5")
        self.assertEqual(row["prev_close"], "1.5")


if __name__ == "__main__":
    unittest.main()
