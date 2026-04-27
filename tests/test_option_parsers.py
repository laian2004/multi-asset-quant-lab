import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.models import OptionQuoteRow, QuoteRow
from src.futures_workflow.exercise_results import _parse_exercise_payload
from src.futures_workflow.parsers.cffex import parse_cffex_daily_quotes
from src.futures_workflow.parsers.options_cffex import parse_cffex_option_daily_quotes
from src.futures_workflow.parsers.options_equity import parse_equity_option_daily_quotes
from src.futures_workflow.platform import build_contract_snapshot_rows, build_options_chain_matrix, build_platform_rows, build_underlying_summary


class OptionParserTests(unittest.TestCase):
    def test_equity_option_parser_maps_normalized_records(self):
        raw = """{"data":[{"product_code":"510050","product_name":"上证50ETF期权","contract":"510050C2604M02650","underlying_exchange":"SSE","underlying_kind":"etf","underlying_product_code":"510050","underlying_contract":"510050","option_type":"call","strike_price":"2.6500","exercise_type":"european","expire_date":"2026-04-22","last_trade_date":"2026-04-22","open":"0.35","high":"0.36","low":"0.33","close":"0.34","prev_settlement":"0.31","settlement":"","change_close":"0.03","change_settlement":"","volume":"123","open_interest":"","open_interest_change":"","turnover":"","delta":"0.98","implied_volatility":"0.41","exercise_volume":""}]}"""
        rows = parse_equity_option_daily_quotes(raw, date(2026, 4, 16), "p", "u", "fallback_online", "SSE")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].exchange, "SSE")
        self.assertEqual(rows[0].contract, "510050C2604M02650")
        self.assertEqual(rows[0].delta, "0.98")
        self.assertEqual(rows[0].implied_volatility, "0.41")

    def test_cffex_parsers_accept_nbsp_entities(self):
        futures_raw = "<data><dailydata><instrumentid>IF2604</instrumentid><productid>IF</productid><openprice>1</openprice><highestprice>2</highestprice><lowestprice>0.5</lowestprice><closeprice>1.5</closeprice><presettlementprice>1.0</presettlementprice><settlementprice>1.4</settlementprice><volume>10</volume><openinterest>20</openinterest><preopeninterest>18</preopeninterest><turnover>30</turnover>&nbsp;</dailydata></data>"
        option_raw = "<data><dailydata><instrumentid>IO2604-C-3500</instrumentid><openprice>1</openprice><highestprice>2</highestprice><lowestprice>0.5</lowestprice><closeprice>1.5</closeprice><presettlementprice>1.0</presettlementprice><settlementprice>1.4</settlementprice><volume>10</volume><openinterest>20</openinterest><preopeninterest>18</preopeninterest><turnover>30</turnover><expiredate>20260417</expiredate><delta>0.5</delta>&NBSP;</dailydata></data>"
        futures_rows = parse_cffex_daily_quotes(futures_raw, date(2026, 4, 16), "raw.xml", "u", "official", {"IF": "股指期货"})
        option_rows = parse_cffex_option_daily_quotes(option_raw, date(2026, 4, 16), "raw.xml", "u", "official", {"IO": "股指期权"})
        self.assertEqual(len(futures_rows), 1)
        self.assertEqual(futures_rows[0].contract, "IF2604")
        self.assertEqual(len(option_rows), 1)
        self.assertEqual(option_rows[0].contract, "IO2604-C-3500")

    def test_platform_views_combine_futures_and_options(self):
        future = QuoteRow(
            trade_date="2026-04-16",
            exchange="SHFE",
            variety_code="CU",
            variety_name="铜",
            contract="CU2605",
            delivery_month="2605",
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
            source_url="u",
            source_type="official",
            retrieved_at="2026-04-17T00:00:00+08:00",
            raw_path="data/raw/future.json",
        )
        call = OptionQuoteRow(
            trade_date="2026-04-16",
            exchange="SHFE",
            product_code="CU",
            product_name="铜期权",
            contract="CU2605-C-80000",
            underlying_exchange="SHFE",
            underlying_kind="futures",
            underlying_product_code="CU",
            underlying_contract="CU2605",
            option_type="call",
            strike_price="80000",
            exercise_type="american",
            expire_date="2026-04-22",
            last_trade_date="2026-04-22",
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
            delta="0.6",
            implied_volatility="0.2",
            exercise_volume="",
            source_url="u",
            source_type="official",
            retrieved_at="2026-04-17T00:00:00+08:00",
            raw_path="data/raw/call.json",
        )
        put = OptionQuoteRow(
            trade_date="2026-04-16",
            exchange="SHFE",
            product_code="CU",
            product_name="铜期权",
            contract="CU2605-P-80000",
            underlying_exchange="SHFE",
            underlying_kind="futures",
            underlying_product_code="CU",
            underlying_contract="CU2605",
            option_type="put",
            strike_price="80000",
            exercise_type="american",
            expire_date="2026-04-22",
            last_trade_date="2026-04-22",
            open="1",
            high="2",
            low="0.5",
            close="1.2",
            prev_settlement="1.0",
            settlement="1.1",
            change_close="0.2",
            change_settlement="0.1",
            volume="8",
            open_interest="15",
            open_interest_change="1",
            turnover="20",
            delta="-0.4",
            implied_volatility="0.25",
            exercise_volume="",
            source_url="u",
            source_type="official",
            retrieved_at="2026-04-17T00:00:00+08:00",
            raw_path="data/raw/put.json",
        )
        chain_rows = build_options_chain_matrix([call, put])
        summary_rows = build_underlying_summary([future], [call, put])
        self.assertEqual(len(chain_rows), 1)
        self.assertEqual(chain_rows[0]["call_contract"], "CU2605-C-80000")
        self.assertEqual(chain_rows[0]["put_contract"], "CU2605-P-80000")
        self.assertEqual(len(summary_rows), 1)
        self.assertEqual(summary_rows[0]["futures_contract"], "CU2605")
        self.assertEqual(summary_rows[0]["options_total_volume"], "18")

    def test_contract_snapshot_prefers_master_metadata(self):
        option = OptionQuoteRow(
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
            source_url="u",
            source_type="fallback_online",
            retrieved_at="2026-04-18T00:00:00+08:00",
            raw_path="data/raw/option.json",
            metadata={"contract_multiplier": "10000", "quote_unit": "元", "delivery_type": "cash"},
        )
        rows = build_contract_snapshot_rows(
            [],
            [option],
            master_metadata={
                ("option", "SZSE", "159919C2604M04000A"): {
                    "contract_status": "trading",
                    "contract_multiplier": "10000",
                    "quote_unit": "元",
                    "delivery_type": "cash",
                    "underlying_exchange": "SZSE",
                    "underlying_kind": "etf",
                    "underlying_product_code": "159919",
                    "underlying_contract": "159919",
                    "option_type": "call",
                    "exercise_type": "european",
                    "strike_price": "4.0000",
                    "expire_date": "2026-04-22",
                    "last_trade_date": "2026-04-22",
                }
            },
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["contract_multiplier"], "10000")
        self.assertEqual(rows[0]["quote_unit"], "元")
        self.assertEqual(rows[0]["delivery_type"], "cash")
        self.assertEqual(rows[0]["source_type"], "fallback_online")

    def test_contract_snapshot_does_not_promote_fallback_metadata_without_master_data(self):
        option = OptionQuoteRow(
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
            delta="0.5",
            implied_volatility="0.2",
            exercise_volume="5",
            source_url="u",
            source_type="fallback_online",
            retrieved_at="2026-04-17T00:00:00+08:00",
            raw_path="data/raw/option.json",
            metadata={"contract_multiplier": "10000"},
        )
        rows = build_contract_snapshot_rows([], [option])
        self.assertEqual(rows[0]["contract_multiplier"], "")
        self.assertEqual(rows[0]["expire_date"], "")

    def test_build_platform_rows_does_not_derive_option_results_from_quotes(self):
        option = OptionQuoteRow(
            trade_date="2026-04-16",
            exchange="GFEX",
            product_code="SI",
            product_name="工业硅期权",
            contract="SI2605-C-10000",
            underlying_exchange="GFEX",
            underlying_kind="futures",
            underlying_product_code="SI",
            underlying_contract="SI2605",
            option_type="call",
            strike_price="10000",
            exercise_type="american",
            expire_date="2026-04-22",
            last_trade_date="2026-04-22",
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
            delta="0.5",
            implied_volatility="0.2",
            exercise_volume="9",
            source_url="u",
            source_type="official",
            retrieved_at="2026-04-17T00:00:00+08:00",
            raw_path="data/raw/option.json",
        )
        dataset_rows = build_platform_rows(futures_rows=[], options_rows=[option], option_result_rows=[], futures_result_rows=[])
        self.assertEqual(dataset_rows["options_exercise_results"], [])

    def test_parse_exercise_results_payload(self):
        rows = _parse_exercise_payload(
            exchange="SHFE",
            raw_text='{"data":[{"contract":"CU2605-C-80000","underlying_contract":"CU2605","option_type":"call","strike_price":"80000","expire_date":"2026-04-22","exercise_volume":"12"}]}',
            trade_date=date(2026, 4, 16),
            raw_path="data/raw/shfe/options_exercise_results/20260416.json",
            source_url="official://shfe",
            source_type="official",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exercise_volume"], "12")
        self.assertEqual(rows[0]["contract"], "CU2605-C-80000")

    def test_parse_xml_exercise_payload_with_nbsp_entity(self):
        rows = _parse_exercise_payload(
            exchange="CFFEX",
            raw_text="""
<dailydatas>
  <dailydata>
    <instrumentid>IO2604-C-5000</instrumentid>
    <expiredate>2026-04-22</expiredate>
    <exercisevolume>12&nbsp;</exercisevolume>
  </dailydata>
</dailydatas>
""".strip(),
            trade_date=date(2026, 4, 22),
            raw_path="data/raw/cffex/options_exercise_results/20260422.xml",
            source_url="official://cffex",
            source_type="official",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["contract"], "IO2604-C-5000")
        self.assertEqual(rows[0]["exercise_volume"], "12")


if __name__ == "__main__":
    unittest.main()
