import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / ".tmp-tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TMP_ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.pregrab_state import append_pregrab_run, read_pregrab_state


class PregrabStateTests(unittest.TestCase):
    def test_append_and_read_pregrab_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state" / "pregrab_runs.json"
            append_pregrab_run(
                {
                    "run_id": "pregrab-1",
                    "mode": "trial",
                    "exchanges": ["CFFEX"],
                    "window_start": "2026-01-21",
                    "window_end": "2026-04-21",
                    "status": "partial_success",
                    "engineering_status": "success",
                    "elapsed_seconds": 12.5,
                    "date_counts": {"success": 60, "blocked_issue": 1},
                    "issue_category_counts": {"result_chain_publication_lag": 1},
                    "blocked_issues": ["options_exercise_results: CFFEX official result is pending publication"],
                    "cleanup_status": "cleaned",
                    "exchange_results": {
                        "CFFEX": {
                            "exchange": "CFFEX",
                            "status": "partial_success",
                            "engineering_status": "success",
                            "elapsed_seconds": 12.5,
                            "day_count": 61,
                            "success_count": 60,
                            "no_data_count": 0,
                            "not_applicable_count": 0,
                            "blocked_external_count": 1,
                            "failed_count": 0,
                            "passed": False,
                            "engineering_passed": True,
                            "issue_category_counts": {"result_chain_publication_lag": 1},
                            "blocked_issues": ["publication lag"],
                            "failed_days": [],
                            "blocked_days": ["2026-04-17"],
                        }
                    },
                },
                state_path=state_path,
            )
            payload = read_pregrab_state(state_path=state_path)

        self.assertIn("updated_at", payload)
        self.assertEqual(len(payload["runs"]), 1)
        self.assertEqual(payload["runs"][0]["run_id"], "pregrab-1")
        self.assertEqual(payload["runs"][0]["exchange_results"]["CFFEX"]["blocked_days"], ["2026-04-17"])


if __name__ == "__main__":
    unittest.main()
