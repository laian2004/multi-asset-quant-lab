import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.parsers.cffex import parse_cffex_daily_quotes
from src.futures_workflow.parsers.czce import parse_czce_daily_quotes
from src.futures_workflow.parsers.dce import parse_dce_daily_quotes
from src.futures_workflow.parsers.gfex import parse_gfex_daily_quotes
from src.futures_workflow.parsers.shfe import parse_shfe_daily_quotes


class ParserTests(unittest.TestCase):
    def test_shfe_parser_filters_totals(self):
        raw = """{"o_curinstrument":[{"PRODUCTCLASS":"1","PRODUCTGROUPID":"cu","PRODUCTNAME":"铜","DELIVERYMONTH":"2605","OPENPRICE":102160,"HIGHESTPRICE":102750,"LOWESTPRICE":101760,"CLOSEPRICE":102680,"PRESETTLEMENTPRICE":102280,"SETTLEMENTPRICE":102330,"ZD1_CHG":400,"ZD2_CHG":50,"VOLUME":75358,"OPENINTEREST":148287,"OPENINTERESTCHG":-11318,"TURNOVER":3855704.735},{"PRODUCTCLASS":"1","PRODUCTGROUPID":"cu","PRODUCTNAME":"铜","DELIVERYMONTH":"小计","VOLUME":174812}]}"""
        rows = parse_shfe_daily_quotes(raw, date(2026, 4, 16), "data/raw/shfe/daily_quotes/20260416.json", "u", "official")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].contract, "CU2605")

    def test_shfe_parser_supports_legacy_product_id_schema(self):
        raw = """{"o_curinstrument":[{"PRODUCTID":"cu_f","PRODUCTNAME":"铜","DELIVERYMONTH":"1005","OPENPRICE":"60100","HIGHESTPRICE":"60750","LOWESTPRICE":"59800","CLOSEPRICE":"60320","PRESETTLEMENTPRICE":"60020","SETTLEMENTPRICE":"60240","VOLUME":"12345","OPENINTEREST":"54321","OPENINTERESTCHG":"120","TURNOVER":"987654.5"}]}"""
        rows = parse_shfe_daily_quotes(raw, date(2010, 4, 16), "data/raw/shfe/daily_quotes/20100416.json", "u", "official")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].contract, "CU1005")
        self.assertEqual(rows[0].variety_code, "CU")

    def test_cffex_parser_filters_options(self):
        raw = """<?xml version="1.0" encoding="UTF-8"?><dailydatas><dailydata><instrumentid>IF2604</instrumentid><productid>IF</productid><openprice>3500</openprice><highestprice>3520</highestprice><lowestprice>3480</lowestprice><closeprice>3510</closeprice><presettlementprice>3490</presettlementprice><settlementprice>3505</settlementprice><volume>100</volume><turnover>1000</turnover><preopeninterest>200</preopeninterest><openinterest>220</openinterest></dailydata><dailydata><instrumentid>HO2604-C-2500</instrumentid><productid>HO</productid></dailydata></dailydatas>"""
        rows = parse_cffex_daily_quotes(raw, date(2026, 4, 16), "p", "u", "official", {"IF": "沪深300股指期货"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].variety_name, "沪深300股指期货")

    def test_czce_parser_infers_delivery_month(self):
        raw = """郑州商品交易所期货每日行情表(2026-04-16)\n合约代码|昨结算|今开盘|最高价|最低价|今收盘|今结算|涨跌1|涨跌2|成交量(手)|持仓量|增减量|成交额(万元)|交割结算价\nAP605|9870.00|9880.00|9890.00|9730.00|9768.00|9814.00|-102.00|-56.00|8204|13858|-2131|80513.86|\n小计|||||||||||||\n"""
        rows = parse_czce_daily_quotes(raw, date(2026, 4, 16), "p", "u", "official", {"AP": "苹果"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].delivery_month, "2605")
        self.assertEqual(rows[0].contract, "AP2605")

    def test_czce_parser_supports_json_fallback_payload(self):
        raw = """{"data":[{"symbol":"CF505","variety":"CF","variety_name":"棉花","open":"12590.0","high":"12715.0","low":"12590.0","close":"12700.0","pre_settle":"12630.0","settle":"12675.0","volume":"3036","open_interest":"23504","turnover":"19241.07"}]}"""
        rows = parse_czce_daily_quotes(raw, date(2015, 4, 16), "p", "u", "fallback_online", {"CF": "棉花"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].contract, "CF1505")
        self.assertEqual(rows[0].settlement, "12675")
        self.assertEqual(rows[0].source_type, "fallback_online")

    def test_gfex_parser(self):
        raw = """{"code":"0","data":[{"variety":"多晶硅","varietyOrder":"ps","delivMonth":"2605","open":"35085","high":"35440","low":"34505","close":"34755","lastClear":"34755","clearPrice":"34960","diff":"0","diff1":"205","volumn":"23549","openInterest":"21864","diffI":"-4731","turnover":"247009.3395"}]}"""
        rows = parse_gfex_daily_quotes(raw, date(2026, 4, 16), "p", "u", "official")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].contract, "PS2605")

    def test_dce_parser_supports_json_payload(self):
        raw = """{"data":[{"variety":"豆一","varietyOrder":"a","deliveryMonth":"2605","contractId":"a2605","open":"4090","high":"4105","low":"4071","close":"4082","lastClear":"4088","clearPrice":"4085","diff":"-6","diff1":"-3","volumn":"12345","openInterest":"54321","diffI":"-120","turnover":"100234.5"}]}"""
        rows = parse_dce_daily_quotes(raw, date(2026, 4, 16), "p", "u", "official_browser_bootstrap", {"A": "豆一"})
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].contract, "A2605")
        self.assertEqual(rows[0].variety_name, "豆一")
        self.assertEqual(rows[0].settlement, "4085")


if __name__ == "__main__":
    unittest.main()
