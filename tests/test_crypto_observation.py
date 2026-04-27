import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.crypto_observation import CryptoObservationRunner


class _FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class CryptoObservationRunnerTests(unittest.TestCase):
    def test_sync_writes_all_crypto_datasets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "crypto_global.json"
            runner = CryptoObservationRunner(state_path=state_path)
            markets_payload = [
                {
                    "id": "bitcoin",
                    "symbol": "btc",
                    "name": "Bitcoin",
                    "current_price": 75286,
                    "price_change_24h": -1784.45,
                    "price_change_percentage_24h": -2.31,
                    "high_24h": 77095,
                    "low_24h": 75271,
                    "total_volume": 49810566286,
                    "market_cap": 1506768120286,
                    "market_cap_rank": 1,
                    "circulating_supply": 20017871,
                    "total_supply": 20017871,
                    "max_supply": 21000000,
                }
            ]
            history_payload = {
                "symbol": "btc",
                "name": "Bitcoin",
                "market_data": {
                    "current_price": {"usd": 75286},
                    "market_cap": {"usd": 1506768120286},
                    "total_volume": {"usd": 49810566286},
                },
            }
            derivatives_payload = [
                {
                    "market": "CME Group",
                    "symbol": "BTC",
                    "index_id": "BTC",
                    "price": "75286",
                    "contract_type": "future",
                    "index": 75300,
                    "basis": 14,
                    "spread": 1,
                    "funding_rate": None,
                    "open_interest": 123456789,
                    "volume_24h": 99887766,
                    "last_traded_at": 1776610229,
                }
            ]
            bitcoin_holdings_payload = {
                "records": [
                    {
                        "代码": "MSTR:NADQ",
                        "公司名称-英文": "MicroStrategy",
                        "公司名称-中文": "",
                        "国家/地区": "美国",
                        "市值": 1000000000,
                        "比特币占市值比重": 0.3,
                        "持仓成本": 900000000,
                        "持仓占比": 0.725,
                        "持仓量": 152333,
                        "当日持仓市值": 4624824000,
                        "查询日期": "2023-07-13",
                        "公告链接": "Filing",
                        "分类": "上市公司",
                    }
                ],
                "retrieved_at": "2026-04-19T18:00:00+08:00",
            }
            cme_report_payload = {
                "records": [
                    {
                        "商品": "比特币",
                        "类型": "期货",
                        "电子交易合约": 7895,
                        "场内成交合约": "",
                        "场外成交合约": 366,
                        "成交量": 8261,
                        "未平仓合约": 15408,
                        "持仓变化": -764,
                    }
                ],
                "retrieved_at": "2026-04-19T18:00:00+08:00",
                "source_trade_date": "20260419",
            }

            def fake_urlopen(request, timeout=20):
                url = request.full_url
                if "coins/markets" in url:
                    return _FakeResponse(markets_payload)
                if "coins/bitcoin/history" in url:
                    return _FakeResponse(history_payload)
                if "derivatives" in url:
                    return _FakeResponse(derivatives_payload)
                raise AssertionError(f"Unexpected url: {url}")

            with mock.patch("src.futures_workflow.crypto_observation.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.crypto_observation.CRYPTO_NORMALIZED_DIR", root / "data" / "normalized" / "crypto_global"
            ), mock.patch(
                "src.futures_workflow.crypto_observation.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.crypto_observation.DEFAULT_COIN_IDS", ["bitcoin"]
            ), mock.patch(
                "src.futures_workflow.crypto_observation.urlopen", side_effect=fake_urlopen
            ), mock.patch(
                "src.futures_workflow.crypto_observation.CryptoObservationRunner._fetch_bitcoin_holdings_payload",
                return_value=bitcoin_holdings_payload,
            ), mock.patch(
                "src.futures_workflow.crypto_observation.CryptoObservationRunner._fetch_cme_bitcoin_report_payload",
                return_value=cme_report_payload,
            ), mock.patch(
                "src.futures_workflow.crypto_observation.now_shanghai"
            ) as mock_now:
                import datetime
                from zoneinfo import ZoneInfo

                mock_now.return_value = datetime.datetime(2026, 4, 19, 18, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
                result = runner.sync("latest")

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["datasets"]["crypto_global_snapshot"]["row_count"], 1)
            self.assertEqual(result["datasets"]["crypto_assets"]["row_count"], 1)
            self.assertEqual(result["datasets"]["crypto_daily_quotes"]["row_count"], 1)
            self.assertEqual(result["datasets"]["crypto_derivatives_public"]["row_count"], 1)
            self.assertEqual(result["datasets"]["crypto_bitcoin_holdings_public"]["row_count"], 1)
            self.assertEqual(result["datasets"]["crypto_cme_bitcoin_report"]["row_count"], 1)
            output_path = root / result["datasets"]["crypto_daily_quotes"]["output_path"]
            self.assertTrue(output_path.exists())

    def test_validate_reports_schema_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "crypto_global.json"
            output_path = root / "data" / "normalized" / "crypto_global" / "crypto_global_snapshot" / "2026-04-19.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "trade_date,asset_family,market,exchange,symbol,name,price_usd,change_amount_24h,change_pct_24h,high_24h,low_24h,total_volume,market_cap,market_cap_rank,circulating_supply,total_supply,max_supply,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id,legal_note\n"
                "2026-04-19,crypto_global_observation,global_crypto,COINGECKO,BTC,Bitcoin,75286,-1784.45,-2.31,77095,75271,49810566286,1506768120286,1,20017871,20017871,21000000,coingecko.coins_markets_public,https://api.coingecko.com/api/v3/coins/markets,fallback_online,2026-04-19T18:00:00+08:00,data/raw/crypto_global/crypto_global_snapshot/20260419.json,crypto_observation_v1,abc,run1,仅作全球公开市场数据研究与行情观察，不提供交易、撮合、开户、引流或任何境内虚拟货币经营服务。\n",
                encoding="utf-8-sig",
            )
            raw_path = root / "data" / "raw" / "crypto_global" / "crypto_global_snapshot" / "20260419.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(json.dumps({"records": []}, ensure_ascii=False), encoding="utf-8")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "dates": {
                            "2026-04-19": {
                                "status": "success",
                                "datasets": {
                                    "crypto_global_snapshot": {
                                        "dataset": "crypto_global_snapshot",
                                        "output_path": "data/normalized/crypto_global/crypto_global_snapshot/2026-04-19.csv",
                                        "status": "success",
                                    }
                                },
                            }
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            with mock.patch("src.futures_workflow.crypto_observation.PROJECT_ROOT", root):
                runner = CryptoObservationRunner(state_path=state_path)
                result = runner.validate("2026-04-19")

            self.assertTrue(result["datasets"]["crypto_global_snapshot"]["schema_ok"])
            self.assertEqual(result["datasets"]["crypto_global_snapshot"]["row_count"], 1)

    def test_derivatives_public_can_fallback_to_cme_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "crypto_global.json"
            runner = CryptoObservationRunner(state_path=state_path)
            markets_payload = [
                {
                    "id": "bitcoin",
                    "symbol": "btc",
                    "name": "Bitcoin",
                    "current_price": 75286,
                    "price_change_24h": -1784.45,
                    "price_change_percentage_24h": -2.31,
                    "high_24h": 77095,
                    "low_24h": 75271,
                    "total_volume": 49810566286,
                    "market_cap": 1506768120286,
                    "market_cap_rank": 1,
                    "circulating_supply": 20017871,
                    "total_supply": 20017871,
                    "max_supply": 21000000,
                }
            ]
            history_payload = {
                "symbol": "btc",
                "name": "Bitcoin",
                "market_data": {
                    "current_price": {"usd": 75286},
                    "market_cap": {"usd": 1506768120286},
                    "total_volume": {"usd": 49810566286},
                },
            }
            bitcoin_holdings_payload = {
                "records": [],
                "retrieved_at": "2026-04-19T18:00:00+08:00",
            }
            cme_report_payload = {
                "records": [
                    {
                        "商品": "比特币",
                        "类型": "期货",
                        "电子交易合约": 7895,
                        "场内成交合约": "",
                        "场外成交合约": 366,
                        "成交量": 8261,
                        "未平仓合约": 15408,
                        "持仓变化": -764,
                    }
                ],
                "retrieved_at": "2026-04-19T18:00:00+08:00",
                "source_trade_date": "20260419",
            }

            def fake_urlopen(request, timeout=20):
                url = request.full_url
                if "coins/markets" in url:
                    return _FakeResponse(markets_payload)
                if "coins/bitcoin/history" in url:
                    return _FakeResponse(history_payload)
                if "derivatives" in url:
                    raise RuntimeError("HTTP 429")
                raise AssertionError(f"Unexpected url: {url}")

            with mock.patch("src.futures_workflow.crypto_observation.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.crypto_observation.CRYPTO_NORMALIZED_DIR", root / "data" / "normalized" / "crypto_global"
            ), mock.patch(
                "src.futures_workflow.crypto_observation.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.crypto_observation.DEFAULT_COIN_IDS", ["bitcoin"]
            ), mock.patch(
                "src.futures_workflow.crypto_observation.urlopen", side_effect=fake_urlopen
            ), mock.patch(
                "src.futures_workflow.crypto_observation.CryptoObservationRunner._fetch_bitcoin_holdings_payload",
                return_value=bitcoin_holdings_payload,
            ), mock.patch(
                "src.futures_workflow.crypto_observation.CryptoObservationRunner._fetch_cme_bitcoin_report_payload",
                return_value=cme_report_payload,
            ), mock.patch(
                "src.futures_workflow.crypto_observation.now_shanghai"
            ) as mock_now:
                import datetime
                from zoneinfo import ZoneInfo

                mock_now.return_value = datetime.datetime(2026, 4, 19, 18, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
                result = runner.sync("latest")

            derivatives_summary = result["datasets"]["crypto_derivatives_public"]
            self.assertEqual(derivatives_summary["status"], "success")
            self.assertEqual(derivatives_summary["row_count"], 1)
            self.assertEqual(derivatives_summary["source_url"], "https://datacenter.jin10.com/reportType/dc_cme_btc_report")
            csv_path = root / derivatives_summary["output_path"]
            rows = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("CME", rows)
            self.assertIn("BTC-FUTURES", rows)

    def test_derivatives_public_can_fallback_to_okx_swaps_when_coingecko_and_cme_unavailable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "crypto_global.json"
            runner = CryptoObservationRunner(state_path=state_path)
            markets_payload = [
                {
                    "id": "bitcoin",
                    "symbol": "btc",
                    "name": "Bitcoin",
                    "current_price": 75286,
                    "price_change_24h": -1784.45,
                    "price_change_percentage_24h": -2.31,
                    "high_24h": 77095,
                    "low_24h": 75271,
                    "total_volume": 49810566286,
                    "market_cap": 1506768120286,
                    "market_cap_rank": 1,
                    "circulating_supply": 20017871,
                    "total_supply": 20017871,
                    "max_supply": 21000000,
                }
            ]
            history_payload = {
                "symbol": "btc",
                "name": "Bitcoin",
                "market_data": {
                    "current_price": {"usd": 75286},
                    "market_cap": {"usd": 1506768120286},
                    "total_volume": {"usd": 49810566286},
                },
            }
            okx_tickers_payload = {
                "data": [
                    {
                        "instId": "BTC-USDT-SWAP",
                        "last": "75286",
                        "askPx": "75290",
                        "bidPx": "75280",
                        "volCcy24h": "99887766",
                        "ts": "1776610229000",
                    },
                    {
                        "instId": "ETH-USDT-SWAP",
                        "last": "3600",
                        "askPx": "3601",
                        "bidPx": "3599",
                        "volCcy24h": "12345678",
                        "ts": "1776610229000",
                    },
                ]
            }
            okx_instruments_payload = {
                "data": [
                    {"instId": "BTC-USDT-SWAP", "uly": "BTC-USDT", "state": "live"},
                    {"instId": "ETH-USDT-SWAP", "uly": "ETH-USDT", "state": "live"},
                ]
            }
            bitcoin_holdings_payload = {"records": [], "retrieved_at": "2026-04-19T18:00:00+08:00"}
            cme_report_payload = {"records": [], "retrieved_at": "2026-04-19T18:00:00+08:00", "source_trade_date": "20260419"}

            def fake_urlopen(request, timeout=20):
                url = request.full_url
                if "coins/markets" in url:
                    return _FakeResponse(markets_payload)
                if "coins/bitcoin/history" in url:
                    return _FakeResponse(history_payload)
                if "api.coingecko.com/api/v3/derivatives" in url:
                    raise RuntimeError("HTTP 429")
                if "okx.com/api/v5/market/tickers" in url:
                    return _FakeResponse(okx_tickers_payload)
                if "okx.com/api/v5/public/instruments" in url:
                    return _FakeResponse(okx_instruments_payload)
                raise AssertionError(f"Unexpected url: {url}")

            with mock.patch("src.futures_workflow.crypto_observation.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.crypto_observation.CRYPTO_NORMALIZED_DIR", root / "data" / "normalized" / "crypto_global"
            ), mock.patch(
                "src.futures_workflow.crypto_observation.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.crypto_observation.DEFAULT_COIN_IDS", ["bitcoin"]
            ), mock.patch(
                "src.futures_workflow.crypto_observation.urlopen", side_effect=fake_urlopen
            ), mock.patch(
                "src.futures_workflow.crypto_observation.CryptoObservationRunner._fetch_bitcoin_holdings_payload",
                return_value=bitcoin_holdings_payload,
            ), mock.patch(
                "src.futures_workflow.crypto_observation.CryptoObservationRunner._fetch_cme_bitcoin_report_payload",
                return_value=cme_report_payload,
            ), mock.patch(
                "src.futures_workflow.crypto_observation.now_shanghai"
            ) as mock_now:
                import datetime
                from zoneinfo import ZoneInfo

                mock_now.return_value = datetime.datetime(2026, 4, 19, 18, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
                result = runner.sync("latest")

            derivatives_summary = result["datasets"]["crypto_derivatives_public"]
            self.assertEqual(derivatives_summary["status"], "success")
            self.assertEqual(derivatives_summary["source_url"], "https://www.okx.com/api/v5/market/tickers?instType=SWAP")
            csv_path = root / derivatives_summary["output_path"]
            rows = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("OKX", rows)
            self.assertIn("BTC-USDT-SWAP", rows)

    def test_historical_uncached_returns_not_applicable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "crypto_global.json"
            runner = CryptoObservationRunner(state_path=state_path)
            with mock.patch("src.futures_workflow.crypto_observation.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.crypto_observation.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.crypto_observation.now_shanghai"
            ) as mock_now:
                import datetime
                from zoneinfo import ZoneInfo

                mock_now.return_value = datetime.datetime(2026, 4, 19, 18, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
                result = runner.sync("2026-04-18")

            self.assertEqual(result["datasets"]["crypto_global_snapshot"]["status"], "not_applicable")
            self.assertEqual(result["datasets"]["crypto_assets"]["status"], "not_applicable")
            self.assertEqual(result["datasets"]["crypto_bitcoin_holdings_public"]["status"], "not_applicable")

    def test_latest_summaries_returns_all_known_crypto_datasets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "crypto_global.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "dates": {
                            "2026-04-19": {
                                "status": "success",
                                "datasets": {
                                    "crypto_global_snapshot": {"dataset": "crypto_global_snapshot", "status": "success", "row_count": 7, "trade_date": "2026-04-19"},
                                    "crypto_assets": {"dataset": "crypto_assets", "status": "success", "row_count": 7, "trade_date": "2026-04-19"},
                                    "crypto_bitcoin_holdings_public": {"dataset": "crypto_bitcoin_holdings_public", "status": "success", "row_count": 59, "trade_date": "2026-04-19"},
                                    "crypto_cme_bitcoin_report": {"dataset": "crypto_cme_bitcoin_report", "status": "success", "row_count": 5, "trade_date": "2023-08-30"},
                                },
                            }
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            runner = CryptoObservationRunner(state_path=state_path)
            summaries = runner.latest_summaries()
            self.assertIn("crypto_global_snapshot", summaries)
            self.assertIn("crypto_assets", summaries)
            self.assertIn("crypto_bitcoin_holdings_public", summaries)
            self.assertIn("crypto_cme_bitcoin_report", summaries)


if __name__ == "__main__":
    unittest.main()
