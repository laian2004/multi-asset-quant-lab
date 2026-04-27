import sys
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.pregrab import PregrabRunner


class _FakeCalendar:
    @staticmethod
    def candidate_dates(_calendar_name, start, end):
        values = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                values.append(current)
            current = date.fromordinal(current.toordinal() + 1)
        return values


class PregrabRunnerTests(unittest.TestCase):
    def test_pregrab_treats_publication_lag_as_external_blocked_issue(self):
        runner = mock.Mock()
        runner.calendar = _FakeCalendar()
        runner.fetch_date.side_effect = lambda trade_date, selection=None: {
            "status": "partial_success" if trade_date == "2026-04-17" else "success",
            "exchange_summaries": {
                "options_exercise_results": {
                    selection.exchanges[0]: {
                        "message": "pending official publication for monthly report" if trade_date == "2026-04-17" else "ok"
                    }
                }
            },
        }
        runner.validate.side_effect = lambda trade_date, selection=None: {
            "checkpoint_status": "partial_success" if trade_date == "2026-04-17" else "success",
            "datasets": {
                "options_exercise_results": {
                    "status": "pending_retry" if trade_date == "2026-04-17" else "success",
                    "csv_exists": True,
                    "schema_ok": True,
                    "duplicate_keys": 0,
                    "missing_raw_paths": [],
                    "completeness_ok": True,
                    "selection_match_ok": True,
                    "result_chain_semantics_ok": True,
                    "master_data_completeness": True,
                }
            },
        }
        state_writer = mock.Mock()
        result = PregrabRunner(workflow_runner=runner, state_writer=state_writer).run_window(
            exchanges=["CFFEX"],
            start_date="2026-04-16",
            end_date="2026-04-17",
            mode="trial",
            persist=False,
        )

        self.assertEqual(result["status"], "partial_success")
        self.assertEqual(result["engineering_status"], "success")
        self.assertEqual(result["exchange_results"]["CFFEX"]["blocked_external_count"], 1)
        self.assertEqual(result["issue_category_counts"], {"result_chain_publication_lag": 1})
        state_writer.assert_not_called()

    def test_pregrab_marks_internal_validation_failure_as_failed(self):
        runner = mock.Mock()
        runner.calendar = _FakeCalendar()
        runner.fetch_date.return_value = {"status": "partial_success", "exchange_summaries": {}}
        runner.validate.return_value = {
            "checkpoint_status": "partial_success",
            "datasets": {
                "options_daily_quotes": {
                    "status": "partial_success",
                    "csv_exists": True,
                    "schema_ok": True,
                    "duplicate_keys": 0,
                    "missing_raw_paths": [],
                    "completeness_ok": False,
                    "selection_match_ok": True,
                    "result_chain_semantics_ok": True,
                    "master_data_completeness": True,
                }
            },
        }
        result = PregrabRunner(workflow_runner=runner).run_window(
            exchanges=["SSE"],
            start_date="2026-04-16",
            end_date="2026-04-16",
            mode="trial",
            persist=False,
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["engineering_status"], "partial")
        self.assertEqual(result["exchange_results"]["SSE"]["failed_count"], 1)
        self.assertEqual(result["issue_category_counts"], {"coverage_gap": 1})


if __name__ == "__main__":
    unittest.main()
