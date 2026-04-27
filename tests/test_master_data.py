import logging
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.master_data import ContractMasterCollector
from src.futures_workflow.models import OptionQuoteRow


class ContractMasterCollectorTests(unittest.TestCase):
    def test_collect_cffex_official_metadata_derives_underlying_contract(self):
        collector = ContractMasterCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
            },
            logging.getLogger("test-master-data-cffex"),
        )
        option_row = OptionQuoteRow(
            trade_date="2026-04-16",
            exchange="CFFEX",
            product_code="HO",
            product_name="上证50股指期权",
            contract="HO2604-C-2500",
            underlying_exchange="CFFEX",
            underlying_kind="index",
            underlying_product_code="HO",
            underlying_contract="",
            option_type="call",
            strike_price="2500",
            exercise_type="european",
            expire_date="2026-04-17",
            last_trade_date="2026-04-17",
            open="10",
            high="12",
            low="8",
            close="11",
            prev_settlement="9",
            settlement="10",
            change_close="2",
            change_settlement="1",
            volume="100",
            open_interest="200",
            open_interest_change="20",
            turnover="1000",
            delta="0.55",
            implied_volatility="",
            exercise_volume="",
            source_url="official://cffex",
            source_type="official",
            retrieved_at="2026-04-18T00:00:00+08:00",
            raw_path="data/raw/cffex/options_daily_quotes/20260416.xml",
        )
        metadata = collector.collect(date(2026, 4, 16), futures_rows=[], options_rows=[option_row])
        key = ("option", "CFFEX", "HO2604-C-2500")
        self.assertIn(key, metadata)
        self.assertEqual(metadata[key]["underlying_product_code"], "IH")
        self.assertEqual(metadata[key]["underlying_contract"], "IH2604")

    def test_collect_dce_fallback_option_metadata_keeps_fallback_provenance(self):
        collector = ContractMasterCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
            },
            logging.getLogger("test-master-data-dce-fallback"),
        )
        option_row = OptionQuoteRow(
            trade_date="2026-04-16",
            exchange="DCE",
            product_code="A",
            product_name="豆一期权",
            contract="A2605C4100",
            underlying_exchange="DCE",
            underlying_kind="futures",
            underlying_product_code="A",
            underlying_contract="A2605",
            option_type="call",
            strike_price="4100",
            exercise_type="american",
            expire_date="",
            last_trade_date="",
            open="1",
            high="2",
            low="0.5",
            close="1.5",
            prev_settlement="1.2",
            settlement="1.4",
            change_close="0.3",
            change_settlement="0.2",
            volume="10",
            open_interest="20",
            open_interest_change="2",
            turnover="30",
            delta="",
            implied_volatility="",
            exercise_volume="",
            source_url="fallback://dce",
            source_type="fallback_online",
            retrieved_at="2026-04-18T00:00:00+08:00",
            raw_path="data/raw/dce/options_daily_quotes/20260416.json",
        )
        metadata = collector.collect(date(2026, 4, 16), futures_rows=[], options_rows=[option_row])
        key = ("option", "DCE", "A2605C4100")
        self.assertIn(key, metadata)
        self.assertEqual(metadata[key]["option_type"], "call")
        self.assertEqual(metadata[key]["underlying_contract"], "A2605")
        self.assertEqual(metadata[key]["source_type"], "fallback_online")

    def test_collect_sse_official_metadata_for_fallback_quotes(self):
        collector = ContractMasterCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "option_product_name_map": {"SSE": {"510050": "上证50ETF期权"}},
            },
            logging.getLogger("test-master-data-sse"),
        )
        option_row = OptionQuoteRow(
            trade_date="2026-04-16",
            exchange="SSE",
            product_code="510050",
            product_name="上证50ETF期权",
            contract="510050C2604M02650",
            underlying_exchange="SSE",
            underlying_kind="etf",
            underlying_product_code="510050",
            underlying_contract="510050",
            option_type="call",
            strike_price="2.6500",
            exercise_type="european",
            expire_date="2026-04-22",
            last_trade_date="2026-04-22",
            open="0.35",
            high="0.36",
            low="0.33",
            close="0.34",
            prev_settlement="0.31",
            settlement="",
            change_close="0.03",
            change_settlement="",
            volume="123",
            open_interest="",
            open_interest_change="",
            turnover="",
            delta="0.98",
            implied_volatility="0.41",
            exercise_volume="",
            source_url="fallback://daily",
            source_type="fallback_online",
            retrieved_at="2026-04-18T00:00:00+08:00",
            raw_path="data/raw/sse/options_daily_quotes/20260416.json",
        )
        with mock.patch.object(
            collector._sse_source,
            "_fetch_risk_rows",
            return_value=[{"SECURITY_ID": "10000001", "CONTRACT_ID": "510050C2604M02650"}],
        ):
            metadata = collector.collect(date(2026, 4, 16), futures_rows=[], options_rows=[option_row])
        key = ("option", "SSE", "510050C2604M02650")
        self.assertIn(key, metadata)
        self.assertEqual(metadata[key]["source_type"], "official")
        self.assertEqual(metadata[key]["option_type"], "call")
        self.assertEqual(metadata[key]["underlying_product_code"], "510050")

    def test_collect_szse_reuses_cached_master_payload(self):
        collector = ContractMasterCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "option_product_name_map": {"SZSE": {"159919": "沪深300ETF期权"}},
            },
            logging.getLogger("test-master-data-szse"),
        )
        option_row = OptionQuoteRow(
            trade_date="2026-04-16",
            exchange="SZSE",
            product_code="159919",
            product_name="沪深300ETF期权",
            contract="159919C2604M04000A",
            underlying_exchange="SZSE",
            underlying_kind="etf",
            underlying_product_code="159919",
            underlying_contract="159919",
            option_type="call",
            strike_price="4.0000",
            exercise_type="european",
            expire_date="2026-04-22",
            last_trade_date="2026-04-22",
            open="0.3",
            high="0.4",
            low="0.2",
            close="0.35",
            prev_settlement="0.31",
            settlement="",
            change_close="0.04",
            change_settlement="",
            volume="100",
            open_interest="200",
            open_interest_change="",
            turnover="",
            delta="",
            implied_volatility="",
            exercise_volume="",
            source_url="fallback://daily",
            source_type="fallback_online",
            retrieved_at="2026-04-18T00:00:00+08:00",
            raw_path="data/raw/szse/options_daily_quotes/20260416.json",
        )
        cached_payload = {
            "data": {
                "90000001": {
                    "contract": "159919C2604M04000A",
                    "strike_price": "4.0000",
                    "expire_date": "2026-04-22",
                    "last_trade_date": "2026-04-22",
                    "contract_multiplier": "10000",
                    "underlying": "159919",
                }
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            raw_root = Path(tmpdir)
            cache_path = raw_root / "szse" / "contracts_snapshot" / "20260416.json"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(__import__("json").dumps(cached_payload, ensure_ascii=False), encoding="utf-8")
            with mock.patch("src.futures_workflow.master_data.RAW_DIR", raw_root):
                with mock.patch.object(collector._szse_source, "_fetch_current_contract_map", side_effect=RuntimeError("boom")):
                    metadata = collector.collect(date(2026, 4, 16), futures_rows=[], options_rows=[option_row])
        key = ("option", "SZSE", "159919C2604M04000A")
        self.assertIn(key, metadata)
        self.assertEqual(metadata[key]["contract_multiplier"], "10000")
        self.assertEqual(metadata[key]["source_type"], "official")

    def test_collect_sse_prefers_cached_master_payload_for_historical_date(self):
        collector = ContractMasterCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "option_product_name_map": {"SSE": {"510050": "上证50ETF期权"}},
            },
            logging.getLogger("test-master-data-sse-cache-first"),
        )
        option_row = OptionQuoteRow(
            trade_date="2026-04-16",
            exchange="SSE",
            product_code="510050",
            product_name="上证50ETF期权",
            contract="510050C2604M02650",
            underlying_exchange="SSE",
            underlying_kind="etf",
            underlying_product_code="510050",
            underlying_contract="510050",
            option_type="call",
            strike_price="2.6500",
            exercise_type="european",
            expire_date="2026-04-22",
            last_trade_date="2026-04-22",
            open="0.35",
            high="0.36",
            low="0.33",
            close="0.34",
            prev_settlement="0.31",
            settlement="",
            change_close="0.03",
            change_settlement="",
            volume="123",
            open_interest="",
            open_interest_change="",
            turnover="",
            delta="0.98",
            implied_volatility="0.41",
            exercise_volume="",
            source_url="fallback://daily",
            source_type="fallback_online",
            retrieved_at="2026-04-18T00:00:00+08:00",
            raw_path="data/raw/sse/options_daily_quotes/20260416.json",
        )
        cached_payload = {"result": [{"SECURITY_ID": "10000001", "CONTRACT_ID": "510050C2604M02650"}]}
        with mock.patch.object(collector, "_load_cached_if_historical", return_value=cached_payload), mock.patch.object(
            collector._sse_source,
            "_fetch_risk_rows",
            side_effect=AssertionError("historical cache should short-circuit live SSE metadata fetch"),
        ):
            metadata = collector.collect(date(2026, 4, 16), futures_rows=[], options_rows=[option_row])
        key = ("option", "SSE", "510050C2604M02650")
        self.assertIn(key, metadata)

    def test_collect_szse_prefers_cached_master_payload_for_historical_date(self):
        collector = ContractMasterCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "option_product_name_map": {"SZSE": {"159919": "沪深300ETF期权"}},
            },
            logging.getLogger("test-master-data-szse-cache-first"),
        )
        option_row = OptionQuoteRow(
            trade_date="2026-04-16",
            exchange="SZSE",
            product_code="159919",
            product_name="沪深300ETF期权",
            contract="159919C2604M04000A",
            underlying_exchange="SZSE",
            underlying_kind="etf",
            underlying_product_code="159919",
            underlying_contract="159919",
            option_type="call",
            strike_price="4.0000",
            exercise_type="european",
            expire_date="2026-04-22",
            last_trade_date="2026-04-22",
            open="0.3",
            high="0.4",
            low="0.2",
            close="0.35",
            prev_settlement="0.31",
            settlement="",
            change_close="0.04",
            change_settlement="",
            volume="100",
            open_interest="200",
            open_interest_change="",
            turnover="",
            delta="",
            implied_volatility="",
            exercise_volume="",
            source_url="fallback://daily",
            source_type="fallback_online",
            retrieved_at="2026-04-18T00:00:00+08:00",
            raw_path="data/raw/szse/options_daily_quotes/20260416.json",
        )
        cached_payload = {
            "data": {
                "90000001": {
                    "contract": "159919C2604M04000A",
                    "strike_price": "4.0000",
                    "expire_date": "2026-04-22",
                    "last_trade_date": "2026-04-22",
                    "contract_multiplier": "10000",
                    "underlying": "159919",
                }
            }
        }
        with mock.patch.object(collector, "_load_cached_if_historical", return_value=cached_payload), mock.patch.object(
            collector._szse_source,
            "_fetch_current_contract_map",
            side_effect=AssertionError("historical cache should short-circuit live SZSE metadata fetch"),
        ):
            metadata = collector.collect(date(2026, 4, 16), futures_rows=[], options_rows=[option_row])
        key = ("option", "SZSE", "159919C2604M04000A")
        self.assertIn(key, metadata)


if __name__ == "__main__":
    unittest.main()
