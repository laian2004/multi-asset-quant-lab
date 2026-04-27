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

from src.futures_workflow.public_references import PublicReferenceRunner


class PublicReferenceRunnerTests(unittest.TestCase):
    def test_sync_writes_reference_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_references.json"
            runner = PublicReferenceRunner(state_path=state_path)

            fake_fx = pd.DataFrame(
                [
                    {"日期": "2026-04-19", "美元": 686.22, "欧元": 806.18},
                ]
            )
            fake_rmb_middle = pd.DataFrame(
                [
                    {"日期": "2026-04-19", "美元/人民币_中间价": 7.02, "美元/人民币_涨跌幅": -12.0, "人民币/韩元_中间价": 191.55, "人民币/韩元_涨跌幅": 23.0},
                ]
            )
            fake_fx_spot = pd.DataFrame(
                [
                    {"货币对": "USD/CNY", "买报价": 7.12, "卖报价": 7.13},
                    {"货币对": "EUR/CNY", "买报价": 8.03, "卖报价": 8.04},
                ]
            )
            fake_fx_pair = pd.DataFrame(
                [
                    {"货币对": "AUD/USD", "买报价": 0.71, "卖报价": 0.72},
                    {"货币对": "USD/JPY", "买报价": 154.1, "卖报价": 154.2},
                ]
            )
            fake_fx_swap = pd.DataFrame(
                [
                    {"货币对": "USD/CNY", "1周": "-10/-9", "1月": "-20/-19", "3月": "-30/-29", "6月": "-40/-39", "9月": "-50/-49", "1年": "-60/-59"},
                    {"货币对": "EUR/CNY", "1周": "10/11", "1月": "20/21", "3月": "30/31", "6月": "40/41", "9月": "50/51", "1年": "60/61"},
                ]
            )
            fake_shibor = pd.DataFrame(
                [
                    {"日期": "2026-04-19", "O/N-定价": 1.221, "O/N-涨跌幅": 0.0, "1W-定价": 1.326, "1W-涨跌幅": -1.0},
                ]
            )
            fake_c_swap_payload = {
                "records": [
                    {"curveTime": "2026-04-19 16:30:00.0", "tenor": "ON", "swapPnt": -4.35},
                    {"curveTime": "2026-04-19 16:30:00.0", "tenor": "1W", "swapPnt": -31.51},
                    {"curveTime": "2026-04-19 16:30:00.0", "tenor": "1M", "swapPnt": -138.58},
                ]
            }
            fake_reserve_eastmoney = pd.DataFrame(
                [
                    {"月份": "2026年02月份", "黄金储备-数值": 3875.88, "黄金储备-环比": 4.87, "国家外汇储备-数值": 34278.07, "国家外汇储备-环比": 0.84},
                    {"月份": "2026年03月份", "黄金储备-数值": 3427.63, "黄金储备-环比": -11.56, "国家外汇储备-数值": 33421.23, "国家外汇储备-环比": -2.49},
                ]
            )
            fake_reserve_pbc = pd.DataFrame(
                [
                    {"统计时间": "2026.2", "黄金储备": 7422.0, "国家外汇储备": 34278.07},
                    {"统计时间": "2026.3", "黄金储备": 7438.0, "国家外汇储备": 33421.23},
                ]
            )
            fake_lpr = pd.DataFrame(
                [
                    {"TRADE_DATE": "2026-03-20", "LPR1Y": 3.0, "LPR5Y": 3.5},
                ]
            )
            fake_repo_fr = pd.DataFrame(
                [
                    {"date": "2026-04-19", "FR001": 1.30, "FR007": 1.41, "FR014": 1.43},
                ]
            )
            fake_repo_fdr = pd.DataFrame(
                [
                    {"date": "2026-04-19", "FDR001": 1.23, "FDR007": 1.31, "FDR014": 1.38},
                ]
            )
            fake_cn_us_rate = pd.DataFrame(
                [
                    {"日期": "2026-04-19", "中国国债收益率2年": 1.55, "美国国债收益率2年": 4.12},
                ]
            )
            fake_gold = pd.DataFrame([{"交易时间": "2026-04-19", "早盘价": 1057.8, "晚盘价": 1058.62}])
            fake_silver = pd.DataFrame([{"交易时间": "2026-04-19", "早盘价": 19826, "晚盘价": 19907}])

            with mock.patch("src.futures_workflow.public_references.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_references.PUBLIC_REFERENCES_NORMALIZED_DIR", root / "data" / "normalized" / "public_references"
            ), mock.patch(
                "src.futures_workflow.public_references.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_references.ak.currency_boc_safe", return_value=fake_fx
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_rmb", return_value=fake_rmb_middle
            ), mock.patch(
                "src.futures_workflow.public_references.ak.fx_spot_quote", return_value=fake_fx_spot
            ), mock.patch(
                "src.futures_workflow.public_references.ak.fx_pair_quote", return_value=fake_fx_pair
            ), mock.patch(
                "src.futures_workflow.public_references.ak.fx_swap_quote", return_value=fake_fx_swap
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_shibor_all", return_value=fake_shibor
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_fx_gold", return_value=fake_reserve_eastmoney
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_foreign_exchange_gold", return_value=fake_reserve_pbc
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_lpr", return_value=fake_lpr
            ), mock.patch(
                "src.futures_workflow.public_references.ak.repo_rate_query", side_effect=[fake_repo_fr, fake_repo_fdr]
            ), mock.patch(
                "src.futures_workflow.public_references.ak.bond_zh_us_rate", return_value=fake_cn_us_rate
            ), mock.patch(
                "src.futures_workflow.public_references.ak.spot_golden_benchmark_sge", return_value=fake_gold
            ), mock.patch(
                "src.futures_workflow.public_references.ak.spot_silver_benchmark_sge", return_value=fake_silver
            ), mock.patch(
                "src.futures_workflow.public_references.requests.get"
            ) as mock_get:
                mock_get.return_value.status_code = 200
                mock_get.return_value.json.return_value = fake_c_swap_payload
                mock_get.return_value.raise_for_status.return_value = None
                result = runner.sync("2026-04-19")

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["families"]["fx_reference_rates"]["row_count"], 2)
            self.assertEqual(result["families"]["rmb_middle_rates"]["row_count"], 2)
            self.assertEqual(result["families"]["fx_spot_quotes"]["row_count"], 2)
            self.assertEqual(result["families"]["fx_pair_quotes"]["row_count"], 2)
            self.assertEqual(result["families"]["fx_swap_quotes"]["row_count"], 12)
            self.assertEqual(result["families"]["fx_c_swap_curve"]["row_count"], 3)
            self.assertEqual(result["families"]["money_market_rates"]["row_count"], 2)
            self.assertEqual(result["families"]["reserve_reference_series"]["row_count"], 4)
            self.assertEqual(result["families"]["loan_prime_rates"]["row_count"], 2)
            self.assertEqual(result["families"]["repo_reference_rates"]["row_count"], 6)
            self.assertEqual(result["families"]["cn_us_treasury_yields"]["row_count"], 2)
            self.assertEqual(result["families"]["precious_metal_reference_quotes"]["row_count"], 4)
            output_path = root / result["families"]["fx_reference_rates"]["output_path"]
            self.assertTrue(output_path.exists())

    def test_validate_reports_schema_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_references.json"
            output_path = root / "data" / "normalized" / "public_references" / "fx_reference_rates" / "2026-04-19.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "trade_date,asset_family,reference_type,market,exchange,symbol,name,base_currency,quote_currency,tenor,value,change_bp,unit,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,fx_money_market_cn,fx_reference_rate,cn_fx_reference,BOC,USD/CNY,美元/人民币参考价,USD,CNY,spot_reference,686.22,,CNY per 100 foreign currency units,akshare.currency_boc_safe,https://www.boc.cn/sourcedb/whpj/,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_references/fx_reference_rates/20260419.json,public_references_v1,abc,run1\n",
                encoding="utf-8-sig",
            )
            raw_path = root / "data" / "raw" / "public_references" / "fx_reference_rates" / "20260419.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(json.dumps({"records": []}, ensure_ascii=False), encoding="utf-8")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "dates": {
                            "2026-04-19": {
                                "status": "success",
                                "families": {
                                    "fx_reference_rates": {
                                        "output_path": "data/normalized/public_references/fx_reference_rates/2026-04-19.csv"
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
            with mock.patch("src.futures_workflow.public_references.PROJECT_ROOT", root):
                runner = PublicReferenceRunner(state_path=state_path)
                result = runner.validate("2026-04-19", families=["fx_reference_rates"])

            self.assertTrue(result["families"]["fx_reference_rates"]["schema_ok"])
            self.assertEqual(result["families"]["fx_reference_rates"]["row_count"], 1)

    def test_state_merges_same_day_families(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_references.json"
            runner = PublicReferenceRunner(state_path=state_path)
            runner._update_state(
                "2026-04-19",
                "success",
                {"fx_reference_rates": {"status": "success", "row_count": 2}},
            )
            runner._update_state(
                "2026-04-19",
                "success",
                {"money_market_rates": {"status": "success", "row_count": 8}},
            )
            payload = json.loads(state_path.read_text(encoding="utf-8"))

        families = payload["dates"]["2026-04-19"]["families"]
        self.assertIn("fx_reference_rates", families)
        self.assertIn("money_market_rates", families)
        self.assertEqual(payload["dates"]["2026-04-19"]["status"], "success")

    def test_latest_weekend_falls_back_to_previous_weekday(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_references.json"
            runner = PublicReferenceRunner(state_path=state_path)
            fake_fx = pd.DataFrame([{"日期": "2026-04-17", "美元": 686.22}])
            fake_rmb_middle = pd.DataFrame([{"日期": "2026-04-17", "美元/人民币_中间价": 7.03, "美元/人民币_涨跌幅": -8.0}])
            fake_fx_spot = pd.DataFrame([{"货币对": "USD/CNY", "买报价": 7.12, "卖报价": 7.13}])
            fake_fx_pair = pd.DataFrame([{"货币对": "AUD/USD", "买报价": 0.71, "卖报价": 0.72}])
            fake_fx_swap = pd.DataFrame([{"货币对": "USD/CNY", "1周": "-10/-9", "1月": "-20/-19", "3月": "-30/-29", "6月": "-40/-39", "9月": "-50/-49", "1年": "-60/-59"}])
            fake_shibor = pd.DataFrame([{"日期": "2026-04-17", "O/N-定价": 1.221, "O/N-涨跌幅": 0.0}])
            fake_reserve_eastmoney = pd.DataFrame(
                [
                    {"月份": "2026年02月份", "黄金储备-数值": 3875.88, "黄金储备-环比": 4.87, "国家外汇储备-数值": 34278.07, "国家外汇储备-环比": 0.84},
                    {"月份": "2026年03月份", "黄金储备-数值": 3427.63, "黄金储备-环比": -11.56, "国家外汇储备-数值": 33421.23, "国家外汇储备-环比": -2.49},
                ]
            )
            fake_reserve_pbc = pd.DataFrame(
                [
                    {"统计时间": "2026.2", "黄金储备": 7422.0, "国家外汇储备": 34278.07},
                    {"统计时间": "2026.3", "黄金储备": 7438.0, "国家外汇储备": 33421.23},
                ]
            )
            fake_lpr = pd.DataFrame([{"TRADE_DATE": "2026-03-20", "LPR1Y": 3.0, "LPR5Y": 3.5}])
            fake_repo_fr = pd.DataFrame([{"date": "2026-04-17", "FR001": 1.30}])
            fake_repo_fdr = pd.DataFrame([{"date": "2026-04-17", "FDR001": 1.23}])
            fake_cn_us_rate = pd.DataFrame([{"日期": "2026-04-17", "中国国债收益率2年": 1.55, "美国国债收益率2年": 4.12}])
            fake_gold = pd.DataFrame([{"交易时间": "2026-04-17", "早盘价": 1057.8, "晚盘价": 1058.62}])
            fake_silver = pd.DataFrame([{"交易时间": "2026-04-17", "早盘价": 19826, "晚盘价": 19907}])

            with mock.patch("src.futures_workflow.public_references.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_references.PUBLIC_REFERENCES_NORMALIZED_DIR", root / "data" / "normalized" / "public_references"
            ), mock.patch(
                "src.futures_workflow.public_references.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_references.ak.currency_boc_safe", return_value=fake_fx
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_rmb", return_value=fake_rmb_middle
            ), mock.patch(
                "src.futures_workflow.public_references.ak.fx_spot_quote", return_value=fake_fx_spot
            ), mock.patch(
                "src.futures_workflow.public_references.ak.fx_pair_quote", return_value=fake_fx_pair
            ), mock.patch(
                "src.futures_workflow.public_references.ak.fx_swap_quote", return_value=fake_fx_swap
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_shibor_all", return_value=fake_shibor
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_fx_gold", return_value=fake_reserve_eastmoney
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_foreign_exchange_gold", return_value=fake_reserve_pbc
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_lpr", return_value=fake_lpr
            ), mock.patch(
                "src.futures_workflow.public_references.ak.repo_rate_query", side_effect=[fake_repo_fr, fake_repo_fdr]
            ), mock.patch(
                "src.futures_workflow.public_references.ak.bond_zh_us_rate", return_value=fake_cn_us_rate
            ), mock.patch(
                "src.futures_workflow.public_references.ak.spot_golden_benchmark_sge", return_value=fake_gold
            ), mock.patch(
                "src.futures_workflow.public_references.ak.spot_silver_benchmark_sge", return_value=fake_silver
            ), mock.patch(
                "src.futures_workflow.public_references.requests.get"
            ) as mock_get, mock.patch(
                "src.futures_workflow.public_references.now_shanghai"
            ) as mock_now:
                mock_get.return_value.status_code = 200
                mock_get.return_value.json.return_value = {
                    "records": [{"curveTime": "2026-04-17 16:30:00.0", "tenor": "ON", "swapPnt": -4.35}]
                }
                mock_get.return_value.raise_for_status.return_value = None
                import datetime
                from zoneinfo import ZoneInfo

                mock_now.return_value = datetime.datetime(2026, 4, 19, 10, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
                result = runner.sync("latest")

        self.assertEqual(result["trade_date"], "2026-04-17")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["families"]["cn_us_treasury_yields"]["row_count"], 2)

    def test_reserve_reference_uses_latest_observation_not_after_requested_day(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_references.json"
            runner = PublicReferenceRunner(state_path=state_path)
            fake_reserve_eastmoney = pd.DataFrame(
                [
                    {"月份": "2026年02月份", "黄金储备-数值": 3875.88, "黄金储备-环比": 4.87, "国家外汇储备-数值": 34278.07, "国家外汇储备-环比": 0.84},
                    {"月份": "2026年03月份", "黄金储备-数值": 3427.63, "黄金储备-环比": -11.56, "国家外汇储备-数值": 33421.23, "国家外汇储备-环比": -2.49},
                ]
            )
            fake_reserve_pbc = pd.DataFrame(
                [
                    {"统计时间": "2026.2", "黄金储备": 7422.0, "国家外汇储备": 34278.07},
                    {"统计时间": "2026.3", "黄金储备": 7438.0, "国家外汇储备": 33421.23},
                ]
            )
            with mock.patch("src.futures_workflow.public_references.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_references.PUBLIC_REFERENCES_NORMALIZED_DIR", root / "data" / "normalized" / "public_references"
            ), mock.patch(
                "src.futures_workflow.public_references.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_fx_gold", return_value=fake_reserve_eastmoney
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_foreign_exchange_gold", return_value=fake_reserve_pbc
            ):
                result = runner.sync("2026-03-15", families=["reserve_reference_series"])

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["families"]["reserve_reference_series"]["row_count"], 4)
            output_path = root / result["families"]["reserve_reference_series"]["output_path"]
            rows = list(pd.read_csv(output_path, dtype=str).to_dict(orient="records"))
            self.assertTrue(all(row["trade_date"] == "2026-03-01" for row in rows))

    def test_latest_summaries_prefers_latest_success_with_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_references.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "dates": {
                            "2026-04-19": {
                                "status": "no_data",
                                "families": {
                                    "fx_reference_rates": {
                                        "status": "no_data",
                                        "trade_date": "2026-04-19",
                                        "row_count": 0,
                                        "output_path": "data/normalized/public_references/fx_reference_rates/2026-04-19.csv",
                                    }
                                },
                            },
                            "2026-04-17": {
                                "status": "success",
                                "families": {
                                    "fx_reference_rates": {
                                        "status": "success",
                                        "trade_date": "2026-04-17",
                                        "row_count": 25,
                                        "output_path": "data/normalized/public_references/fx_reference_rates/2026-04-17.csv",
                                    }
                                },
                            },
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            runner = PublicReferenceRunner(state_path=state_path)
            summaries = runner.latest_summaries()

        self.assertEqual(summaries["fx_reference_rates"]["trade_date"], "2026-04-17")
        self.assertEqual(summaries["fx_reference_rates"]["status"], "success")

    def test_partial_success_is_used_for_mixed_success_and_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_references.json"
            runner = PublicReferenceRunner(state_path=state_path)
            fake_fx = pd.DataFrame([{"日期": "2026-04-17", "美元": 686.22}])
            fake_rmb_middle = pd.DataFrame([{"日期": "2026-04-17", "美元/人民币_中间价": 7.01, "美元/人民币_涨跌幅": -10.0}])
            fake_fx_spot = pd.DataFrame([{"货币对": "USD/CNY", "买报价": 7.12, "卖报价": 7.13}])
            fake_fx_pair = pd.DataFrame([{"货币对": "AUD/USD", "买报价": 0.71, "卖报价": 0.72}])
            fake_fx_swap = pd.DataFrame([{"货币对": "USD/CNY", "1周": "-10/-9", "1月": "-20/-19", "3月": "-30/-29", "6月": "-40/-39", "9月": "-50/-49", "1年": "-60/-59"}])
            fake_shibor = pd.DataFrame([{"日期": "2026-04-17", "O/N-定价": 1.221, "O/N-涨跌幅": 0.0}])
            fake_reserve_eastmoney = pd.DataFrame([{"月份": "2026年03月份", "黄金储备-数值": 3427.63, "黄金储备-环比": -11.56, "国家外汇储备-数值": 33421.23, "国家外汇储备-环比": -2.49}])
            fake_reserve_pbc = pd.DataFrame([{"统计时间": "2026.3", "黄金储备": 7438.0, "国家外汇储备": 33421.23}])
            fake_lpr = pd.DataFrame([{"TRADE_DATE": "2026-03-20", "LPR1Y": 3.0, "LPR5Y": 3.5}])
            fake_repo_fr = pd.DataFrame([{"date": "2026-04-17", "FR001": 1.30}])
            fake_repo_fdr = pd.DataFrame([{"date": "2026-04-17", "FDR001": 1.23}])
            fake_cn_us_rate = pd.DataFrame([{"日期": "2026-04-17", "中国国债收益率2年": 1.55, "美国国债收益率2年": 4.12}])
            fake_gold = pd.DataFrame([], columns=["交易时间", "早盘价", "晚盘价"])
            fake_silver = pd.DataFrame([], columns=["交易时间", "早盘价", "晚盘价"])

            with mock.patch("src.futures_workflow.public_references.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_references.PUBLIC_REFERENCES_NORMALIZED_DIR", root / "data" / "normalized" / "public_references"
            ), mock.patch(
                "src.futures_workflow.public_references.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_references.ak.currency_boc_safe", return_value=fake_fx
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_rmb", return_value=fake_rmb_middle
            ), mock.patch(
                "src.futures_workflow.public_references.ak.fx_spot_quote", return_value=fake_fx_spot
            ), mock.patch(
                "src.futures_workflow.public_references.ak.fx_pair_quote", return_value=fake_fx_pair
            ), mock.patch(
                "src.futures_workflow.public_references.ak.fx_swap_quote", return_value=fake_fx_swap
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_shibor_all", return_value=fake_shibor
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_fx_gold", return_value=fake_reserve_eastmoney
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_foreign_exchange_gold", return_value=fake_reserve_pbc
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_lpr", return_value=fake_lpr
            ), mock.patch(
                "src.futures_workflow.public_references.ak.repo_rate_query", side_effect=[fake_repo_fr, fake_repo_fdr]
            ), mock.patch(
                "src.futures_workflow.public_references.ak.bond_zh_us_rate", return_value=fake_cn_us_rate
            ), mock.patch(
                "src.futures_workflow.public_references.ak.spot_golden_benchmark_sge", return_value=fake_gold
            ), mock.patch(
                "src.futures_workflow.public_references.ak.spot_silver_benchmark_sge", return_value=fake_silver
            ), mock.patch(
                "src.futures_workflow.public_references.requests.get"
            ) as mock_get:
                mock_get.return_value.status_code = 200
                mock_get.return_value.json.return_value = {
                    "records": [{"curveTime": "2026-04-17 16:30:00.0", "tenor": "ON", "swapPnt": -4.35}]
                }
                mock_get.return_value.raise_for_status.return_value = None
                result = runner.sync("2026-04-17")

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["families"]["precious_metal_reference_quotes"]["status"], "no_data")

    def test_cn_us_treasury_rates_normalization(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_references.json"
            runner = PublicReferenceRunner(state_path=state_path)
            fake_cn_us_rate = pd.DataFrame(
                [
                    {"日期": "2026-04-17", "中国国债收益率2年": 1.55, "美国国债收益率2年": 4.12},
                ]
            )

            with mock.patch("src.futures_workflow.public_references.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_references.PUBLIC_REFERENCES_NORMALIZED_DIR", root / "data" / "normalized" / "public_references"
            ), mock.patch(
                "src.futures_workflow.public_references.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_references.ak.bond_zh_us_rate", return_value=fake_cn_us_rate
            ):
                result = runner.sync("2026-04-17", families=["cn_us_treasury_yields"])

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["families"]["cn_us_treasury_yields"]["row_count"], 2)

    def test_rmb_middle_rates_normalization(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_references.json"
            runner = PublicReferenceRunner(state_path=state_path)
            fake_rmb_middle = pd.DataFrame(
                [
                    {"日期": "2026-04-17", "美元/人民币_中间价": 7.05, "美元/人民币_涨跌幅": -18.0, "100日元/人民币_中间价": 4.61, "100日元/人民币_涨跌幅": 12.0},
                ]
            )

            with mock.patch("src.futures_workflow.public_references.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_references.PUBLIC_REFERENCES_NORMALIZED_DIR", root / "data" / "normalized" / "public_references"
            ), mock.patch(
                "src.futures_workflow.public_references.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_rmb", return_value=fake_rmb_middle
            ):
                result = runner.sync("2026-04-17", families=["rmb_middle_rates"])

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["families"]["rmb_middle_rates"]["row_count"], 2)
            csv_path = root / result["families"]["rmb_middle_rates"]["output_path"]
            rows = list(pd.read_csv(csv_path, dtype=str).to_dict(orient="records"))
            self.assertEqual(rows[0]["reference_type"], "rmb_central_parity")
            self.assertIn(rows[0]["symbol"], {"USD/CNY", "100JPY/CNY"})

    def test_lpr_uses_latest_available_before_requested_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_references.json"
            runner = PublicReferenceRunner(state_path=state_path)
            fake_lpr = pd.DataFrame(
                [
                    {"TRADE_DATE": "2026-02-20", "LPR1Y": 3.1, "LPR5Y": 3.6},
                    {"TRADE_DATE": "2026-03-20", "LPR1Y": 3.0, "LPR5Y": 3.5},
                ]
            )

            with mock.patch("src.futures_workflow.public_references.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_references.PUBLIC_REFERENCES_NORMALIZED_DIR", root / "data" / "normalized" / "public_references"
            ), mock.patch(
                "src.futures_workflow.public_references.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_references.ak.macro_china_lpr", return_value=fake_lpr
            ):
                result = runner.sync("2026-04-17", families=["loan_prime_rates"])

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["families"]["loan_prime_rates"]["row_count"], 2)
            csv_path = root / result["families"]["loan_prime_rates"]["output_path"]
            rows = csv_path.read_text(encoding="utf-8-sig")
            self.assertIn("2026-03-20", rows)


if __name__ == "__main__":
    unittest.main()
