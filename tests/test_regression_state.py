import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.regression_state import (
    read_regression_smoke_state,
    summarize_regression_smoke,
    write_regression_smoke_state,
)


class RegressionStateTests(unittest.TestCase):
    def test_summarize_regression_smoke_keeps_core_fields(self):
        result = {
            "status": "success",
            "dates": ["2021-04-16", "2026-04-16"],
            "date_results": {
                "2021-04-16": {"checkpoint_status": "success"},
                "2026-04-16": {"checkpoint_status": "success"},
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
                "issues": [],
                "blocked_issues": ["cffex publication lag"],
            },
            "platform_sync": {"status": "success"},
            "platform_validation": {"status": "success"},
            "build_db": {"status": "success"},
            "gui_smoke": {"has_yield_curves": True},
        }

        summary = summarize_regression_smoke(result)

        self.assertEqual(summary["status"], "success")
        self.assertEqual(summary["engineering_status"], "success")
        self.assertEqual(summary["date_statuses"]["2021-04-16"], "success")
        self.assertEqual(summary["window_results"]["latest_7_trading_days"]["sample_count"], 4)
        self.assertEqual(summary["audit"]["issue_category_counts"], {"result_chain_publication_lag": 1})
        self.assertEqual(summary["build_db_status"], "success")
        self.assertTrue(summary["gui_smoke"]["has_yield_curves"])

    def test_write_and_read_regression_smoke_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state" / "regression_smoke.json"
            result = {
                "status": "partial_success",
                "engineering_status": "success",
                "dates": ["2026-04-16"],
                "date_results": {"2026-04-16": {"checkpoint_status": "partial_success"}},
                "window_results": {
                    "latest_1m_trading_days": {
                        "status": "partial_success",
                        "sample_count": 2,
                        "sampled_dates": ["2026-04-15", "2026-04-16"],
                        "status_counts": {"success": 1, "partial_success": 1},
                    }
                },
                "audit": {"needs_repair_dates": [], "issue_category_counts": {}, "issues": [], "blocked_issues": []},
                "platform_sync": {"status": "success"},
                "platform_validation": {"status": "success"},
                "build_db": {"status": "success"},
                "gui_smoke": {"has_yield_curves": True},
            }
            payload = write_regression_smoke_state(result, state_path=state_path)
            restored = read_regression_smoke_state(state_path=state_path)

        self.assertEqual(restored["result"]["status"], "partial_success")
        self.assertEqual(restored["result"]["engineering_status"], "success")
        self.assertEqual(restored["result"]["date_statuses"]["2026-04-16"], "partial_success")
        self.assertEqual(restored["result"]["window_results"]["latest_1m_trading_days"]["status"], "partial_success")
        self.assertIn("updated_at", payload)

    def test_read_regression_smoke_state_backfills_engineering_status_for_legacy_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state" / "regression_smoke.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                """
                {
                  "updated_at": "2026-04-21T16:00:00+08:00",
                  "result": {
                    "status": "partial_success",
                    "dates": ["2026-04-16"],
                    "date_statuses": {"2026-04-16": "success"},
                    "window_results": {"latest_7_trading_days": {"status": "partial_success", "sample_count": 7, "sampled_dates": ["2026-04-10"], "status_counts": {"partial_success": 1}}},
                    "audit": {"needs_repair_dates": [], "issue_category_counts": {"result_chain_publication_lag": 1}},
                    "platform_sync_status": "success",
                    "platform_validation_status": "success",
                    "build_db_status": "",
                    "gui_smoke": {"has_yield_curves": true}
                  }
                }
                """,
                encoding="utf-8",
            )

            restored = read_regression_smoke_state(state_path=state_path)

        self.assertEqual(restored["result"]["engineering_status"], "success")


if __name__ == "__main__":
    unittest.main()
