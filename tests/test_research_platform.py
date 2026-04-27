import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from src.futures_workflow.research_platform import ResearchPlatformRunner, SchedulerRunner


class ResearchPlatformTests(unittest.TestCase):
    def test_research_metrics_mark_missing_numeric_fields_not_applicable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            normalized = root / "data" / "normalized"
            source = normalized / "platform" / "daily_ohlcv" / "2026-04-19.csv"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                "trade_date,instrument_id,asset_family,market,exchange,instrument_type,symbol,name,currency,open,high,low,close,pre_close,settlement,pre_settlement,volume,amount,open_interest,turnover_rate,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,SSE:600000,equities_funds_cn,cn_equities,SSE,stock,600000,浦发银行,CNY,,,,,,,,,,,,akshare.stock,https://example.test,fallback_online,2026-04-19T15:00:00+08:00,,platform_metadata_v1,abc,run1\n",
                encoding="utf-8-sig",
            )
            runner = ResearchPlatformRunner(project_root=root, normalized_root=normalized, platform_dir=normalized / "platform", reports_dir=root / "reports")

            result = runner.run_research(date_value="2026-04-19", dataset="daily_ohlcv")

            self.assertEqual(result["status"], "success")
            rows = list((normalized / "platform" / "research_metrics" / "2026-04-19.csv").read_text(encoding="utf-8-sig").splitlines())
            self.assertIn("research_metrics", result["datasets"])
            self.assertTrue(any("not_applicable" in row for row in rows))

    def test_factor_strategy_and_report_chain_materializes_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            normalized = root / "data" / "normalized"
            source = normalized / "platform" / "daily_ohlcv" / "2026-04-20.csv"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                "trade_date,instrument_id,asset_family,market,exchange,instrument_type,symbol,name,currency,open,high,low,close,pre_close,settlement,pre_settlement,volume,amount,open_interest,turnover_rate,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,SSE:600000,equities_funds_cn,cn_equities,SSE,stock,600000,浦发银行,CNY,10,10.2,9.9,10,,,,1000,10000,,,akshare.stock,https://example.test,fallback_online,2026-04-19T15:00:00+08:00,,platform_metadata_v1,abc,run1\n"
                "2026-04-20,SSE:600000,equities_funds_cn,cn_equities,SSE,stock,600000,浦发银行,CNY,10.1,10.5,10,10.4,,,,1200,12000,,,akshare.stock,https://example.test,fallback_online,2026-04-20T15:00:00+08:00,,platform_metadata_v1,def,run2\n",
                encoding="utf-8-sig",
            )
            source_health = normalized / "platform" / "source_health" / "2026-04-20.csv"
            source_health.parent.mkdir(parents=True, exist_ok=True)
            source_health.write_text(
                "trade_date,source_id,asset_family,market,exchange,dataset,source_type,priority,source_url,last_status,last_trade_date,last_success_trade_date,output_path,issue_category,issue_root_cause,is_external_blocker,blocked_reason,message\n"
                "2026-04-20,platform.test,platform_metadata,platform,DERIVED,daily_ohlcv,derived,1,platform://daily_ohlcv,success,2026-04-20,2026-04-20,data/normalized/platform/daily_ohlcv/2026-04-20.csv,healthy,,false,,\n",
                encoding="utf-8-sig",
            )
            runner = ResearchPlatformRunner(project_root=root, normalized_root=normalized, platform_dir=normalized / "platform", reports_dir=root / "reports")

            factor = runner.run_factors(start_date="2026-04-19", end_date="2026-04-20", factor="momentum")
            backtest = runner.run_strategy_backtest(start_date="2026-04-19", end_date="2026-04-20", strategy="momentum")
            quality = runner.quality_diagnose(date_value="2026-04-20")
            report = runner.report_generate(date_value="2026-04-20")

            self.assertEqual(factor["status"], "success")
            self.assertEqual(backtest["status"], "success")
            self.assertEqual(quality["status"], "success")
            self.assertEqual(report["status"], "success")
            self.assertTrue((root / report["markdown_path"]).exists())
            self.assertTrue((root / report["html_path"]).exists())

    def test_algorithm_risk_portfolio_and_backtest_outputs_materialize(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            normalized = root / "data" / "normalized"
            source = normalized / "platform" / "daily_ohlcv" / "2026-04-22.csv"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                "trade_date,instrument_id,asset_family,market,exchange,instrument_type,symbol,name,currency,open,high,low,close,pre_close,settlement,pre_settlement,volume,amount,open_interest,turnover_rate,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-20,SSE:600000,equities_funds_cn,cn_equities,SSE,stock,600000,浦发银行,CNY,10,10.2,9.9,10,,,,1000,10000,,,akshare.stock,https://example.test,fallback_online,2026-04-20T15:00:00+08:00,,platform_metadata_v1,abc,run1\n"
                "2026-04-21,SSE:600000,equities_funds_cn,cn_equities,SSE,stock,600000,浦发银行,CNY,10.2,10.5,10,10.4,,,,1300,12000,,,akshare.stock,https://example.test,fallback_online,2026-04-21T15:00:00+08:00,,platform_metadata_v1,def,run2\n"
                "2026-04-22,SSE:600000,equities_funds_cn,cn_equities,SSE,stock,600000,浦发银行,CNY,10.3,10.8,10.2,10.6,,,,1600,15000,,,akshare.stock,https://example.test,fallback_online,2026-04-22T15:00:00+08:00,,platform_metadata_v1,ghi,run3\n"
                "2026-04-20,SZSE:000001,equities_funds_cn,cn_equities,SZSE,stock,000001,平安银行,CNY,12,12.1,11.8,12,,,,2000,24000,,,akshare.stock,https://example.test,fallback_online,2026-04-20T15:00:00+08:00,,platform_metadata_v1,jkl,run4\n"
                "2026-04-21,SZSE:000001,equities_funds_cn,cn_equities,SZSE,stock,000001,平安银行,CNY,12.1,12.3,12,12.2,,,,1900,23500,,,akshare.stock,https://example.test,fallback_online,2026-04-21T15:00:00+08:00,,platform_metadata_v1,mno,run5\n"
                "2026-04-22,SZSE:000001,equities_funds_cn,cn_equities,SZSE,stock,000001,平安银行,CNY,12.2,12.5,12.1,12.4,,,,2100,26000,,,akshare.stock,https://example.test,fallback_online,2026-04-22T15:00:00+08:00,,platform_metadata_v1,pqr,run6\n",
                encoding="utf-8-sig",
            )
            runner = ResearchPlatformRunner(project_root=root, normalized_root=normalized, platform_dir=normalized / "platform", reports_dir=root / "reports")

            algorithm = runner.run_algorithm(
                template="black_scholes_price",
                start_date="2026-04-20",
                end_date="2026-04-22",
                dataset="daily_ohlcv",
                params_json='{"underlying_price":100,"strike_price":100,"maturity_years":0.5,"risk_free_rate":0.02,"volatility":0.2,"option_type":"call"}',
            )
            factor_algorithm = runner.run_algorithm(template="volume_turnover", start_date="2026-04-20", end_date="2026-04-22", dataset="daily_ohlcv")
            risk = runner.run_risk(template="var_cvar", start_date="2026-04-20", end_date="2026-04-22", dataset="daily_ohlcv", params_json='{"confidence":0.95}')
            portfolio = runner.optimize_portfolio(template="risk_parity", start_date="2026-04-20", end_date="2026-04-22", dataset="daily_ohlcv")
            backtest = runner.run_backtest(strategy="momentum", start_date="2026-04-20", end_date="2026-04-22", dataset="daily_ohlcv", slippage_bps=1.0)

            self.assertEqual(algorithm["status"], "success")
            self.assertEqual(factor_algorithm["status"], "success")
            self.assertEqual(risk["status"], "success")
            self.assertEqual(portfolio["status"], "success")
            self.assertEqual(backtest["status"], "success")
            self.assertTrue((normalized / "platform" / "algorithm_outputs" / "2026-04-22.csv").exists())
            self.assertTrue((normalized / "platform" / "option_analytics" / "2026-04-22.csv").exists())
            self.assertTrue((normalized / "platform" / "risk_metrics" / "2026-04-22.csv").exists())
            self.assertTrue((normalized / "platform" / "portfolio_allocations" / "2026-04-22.csv").exists())
            self.assertTrue((normalized / "platform" / "backtest_equity_curves" / "2026-04-22.csv").exists())
            self.assertTrue((normalized / "platform" / "backtest_positions" / "2026-04-22.csv").exists())
            self.assertTrue((normalized / "platform" / "backtest_trades" / "2026-04-22.csv").exists())
            self.assertTrue((normalized / "platform" / "strategy_comparisons" / "2026-04-22.csv").exists())

    def test_ml_factor_performance_stress_quality_and_artifacts_materialize(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            normalized = root / "data" / "normalized"
            source = normalized / "platform" / "daily_ohlcv" / "2026-04-24.csv"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                "trade_date,instrument_id,asset_family,market,exchange,instrument_type,symbol,name,currency,open,high,low,close,pre_close,settlement,pre_settlement,volume,amount,open_interest,turnover_rate,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-20,SSE:600000,equities_funds_cn,cn_equities,SSE,stock,600000,浦发银行,CNY,10,10.2,9.9,10,,,,1000,10000,,,akshare.stock,https://example.test,fallback_online,2026-04-20T15:00:00+08:00,,platform_metadata_v1,abc,run1\n"
                "2026-04-21,SSE:600000,equities_funds_cn,cn_equities,SSE,stock,600000,浦发银行,CNY,10.2,10.5,10,10.4,,,,1300,12000,,,akshare.stock,https://example.test,fallback_online,2026-04-21T15:00:00+08:00,,platform_metadata_v1,def,run2\n"
                "2026-04-22,SSE:600000,equities_funds_cn,cn_equities,SSE,stock,600000,浦发银行,CNY,10.3,10.8,10.2,10.6,,,,1600,15000,,,akshare.stock,https://example.test,fallback_online,2026-04-22T15:00:00+08:00,,platform_metadata_v1,ghi,run3\n"
                "2026-04-23,SSE:600000,equities_funds_cn,cn_equities,SSE,stock,600000,浦发银行,CNY,10.6,10.9,10.3,10.7,,,,1500,15500,,,akshare.stock,https://example.test,fallback_online,2026-04-23T15:00:00+08:00,,platform_metadata_v1,jkl,run4\n"
                "2026-04-24,SSE:600000,equities_funds_cn,cn_equities,SSE,stock,600000,浦发银行,CNY,10.7,11.1,10.5,10.9,,,,1700,18000,,,akshare.stock,https://example.test,fallback_online,2026-04-24T15:00:00+08:00,,platform_metadata_v1,mno,run5\n",
                encoding="utf-8-sig",
            )
            runner = ResearchPlatformRunner(project_root=root, normalized_root=normalized, platform_dir=normalized / "platform", reports_dir=root / "reports")

            ml = runner.run_ml(template="linear_regression", start_date="2026-04-20", end_date="2026-04-24", dataset="daily_ohlcv", target="close", features=["open", "high", "low", "volume"], tune=True)
            factor_perf = runner.factor_performance(factor="momentum", start_date="2026-04-20", end_date="2026-04-24", dataset="daily_ohlcv")
            stress = runner.stress_test(template="equity_down", start_date="2026-04-20", end_date="2026-04-24", dataset="daily_ohlcv", params_json='{"shock_pct":-0.1}')
            quality_score = runner.quality_score(date_value="2026-04-24")
            report = runner.report_generate(date_value="2026-04-24", report_type="comprehensive")
            experiments = runner.experiment_list(date_value="2026-04-24")
            artifacts = runner.artifact_list(date_value="2026-04-24")

            self.assertEqual(ml["status"], "success")
            self.assertEqual(factor_perf["status"], "success")
            self.assertEqual(stress["status"], "success")
            self.assertEqual(quality_score["status"], "success")
            self.assertEqual(report["status"], "success")
            self.assertGreaterEqual(experiments["row_count"], 3)
            self.assertGreaterEqual(artifacts["row_count"], 1)
            self.assertTrue((normalized / "platform" / "ml_model_runs" / "2026-04-24.csv").exists())
            self.assertTrue((normalized / "platform" / "ml_predictions" / "2026-04-24.csv").exists())
            self.assertTrue((normalized / "platform" / "ml_feature_importance" / "2026-04-24.csv").exists())
            self.assertTrue((normalized / "platform" / "model_diagnostics" / "2026-04-24.csv").exists())
            model_text = (normalized / "platform" / "ml_model_runs" / "2026-04-24.csv").read_text(encoding="utf-8-sig")
            diagnostic_text = (normalized / "platform" / "model_diagnostics" / "2026-04-24.csv").read_text(encoding="utf-8-sig")
            self.assertIn("open,high,low,volume", model_text)
            self.assertIn("validation_r2", model_text)
            self.assertIn("train_count", diagnostic_text)
            self.assertIn("test_count", diagnostic_text)
            self.assertIn("mae", diagnostic_text)
            self.assertTrue((normalized / "platform" / "factor_performance" / "2026-04-24.csv").exists())
            self.assertTrue((normalized / "platform" / "stress_test_results" / "2026-04-24.csv").exists())
            self.assertTrue((normalized / "platform" / "dataset_quality_scores" / "2026-04-24.csv").exists())
            self.assertTrue((normalized / "platform" / "report_artifacts" / "2026-04-24.csv").exists())
            self.assertTrue((normalized / "platform" / "artifact_manifest" / "2026-04-24.csv").exists())

    def test_project_run_builds_full_research_loop_and_report_interpretation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            normalized = root / "data" / "normalized"
            source = normalized / "platform" / "daily_ohlcv" / "2026-04-25.csv"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_text(
                "trade_date,instrument_id,asset_family,market,exchange,instrument_type,symbol,name,currency,open,high,low,close,pre_close,settlement,pre_settlement,volume,amount,open_interest,turnover_rate,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-23,SSE:510300,equities_funds_cn,cn_equities,SSE,etf,510300,沪深300ETF,CNY,4.0,4.1,3.9,4.0,,,,1000,4000,,,akshare.etf,https://example.test,fallback_online,2026-04-23T15:00:00+08:00,,platform_metadata_v1,abc,run1\n"
                "2026-04-24,SSE:510300,equities_funds_cn,cn_equities,SSE,etf,510300,沪深300ETF,CNY,4.1,4.2,4.0,4.2,,,,1100,4620,,,akshare.etf,https://example.test,fallback_online,2026-04-24T15:00:00+08:00,,platform_metadata_v1,def,run2\n"
                "2026-04-25,SSE:510300,equities_funds_cn,cn_equities,SSE,etf,510300,沪深300ETF,CNY,4.2,4.3,4.1,4.25,,,,1200,5100,,,akshare.etf,https://example.test,fallback_online,2026-04-25T15:00:00+08:00,,platform_metadata_v1,ghi,run3\n",
                encoding="utf-8-sig",
            )
            runner = ResearchPlatformRunner(project_root=root, normalized_root=normalized, platform_dir=normalized / "platform", reports_dir=root / "reports")

            project = runner.project_create(name="ETF动量研究", description="测试项目闭环", date_value="2026-04-25")
            run = runner.project_run(
                project_id=project["project_id"],
                template="momentum",
                start_date="2026-04-23",
                end_date="2026-04-25",
                dataset="daily_ohlcv",
                params_json='{"report_type":"project","fee_bps":1,"slippage_bps":1}',
            )

            self.assertEqual(run["status"], "success")
            self.assertTrue((normalized / "platform" / "factor_experiments" / "2026-04-25.csv").exists())
            self.assertTrue((normalized / "platform" / "backtest_equity_curves" / "2026-04-25.csv").exists())
            self.assertTrue((normalized / "platform" / "strategy_leaderboard" / "2026-04-25.csv").exists())
            self.assertTrue((normalized / "platform" / "project_runs" / "2026-04-25.csv").exists())
            self.assertTrue((normalized / "platform" / "reproducible_packages" / "2026-04-25.csv").exists())
            self.assertTrue((normalized / "platform" / "report_insights" / "2026-04-25.csv").exists())
            self.assertTrue((normalized / "platform" / "recommendation_items" / "2026-04-25.csv").exists())
            project_run_text = (normalized / "platform" / "project_runs" / "2026-04-25.csv").read_text(encoding="utf-8-sig")
            insight_text = (normalized / "platform" / "report_insights" / "2026-04-25.csv").read_text(encoding="utf-8-sig")
            self.assertIn("momentum", project_run_text)
            self.assertIn("报告自动解读已生成", insight_text)

    def test_scheduler_tick_executes_due_task_once_and_materializes_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            def fake_run(command, **_kwargs):
                return subprocess.CompletedProcess(command, 0, stdout=json.dumps({"status": "success"}), stderr="")

            runner = SchedulerRunner(
                project_root=root,
                schedules_path=root / "state" / "schedules.json",
                runs_path=root / "state" / "scheduler_runs.json",
                platform_dir=root / "data" / "normalized" / "platform",
                subprocess_runner=fake_run,
            )
            runner.set_enabled(schedule_id="daily_build_db", enabled=True)

            result = runner.tick(schedule_id="daily_build_db")

            self.assertEqual(result["status"], "success")
            self.assertEqual(result["run_count"], 1)
            self.assertTrue((root / "state" / "scheduler_runs.json").exists())
            self.assertTrue((root / "data" / "normalized" / "platform" / "scheduler_runs").exists())


if __name__ == "__main__":
    unittest.main()
