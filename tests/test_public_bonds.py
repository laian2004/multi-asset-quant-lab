import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.public_bonds import PublicBondRunner


class PublicBondRunnerTests(unittest.TestCase):
    def test_sync_writes_bond_and_curve_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_bonds.json"
            runner = PublicBondRunner(state_path=state_path)

            fake_deal = pd.DataFrame(
                [
                    {
                        "债券简称": "26国开05",
                        "成交净价": 100.71,
                        "最新收益率": 1.8410,
                        "涨跌": -3.55,
                        "加权收益率": 1.8604,
                        "交易量": 514.2,
                    }
                ]
            )
            fake_quote = pd.DataFrame(
                [
                    {
                        "报价机构": "招商银行",
                        "债券简称": "26浦发银行CD080",
                        "买入净价": 98.49,
                        "卖出净价": 98.57,
                        "买入收益率": 1.53,
                        "卖出收益率": 1.44,
                    }
                ]
            )
            fake_curve = pd.DataFrame(
                [
                    {
                        "曲线名称": "中债国债收益率曲线",
                        "日期": "2026-04-17",
                        "3月": 1.17,
                        "6月": 1.17,
                        "1年": 1.16,
                        "3年": 1.34,
                        "5年": 1.53,
                        "7年": 1.65,
                        "10年": 1.78,
                        "30年": 2.27,
                    }
                ]
            )
            fake_sse_deal = pd.DataFrame(
                [
                    {
                        "债券类型": "记账式国债",
                        "当日成交笔数": 3685,
                        "当日成交金额": 363349.44,
                        "当年成交笔数": 3685,
                        "当年成交金额": 363349.44,
                        "数据日期": "2026-04-17",
                    }
                ]
            )
            fake_sse_cash = pd.DataFrame(
                [
                    {
                        "债券现货": "国债",
                        "托管只数": 193,
                        "托管市值": 6815.47,
                        "托管面值": 6758.46,
                        "数据日期": "2026-04-17",
                    }
                ]
            )

            with mock.patch("src.futures_workflow.public_bonds.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_bonds.PUBLIC_BONDS_NORMALIZED_DIR", root / "data" / "normalized" / "public_bonds"
            ), mock.patch(
                "src.futures_workflow.public_bonds.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_bonds.ak.bond_spot_deal", return_value=fake_deal
            ), mock.patch(
                "src.futures_workflow.public_bonds.ak.bond_spot_quote", return_value=fake_quote
            ), mock.patch(
                "src.futures_workflow.public_bonds.ak.bond_china_yield", return_value=fake_curve
            ), mock.patch(
                "src.futures_workflow.public_bonds.ak.bond_deal_summary_sse", return_value=fake_sse_deal
            ), mock.patch(
                "src.futures_workflow.public_bonds.ak.bond_cash_summary_sse", return_value=fake_sse_cash
            ), mock.patch(
                "src.futures_workflow.public_bonds.now_shanghai"
            ) as mock_now:
                import datetime
                from zoneinfo import ZoneInfo

                mock_now.return_value = datetime.datetime(2026, 4, 19, 15, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
                result = runner.sync("latest")

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["families"]["interbank_bond_deal_snapshot"]["row_count"], 1)
            self.assertEqual(result["families"]["yield_curve_points"]["row_count"], 8)
            self.assertEqual(result["families"]["sse_bond_deal_summary"]["row_count"], 1)
            self.assertEqual(result["families"]["sse_bond_cash_summary"]["row_count"], 1)
            output_path = root / result["families"]["yield_curve_points"]["output_path"]
            self.assertTrue(output_path.exists())

    def test_validate_reports_schema_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_bonds.json"
            output_path = root / "data" / "normalized" / "public_bonds" / "yield_curve_points" / "2026-04-17.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "trade_date,asset_family,dataset_type,market,exchange,symbol,name,curve_name,counterparty,tenor,price,bid_price,ask_price,yield,bid_yield,ask_yield,weighted_yield,change_bp,volume,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-17,bonds_rates_cn,yield_curve_points,cn_yield_curve,CHINABOND,,,中债国债收益率曲线,,3M,,,,1.17,,,,,,akshare.bond_china_yield,https://yield.chinabond.com.cn/,fallback_online,2026-04-19T16:00:00+08:00,data/raw/public_bonds/yield_curve_points/20260417.json,public_bonds_v1,abc,run1\n",
                encoding="utf-8-sig",
            )
            raw_path = root / "data" / "raw" / "public_bonds" / "yield_curve_points" / "20260417.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(json.dumps({"records": []}, ensure_ascii=False), encoding="utf-8")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "dates": {
                            "2026-04-17": {
                                "status": "success",
                                "families": {
                                    "yield_curve_points": {
                                        "output_path": "data/normalized/public_bonds/yield_curve_points/2026-04-17.csv"
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
            with mock.patch("src.futures_workflow.public_bonds.PROJECT_ROOT", root):
                runner = PublicBondRunner(state_path=state_path)
                result = runner.validate("2026-04-17", families=["yield_curve_points"])

            self.assertTrue(result["families"]["yield_curve_points"]["schema_ok"])
            self.assertEqual(result["families"]["yield_curve_points"]["row_count"], 1)

    def test_validate_reports_schema_ok_for_sse_bond_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_bonds.json"
            output_path = root / "data" / "normalized" / "public_bonds" / "sse_bond_deal_summary" / "2026-04-17.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "trade_date,asset_family,dataset_type,market,exchange,category,name,count_value,amount,market_value,par_value,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-17,bonds_rates_cn,sse_bond_deal_summary,cn_exchange_bonds,SSE,记账式国债,记账式国债,3685,363349.44,363349.44,3685,akshare.bond_deal_summary_sse,http://bond.sse.com.cn/data/statistics/overview/turnover/,fallback_online,2026-04-19T16:00:00+08:00,data/raw/public_bonds/sse_bond_deal_summary/20260417.json,public_bonds_v1,abc,run1\n",
                encoding="utf-8-sig",
            )
            raw_path = root / "data" / "raw" / "public_bonds" / "sse_bond_deal_summary" / "20260417.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(json.dumps({"records": []}, ensure_ascii=False), encoding="utf-8")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "dates": {
                            "2026-04-17": {
                                "status": "success",
                                "families": {
                                    "sse_bond_deal_summary": {
                                        "output_path": "data/normalized/public_bonds/sse_bond_deal_summary/2026-04-17.csv"
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
            with mock.patch("src.futures_workflow.public_bonds.PROJECT_ROOT", root):
                runner = PublicBondRunner(state_path=state_path)
                result = runner.validate("2026-04-17", families=["sse_bond_deal_summary"])

        self.assertTrue(result["families"]["sse_bond_deal_summary"]["schema_ok"])
        self.assertEqual(result["families"]["sse_bond_deal_summary"]["row_count"], 1)


if __name__ == "__main__":
    unittest.main()
