import sys
import unittest
import json
from pathlib import Path
from unittest import mock
from datetime import date, timedelta


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.cli import (
    _history_sync_candidate_dates,
    _run_pregrab_trial_subprocess,
    _run_window_sync,
    _sample_regression_windows,
    build_parser,
    run_regression_smoke,
)
from src.futures_workflow.environment_health import _check_playwright_runtime


class CliParserTests(unittest.TestCase):
    def test_export_parser_accepts_repeatable_filters(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "export",
                "--dataset",
                "options_daily_quotes",
                "--date",
                "2026-04-16",
                "--format",
                "json",
                "--filter",
                "exchange=SSE",
                "--filter",
                "contract=510050C2604M02650",
            ]
        )
        self.assertEqual(args.command, "export")
        self.assertEqual(args.filter, ["exchange=SSE", "contract=510050C2604M02650"])

    def test_pregrab_window_parser_accepts_repeatable_exchanges(self):
        parser = build_parser()
        args = parser.parse_args([
            "pregrab-window",
            "--start",
            "2026-01-21",
            "--end",
            "2026-04-21",
            "--exchange",
            "CFFEX",
            "--exchange",
            "DCE,SSE",
            "--mode",
            "trial",
            "--no-persist",
        ])
        self.assertEqual(args.command, "pregrab-window")
        self.assertEqual(args.exchange, ["CFFEX", "DCE,SSE"])
        self.assertEqual(args.mode, "trial")
        self.assertTrue(args.no_persist)

    def test_regression_smoke_parser_accepts_repeatable_dates(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "regression-smoke",
                "--date",
                "2021-04-16",
                "--date",
                "2026-04-16",
                "--skip-gui-smoke",
            ]
        )
        self.assertEqual(args.command, "regression-smoke")
        self.assertEqual(args.date, ["2021-04-16", "2026-04-16"])
        self.assertTrue(args.skip_gui_smoke)

    def test_regression_smoke_parser_accepts_phase2_profile(self):
        parser = build_parser()
        args = parser.parse_args(["regression-smoke", "--profile", "phase2"])
        self.assertEqual(args.command, "regression-smoke")
        self.assertEqual(args.profile, "phase2")

    def test_public_sync_parser_accepts_window_args(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "sync-public-assets",
                "--start",
                "2026-04-01",
                "--end",
                "2026-04-21",
                "--family",
                "equities_spot_snapshot,etf_spot_snapshot",
                "--force",
            ]
        )
        self.assertEqual(args.command, "sync-public-assets")
        self.assertEqual(args.start, "2026-04-01")
        self.assertEqual(args.end, "2026-04-21")
        self.assertEqual(args.family, ["equities_spot_snapshot,etf_spot_snapshot"])
        self.assertTrue(args.force)

    def test_environment_check_parser_is_available(self):
        parser = build_parser()
        args = parser.parse_args(["environment-check", "--json-only"])
        self.assertEqual(args.command, "environment-check")
        self.assertTrue(args.json_only)

    def test_quant_research_parser_accepts_new_algorithm_commands(self):
        parser = build_parser()
        algorithm_args = parser.parse_args([
            "algorithm-run",
            "--template",
            "black_scholes_price",
            "--start",
            "2026-04-20",
            "--end",
            "2026-04-22",
            "--params",
            '{"underlying_price":100}',
        ])
        risk_args = parser.parse_args(["risk-run", "--template", "var_cvar", "--start", "2026-04-20", "--end", "2026-04-22"])
        portfolio_args = parser.parse_args(["portfolio-optimize", "--template", "risk_parity", "--start", "2026-04-20", "--end", "2026-04-22"])
        backtest_args = parser.parse_args(["backtest-run", "--strategy", "momentum", "--start", "2026-04-20", "--end", "2026-04-22", "--slippage-bps", "1.5"])
        ml_args = parser.parse_args(["ml-run", "--template", "ridge", "--start", "2026-04-20", "--end", "2026-04-22", "--dataset", "daily_ohlcv", "--target", "close", "--features", "open,volume", "--tune"])
        factor_perf_args = parser.parse_args(["factor-performance", "--factor", "momentum", "--start", "2026-04-20", "--end", "2026-04-22"])
        stress_args = parser.parse_args(["stress-test", "--template", "equity_down", "--start", "2026-04-20", "--end", "2026-04-22", "--params", '{"shock_pct":-0.1}'])
        quality_score_args = parser.parse_args(["quality-score", "--date", "latest"])
        report_args = parser.parse_args(["report-generate", "--date", "latest", "--report-type", "ml"])
        artifact_args = parser.parse_args(["artifact-list", "--date", "2026-04-22", "--run-id", "run-1"])
        history_args = parser.parse_args(["history-sync", "--scope", "public_assets", "--mode", "1y"])

        self.assertEqual(algorithm_args.command, "algorithm-run")
        self.assertEqual(algorithm_args.template, "black_scholes_price")
        self.assertEqual(risk_args.command, "risk-run")
        self.assertEqual(portfolio_args.command, "portfolio-optimize")
        self.assertEqual(backtest_args.command, "backtest-run")
        self.assertEqual(backtest_args.slippage_bps, 1.5)
        self.assertEqual(ml_args.command, "ml-run")
        self.assertTrue(ml_args.tune)
        self.assertEqual(factor_perf_args.command, "factor-performance")
        self.assertEqual(stress_args.command, "stress-test")
        self.assertEqual(quality_score_args.command, "quality-score")
        self.assertEqual(report_args.report_type, "ml")
        self.assertEqual(artifact_args.run_id, "run-1")
        self.assertEqual(history_args.command, "history-sync")
        self.assertEqual(history_args.mode, "1y")

    def test_sample_regression_windows_uses_calendar_targets(self):
        class _FakeCalendar:
            @staticmethod
            def candidate_dates(calendar_name, start, end):
                values = []
                current = start
                while current <= end:
                    if current.weekday() < 5:
                        values.append(current)
                    current += timedelta(days=1)
                return values

        windows = _sample_regression_windows(calendar=_FakeCalendar(), reference_date=date(2026, 4, 20))

        self.assertEqual(len(windows["latest_7_trading_days"]), 7)
        self.assertEqual(windows["latest_7_trading_days"][-1], "2026-04-20")
        self.assertEqual(len(windows["latest_1y_monthly_sample"]), 12)
        self.assertEqual(len(windows["latest_3y_quarterly_sample"]), 12)

    def test_sample_regression_windows_uses_existing_canonical_baseline_for_long_windows(self):
        class _FakeCalendar:
            @staticmethod
            def candidate_dates(calendar_name, start, end):
                values = []
                current = start
                while current <= end:
                    if current.weekday() < 5:
                        values.append(current)
                    current += timedelta(days=1)
                return values

        windows = _sample_regression_windows(
            calendar=_FakeCalendar(),
            reference_date=date(2026, 4, 20),
            canonical_dates=[
                "2026-03-20",
                "2026-03-23",
                "2026-03-24",
                "2026-03-25",
                "2026-03-26",
                "2026-03-27",
                "2026-03-30",
                "2026-03-31",
                "2026-04-01",
                "2026-04-02",
                "2026-04-03",
                "2026-04-10",
                "2026-04-13",
                "2026-04-14",
                "2026-04-15",
                "2026-04-16",
                "2026-04-17",
                "2026-04-20",
            ],
        )

        self.assertEqual(windows["latest_7_trading_days"], ["2026-04-10", "2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17", "2026-04-20"])
        self.assertEqual(windows["latest_1m_trading_days"][0], "2026-03-20")
        self.assertEqual(windows["latest_1m_trading_days"][-1], "2026-04-20")
        self.assertEqual(windows["latest_1y_monthly_sample"], ["2026-03-31", "2026-04-20"])
        self.assertEqual(windows["latest_3y_quarterly_sample"], ["2026-03-31", "2026-04-20"])

    def test_run_regression_smoke_hydrates_missing_window_dates_and_sets_engineering_status(self):
        runner = mock.Mock()
        runner.existing_canonical_dates.return_value = [
            "2010-04-16",
            "2015-04-16",
            "2021-04-16",
            "2026-03-31",
            "2026-04-01",
            "2026-04-02",
            "2026-04-13",
            "2026-04-15",
            "2026-04-16",
            "2026-04-17",
        ]
        runner.fetch_date.side_effect = lambda trade_date, selection=None: {"status": "success", "trade_date": trade_date}
        runner.validate.side_effect = lambda trade_date: {
            "checkpoint_status": "partial_success" if trade_date == "2026-04-17" else "success",
            "trade_date": trade_date,
        }
        runner.audit_canonical_dates.return_value = {
            "needs_repair_dates": [],
            "issue_category_counts": {"result_chain_publication_lag": 1},
            "blocked_issues": ["options_exercise_results: missing exchanges [CFFEX] are pending official publication"],
            "issues": [],
        }
        runner.calendar = mock.Mock()
        runner.calendar.previous_trading_day.return_value = date(2026, 4, 20)
        platform_runner = mock.Mock()
        platform_runner.sync.return_value = {"trade_date": "2026-04-20", "status": "success"}
        platform_runner.validate.return_value = {"status": "success"}
        state_writer = mock.Mock()

        with mock.patch(
            "src.futures_workflow.cli._sample_regression_windows",
            return_value={
                "latest_7_trading_days": [
                    "2026-04-10",
                    "2026-04-13",
                    "2026-04-14",
                    "2026-04-15",
                    "2026-04-16",
                    "2026-04-17",
                    "2026-04-20",
                ],
                "latest_1m_trading_days": ["2026-04-10", "2026-04-13", "2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17", "2026-04-20"],
                "latest_1y_monthly_sample": ["2026-03-31", "2026-04-20"],
                "latest_3y_quarterly_sample": ["2026-03-31", "2026-04-20"],
            },
        ), mock.patch("src.futures_workflow.cli.build_duckdb_database", return_value={"status": "success"}), mock.patch(
            "src.futures_workflow.cli.read_dataset_manifest", return_value=[{"dataset": "yield_curves"}]
        ), mock.patch("src.futures_workflow.cli.gui_module.DashboardApp") as app_cls:
            app_cls.return_value.build_context.return_value = {
                "selected_dataset": "yield_curves",
                "selected_date": "2026-04-20",
                "platform_metadata": [{"dataset": "yield_curves"}],
            }
            result = run_regression_smoke(
                runner=runner,
                platform_runner=platform_runner,
                trade_dates=["2021-04-16", "2026-04-16"],
                state_writer=state_writer,
            )

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["engineering_status"], "success")
        self.assertEqual(result["dates"], ["2021-04-16", "2026-04-16"])
        self.assertEqual(result["window_results"]["latest_7_trading_days"]["status"], "partial_success")
        self.assertEqual(result["window_results"]["latest_7_trading_days"]["sample_count"], 7)
        self.assertEqual(set(result["hydrated_dates"]), {"2026-04-10", "2026-04-14", "2026-04-20"})
        self.assertTrue(result["gui_smoke"]["has_yield_curves"])
        self.assertEqual(result["build_db"]["status"], "success")
        self.assertEqual(runner.fetch_date.call_count, 3)
        for _, kwargs in runner.fetch_date.call_args_list:
            self.assertEqual(kwargs["selection"].instrument_group, "all")
        state_writer.assert_called_once()

    def test_run_pregrab_trial_subprocess_uses_isolated_storage_and_marks_cleaned(self):
        captured = {}

        def _fake_run(command, cwd=None, env=None, capture_output=None, text=None, check=None):
            captured["command"] = list(command)
            captured["cwd"] = cwd
            captured["env"] = dict(env or {})
            return mock.Mock(
                returncode=0,
                stdout=json.dumps(
                    {
                        "run_id": "pregrab-test",
                        "mode": "trial",
                        "exchanges": ["CFFEX"],
                        "window_start": "2026-04-17",
                        "window_end": "2026-04-17",
                        "status": "partial_success",
                        "engineering_status": "success",
                        "cleanup_status": "pending_cleanup",
                    },
                    ensure_ascii=False,
                ),
                stderr="",
            )

        with mock.patch("src.futures_workflow.cli.subprocess.run", side_effect=_fake_run), mock.patch(
            "src.futures_workflow.cli.append_pregrab_run"
        ) as state_writer:
            result = _run_pregrab_trial_subprocess(
                start_date="2026-04-17",
                end_date="2026-04-17",
                exchanges=["CFFEX"],
                persist=True,
            )

        self.assertEqual(result["cleanup_status"], "cleaned")
        self.assertEqual(captured["cwd"], str(ROOT))
        self.assertIn("--no-persist", captured["command"])
        self.assertEqual(captured["env"]["FUTURES_WORKFLOW_PREGRAB_TRIAL_INNER"], "1")
        self.assertIn("FUTURES_WORKFLOW_DATA_DIR", captured["env"])
        self.assertTrue(captured["env"]["FUTURES_WORKFLOW_DATA_DIR"].endswith("/data"))
        state_writer.assert_called_once_with(result)

    def test_run_window_sync_persists_summary_and_marks_dns_issue(self):
        runner = mock.Mock()
        runner.calendar.candidate_dates.return_value = [
            date(2026, 4, 21),
            date(2026, 4, 22),
        ]

        def _sync_callable(trade_date, families=None, force=False):
            if trade_date == "2026-04-22":
                return {"status": "pending_retry", "message": "Temporary failure in name resolution"}
            return {"status": "success", "row_counts": {"fx_reference_rates": 25}}

        with mock.patch("src.futures_workflow.cli.append_window_run") as state_writer:
            result = _run_window_sync(
                runner=runner,
                sync_callable=_sync_callable,
                action_name="sync_public_references_window",
                scope="public_references",
                start_date="2026-04-21",
                end_date="2026-04-22",
                families=["fx_reference_rates"],
                force=True,
            )

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["engineering_status"], "success")
        self.assertEqual(result["target"], "fx_reference_rates")
        self.assertEqual(result["date_counts"], {"success": 1, "pending_retry": 1})
        self.assertEqual(result["issue_category_counts"]["dns_failure"], 1)
        self.assertEqual(result["details"]["force"], True)
        state_writer.assert_called_once_with(result)

    def test_run_window_sync_accepts_sampled_candidate_dates(self):
        runner = mock.Mock()
        runner.calendar.candidate_dates.side_effect = AssertionError("calendar should not be used")
        called_dates = []

        def _sync_callable(trade_date, families=None, force=False):
            called_dates.append(trade_date)
            return {"status": "success", "row_counts": {"daily_ohlcv": 1}}

        result = _run_window_sync(
            runner=runner,
            sync_callable=_sync_callable,
            action_name="history_sync_public_assets",
            scope="public_assets",
            start_date="2026-01-01",
            end_date="2026-04-30",
            candidate_dates=["2026-01-30", "2026-02-27"],
            persist_state=False,
        )

        self.assertEqual(called_dates, ["2026-01-30", "2026-02-27"])
        self.assertEqual(result["date_counts"], {"success": 2})

    def test_history_sync_candidate_dates_samples_monthly_and_quarterly(self):
        runner = mock.Mock()

        def _candidate_dates(calendar_name, start, end):
            values = []
            current = start
            while current <= end:
                if current.weekday() < 5:
                    values.append(current)
                current += timedelta(days=1)
            return values

        runner.calendar.candidate_dates.side_effect = _candidate_dates

        monthly = _history_sync_candidate_dates(
            runner=runner,
            mode="1y",
            start_date="2025-04-25",
            end_date="2026-04-25",
        )
        quarterly = _history_sync_candidate_dates(
            runner=runner,
            mode="3y",
            start_date="2023-04-25",
            end_date="2026-04-25",
        )

        self.assertEqual(len(monthly), 12)
        self.assertTrue(monthly[-1].startswith("2026-04"))
        self.assertEqual(len(quarterly), 12)
        self.assertTrue(quarterly[-1].startswith("2026-04"))

    def test_check_playwright_runtime_treats_zero_returncode_as_success(self):
        responses = iter(
            [
                mock.Mock(returncode=0, stdout="Version 1.58.0\n", stderr=""),
                mock.Mock(returncode=0, stdout="chromium_launch_ok\n", stderr=""),
            ]
        )
        payload = _check_playwright_runtime(
            subprocess_runner=lambda *args, **kwargs: next(responses)
        )
        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["message"], "Version 1.58.0")
        self.assertTrue(payload["browser_launch"])

    def test_check_playwright_runtime_requires_browser_launch(self):
        responses = iter(
            [
                mock.Mock(returncode=0, stdout="Version 1.58.0\n", stderr=""),
                mock.Mock(returncode=1, stdout="", stderr="Executable doesn't exist"),
            ]
        )
        payload = _check_playwright_runtime(
            subprocess_runner=lambda *args, **kwargs: next(responses)
        )
        self.assertEqual(payload["status"], "failed")
        self.assertFalse(payload["browser_launch"])
        self.assertIn("Executable doesn't exist", payload["message"])


if __name__ == "__main__":
    unittest.main()
