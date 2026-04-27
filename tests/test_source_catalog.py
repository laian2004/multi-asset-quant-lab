import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.source_catalog import build_source_catalog


class SourceCatalogTests(unittest.TestCase):
    def test_build_source_catalog_contains_new_public_sources(self):
        catalog = build_source_catalog()
        source_map = {item["source_id"]: item for item in catalog}

        self.assertIn("sge_spot_daily_quotes", source_map)
        self.assertIn("sse_bond_deal_summary", source_map)
        self.assertIn("sse_bond_cash_summary", source_map)
        self.assertIn("reserve_reference_series", source_map)
        self.assertIn("rmb_middle_rates", source_map)
        self.assertIn("fx_pair_quotes", source_map)
        self.assertIn("fx_swap_quotes", source_map)
        self.assertIn("fx_c_swap_curve", source_map)
        self.assertIn("cn_us_treasury_yields", source_map)
        self.assertIn("crypto_bitcoin_holdings_public", source_map)
        self.assertIn("crypto_cme_bitcoin_report", source_map)
        self.assertIn("carbon_market_snapshot", source_map)
        self.assertIn("shfe.futures_delivery_results", source_map)
        self.assertIn("ine.futures_delivery_results", source_map)
        self.assertIn("dce.futures_delivery_results", source_map)
        self.assertIn("dce.options_exercise_results", source_map)
        self.assertIn("sse.options_exercise_results", source_map)
        self.assertIn("szse.options_exercise_results", source_map)
        self.assertIn("daily_ohlcv", source_map)
        self.assertIn("fund_nav", source_map)
        self.assertIn("reits_quotes", source_map)
        self.assertIn("trading_calendar", source_map)
        self.assertIn("yield_curves", source_map)
        self.assertIn("asset_coverage", source_map)
        self.assertIn("source_type_overview", source_map)
        self.assertIn("issue_category_overview", source_map)
        self.assertIn("ml_model_runs", source_map)
        self.assertIn("ml_predictions", source_map)
        self.assertIn("ml_feature_importance", source_map)
        self.assertIn("model_diagnostics", source_map)
        self.assertIn("backtest_input_quality", source_map)
        self.assertIn("experiment_runs", source_map)
        self.assertIn("factor_performance", source_map)
        self.assertIn("stress_test_results", source_map)
        self.assertIn("artifact_manifest", source_map)
        self.assertIn("dataset_quality_scores", source_map)
        self.assertIn("report_artifacts", source_map)
        self.assertEqual(source_map["sge_spot_daily_quotes"]["asset_family"], "precious_metals_spot_cn")
        self.assertEqual(source_map["sse_bond_deal_summary"]["exchange"], "SSE")
        self.assertEqual(source_map["reserve_reference_series"]["market"], "cn_reserve_reference")
        self.assertEqual(source_map["rmb_middle_rates"]["market"], "cn_rmb_central_parity")
        self.assertEqual(source_map["fx_pair_quotes"]["market"], "cn_fx_pair")
        self.assertEqual(source_map["fx_c_swap_curve"]["exchange"], "CFETS")
        self.assertEqual(source_map["cn_us_treasury_yields"]["market"], "cross_market_treasury_yield")
        self.assertEqual(source_map["crypto_bitcoin_holdings_public"]["market"], "crypto_public_bitcoin_holdings")
        self.assertEqual(source_map["crypto_cme_bitcoin_report"]["exchange"], "CME/JIN10")
        self.assertEqual(source_map["carbon_market_snapshot"]["market"], "cn_carbon")
        self.assertEqual(source_map["shfe.futures_delivery_results"]["dataset"], "futures_delivery_results")
        self.assertEqual(source_map["ine.futures_delivery_results"]["exchange"], "INE")
        self.assertIn("/servlets/MonthlyReport", source_map["dce.futures_delivery_results"]["url"])
        self.assertEqual(source_map["sse.options_exercise_results"]["dataset"], "options_exercise_results")
        self.assertIn("/servlets/MonthlyReport", source_map["dce.options_exercise_results"]["url"])
        self.assertIn("/commonQuery.do", source_map["sse.options_exercise_results"]["url"])
        self.assertIn("/api/report/ShowReport/data", source_map["szse.options_exercise_results"]["url"])
        self.assertEqual(source_map["daily_ohlcv"]["source_type"], "derived")
        self.assertEqual(source_map["trading_calendar"]["market"], "platform_unified")
        self.assertEqual(source_map["yield_curves"]["source_type"], "derived")
        self.assertEqual(source_map["asset_coverage"]["market"], "platform_overview")
        self.assertEqual(source_map["source_type_overview"]["market"], "platform_quality")
        self.assertEqual(source_map["issue_category_overview"]["market"], "platform_quality")
        self.assertEqual(source_map["ml_model_runs"]["source_type"], "derived")
        self.assertEqual(source_map["factor_performance"]["market"], "platform_factor_analytics")
        self.assertEqual(source_map["stress_test_results"]["asset_family"], "platform_metadata")


if __name__ == "__main__":
    unittest.main()
