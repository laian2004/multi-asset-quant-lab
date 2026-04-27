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

from src.futures_workflow.public_assets import PublicAssetSnapshotRunner


def _mock_response(text: str, *, encoding: str = "utf-8"):
    response = mock.Mock()
    response.status_code = 200
    response.text = text
    response.encoding = encoding
    response.raise_for_status.return_value = None
    return response


def _iter_csv_rows(path: Path):
    import csv

    with path.open("r", encoding="utf-8-sig") as handle:
        yield from csv.DictReader(handle)


class PublicAssetSnapshotRunnerTests(unittest.TestCase):
    def test_sync_writes_public_asset_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_assets.json"
            runner = PublicAssetSnapshotRunner(state_path=state_path)

            fake_stock = pd.DataFrame(
                [
                    {
                        "代码": "sh600000",
                        "名称": "浦发银行",
                        "最新价": 10.5,
                        "涨跌额": 0.2,
                        "涨跌幅": 1.9,
                        "今开": 10.3,
                        "最高": 10.6,
                        "最低": 10.2,
                        "昨收": 10.3,
                        "成交量": 1000,
                        "成交额": 10000,
                    }
                ]
            )
            fake_etf = pd.DataFrame(
                [
                    {
                        "基金代码": "510050",
                        "基金名称": "上证50ETF",
                        "当前-单位净值": 2.98,
                        "前一日-单位净值": 2.95,
                        "增长值": 0.03,
                        "增长率": 1.02,
                        "查询日期": "2026-04-19",
                    }
                ]
            )
            fake_lof = pd.DataFrame(
                [
                    {
                        "代码": "160526",
                        "名称": "博时优势企业",
                        "最新价": 1.438,
                        "涨跌额": 0.131,
                        "涨跌幅": 10.02,
                        "成交量": 136.0,
                        "成交额": 18362.302,
                        "开盘价": 1.317,
                        "最高价": 1.438,
                        "最低价": 1.317,
                        "昨收": 1.307,
                    }
                ]
            )
            fake_open_fund = pd.DataFrame(
                [
                    {
                        "基金代码": "014279",
                        "基金简称": "汇添富北交所创新精选两年定开混合A",
                        "2026-04-17-单位净值": "1.9704",
                        "2026-04-17-累计净值": "2.0334",
                        "2026-04-16-单位净值": "1.8031",
                        "2026-04-16-累计净值": "1.8661",
                        "日增长值": "0.1673",
                        "日增长率": "9.28",
                    }
                ]
            )
            fake_money_fund = pd.DataFrame(
                [
                    {
                        "基金代码": "018655",
                        "基金简称": "光大保德信耀钱包货币C",
                        "2026-04-17-万份收益": "1.4667",
                        "2026-04-17-7日年化%": "2.0300%",
                        "2026-04-17-单位净值": "---",
                        "2026-04-16-万份收益": "0.7845",
                        "2026-04-16-7日年化%": "1.4020%",
                        "2026-04-16-单位净值": "---",
                        "日涨幅": "---",
                    }
                ]
            )
            fake_bse = pd.DataFrame(
                [
                    {
                        "代码": "920001",
                        "名称": "北证样本",
                        "最新价": 12.3,
                        "涨跌额": 0.4,
                        "涨跌幅": 3.4,
                        "今开": 11.9,
                        "最高": 12.4,
                        "最低": 11.8,
                        "昨收": 11.9,
                        "成交量": 2000,
                        "成交额": 24000,
                    }
                ]
            )
            fake_reits = pd.DataFrame(
                [
                    {
                        "代码": "180102",
                        "名称": "华夏合肥高新REIT",
                        "最新价": 1.52,
                        "涨跌额": 0.02,
                        "涨跌幅": 1.3,
                        "开盘价": 1.50,
                        "最高价": 1.53,
                        "最低价": 1.49,
                        "昨收": 1.50,
                        "成交量": 100,
                        "成交额": 1000,
                    }
                ]
            )
            fake_cov = pd.DataFrame(
                [
                    {
                        "symbol": "sh110001",
                        "name": "样本转债",
                        "trade": "123.45",
                        "pricechange": "1.23",
                        "changepercent": "1.01",
                        "buy": "123.40",
                        "sell": "123.50",
                        "settlement": "122.22",
                        "open": "122.8",
                        "high": "123.8",
                        "low": "122.6",
                        "volume": 20000,
                        "amount": 2400000,
                        "code": "110001",
                        "ticktime": "15:00:00",
                    }
                ]
            )
            fake_carbon_payload = {
                "湖北": [
                    {"deal": 68.2, "DEALNUM": 1200, "HOUSENAME": "湖北", "DEALAMOUNT": 81840, "INDATE": "2026-04-18"},
                ],
                "上海": [
                    {"deal": 72.5, "DEALNUM": 900, "HOUSENAME": "上海", "DEALAMOUNT": 65250, "INDATE": "2026-04-19"},
                ],
            }

            with mock.patch("src.futures_workflow.public_assets.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_assets.PUBLIC_ASSETS_NORMALIZED_DIR", root / "data" / "normalized" / "public_assets"
            ), mock.patch(
                "src.futures_workflow.public_assets.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.stock_zh_a_spot", return_value=fake_stock
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.stock_bj_a_spot_em", return_value=fake_bse
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.fund_etf_spot_ths", return_value=fake_etf
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.fund_lof_spot_em", return_value=fake_lof
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.fund_open_fund_daily_em", return_value=fake_open_fund
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.fund_money_fund_daily_em", return_value=fake_money_fund
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.reits_realtime_em", return_value=fake_reits
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.bond_zh_hs_cov_spot", return_value=fake_cov
            ), mock.patch(
                "src.futures_workflow.public_assets.requests.get"
            ) as mock_get, mock.patch(
                "src.futures_workflow.public_assets.now_shanghai"
            ) as mock_now:
                mock_get.return_value.status_code = 200
                mock_get.return_value.text = "null(" + json.dumps(fake_carbon_payload, ensure_ascii=False) + ")"
                mock_get.return_value.raise_for_status.return_value = None
                import datetime
                from zoneinfo import ZoneInfo

                mock_now.return_value = datetime.datetime(2026, 4, 19, 15, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
                result = runner.sync(
                    "latest",
                    families=[
                        "equities_spot_snapshot",
                        "bse_equities_spot_snapshot",
                        "etf_spot_snapshot",
                        "lof_spot_snapshot",
                        "open_fund_nav_snapshot",
                        "money_market_fund_snapshot",
                        "reits_spot_snapshot",
                        "convertible_bond_spot_snapshot",
                        "carbon_market_snapshot",
                    ],
                )

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["families"]["equities_spot_snapshot"]["row_count"], 1)
            self.assertEqual(result["families"]["bse_equities_spot_snapshot"]["row_count"], 1)
            self.assertEqual(result["families"]["lof_spot_snapshot"]["row_count"], 1)
            self.assertEqual(result["families"]["open_fund_nav_snapshot"]["row_count"], 1)
            self.assertEqual(result["families"]["money_market_fund_snapshot"]["row_count"], 1)
            self.assertEqual(result["families"]["convertible_bond_spot_snapshot"]["row_count"], 1)
            self.assertEqual(result["families"]["carbon_market_snapshot"]["row_count"], 2)
            output_path = root / result["families"]["equities_spot_snapshot"]["output_path"]
            self.assertTrue(output_path.exists())

    def test_validate_reports_schema_ok(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_assets.json"
            output_path = root / "data" / "normalized" / "public_assets" / "reits_spot_snapshot" / "2026-04-19.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "trade_date,asset_family,asset_type,market,exchange,symbol,name,last_price,change_amount,change_pct,open,high,low,prev_close,volume,amount,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,equities_funds_cn,reits,cn_reits,SSE,180102,华夏合肥高新REIT,1.52,0.02,1.3,1.50,1.53,1.49,1.50,100,1000,akshare.reits_realtime_em,https://quote.eastmoney.com/center/gridlist.html#fund_reits_all,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_assets/reits_spot_snapshot/20260419.json,public_assets_v1,abc,run1\n",
                encoding="utf-8-sig",
            )
            raw_path = root / "data" / "raw" / "public_assets" / "reits_spot_snapshot" / "20260419.json"
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
                                    "reits_spot_snapshot": {
                                        "output_path": "data/normalized/public_assets/reits_spot_snapshot/2026-04-19.csv"
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
            with mock.patch("src.futures_workflow.public_assets.PROJECT_ROOT", root):
                runner = PublicAssetSnapshotRunner(state_path=state_path)
                result = runner.validate("2026-04-19", families=["reits_spot_snapshot"])

            self.assertTrue(result["families"]["reits_spot_snapshot"]["schema_ok"])
            self.assertEqual(result["families"]["reits_spot_snapshot"]["row_count"], 1)

    def test_default_families_cover_all_implemented_public_asset_datasets(self):
        normalized = PublicAssetSnapshotRunner._normalize_families(None)
        self.assertIn("equities_spot_snapshot", normalized)
        self.assertIn("bse_equities_spot_snapshot", normalized)
        self.assertIn("etf_spot_snapshot", normalized)
        self.assertIn("lof_spot_snapshot", normalized)
        self.assertIn("open_fund_nav_snapshot", normalized)
        self.assertIn("money_market_fund_snapshot", normalized)
        self.assertIn("reits_spot_snapshot", normalized)
        self.assertIn("convertible_bond_spot_snapshot", normalized)
        self.assertIn("sge_spot_daily_quotes", normalized)
        self.assertIn("carbon_market_snapshot", normalized)

    def test_state_merges_same_day_families(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_assets.json"
            runner = PublicAssetSnapshotRunner(state_path=state_path)
            runner._update_state(
                "2026-04-19",
                "success",
                {"etf_spot_snapshot": {"status": "success", "row_count": 1}},
            )
            runner._update_state(
                "2026-04-19",
                "success",
                {"reits_spot_snapshot": {"status": "success", "row_count": 2}},
            )
            payload = json.loads(state_path.read_text(encoding="utf-8"))

        families = payload["dates"]["2026-04-19"]["families"]
        self.assertIn("etf_spot_snapshot", families)
        self.assertIn("reits_spot_snapshot", families)
        self.assertEqual(payload["dates"]["2026-04-19"]["status"], "success")

    def test_validate_scopes_status_to_requested_families(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_assets.json"
            output_path = root / "data" / "normalized" / "public_assets" / "equities_spot_snapshot" / "2026-04-19.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "trade_date,asset_family,asset_type,market,exchange,symbol,name,last_price,change_amount,change_pct,open,high,low,prev_close,volume,amount,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,equities_funds_cn,stock,cn_equities,SSE,sh600000,浦发银行,10.5,0.2,1.9,10.3,10.6,10.2,10.3,1000,10000,akshare.stock_zh_a_spot,https://vip.stock.finance.sina.com.cn/mkt/#hs_a,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_assets/equities_spot_snapshot/20260419.json,public_assets_v1,abc,run1\n",
                encoding="utf-8-sig",
            )
            raw_path = root / "data" / "raw" / "public_assets" / "equities_spot_snapshot" / "20260419.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(json.dumps({"records": []}, ensure_ascii=False), encoding="utf-8")
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "dates": {
                            "2026-04-19": {
                                "status": "pending_retry",
                                "families": {
                                    "equities_spot_snapshot": {
                                        "status": "success",
                                        "output_path": "data/normalized/public_assets/equities_spot_snapshot/2026-04-19.csv",
                                    },
                                    "bse_equities_spot_snapshot": {
                                        "status": "pending_retry",
                                        "output_path": "",
                                    },
                                },
                            }
                        }
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            with mock.patch("src.futures_workflow.public_assets.PROJECT_ROOT", root):
                runner = PublicAssetSnapshotRunner(state_path=state_path)
                result = runner.validate("2026-04-19", families=["equities_spot_snapshot"])

        self.assertEqual(result["status"], "success")
        self.assertTrue(result["families"]["equities_spot_snapshot"]["schema_ok"])

    def test_latest_summaries_prefers_latest_success_with_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_assets.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "dates": {
                            "2026-04-19": {
                                "status": "success",
                                "families": {
                                    "sge_spot_daily_quotes": {
                                        "status": "no_data",
                                        "trade_date": "2026-04-19",
                                        "row_count": 0,
                                        "output_path": "",
                                    }
                                },
                            },
                            "2026-04-17": {
                                "status": "success",
                                "families": {
                                    "sge_spot_daily_quotes": {
                                        "status": "success",
                                        "trade_date": "2026-04-17",
                                        "row_count": 13,
                                        "output_path": "data/normalized/public_assets/sge_spot_daily_quotes/2026-04-17.csv",
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
            runner = PublicAssetSnapshotRunner(state_path=state_path)
            summaries = runner.latest_summaries()

        self.assertEqual(summaries["sge_spot_daily_quotes"]["trade_date"], "2026-04-17")
        self.assertEqual(summaries["sge_spot_daily_quotes"]["status"], "success")

    def test_sync_writes_sge_spot_daily_quotes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_assets.json"
            runner = PublicAssetSnapshotRunner(state_path=state_path)

            fake_symbols = pd.DataFrame([{"品种": "Au99.99"}, {"品种": "Ag(T+D)"}])
            fake_histories = {
                "Au99.99": pd.DataFrame(
                    [
                        {"date": "2026-04-16", "open": 1050.0, "close": 1058.36, "low": 1050.0, "high": 1060.2},
                        {"date": "2026-04-17", "open": 1058.0, "close": 1053.0, "low": 1046.1, "high": 1060.0},
                    ]
                ),
                "Ag(T+D)": pd.DataFrame(
                    [
                        {"date": "2026-04-16", "open": 19556.0, "close": 19853.0, "low": 19409.0, "high": 20000.0},
                        {"date": "2026-04-17", "open": 19760.0, "close": 19588.0, "low": 19320.0, "high": 19800.0},
                    ]
                ),
            }

            with mock.patch("src.futures_workflow.public_assets.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_assets.PUBLIC_ASSETS_NORMALIZED_DIR", root / "data" / "normalized" / "public_assets"
            ), mock.patch(
                "src.futures_workflow.public_assets.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.spot_symbol_table_sge", return_value=fake_symbols
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.spot_hist_sge", side_effect=lambda symbol: fake_histories[symbol]
            ), mock.patch(
                "src.futures_workflow.public_assets.time.sleep"
            ):
                result = runner.sync("2026-04-17", families=["sge_spot_daily_quotes"])
                self.assertEqual(result["status"], "success")
                self.assertEqual(result["families"]["sge_spot_daily_quotes"]["row_count"], 2)
                output_path = root / result["families"]["sge_spot_daily_quotes"]["output_path"]
                self.assertTrue(output_path.exists())

    def test_sync_writes_empty_csv_for_sge_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_assets.json"
            runner = PublicAssetSnapshotRunner(state_path=state_path)

            fake_symbols = pd.DataFrame([{"品种": "Au99.99"}])
            fake_history = pd.DataFrame(
                [
                    {"date": "2026-04-16", "open": 1050.0, "close": 1058.36, "low": 1050.0, "high": 1060.2},
                ]
            )

            with mock.patch("src.futures_workflow.public_assets.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_assets.PUBLIC_ASSETS_NORMALIZED_DIR", root / "data" / "normalized" / "public_assets"
            ), mock.patch(
                "src.futures_workflow.public_assets.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.spot_symbol_table_sge", return_value=fake_symbols
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.spot_hist_sge", return_value=fake_history
            ), mock.patch(
                "src.futures_workflow.public_assets.time.sleep"
            ):
                result = runner.sync("2026-04-17", families=["sge_spot_daily_quotes"])
                self.assertEqual(result["status"], "no_data")
                family = result["families"]["sge_spot_daily_quotes"]
                self.assertEqual(family["status"], "no_data")
                self.assertEqual(family["row_count"], 0)
                output_path = root / family["output_path"]
                self.assertTrue(output_path.exists())
                rows = list(_iter_csv_rows(output_path))
                self.assertEqual(rows, [])
                validation = runner.validate("2026-04-17", families=["sge_spot_daily_quotes"])
                self.assertTrue(validation["families"]["sge_spot_daily_quotes"]["csv_exists"])
                self.assertTrue(validation["families"]["sge_spot_daily_quotes"]["schema_ok"])
                self.assertEqual(validation["families"]["sge_spot_daily_quotes"]["row_count"], 0)

    def test_bse_snapshot_falls_back_to_gtimg_public_quotes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_assets.json"
            runner = PublicAssetSnapshotRunner(state_path=state_path)

            def fake_get(url, **kwargs):
                if "qt.gtimg.cn" in url:
                    return _mock_response(
                        'v_bj920001="62~北证样本~920001~12.30~11.90~11.95~2000~1000~1000~12.29~5~12.28~3~12.27~2~12.26~1~12.31~4~12.32~2~12.33~1~12.34~1~12.35~1~~20260421143058~0.40~3.36~12.40~11.80~12.30/2000/24000~2000~2~0.00~~~";',
                        encoding="gbk",
                    )
                raise AssertionError(url)

            with mock.patch("src.futures_workflow.public_assets.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_assets.PUBLIC_ASSETS_NORMALIZED_DIR", root / "data" / "normalized" / "public_assets"
            ), mock.patch(
                "src.futures_workflow.public_assets.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.stock_bj_a_spot_em", side_effect=RuntimeError("eastmoney down")
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.stock_info_bj_name_code",
                return_value=pd.DataFrame([{"证券代码": "920001", "证券简称": "北证样本"}]),
            ), mock.patch(
                "src.futures_workflow.public_assets.requests.get", side_effect=fake_get
            ), mock.patch(
                "src.futures_workflow.public_assets.now_shanghai"
            ) as mock_now:
                import datetime
                from zoneinfo import ZoneInfo

                mock_now.return_value = datetime.datetime(2026, 4, 21, 15, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
                result = runner.sync("latest", families=["bse_equities_spot_snapshot"])

            self.assertEqual(result["status"], "success")
            summary = result["families"]["bse_equities_spot_snapshot"]
            self.assertEqual(summary["row_count"], 1)
            self.assertEqual(summary["source_id"], "tencent.qt_bj_quote_public")
            output_path = root / summary["output_path"]
            rows = list(_iter_csv_rows(output_path))
            self.assertEqual(rows[0]["source_id"], "tencent.qt_bj_quote_public")
            self.assertEqual(rows[0]["source_url"], "https://qt.gtimg.cn/")

    def test_lof_snapshot_falls_back_to_sina_public_quotes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_assets.json"
            runner = PublicAssetSnapshotRunner(state_path=state_path)
            lof_html = """
            <table>
              <thead>
                <tr><th>序号</th><th>基金代码</th><th>基金简称</th></tr>
              </thead>
              <tbody>
                <tr><td>1</td><td>166009</td><td>中欧动力(LOF)估值图基金吧</td></tr>
              </tbody>
            </table>
            """

            def fake_get(url, **kwargs):
                if "LOF_jzzzl.html" in url:
                    return _mock_response(lof_html)
                if "hq.sinajs.cn" in url:
                    return _mock_response(
                        'var hq_str_sz166009="中欧动力,3.652,3.690,3.654,3.716,3.646,3.658,3.716,134,489.568,200,3.658,5500,3.657,1300,3.653,100,3.647,300,3.646,3000,3.716,1300,3.717,200,3.720,200,3.734,100,3.748,2026-04-21,13:30:57,00";',
                        encoding="gbk",
                    )
                raise AssertionError(url)

            with mock.patch("src.futures_workflow.public_assets.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_assets.PUBLIC_ASSETS_NORMALIZED_DIR", root / "data" / "normalized" / "public_assets"
            ), mock.patch(
                "src.futures_workflow.public_assets.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.fund_lof_spot_em", side_effect=RuntimeError("eastmoney down")
            ), mock.patch(
                "src.futures_workflow.public_assets.requests.get", side_effect=fake_get
            ), mock.patch(
                "src.futures_workflow.public_assets.now_shanghai"
            ) as mock_now:
                import datetime
                from zoneinfo import ZoneInfo

                mock_now.return_value = datetime.datetime(2026, 4, 21, 15, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
                result = runner.sync("latest", families=["lof_spot_snapshot"])

            self.assertEqual(result["status"], "success")
            summary = result["families"]["lof_spot_snapshot"]
            self.assertEqual(summary["row_count"], 1)
            self.assertEqual(summary["source_id"], "sina.hq_fund_quote_public")
            output_path = root / summary["output_path"]
            rows = list(_iter_csv_rows(output_path))
            self.assertEqual(rows[0]["symbol"], "166009")
            self.assertEqual(rows[0]["source_id"], "sina.hq_fund_quote_public")

    def test_reits_snapshot_falls_back_to_recent_universe_and_sina_quotes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "public_assets.json"
            output_path = root / "data" / "normalized" / "public_assets" / "reits_spot_snapshot" / "2026-04-19.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "trade_date,asset_family,asset_type,market,exchange,symbol,name,last_price,change_amount,change_pct,open,high,low,prev_close,volume,amount,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,equities_funds_cn,reits,cn_reits,SSE,508000,华安张江产业园REIT,2.43,0.01,0.4,2.42,2.45,2.41,2.42,100,1000,akshare.reits_realtime_em,https://quote.eastmoney.com/center/gridlist.html#fund_reits_all,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_assets/reits_spot_snapshot/20260419.json,public_assets_v1,abc,run1\n",
                encoding="utf-8-sig",
            )
            raw_path = root / "data" / "raw" / "public_assets" / "reits_spot_snapshot" / "20260419.json"
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
                                    "reits_spot_snapshot": {
                                        "status": "success",
                                        "trade_date": "2026-04-19",
                                        "row_count": 1,
                                        "output_path": "data/normalized/public_assets/reits_spot_snapshot/2026-04-19.csv",
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

            def fake_get(url, **kwargs):
                if "hq.sinajs.cn" in url:
                    return _mock_response(
                        'var hq_str_sh508000="华安张江产业园REIT,2.439,2.447,2.437,2.459,2.425,2.437,2.438,1266229,3089825.000,30300,2.437,200,2.436,86400,2.435,100,2.434,200,2.433,57000,2.438,1500,2.441,200,2.442,200,2.443,332200,2.444,2026-04-21,13:30:58,00,";',
                        encoding="gbk",
                    )
                raise AssertionError(url)

            with mock.patch("src.futures_workflow.public_assets.PROJECT_ROOT", root), mock.patch(
                "src.futures_workflow.public_assets.PUBLIC_ASSETS_NORMALIZED_DIR", root / "data" / "normalized" / "public_assets"
            ), mock.patch(
                "src.futures_workflow.public_assets.RAW_DIR", root / "data" / "raw"
            ), mock.patch(
                "src.futures_workflow.public_assets.ak.reits_realtime_em", side_effect=RuntimeError("eastmoney down")
            ), mock.patch(
                "src.futures_workflow.public_assets.requests.get", side_effect=fake_get
            ), mock.patch(
                "src.futures_workflow.public_assets.now_shanghai"
            ) as mock_now:
                import datetime
                from zoneinfo import ZoneInfo

                mock_now.return_value = datetime.datetime(2026, 4, 21, 15, 0, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
                runner = PublicAssetSnapshotRunner(state_path=state_path)
                result = runner.sync("latest", families=["reits_spot_snapshot"])

            self.assertEqual(result["status"], "success")
            summary = result["families"]["reits_spot_snapshot"]
            self.assertEqual(summary["row_count"], 1)
            self.assertEqual(summary["source_id"], "sina.hq_reits_quote_public")


if __name__ == "__main__":
    unittest.main()
