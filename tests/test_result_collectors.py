import logging
import sys
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import requests


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.delivery_results import FuturesDeliveryCollector
from src.futures_workflow.exercise_results import OptionExerciseCollector


class ResultCollectorApplicabilityTests(unittest.TestCase):
    def test_option_exercise_pre_launch_is_not_applicable(self):
        collector = OptionExerciseCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchange_metadata": {
                    "SHFE": {"options_launch_date": "2018-09-21"},
                },
            },
            logging.getLogger("test-option-exercise-launch"),
        )
        rows, summaries = collector.collect(date(2018, 9, 1))
        self.assertEqual(rows, [])
        self.assertEqual(summaries["SHFE"]["status"], "not_applicable")

    def test_futures_delivery_pre_launch_is_not_applicable(self):
        collector = FuturesDeliveryCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchange_metadata": {
                    "GFEX": {"launch_date": "2022-12-22"},
                },
            },
            logging.getLogger("test-futures-delivery-launch"),
        )
        rows, summaries = collector.collect(date(2021, 4, 16))
        self.assertEqual(rows, [])
        self.assertEqual(summaries["GFEX"]["status"], "not_applicable")

    def test_shfe_futures_delivery_uses_official_daily_and_monthly_endpoints(self):
        collector = FuturesDeliveryCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchanges": {
                    "SHFE": {
                        "delivery_param_url": "https://example.com/delivery/{trade_date}.dat",
                        "monthly_delivery_results_url": "https://example.com/monthly/{year_month}.dat",
                    }
                },
            },
            logging.getLogger("test-shfe-futures-delivery"),
        )
        daily_response = mock.Mock()
        daily_response.status_code = 200
        daily_response.json.return_value = {
            "Delivery": [
                {
                    "INSTRUMENTID": "cu2604",
                    "DELIVERYPRICE": "102430",
                    "ENDDELIVERYDATE": "20260417",
                }
            ]
        }
        daily_response.raise_for_status.return_value = None
        monthly_response = mock.Mock()
        monthly_response.status_code = 200
        monthly_response.json.return_value = {
            "ExchangeDelivery": [
                {
                    "INSTRUMENTID": "cu2604",
                    "DELIVERYVOLUME": 100,
                    "DELIVERYAMOUNT": "9602000",
                    "EXCHANGE_DELIVERYVOLUME": 100,
                    "DELIVERYDAY": "20260416",
                }
            ]
        }
        monthly_response.raise_for_status.return_value = None
        collector.session.get = mock.Mock(side_effect=[daily_response, monthly_response])

        summary, rows = collector._collect_exchange("SHFE", date(2026, 4, 16))
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["row_count"], 1)
        self.assertEqual(rows[0]["contract"], "CU2604")
        self.assertTrue(rows[0]["raw_path"].endswith("data/raw/shfe/futures_delivery_results/20260416.json"))

    def test_ine_futures_delivery_reuses_shfe_official_payload_and_splits_exchange(self):
        collector = FuturesDeliveryCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchange_metadata": {
                    "INE": {"launch_date": "2018-03-26"},
                },
                "exchanges": {
                    "SHFE": {
                        "delivery_param_url": "https://example.com/delivery/{trade_date}.dat",
                        "monthly_delivery_results_url": "https://example.com/monthly/{year_month}.dat",
                    }
                },
            },
            logging.getLogger("test-ine-futures-delivery"),
        )
        daily_response = mock.Mock()
        daily_response.status_code = 200
        daily_response.json.return_value = {
            "Delivery": [
                {
                    "INSTRUMENTID": "sc2604",
                    "DELIVERYPRICE": "510.2",
                    "ENDDELIVERYDATE": "20260417",
                }
            ]
        }
        daily_response.raise_for_status.return_value = None
        monthly_response = mock.Mock()
        monthly_response.status_code = 200
        monthly_response.json.return_value = {
            "ExchangeDelivery": [
                {
                    "INSTRUMENTID": "sc2604",
                    "DELIVERYVOLUME": 6,
                    "DELIVERYAMOUNT": "3061200",
                    "EXCHANGE_DELIVERYVOLUME": 6,
                    "DELIVERYDAY": "20260416",
                }
            ]
        }
        monthly_response.raise_for_status.return_value = None
        collector.session.get = mock.Mock(side_effect=[daily_response, monthly_response])

        summary, rows = collector._collect_exchange("INE", date(2026, 4, 16))
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["row_count"], 1)
        self.assertEqual(rows[0]["exchange"], "INE")
        self.assertEqual(rows[0]["contract"], "SC2604")
        self.assertTrue(rows[0]["raw_path"].endswith("data/raw/shfe/futures_delivery_results/20260416.json"))

    def test_delivery_raw_write_prunes_stale_extensions(self):
        collector = FuturesDeliveryCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
            },
            logging.getLogger("test-futures-delivery-prune"),
        )
        with TemporaryDirectory() as tmpdir:
            raw_root = Path(tmpdir)
            target_dir = raw_root / "shfe" / "futures_delivery_results"
            target_dir.mkdir(parents=True, exist_ok=True)
            target_dir.joinpath("20260416.xml").write_text("<old/>", encoding="utf-8")
            with mock.patch("src.futures_workflow.delivery_results.RAW_DIR", raw_root):
                path = collector._write_raw_json("SHFE", date(2026, 4, 16), {"ok": True})
            self.assertEqual(path.name, "20260416.json")
            self.assertTrue(target_dir.joinpath("20260416.json").exists())
            self.assertFalse(target_dir.joinpath("20260416.xml").exists())

    def test_gfex_futures_delivery_uses_official_monthly_endpoint(self):
        collector = FuturesDeliveryCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchange_metadata": {
                    "GFEX": {"launch_date": "2022-12-22"},
                },
                "exchanges": {
                    "GFEX": {
                        "monthly_delivery_results_url": "http://example.com/gfex/monthly",
                        "delivery_results_referer": "http://example.com/gfex/referer",
                    }
                },
            },
            logging.getLogger("test-gfex-futures-delivery"),
        )
        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = {
            "data": [
                {
                    "contractId": "si2605",
                    "deliveryDate": "20260416",
                    "deliveryQty": 15,
                    "deliveryAmt": 300000,
                    "deliveryPrice": "20000",
                }
            ]
        }
        response.raise_for_status.return_value = None
        collector.session.post = mock.Mock(return_value=response)

        summary, rows = collector._collect_exchange("GFEX", date(2026, 4, 16))
        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["row_count"], 1)
        self.assertEqual(rows[0]["exchange"], "GFEX")
        self.assertEqual(rows[0]["delivery_volume"], "15")

    def test_generic_futures_delivery_request_error_is_pending_retry(self):
        collector = FuturesDeliveryCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchanges": {
                    "CFFEX": {
                        "delivery_results_url": "https://example.com/cffex/{trade_date}.xml",
                    }
                },
            },
            logging.getLogger("test-generic-futures-delivery-pending-retry"),
        )
        collector.session.get = mock.Mock(side_effect=requests.RequestException("timeout"))

        summary, rows = collector._collect_exchange("CFFEX", date(2026, 4, 16))
        self.assertEqual(rows, [])
        self.assertEqual(summary["status"], "pending_retry")

    def test_generic_option_exercise_request_error_is_pending_retry(self):
        collector = OptionExerciseCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchanges": {
                    "CFFEX": {
                        "exercise_results_url": "https://example.com/cffex-option/{trade_date}.xml",
                    }
                },
            },
            logging.getLogger("test-generic-option-exercise-pending-retry"),
        )
        collector.session.get = mock.Mock(side_effect=requests.RequestException("timeout"))

        summary, rows = collector._collect_exchange("CFFEX", date(2026, 4, 16))
        self.assertEqual(rows, [])
        self.assertEqual(summary["status"], "pending_retry")

    def test_option_exercise_local_summary_returns_no_data_when_exchange_has_rows_but_no_expiry(self):
        collector = OptionExerciseCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
            },
            logging.getLogger("test-option-exercise-local-no-expiry"),
        )
        summary = collector.summarize_without_fetch(
            "SSE",
            date(2026, 4, 16),
            option_rows=[
                {
                    "exchange": "SSE",
                    "contract": "510050C2604M02650",
                    "expire_date": "2026-04-22",
                    "last_trade_date": "2026-04-22",
                }
            ],
        )
        self.assertIsNotNone(summary)
        self.assertEqual(summary["status"], "no_data")
        self.assertIn("No expiring SSE option contracts found", summary["message"])
        self.assertIn("tradeDate=20260416", summary["source_url"])

    def test_futures_delivery_local_summary_returns_no_data_when_exchange_has_rows_but_no_expiry(self):
        collector = FuturesDeliveryCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchanges": {
                    "DCE": {
                        "monthly_market_report_url": "http://example.com/dce/{year_month}.pdf",
                    }
                },
            },
            logging.getLogger("test-futures-delivery-local-no-expiry"),
        )
        summary = collector.summarize_without_fetch(
            "DCE",
            date(2026, 4, 16),
            futures_rows=[
                {
                    "exchange": "DCE",
                    "contract": "M2609",
                    "metadata": {
                        "expire_date": "2026-09-15",
                        "last_trade_date": "2026-09-15",
                    },
                }
            ],
        )
        self.assertIsNotNone(summary)
        self.assertEqual(summary["status"], "no_data")
        self.assertIn("No expiring DCE futures contracts found", summary["message"])
        self.assertIn("202604", summary["source_url"])

    def test_cffex_option_exercise_can_use_official_monthly_report(self):
        with TemporaryDirectory() as tmpdir:
            raw_root = Path(tmpdir)
            options_dir = raw_root / "cffex" / "options_daily_quotes"
            options_dir.mkdir(parents=True, exist_ok=True)
            options_dir.joinpath("20210416.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<dailydatas>
  <dailydata>
    <instrumentid>IO2104-C-5000</instrumentid>
    <tradingday>20210416</tradingday>
    <expiredate>20210416</expiredate>
    <productid>IO</productid>
    <openprice>1</openprice>
    <highestprice>1</highestprice>
    <lowestprice>1</lowestprice>
    <closeprice>1</closeprice>
    <presettlementprice>1</presettlementprice>
    <settlementprice>1</settlementprice>
    <volume>1</volume>
    <openinterest>1</openinterest>
    <delta>0.5</delta>
  </dailydata>
</dailydatas>
""",
                encoding="utf-8",
            )
            collector = OptionExerciseCollector(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "exchange_metadata": {
                        "CFFEX": {"options_launch_date": "2019-12-23"},
                    },
                    "exchanges": {
                        "CFFEX": {
                            "monthly_exercise_report_url": "http://example.com/cffex/monthly/{year_month}.pdf",
                        }
                    },
                    "option_product_name_map": {
                        "CFFEX": {"IO": "沪深300股指期权"},
                    },
                },
                logging.getLogger("test-cffex-option-exercise-monthly"),
            )
            response = mock.Mock()
            response.status_code = 200
            response.content = b"%PDF-1.4 mock"
            response.raise_for_status.return_value = None
            collector.session.get = mock.Mock(return_value=response)
            with mock.patch("src.futures_workflow.exercise_results.RAW_DIR", raw_root):
                with mock.patch(
                    "src.futures_workflow.exercise_results._extract_pdf_text",
                    return_value="""
七、期权各产品行权数据统计
产品 到期未平仓量 到期未行权量 行权量 当年累计到期未平仓量 当年累计到期未行权量 当年累计行权量
IO 56998 45835 11163 208342 165346 42996
总计 56998 45835 11163 208342 165346 42996
注：到期未平仓量、到期未行权量、行权量：手（单边计算）
""",
                ):
                    summary, rows = collector._collect_exchange("CFFEX", date(2021, 4, 16))
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["row_count"], 1)
            self.assertEqual(rows[0]["contract"], "IO")
            self.assertEqual(rows[0]["exercise_volume"], "11163")
            self.assertEqual(rows[0]["result_status"], "reported_product_aggregate")
            self.assertTrue(rows[0]["raw_path"].endswith("cffex/options_exercise_results/20210416.pdf"))

    def test_cffex_option_exercise_404_monthly_report_is_pending_retry_when_expiry_exists(self):
        with TemporaryDirectory() as tmpdir:
            raw_root = Path(tmpdir)
            options_dir = raw_root / "cffex" / "options_daily_quotes"
            options_dir.mkdir(parents=True, exist_ok=True)
            options_dir.joinpath("20260416.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<dailydatas>
  <dailydata>
    <instrumentid>IO2604-C-5000</instrumentid>
    <tradingday>20260416</tradingday>
    <expiredate>20260416</expiredate>
    <productid>IO</productid>
    <openprice>1</openprice>
    <highestprice>1</highestprice>
    <lowestprice>1</lowestprice>
    <closeprice>1</closeprice>
    <presettlementprice>1</presettlementprice>
    <settlementprice>1</settlementprice>
    <volume>1</volume>
    <openinterest>1</openinterest>
    <delta>0.5</delta>
  </dailydata>
</dailydatas>
""",
                encoding="utf-8",
            )
            collector = OptionExerciseCollector(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "exchange_metadata": {
                        "CFFEX": {"options_launch_date": "2019-12-23"},
                    },
                    "exchanges": {
                        "CFFEX": {
                            "monthly_exercise_report_url": "http://example.com/cffex/monthly/{year_month}.pdf",
                        }
                    },
                    "option_product_name_map": {
                        "CFFEX": {"IO": "沪深300股指期权"},
                    },
                },
                logging.getLogger("test-cffex-option-exercise-monthly-pending"),
            )
            response = mock.Mock()
            response.status_code = 404
            collector.session.get = mock.Mock(return_value=response)
            with mock.patch("src.futures_workflow.exercise_results.RAW_DIR", raw_root):
                summary, rows = collector._collect_exchange("CFFEX", date(2026, 4, 16))
            self.assertEqual(rows, [])
            self.assertEqual(summary["status"], "pending_retry")
            self.assertIn("not yet published", summary["message"])

    def test_cffex_option_exercise_html_error_page_is_pending_retry(self):
        with TemporaryDirectory() as tmpdir:
            raw_root = Path(tmpdir)
            options_dir = raw_root / "cffex" / "options_daily_quotes"
            result_dir = raw_root / "cffex" / "options_exercise_results"
            options_dir.mkdir(parents=True, exist_ok=True)
            result_dir.mkdir(parents=True, exist_ok=True)
            options_dir.joinpath("20260417.xml").write_text(
                """<?xml version="1.0" encoding="UTF-8"?>
<dailydatas>
  <dailydata>
    <instrumentid>HO2604-C-2500</instrumentid>
    <tradingday>20260417</tradingday>
    <expiredate>20260417</expiredate>
    <productid>HO</productid>
    <openprice>1</openprice>
    <highestprice>1</highestprice>
    <lowestprice>1</lowestprice>
    <closeprice>1</closeprice>
    <presettlementprice>1</presettlementprice>
    <settlementprice>1</settlementprice>
    <volume>1</volume>
    <openinterest>1</openinterest>
    <delta>0.5</delta>
  </dailydata>
</dailydatas>
""",
                encoding="utf-8",
            )
            result_dir.joinpath("20260417.pdf").write_bytes(b"%PDF-old-stale")
            collector = OptionExerciseCollector(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "exchange_metadata": {
                        "CFFEX": {"options_launch_date": "2019-12-23"},
                    },
                    "exchanges": {
                        "CFFEX": {
                            "monthly_exercise_report_url": "http://example.com/cffex/monthly/{year_month}.pdf",
                        }
                    },
                    "option_product_name_map": {
                        "CFFEX": {"HO": "上证50股指期权"},
                    },
                },
                logging.getLogger("test-cffex-option-exercise-html"),
            )
            response = mock.Mock()
            response.status_code = 200
            response.content = b'<!DOCTYPE html><html><head><title>\xcd\xf8\xd2\xb3\xb4\xed\xce\xf3</title></head><body>404</body></html>'
            response.raise_for_status.return_value = None
            collector.session.get = mock.Mock(return_value=response)
            with mock.patch("src.futures_workflow.exercise_results.RAW_DIR", raw_root):
                summary, rows = collector._collect_exchange("CFFEX", date(2026, 4, 17))
            self.assertEqual(rows, [])
            self.assertEqual(summary["status"], "pending_retry")
            self.assertIn("HTML error page", summary["message"])
            self.assertTrue(str(summary["raw_path"]).endswith("20260417.html"))
            self.assertFalse(result_dir.joinpath("20260417.pdf").exists())
            self.assertTrue(result_dir.joinpath("20260417.html").exists())

    def test_dce_option_exercise_can_use_official_monthly_report(self):
        with TemporaryDirectory() as tmpdir:
            raw_root = Path(tmpdir)
            collector = OptionExerciseCollector(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "exchange_metadata": {
                        "DCE": {"options_launch_date": "2017-03-31"},
                    },
                    "exchanges": {
                        "DCE": {
                            "monthly_market_report_overrides": {
                                "201904": "http://example.com/dce/201904.pdf",
                            }
                        }
                    },
                },
                logging.getLogger("test-dce-option-exercise-monthly"),
            )
            collector._current_option_rows = [
                {
                    "exchange": "DCE",
                    "underlying_contract": "M1905",
                    "expire_date": "2019-04-16",
                    "last_trade_date": "2019-04-16",
                }
            ]
            response = mock.Mock()
            response.status_code = 200
            response.content = b"%PDF-1.4 mock"
            response.raise_for_status.return_value = None
            collector.session.get = mock.Mock(return_value=response)
            sample_text = """
3、期权行权
2019年04月DCE期权行权情况
单位：手
品种
期权系列
月行权量
年行权量
月看涨行权量
 占比
月看跌行权量
 占比
年看涨行权量
 占比
年看跌行权量
 占比
玉米期权c1905 17,860 18,615 7,709 55.26% 10,151 33.19% 8,457 54.34% 10,158 22.74%
豆粕期权m1905 26,257 31,547 5,930 42.51% 20,327 66.46% 5,943 38.19% 25,604 57.32%
总计
 44,535
二、实物交割
"""
            with mock.patch("src.futures_workflow.exercise_results.RAW_DIR", raw_root):
                with mock.patch("src.futures_workflow.exercise_results._extract_pdf_text", return_value=sample_text):
                    summary, rows = collector._collect_exchange("DCE", date(2019, 4, 16))
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["row_count"], 2)
            self.assertEqual({row["contract"] for row in rows}, {"M1905-CALL-AGG", "M1905-PUT-AGG"})
            self.assertEqual({row["option_type"] for row in rows}, {"call", "put"})
            self.assertEqual({row["exercise_volume"] for row in rows}, {"5930", "20327"})
            self.assertTrue(rows[0]["raw_path"].endswith("dce/options_exercise_results/20190416.pdf"))

    def test_dce_option_exercise_without_monthly_report_url_is_pending_retry(self):
        collector = OptionExerciseCollector(
            {
                "user_agent": "ua",
                "timeout_seconds": 5,
                "exchange_metadata": {
                    "DCE": {"options_launch_date": "2017-03-31"},
                },
                "exchanges": {"DCE": {}},
            },
            logging.getLogger("test-dce-option-exercise-pending"),
        )
        collector._current_option_rows = [
            {
                "exchange": "DCE",
                "underlying_contract": "M2605",
                "expire_date": "2026-04-16",
                "last_trade_date": "2026-04-16",
            }
        ]
        summary, rows = collector._collect_exchange("DCE", date(2026, 4, 16))
        self.assertEqual(rows, [])
        self.assertEqual(summary["status"], "pending_retry")
        self.assertIn("not yet published", summary["message"])

    def test_sse_option_exercise_can_use_official_settlement_summary(self):
        with TemporaryDirectory() as tmpdir:
            raw_root = Path(tmpdir)
            collector = OptionExerciseCollector(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "exchange_metadata": {
                        "SSE": {"options_launch_date": "2015-02-09"},
                    },
                },
                logging.getLogger("test-sse-option-exercise-summary"),
            )
            response = mock.Mock()
            response.status_code = 200
            response.json.return_value = {
                "result": [
                    {
                        "UNDERLYING_SECURITY_ID": "510050",
                        "UNDERLYING_SECURITY_ABBR": "50ETF",
                        "CALL_EXE_VALUE": "17,293",
                        "PUT_EXE_VALUE": "25,319",
                        "TRADE_DATE": "20210428",
                    },
                    {
                        "UNDERLYING_SECURITY_ID": "510300",
                        "UNDERLYING_SECURITY_ABBR": "300ETF",
                        "CALL_EXE_VALUE": "0",
                        "PUT_EXE_VALUE": "6,201",
                        "TRADE_DATE": "20210428",
                    },
                ]
            }
            response.raise_for_status.return_value = None
            collector.session.get = mock.Mock(return_value=response)
            with mock.patch("src.futures_workflow.exercise_results.RAW_DIR", raw_root):
                summary, rows = collector._collect_exchange("SSE", date(2021, 4, 28))
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["row_count"], 3)
            self.assertEqual({row["contract"] for row in rows}, {"510050-CALL-AGG", "510050-PUT-AGG", "510300-PUT-AGG"})
            self.assertEqual({row["option_type"] for row in rows}, {"call", "put"})
            self.assertTrue(all(row["result_status"] == "reported_underlying_aggregate" for row in rows))
            self.assertTrue(rows[0]["raw_path"].endswith("sse/options_exercise_results/20210428.json"))

    def test_sse_option_exercise_empty_summary_is_no_data(self):
        with TemporaryDirectory() as tmpdir:
            raw_root = Path(tmpdir)
            collector = OptionExerciseCollector(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "exchange_metadata": {
                        "SSE": {"options_launch_date": "2015-02-09"},
                    },
                },
                logging.getLogger("test-sse-option-exercise-empty"),
            )
            response = mock.Mock()
            response.status_code = 200
            response.json.return_value = {"result": []}
            response.raise_for_status.return_value = None
            collector.session.get = mock.Mock(return_value=response)
            with mock.patch("src.futures_workflow.exercise_results.RAW_DIR", raw_root):
                summary, rows = collector._collect_exchange("SSE", date(2026, 4, 16))
            self.assertEqual(rows, [])
            self.assertEqual(summary["status"], "no_data")
            self.assertIn("contained no rows", summary["message"])

    def test_dce_futures_delivery_can_use_official_monthly_report(self):
        with TemporaryDirectory() as tmpdir:
            raw_root = Path(tmpdir)
            collector = FuturesDeliveryCollector(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "exchange_metadata": {
                        "DCE": {"launch_date": "1993-03-01"},
                    },
                    "exchanges": {
                        "DCE": {
                            "monthly_market_report_overrides": {
                                "201904": "http://example.com/dce/201904.pdf",
                            }
                        }
                    },
                    "product_name_map": {
                        "DCE": {"JD": "鸡蛋"},
                    },
                },
                logging.getLogger("test-dce-futures-delivery-monthly"),
            )
            collector._current_futures_rows = [
                {
                    "exchange": "DCE",
                    "contract": "JD1905",
                    "variety_code": "JD",
                    "metadata": {
                        "expire_date": "2019-04-16",
                        "last_trade_date": "2019-04-16",
                    },
                }
            ]
            response = mock.Mock()
            response.status_code = 200
            response.content = b"%PDF-1.4 mock"
            response.raise_for_status.return_value = None
            collector.session.get = mock.Mock(return_value=response)
            sample_text = """
二、实物交割
1、交割信息
2019年04月DCE交割情况
单位：元/吨、手、亿元；单边
品种
 交割量
 交割金额
 年累计交割量
 年累计交割金额
 交割方式
鸡蛋7 0.00 54 0.02 一次性交割
总计
 138
2、仓单信息
"""
            with mock.patch("src.futures_workflow.delivery_results.RAW_DIR", raw_root):
                with mock.patch("src.futures_workflow.delivery_results._extract_pdf_text", return_value=sample_text):
                    summary, rows = collector._collect_exchange("DCE", date(2019, 4, 16))
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["row_count"], 1)
            self.assertEqual(rows[0]["contract"], "JD1905")
            self.assertEqual(rows[0]["delivery_volume"], "7")
            self.assertEqual(rows[0]["result_status"], "一次性交割")
            self.assertTrue(rows[0]["raw_path"].endswith("dce/futures_delivery_results/20190416.pdf"))

    def test_szse_option_exercise_can_use_official_summary(self):
        with TemporaryDirectory() as tmpdir:
            raw_root = Path(tmpdir)
            collector = OptionExerciseCollector(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "exchange_metadata": {
                        "SZSE": {"options_launch_date": "2019-12-23"},
                    },
                },
                logging.getLogger("test-szse-option-exercise-summary"),
            )
            response = mock.Mock()
            response.status_code = 200
            response.json.return_value = [
                {
                    "metadata": {"pagecount": 1, "recordcount": 2},
                    "data": [
                        {
                            "jyrq": "20260326",
                            "bdzqdm": "中证500ETF嘉实(159922)",
                            "cxqhysl": "20,958",
                            "pxqhysl": "14,029",
                        },
                        {
                            "jyrq": "20260326",
                            "bdzqdm": "创业板ETF易方达(159915)",
                            "cxqhysl": "20,879",
                            "pxqhysl": "0",
                        },
                    ],
                    "error": None,
                }
            ]
            response.raise_for_status.return_value = None
            collector.session.get = mock.Mock(return_value=response)
            with mock.patch("src.futures_workflow.exercise_results.RAW_DIR", raw_root):
                summary, rows = collector._collect_exchange("SZSE", date(2026, 3, 26))
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["row_count"], 3)
            self.assertEqual(
                {row["contract"] for row in rows},
                {"159922-CALL-AGG", "159922-PUT-AGG", "159915-CALL-AGG"},
            )
            self.assertEqual({row["option_type"] for row in rows}, {"call", "put"})
            self.assertTrue(all(row["result_status"] == "reported_underlying_aggregate" for row in rows))
            self.assertTrue(rows[0]["raw_path"].endswith("szse/options_exercise_results/20260326.json"))

    def test_szse_option_exercise_empty_summary_is_no_data(self):
        with TemporaryDirectory() as tmpdir:
            raw_root = Path(tmpdir)
            collector = OptionExerciseCollector(
                {
                    "user_agent": "ua",
                    "timeout_seconds": 5,
                    "exchange_metadata": {
                        "SZSE": {"options_launch_date": "2019-12-23"},
                    },
                },
                logging.getLogger("test-szse-option-exercise-empty"),
            )
            response = mock.Mock()
            response.status_code = 200
            response.json.return_value = [{"metadata": {"pagecount": 0, "recordcount": 0}, "data": [], "error": None}]
            response.raise_for_status.return_value = None
            collector.session.get = mock.Mock(return_value=response)
            with mock.patch("src.futures_workflow.exercise_results.RAW_DIR", raw_root):
                summary, rows = collector._collect_exchange("SZSE", date(2021, 4, 28))
            self.assertEqual(rows, [])
            self.assertEqual(summary["status"], "no_data")
            self.assertIn("contained no rows", summary["message"])


if __name__ == "__main__":
    unittest.main()
