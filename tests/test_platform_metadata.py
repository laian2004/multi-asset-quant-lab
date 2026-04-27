import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.platform_metadata import PlatformMetadataRunner


class _FakeCheckpointStore:
    def __init__(self):
        self.data = {
            "dates": {
                "2026-04-16": {
                    "status": "success",
                    "outputs": {
                        "contracts_snapshot": "data/normalized/master/contracts/2026-04-16.csv",
                        "futures_daily_quotes": "data/normalized/daily_quotes/2026-04-16.csv",
                    },
                    "datasets": {
                        "contracts_snapshot": {"status": "success", "expected_exchanges": ["SHFE"], "observed_exchanges": ["SHFE"], "completeness_ok": True},
                        "futures_daily_quotes": {
                            "status": "success",
                            "expected_exchanges": ["SHFE"],
                            "observed_exchanges": ["SHFE"],
                            "completeness_ok": True,
                            "exchanges": {
                                "SHFE": {
                                    "trade_date": "2026-04-16",
                                    "status": "success",
                                    "source_url": "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx20260416.dat",
                                }
                            },
                        },
                    },
                }
            }
        }

    def get_day(self, trade_date: str):
        return self.data["dates"].get(trade_date, {})

    def get_last_fully_successful_trade_date(self):
        return "2026-04-16"


class _FakeWorkflowRunner:
    def __init__(self, checkpoint_store):
        self.checkpoints = checkpoint_store

    def validate(self, trade_date_value, selection=None):
        return {
            "trade_date": trade_date_value,
            "checkpoint_status": "success",
            "datasets": {
                "futures_daily_quotes": {
                    "row_count": 1,
                    "schema_ok": True,
                    "duplicate_keys": 0,
                    "missing_raw_paths": [],
                    "expected_exchanges": ["SHFE"],
                    "observed_exchanges": ["SHFE"],
                    "completeness_ok": True,
                },
                "options_exercise_results": {
                    "row_count": 0,
                    "schema_ok": True,
                    "duplicate_keys": 0,
                    "missing_raw_paths": [],
                    "expected_exchanges": ["SSE", "SZSE"],
                    "observed_exchanges": [],
                    "completeness_ok": False,
                    "result_chain_semantics_ok": False,
                    "no_data_reason": "No official exercise result endpoint configured.",
                    "status": "failed",
                },
            },
        }

    def audit_canonical_date(self, trade_date_value):
        return {
            "trade_date": trade_date_value,
            "needs_repair": False,
            "issues": [],
            "blocked_issues": [
                "options_exercise_results: missing exchanges [SSE, SZSE] are blocked by official result-chain source unavailability"
            ],
            "outputs": {},
        }


class _FakePublicRunner:
    def __init__(self, dataset_map, latest_recorded_map=None):
        self.dataset_map = dataset_map
        self.latest_recorded_map = latest_recorded_map

    def latest_summaries(self):
        return {
            dataset_name: {
                "dataset": dataset_name,
                "status": "success",
                "row_count": 1,
                "trade_date": "2026-04-19",
                "output_path": output_path,
            }
            for dataset_name, output_path in self.dataset_map.items()
        }

    def latest_recorded_summaries(self):
        if self.latest_recorded_map is not None:
            return self.latest_recorded_map
        return self.latest_summaries()

    def validate(self, trade_date_value, families=None):
        requested = list(families or self.dataset_map.keys())
        return {
            "trade_date": trade_date_value,
            "status": "success",
            "families": {
                dataset_name: {
                    "csv_exists": True,
                    "schema_ok": True,
                    "row_count": 1,
                    "missing_raw_paths": [],
                }
                for dataset_name in requested
                if dataset_name in self.dataset_map
            },
        }


class _FakeCryptoRunner:
    def latest_summaries(self):
        return {
            "crypto_global_snapshot": {
                "dataset": "crypto_global_snapshot",
                "status": "success",
                "row_count": 1,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/crypto_global/crypto_global_snapshot/2026-04-19.csv",
            },
            "crypto_derivatives_public": {
                "dataset": "crypto_derivatives_public",
                "status": "success",
                "row_count": 1,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/crypto_global/crypto_derivatives_public/2026-04-19.csv",
            },
        }

    def validate(self, trade_date_value):
        return {
            "trade_date": trade_date_value,
            "status": "success",
            "datasets": {
                "crypto_global_snapshot": {
                    "csv_exists": True,
                    "schema_ok": True,
                    "row_count": 1,
                    "missing_raw_paths": [],
                },
                "crypto_derivatives_public": {
                    "csv_exists": True,
                    "schema_ok": True,
                    "row_count": 1,
                    "missing_raw_paths": [],
                },
            },
        }


