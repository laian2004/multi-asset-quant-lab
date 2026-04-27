import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.delivery_results import _parse_delivery_payload
from src.futures_workflow.delivery_results import _build_gfex_delivery_rows, _build_shfe_delivery_rows


class DeliveryResultParserTests(unittest.TestCase):
    def test_parse_shfe_json_delivery_rows(self):
        rows = _parse_delivery_payload(
            exchange="SHFE",
            raw_text='{"data":[{"contract":"CU2605","delivery_month":"2605","final_settlement_price":"78120","delivery_volume":"12"}]}',
            trade_date=date(2026, 4, 16),
            raw_path="data/raw/shfe/futures_delivery_results/20260416.json",
            source_url="official://shfe",
            source_type="official",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exchange"], "SHFE")
        self.assertEqual(rows[0]["contract"], "CU2605")

    def test_parse_cffex_xml_delivery_rows(self):
        rows = _parse_delivery_payload(
            exchange="CFFEX",
            raw_text="<root><dailydata><instrumentid>IF2604</instrumentid><deliverymonth>2604</deliverymonth><finalsettlementprice>4220.2</finalsettlementprice><deliveryvolume>8</deliveryvolume></dailydata></root>",
            trade_date=date(2026, 4, 16),
            raw_path="data/raw/cffex/futures_delivery_results/20260416.xml",
            source_url="official://cffex",
            source_type="official",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exchange"], "CFFEX")
        self.assertEqual(rows[0]["delivery_volume"], "8")

    def test_parse_czce_pipe_delivery_rows(self):
        rows = _parse_delivery_payload(
            exchange="CZCE",
            raw_text="合约代码|交割月份|交割结算价|交割量\nSR605|2605|6112|5",
            trade_date=date(2026, 4, 16),
            raw_path="data/raw/czce/futures_delivery_results/20260416.txt",
            source_url="official://czce",
            source_type="official",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exchange"], "CZCE")
        self.assertEqual(rows[0]["final_settlement_price"], "6112")

    def test_build_shfe_delivery_rows_from_daily_and_monthly_payloads(self):
        rows = _build_shfe_delivery_rows(
            trade_date=date(2026, 4, 16),
            daily_payload={
                "Delivery": [
                    {
                        "INSTRUMENTID": "cu2604",
                        "DELIVERYPRICE": "102430",
                        "ENDDELIVERYDATE": "20260417",
                    }
                ]
            },
            monthly_payload={
                "ExchangeDelivery": [
                    {
                        "INSTRUMENTID": "cu2604",
                        "DELIVERYVOLUME": 100,
                        "DELIVERYAMOUNT": "9602000",
                        "EXCHANGE_DELIVERYVOLUME": 100,
                        "DELIVERYDAY": "20260416",
                    }
                ]
            },
            raw_path="data/raw/shfe/futures_delivery_results/20260416.json",
            source_url="official://shfe/month",
            source_type="official",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exchange"], "SHFE")
        self.assertEqual(rows[0]["contract"], "CU2604")
        self.assertEqual(rows[0]["expire_date"], "2026-04-17")
        self.assertEqual(rows[0]["delivery_volume"], "100")
        self.assertEqual(rows[0]["warehouse_delivery_quantity"], "100")

    def test_build_gfex_delivery_rows_from_monthly_payload(self):
        rows = _build_gfex_delivery_rows(
            trade_date=date(2026, 4, 16),
            payload={
                "data": [
                    {
                        "contractId": "si2605",
                        "deliveryDate": "20260416",
                        "deliveryQty": 15,
                        "deliveryAmt": 300000,
                        "deliveryPrice": "20000",
                    }
                ]
            },
            raw_path="data/raw/gfex/futures_delivery_results/20260416.json",
            source_url="official://gfex/month",
            source_type="official",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["exchange"], "GFEX")
        self.assertEqual(rows[0]["contract"], "SI2605")
        self.assertEqual(rows[0]["delivery_month"], "2605")
        self.assertEqual(rows[0]["delivery_amount"], "300000")


if __name__ == "__main__":
    unittest.main()
