import logging
import sys
import unittest
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.sources.gfex import GFEXSource


class GFEXSourceTests(unittest.TestCase):
    def test_pre_launch_date_is_not_applicable(self):
        settings = {
            "user_agent": "ua",
            "timeout_seconds": 5,
            "exchange_metadata": {
                "GFEX": {
                    "launch_date": "2022-12-22",
                }
            },
            "exchanges": {
                "GFEX": {
                    "bootstrap_url": "http://bootstrap.example.com",
                    "daily_url": "http://daily.example.com",
                }
            },
        }
        source = GFEXSource(settings, logging.getLogger("test-gfex-source"))
        result = source.run(date(2021, 4, 16))
        self.assertEqual(result.status, "not_applicable")
        self.assertIn("2022-12-22", result.message)


if __name__ == "__main__":
    unittest.main()