def _fake_regression_state_reader():
    return {
        "updated_at": "2026-04-20T19:47:10+08:00",
        "result": {
            "status": "success",
            "engineering_status": "success",
            "dates": ["2010-04-16", "2015-04-16", "2021-04-16", "2026-04-16"],
            "date_statuses": {
                "2010-04-16": "success",
                "2015-04-16": "success",
                "2021-04-16": "success",
                "2026-04-16": "success",
            },
            "window_results": {
                "latest_7_trading_days": {
                    "status": "success",
                    "sample_count": 4,
                    "sampled_dates": ["2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17"],
                    "status_counts": {"success": 4},
                }
            },
            "audit": {
                "needs_repair_dates": [],
                "issue_category_counts": {"result_chain_publication_lag": 1},
                "blocked_issues": ["options_exercise_results: missing exchanges [CFFEX] are pending official publication"],
            },
            "platform_sync_status": "success",
            "platform_validation_status": "success",
            "build_db_status": "success",
            "gui_smoke": {"has_yield_curves": True},
        },
    }


class PlatformMetadataRunnerTests(unittest.TestCase):
    def test_sync_materializes_platform_metadata_datasets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            contracts_path = root / "data" / "normalized" / "master" / "contracts" / "2026-04-16.csv"
            contracts_path.parent.mkdir(parents=True, exist_ok=True)
            contracts_path.write_text(
                "trade_date,instrument_type,exchange,product_code,product_name,contract,contract_status,list_date,expire_date,last_trade_date,contract_multiplier,quote_unit,price_tick,delivery_type,exercise_type,option_type,strike_price,underlying_exchange,underlying_kind,underlying_product_code,underlying_contract,source_url,source_type,retrieved_at,raw_path\n"
                "2026-04-16,future,SHFE,CU,沪铜,CU2605,active,2025-01-01,2026-05-15,2026-05-14,5,元/吨,10,实物交割,,,,,,, ,https://www.shfe.com.cn/,official,2026-04-19T15:00:00+08:00,data/raw/shfe/contracts_snapshot/20260416.json\n",
                encoding="utf-8-sig",
            )
            asset_path = root / "data" / "normalized" / "public_assets" / "equities_spot_snapshot" / "2026-04-19.csv"
            asset_path.parent.mkdir(parents=True, exist_ok=True)
            asset_path.write_text(
                "trade_date,asset_family,asset_type,market,exchange,symbol,name,last_price,change_amount,change_pct,open,high,low,prev_close,volume,amount,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,equities_funds_cn,stock,cn_equities,SSE,600000,浦发银行,10.1,0.1,1.0,10,10.2,9.9,10,1000,10000,akshare.stock_zh_a_spot,https://vip.stock.finance.sina.com.cn/mkt/#hs_a,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_assets/equities_spot_snapshot/20260419.json,public_assets_v1,a,b\n",
                encoding="utf-8-sig",
            )
            fund_path = root / "data" / "normalized" / "public_assets" / "open_fund_nav_snapshot" / "2026-04-19.csv"
            fund_path.parent.mkdir(parents=True, exist_ok=True)
            fund_path.write_text(
                "trade_date,asset_family,asset_type,market,exchange,symbol,name,last_price,change_amount,change_pct,open,high,low,prev_close,volume,amount,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,equities_funds_cn,open_fund,cn_funds,CN_FUNDS,000001,华夏成长混合,1.121,0.003,0.27,,,,1.118,,,akshare.fund_open_fund_daily_em,https://fund.eastmoney.com/fund.html#os_0;isall_0;ft_;pt_1,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_assets/open_fund_nav_snapshot/20260419.json,public_assets_v1,aa,bb\n",
                encoding="utf-8-sig",
            )
            reits_path = root / "data" / "normalized" / "public_assets" / "reits_spot_snapshot" / "2026-04-19.csv"
            reits_path.parent.mkdir(parents=True, exist_ok=True)
            reits_path.write_text(
                "trade_date,asset_family,asset_type,market,exchange,symbol,name,last_price,change_amount,change_pct,open,high,low,prev_close,volume,amount,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,equities_funds_cn,reits,cn_reits,SSE,180101,博时蛇口产园REIT,1.9,0.013,0.69,1.886,1.9,1.872,1.887,32113,6062173.81,akshare.reits_realtime_em,https://quote.eastmoney.com/center/gridlist.html#fund_reits_all,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_assets/reits_spot_snapshot/20260419.json,public_assets_v1,cc,dd\n",
                encoding="utf-8-sig",
            )
            commodity_path = root / "data" / "normalized" / "public_assets" / "sge_spot_daily_quotes" / "2026-04-19.csv"
            commodity_path.parent.mkdir(parents=True, exist_ok=True)
            commodity_path.write_text(
                "trade_date,asset_family,asset_type,market,exchange,symbol,name,last_price,change_amount,change_pct,open,high,low,prev_close,volume,amount,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,precious_metals_spot_cn,spot,cn_sge_spot,SGE,Au99.99,Au99.99,570.1,1.1,0.19,569,571,568,569,120,680000,akshare.spot_hist_sge,https://www.sge.com.cn/sjzx/mrhqsj,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_assets/sge_spot_daily_quotes/20260419.json,public_assets_v1,i,j\n",
                encoding="utf-8-sig",
            )
            reference_path = root / "data" / "normalized" / "public_references" / "fx_reference_rates" / "2026-04-19.csv"
            reference_path.parent.mkdir(parents=True, exist_ok=True)
            reference_path.write_text(
                "trade_date,asset_family,reference_type,market,exchange,symbol,name,base_currency,quote_currency,tenor,value,change_bp,unit,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,fx_money_market_cn,fx_reference_rate,cn_fx_reference,BOC,USD/CNY,美元/人民币参考价,USD,CNY,spot,686.22,,CNY,akshare.currency_boc_safe,https://www.boc.cn/sourcedb/whpj/,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_references/fx_reference_rates/20260419.json,public_references_v1,c,d\n",
                encoding="utf-8-sig",
            )
            precious_ref_path = root / "data" / "normalized" / "public_references" / "precious_metal_reference_quotes" / "2026-04-19.csv"
            precious_ref_path.parent.mkdir(parents=True, exist_ok=True)
            precious_ref_path.write_text(
                "trade_date,asset_family,reference_type,market,exchange,symbol,name,base_currency,quote_currency,tenor,value,change_bp,unit,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,precious_metals_spot_cn,benchmark,cn_pm_reference,SGE,AU_BENCH,上海金基准价,,CNY,spot,568.88,,元/克,akshare.spot_symbol_table_sge,https://www.sge.com.cn/sjzx/jzj,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_references/precious_metal_reference_quotes/20260419.json,public_references_v1,k,l\n",
                encoding="utf-8-sig",
            )
            treasury_path = root / "data" / "normalized" / "public_references" / "cn_us_treasury_yields" / "2026-04-19.csv"
            treasury_path.parent.mkdir(parents=True, exist_ok=True)
            treasury_path.write_text(
                "trade_date,asset_family,reference_type,market,exchange,symbol,name,base_currency,quote_currency,tenor,value,change_bp,unit,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,bonds_rates_cn,treasury_yield,cross_market_treasury_yield,EASTMONEY,CN_GOVT_10Y,中国国债10年, ,CNY,10Y,2.31,1,bp,cn_us_treasury_yields,https://data.eastmoney.com/cjsj/zmgzsyl.html,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_references/cn_us_treasury_yields/20260419.json,public_references_v1,ct,rt\n",
                encoding="utf-8-sig",
            )
            bond_path = root / "data" / "normalized" / "public_bonds" / "interbank_bond_deal_snapshot" / "2026-04-19.csv"
            bond_path.parent.mkdir(parents=True, exist_ok=True)
            bond_path.write_text(
                "trade_date,asset_family,dataset_type,market,exchange,symbol,name,curve_name,counterparty,tenor,price,bid_price,ask_price,yield,bid_yield,ask_yield,weighted_yield,change_bp,volume,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,bonds_rates_cn,interbank_bond_deal,cn_interbank_bond,CFETS,240210,国债240210,,,,101.1,,,1.95,,,1.95,,1000000,akshare.bond_spot_deal,https://www.chinamoney.com.cn/chinese/mkdatabond/,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_bonds/interbank_bond_deal_snapshot/20260419.json,public_bonds_v1,e,f\n",
                encoding="utf-8-sig",
            )
            curve_path = root / "data" / "normalized" / "public_bonds" / "yield_curve_points" / "2026-04-19.csv"
            curve_path.parent.mkdir(parents=True, exist_ok=True)
            curve_path.write_text(
                "trade_date,asset_family,dataset_type,market,exchange,symbol,name,curve_name,counterparty,tenor,price,bid_price,ask_price,yield,bid_yield,ask_yield,weighted_yield,change_bp,volume,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,bonds_rates_cn,yield_curve_points,cn_yield_curve,CHINABOND,,中债国债收益率曲线,中债国债收益率曲线,,10Y,,,,2.28,,,,1,,akshare.bond_china_yield,https://yield.chinabond.com.cn/,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_bonds/yield_curve_points/20260419.json,public_bonds_v1,yc1,yc2\n",
                encoding="utf-8-sig",
            )
            crypto_path = root / "data" / "normalized" / "crypto_global" / "crypto_global_snapshot" / "2026-04-19.csv"
            crypto_path.parent.mkdir(parents=True, exist_ok=True)
            crypto_path.write_text(
                "trade_date,asset_family,market,exchange,symbol,name,price_usd,change_amount_24h,change_pct_24h,high_24h,low_24h,total_volume,market_cap,market_cap_rank,circulating_supply,total_supply,max_supply,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id,legal_note\n"
                "2026-04-19,crypto_global_observation,global_crypto,COINGECKO,BTC,Bitcoin,75286,-100,-1,76000,74000,40000,1500000000000,1,20000000,20000000,21000000,coingecko.coins_markets_public,https://api.coingecko.com/api/v3/coins/markets,fallback_online,2026-04-19T15:00:00+08:00,data/raw/crypto_global/crypto_global_snapshot/20260419.json,crypto_observation_v2,g,h,仅作全球公开市场数据研究与行情观察，不提供交易、撮合、开户、引流或任何境内虚拟货币经营服务。\n",
                encoding="utf-8-sig",
            )
            crypto_derivatives_path = root / "data" / "normalized" / "crypto_global" / "crypto_derivatives_public" / "2026-04-19.csv"
            crypto_derivatives_path.parent.mkdir(parents=True, exist_ok=True)
            crypto_derivatives_path.write_text(
                "trade_date,asset_family,market,exchange,symbol,underlying_symbol,contract_type,price_usd,index_price_usd,basis,spread,funding_rate,open_interest_usd,volume_24h_usd,last_traded_at,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id,legal_note\n"
                "2026-04-19,crypto_global_observation,crypto_derivatives_public,CME,BTC,BTC,future,75300,75200,100,0.13,,99887766,1776610229,2026-04-19T14:59:00+08:00,coingecko.derivatives_public,https://api.coingecko.com/api/v3/derivatives,fallback_online,2026-04-19T15:00:00+08:00,data/raw/crypto_global/crypto_derivatives_public/20260419.json,crypto_observation_v2,m,n,仅作全球公开市场数据研究与行情观察，不提供交易、撮合、开户、引流或任何境内虚拟货币经营服务。\n",
                encoding="utf-8-sig",
            )
            state_path = root / "state" / "platform_metadata.json"
            checkpoint_store = _FakeCheckpointStore()
            workflow_runner = _FakeWorkflowRunner(checkpoint_store)

            with mock.patch("src.futures_workflow.platform_metadata.PLATFORM_NORMALIZED_DIR", root / "data" / "normalized" / "platform"), mock.patch(
                "src.futures_workflow.platform_metadata.PROJECT_ROOT", root
            ):
                runner = PlatformMetadataRunner(
                    workflow_runner=workflow_runner,
                    checkpoint_store=checkpoint_store,
                    public_asset_runner=_FakePublicRunner(
                        {
                            "equities_spot_snapshot": "data/normalized/public_assets/equities_spot_snapshot/2026-04-19.csv",
                            "open_fund_nav_snapshot": "data/normalized/public_assets/open_fund_nav_snapshot/2026-04-19.csv",
                            "reits_spot_snapshot": "data/normalized/public_assets/reits_spot_snapshot/2026-04-19.csv",
                            "sge_spot_daily_quotes": "data/normalized/public_assets/sge_spot_daily_quotes/2026-04-19.csv",
                        }
                    ),
                    public_reference_runner=_FakePublicRunner(
                        {
                            "fx_reference_rates": "data/normalized/public_references/fx_reference_rates/2026-04-19.csv",
                            "precious_metal_reference_quotes": "data/normalized/public_references/precious_metal_reference_quotes/2026-04-19.csv",
                            "cn_us_treasury_yields": "data/normalized/public_references/cn_us_treasury_yields/2026-04-19.csv",
                        }
                    ),
                    public_bond_runner=_FakePublicRunner(
                        {
                            "interbank_bond_deal_snapshot": "data/normalized/public_bonds/interbank_bond_deal_snapshot/2026-04-19.csv",
                            "yield_curve_points": "data/normalized/public_bonds/yield_curve_points/2026-04-19.csv",
                        }
                    ),
                    crypto_runner=_FakeCryptoRunner(),
                    regression_state_reader=_fake_regression_state_reader,
                    state_path=state_path,
                    project_root=root,
                )
                result = runner.sync("2026-04-19")
                validation = runner.validate("2026-04-19")

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["datasets"]["instrument_master"]["row_count"], 11)
            self.assertEqual(result["datasets"]["bond_master"]["row_count"], 2)
            self.assertEqual(result["datasets"]["bond_quotes"]["row_count"], 2)
            self.assertEqual(result["datasets"]["fx_quotes"]["row_count"], 1)
            self.assertEqual(result["datasets"]["commodity_spot_quotes"]["row_count"], 2)
            self.assertEqual(result["datasets"]["crypto_global_quotes"]["row_count"], 2)
            self.assertEqual(result["datasets"]["yield_curves"]["row_count"], 2)
            self.assertEqual(result["datasets"]["daily_ohlcv"]["row_count"], 3)
            self.assertEqual(result["datasets"]["fund_nav"]["row_count"], 1)
            self.assertEqual(result["datasets"]["reits_quotes"]["row_count"], 1)
            self.assertGreaterEqual(result["datasets"]["trading_calendar"]["row_count"], 4)
            self.assertEqual(result["datasets"]["asset_coverage"]["row_count"], 8)
            self.assertGreaterEqual(result["datasets"]["source_type_overview"]["row_count"], 3)
            self.assertGreaterEqual(result["datasets"]["issue_category_overview"]["row_count"], 2)
            self.assertTrue((root / "data" / "normalized" / "platform" / "instrument_master" / "2026-04-19.csv").exists())
            self.assertTrue((root / "data" / "normalized" / "platform" / "bond_master" / "2026-04-19.csv").exists())
            self.assertTrue((root / "data" / "normalized" / "platform" / "fx_quotes" / "2026-04-19.csv").exists())
            self.assertTrue((root / "data" / "normalized" / "platform" / "daily_ohlcv" / "2026-04-19.csv").exists())
            self.assertTrue(validation["datasets"]["instrument_master"]["schema_ok"])
            self.assertTrue(validation["datasets"]["bond_master"]["schema_ok"])
            self.assertTrue(validation["datasets"]["bond_quotes"]["schema_ok"])
            self.assertTrue(validation["datasets"]["fx_quotes"]["schema_ok"])
            self.assertTrue(validation["datasets"]["commodity_spot_quotes"]["schema_ok"])
            self.assertTrue(validation["datasets"]["crypto_global_quotes"]["schema_ok"])
            self.assertTrue(validation["datasets"]["yield_curves"]["schema_ok"])
            self.assertTrue(validation["datasets"]["daily_ohlcv"]["schema_ok"])
            self.assertTrue(validation["datasets"]["fund_nav"]["schema_ok"])
            self.assertTrue(validation["datasets"]["reits_quotes"]["schema_ok"])
            self.assertTrue(validation["datasets"]["trading_calendar"]["schema_ok"])
            self.assertTrue(validation["datasets"]["asset_coverage"]["schema_ok"])
            self.assertTrue(validation["datasets"]["run_health"]["schema_ok"])
            self.assertTrue(validation["datasets"]["run_history"]["schema_ok"])
            self.assertTrue(validation["datasets"]["coverage_history"]["schema_ok"])
            self.assertTrue(validation["datasets"]["validation_results"]["schema_ok"])
            self.assertTrue(validation["datasets"]["source_health"]["schema_ok"])
            self.assertTrue(validation["datasets"]["source_health_history"]["schema_ok"])
            self.assertTrue(validation["datasets"]["source_type_overview"]["schema_ok"])
            self.assertTrue(validation["datasets"]["issue_category_overview"]["schema_ok"])
            self.assertTrue(validation["datasets"]["research_metrics"]["schema_ok"])
            self.assertTrue(validation["datasets"]["factor_signals"]["schema_ok"])
            self.assertTrue(validation["datasets"]["strategy_backtests"]["schema_ok"])
            self.assertTrue(validation["datasets"]["paper_portfolios"]["schema_ok"])
            self.assertTrue(validation["datasets"]["quality_diagnostics"]["schema_ok"])
            self.assertTrue(validation["datasets"]["scheduler_runs"]["schema_ok"])
            self.assertTrue(validation["datasets"]["research_reports"]["schema_ok"])
            self.assertTrue(validation["datasets"]["algorithm_outputs"]["schema_ok"])
            self.assertTrue(validation["datasets"]["option_analytics"]["schema_ok"])
            self.assertTrue(validation["datasets"]["bond_analytics"]["schema_ok"])
            self.assertTrue(validation["datasets"]["curve_analytics"]["schema_ok"])
            self.assertTrue(validation["datasets"]["risk_metrics"]["schema_ok"])
            self.assertTrue(validation["datasets"]["portfolio_allocations"]["schema_ok"])
            self.assertTrue(validation["datasets"]["backtest_equity_curves"]["schema_ok"])
            self.assertTrue(validation["datasets"]["backtest_positions"]["schema_ok"])
            self.assertTrue(validation["datasets"]["backtest_trades"]["schema_ok"])
            self.assertTrue(validation["datasets"]["strategy_comparisons"]["schema_ok"])
            self.assertTrue(validation["datasets"]["anomaly_events"]["schema_ok"])
            self.assertTrue(validation["datasets"]["ml_model_runs"]["schema_ok"])
            self.assertTrue(validation["datasets"]["ml_predictions"]["schema_ok"])
            self.assertTrue(validation["datasets"]["ml_feature_importance"]["schema_ok"])
            self.assertTrue(validation["datasets"]["model_diagnostics"]["schema_ok"])
            self.assertTrue(validation["datasets"]["backtest_input_quality"]["schema_ok"])
            self.assertTrue(validation["datasets"]["experiment_runs"]["schema_ok"])
            self.assertTrue(validation["datasets"]["factor_performance"]["schema_ok"])
            self.assertTrue(validation["datasets"]["stress_test_results"]["schema_ok"])
            self.assertTrue(validation["datasets"]["artifact_manifest"]["schema_ok"])
            self.assertTrue(validation["datasets"]["dataset_quality_scores"]["schema_ok"])
            self.assertTrue(validation["datasets"]["report_artifacts"]["schema_ok"])
            asset_coverage_csv = root / "data" / "normalized" / "platform" / "asset_coverage" / "2026-04-19.csv"
            asset_coverage_rows = asset_coverage_csv.read_text(encoding="utf-8-sig")
            self.assertIn("family_label", asset_coverage_rows.splitlines()[0])
            self.assertIn("exchange_derivatives_cn", asset_coverage_rows)
            self.assertIn("crypto_global_observation", asset_coverage_rows)
            with asset_coverage_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                coverage_by_family = {row["asset_family"]: row for row in csv.DictReader(handle)}
            platform_family = coverage_by_family["platform_metadata"]
            self.assertEqual(platform_family["coverage_ratio"], "40/40")
            self.assertEqual(platform_family["engineering_status"], "done")
            self.assertEqual(platform_family["runtime_status"], "success")
            self.assertEqual(platform_family["missing_datasets"], "[]")
            commodity_family = coverage_by_family["commodity_energy_cn"]
            self.assertEqual(commodity_family["expected_dataset_count"], "1")
            self.assertIn(commodity_family["runtime_status"], {"no_data", "success"})
            self.assertIn(commodity_family["engineering_status"], {"done", "partial", "pending"})
            run_health_csv = root / "data" / "normalized" / "platform" / "run_health" / "2026-04-19.csv"
            run_health_rows = run_health_csv.read_text(encoding="utf-8-sig")
            self.assertIn("workflow_name", run_health_rows.splitlines()[0])
            self.assertIn("engineering_status", run_health_rows.splitlines()[0])
            self.assertIn("regression_smoke", run_health_rows)
            self.assertIn("result_chain_publication_lag", run_health_rows)
            self.assertIn("window_statuses", run_health_rows.splitlines()[0])
            self.assertIn("latest_7_trading_days", run_health_rows)
            run_history_csv = root / "data" / "normalized" / "platform" / "run_history" / "2026-04-19.csv"
            run_history_rows = run_history_csv.read_text(encoding="utf-8-sig")
            self.assertIn("history_kind", run_history_rows.splitlines()[0])
            self.assertIn("regression_smoke", run_history_rows)
            coverage_history_csv = root / "data" / "normalized" / "platform" / "coverage_history" / "2026-04-19.csv"
            coverage_history_rows = coverage_history_csv.read_text(encoding="utf-8-sig")
            self.assertIn("coverage_ratio", coverage_history_rows.splitlines()[0])
            self.assertIn("platform_metadata", coverage_history_rows)
            validation_results_csv = root / "data" / "normalized" / "platform" / "validation_results" / "2026-04-19.csv"
            validation_rows = validation_results_csv.read_text(encoding="utf-8-sig")
            self.assertIn("blocked_issue_count", validation_rows.splitlines()[0])
            self.assertIn("blocked_issues", validation_rows.splitlines()[0])
            self.assertIn("options_exercise_results: missing exchanges [SSE, SZSE] are blocked by official result-chain source unavailability", validation_rows)
            self.assertIn("platform_metadata,daily_ohlcv,2026-04-19,success", validation_rows)
            self.assertIn("platform_metadata,fund_nav,2026-04-19,success", validation_rows)
            self.assertIn("platform_metadata,yield_curves,2026-04-19,success", validation_rows)
            source_health_csv = root / "data" / "normalized" / "platform" / "source_health" / "2026-04-19.csv"
            source_health_rows = source_health_csv.read_text(encoding="utf-8-sig")
            self.assertIn("issue_category", source_health_rows.splitlines()[0])
            self.assertIn("issue_root_cause", source_health_rows.splitlines()[0])
            self.assertIn("is_external_blocker", source_health_rows.splitlines()[0])
            self.assertIn("blocked_reason", source_health_rows.splitlines()[0])
            self.assertIn("futures_delivery_results", source_health_rows)
            self.assertIn("options_exercise_results", source_health_rows)
            self.assertIn("daily_ohlcv", source_health_rows)
            self.assertIn("fund_nav", source_health_rows)
            self.assertIn("trading_calendar", source_health_rows)
            self.assertIn("yield_curves", source_health_rows)
            self.assertIn("run_history", source_health_rows)
            self.assertIn("coverage_history", source_health_rows)
            self.assertIn("source_health_history", source_health_rows)
            self.assertIn("research_metrics", source_health_rows)
            self.assertIn("factor_signals", source_health_rows)
            self.assertIn("strategy_backtests", source_health_rows)
            self.assertIn("paper_portfolios", source_health_rows)
            self.assertIn("quality_diagnostics", source_health_rows)
            self.assertIn("scheduler_runs", source_health_rows)
            self.assertIn("research_reports", source_health_rows)
            self.assertIn("ml_model_runs", source_health_rows)
            self.assertIn("ml_predictions", source_health_rows)
            self.assertIn("ml_feature_importance", source_health_rows)
            self.assertIn("model_diagnostics", source_health_rows)
            self.assertIn("backtest_input_quality", source_health_rows)
            self.assertIn("experiment_runs", source_health_rows)
            self.assertIn("factor_performance", source_health_rows)
            self.assertIn("stress_test_results", source_health_rows)
            self.assertIn("artifact_manifest", source_health_rows)
            self.assertIn("dataset_quality_scores", source_health_rows)
            self.assertIn("report_artifacts", source_health_rows)
            self.assertIn("derived", source_health_rows)
            self.assertIn("blocked_issue", source_health_rows)
            self.assertNotIn("source_type_overview,,,", source_health_rows)
            self.assertNotIn("issue_category_overview,,,", source_health_rows)
            self.assertNotIn("source_health,,,", source_health_rows)
            source_health_history_csv = root / "data" / "normalized" / "platform" / "source_health_history" / "2026-04-19.csv"
            source_health_history_rows = source_health_history_csv.read_text(encoding="utf-8-sig")
            self.assertIn("issue_root_cause", source_health_history_rows.splitlines()[0])
            self.assertIn("cffex.options_exercise_results", source_health_history_rows)
            source_type_overview_csv = root / "data" / "normalized" / "platform" / "source_type_overview" / "2026-04-19.csv"
            source_type_overview_rows = source_type_overview_csv.read_text(encoding="utf-8-sig")
            self.assertIn("source_type", source_type_overview_rows.splitlines()[0])
            self.assertIn("official", source_type_overview_rows)
            self.assertIn("derived", source_type_overview_rows)
            self.assertIn("blocked_issue_count", source_type_overview_rows.splitlines()[0])
            issue_category_overview_csv = root / "data" / "normalized" / "platform" / "issue_category_overview" / "2026-04-19.csv"
            issue_category_overview_rows = issue_category_overview_csv.read_text(encoding="utf-8-sig")
            self.assertIn("issue_category", issue_category_overview_rows.splitlines()[0])
            self.assertIn("healthy", issue_category_overview_rows)
            self.assertIn("blocked_issue", issue_category_overview_rows)
            self.assertIn("source_type_counts", issue_category_overview_rows.splitlines()[0])

    def test_source_health_uses_latest_recorded_derivative_day(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "platform_metadata.json"
            checkpoint_store = _FakeCheckpointStore()
            checkpoint_store.data["dates"]["2026-04-17"] = {
                "status": "partial_success",
                "outputs": {
                    "futures_delivery_results": "data/normalized/results/futures_delivery/2026-04-17.csv",
                },
                "datasets": {
                    "futures_delivery_results": {
                        "status": "partial_success",
                        "expected_exchanges": ["CFFEX", "SHFE"],
                        "observed_exchanges": ["SHFE"],
                        "completeness_ok": False,
                        "exchanges": {
                            "SHFE": {
                                "trade_date": "2026-04-17",
                                "status": "success",
                                "source_url": "https://www.shfe.com.cn/data/tradedata/future/monthdata/ExchangeDelivery202604.dat",
                                "message": "",
                            },
                            "CFFEX": {
                                "trade_date": "2026-04-17",
                                "status": "pending_retry",
                                "source_url": "http://www.cffex.com.cn/unknown",
                                "message": "upstream timeout",
                            },
                        },
                    }
                },
            }
            workflow_runner = _FakeWorkflowRunner(checkpoint_store)
            with mock.patch("src.futures_workflow.platform_metadata.PLATFORM_NORMALIZED_DIR", root / "data" / "normalized" / "platform"), mock.patch(
                "src.futures_workflow.platform_metadata.PROJECT_ROOT", root
            ):
                runner = PlatformMetadataRunner(
                    workflow_runner=workflow_runner,
                    checkpoint_store=checkpoint_store,
                    public_asset_runner=_FakePublicRunner({}),
                    public_reference_runner=_FakePublicRunner({}),
                    public_bond_runner=_FakePublicRunner({}),
                    crypto_runner=_FakeCryptoRunner(),
                    regression_state_reader=_fake_regression_state_reader,
                    state_path=state_path,
                    project_root=root,
                )
                result = runner.sync("2026-04-20")
            self.assertEqual(result["datasets"]["source_health"]["status"], "success")
            source_health_csv = root / "data" / "normalized" / "platform" / "source_health" / "2026-04-20.csv"
            rows = source_health_csv.read_text(encoding="utf-8-sig")
            self.assertIn("2026-04-17", rows)
            self.assertIn("upstream timeout", rows)

    def test_source_health_and_asset_coverage_use_latest_recorded_public_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            state_path = root / "state" / "platform_metadata.json"
            latest_recorded = {
                "reits_spot_snapshot": {
                    "dataset": "reits_spot_snapshot",
                    "status": "pending_retry",
                    "trade_date": "2026-04-21",
                    "row_count": 0,
                    "message": "ProxyError: Unable to connect to proxy",
                    "source_url": "https://quote.eastmoney.com/center/gridlist.html#fund_reits_all",
                    "output_path": "",
                }
            }
            with mock.patch("src.futures_workflow.platform_metadata.PLATFORM_NORMALIZED_DIR", root / "data" / "normalized" / "platform"), mock.patch(
                "src.futures_workflow.platform_metadata.PROJECT_ROOT", root
            ):
                runner = PlatformMetadataRunner(
                    workflow_runner=_FakeWorkflowRunner(_FakeCheckpointStore()),
                    checkpoint_store=_FakeCheckpointStore(),
                    public_asset_runner=_FakePublicRunner({}, latest_recorded_map=latest_recorded),
                    public_reference_runner=_FakePublicRunner({}),
                    public_bond_runner=_FakePublicRunner({}),
                    crypto_runner=_FakeCryptoRunner(),
                    regression_state_reader=_fake_regression_state_reader,
                    state_path=state_path,
                    project_root=root,
                )
                runner.sync("2026-04-21")
            source_health_csv = root / "data" / "normalized" / "platform" / "source_health" / "2026-04-21.csv"
            source_health_rows = source_health_csv.read_text(encoding="utf-8-sig")
            self.assertIn("reits_spot_snapshot,fallback_online,10,https://quote.eastmoney.com/center/gridlist.html#fund_reits_all,pending_retry", source_health_rows)
            self.assertIn("proxy_failure", source_health_rows)
            asset_coverage_csv = root / "data" / "normalized" / "platform" / "asset_coverage" / "2026-04-21.csv"
            asset_coverage_rows = asset_coverage_csv.read_text(encoding="utf-8-sig")
            self.assertIn("equities_funds_cn", asset_coverage_rows)
            self.assertIn("pending_retry", asset_coverage_rows)
            self.assertIn("proxy_failure", asset_coverage_rows)


if __name__ == "__main__":
    unittest.main()
