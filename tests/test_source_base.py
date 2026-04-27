import logging
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.models import RawPayload
from src.futures_workflow.sources import base as base_module
from src.futures_workflow.sources.base import ExchangeSource


class _DummySource(ExchangeSource):
    exchange = "TEST"
    dataset = "options_daily_quotes"

    def fetch_raw(self, trade_date: date) -> RawPayload:
        raise NotImplementedError

    def parse_raw(self, trade_date: date, payload: RawPayload, raw_path):
        raise NotImplementedError


class SourceBaseTests(unittest.TestCase):
    def test_cached_payload_restores_sidecar_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            source = _DummySource({"user_agent": "ua", "timeout_seconds": 5}, logging.getLogger("test-source-base"))
            raw_root = Path(tmpdir)
            with mock.patch.object(base_module, "RAW_DIR", raw_root):
                payload = RawPayload(
                    content='{"data":[]}',
                    url="https://example.com/official.json",
                    extension="json",
                    source_type="official",
                    meta={"marker": "ok"},
                )
                source._write_raw_file(date(2026, 4, 16), payload)
                cached = source._load_cached_payload(
                    date(2026, 4, 16),
                    "https://fallback.example.com/raw.json",
                    "fallback_online",
                )
            self.assertEqual(cached.url, "https://example.com/official.json")
            self.assertEqual(cached.source_type, "official")
            self.assertEqual(cached.meta["marker"], "ok")


if __name__ == "__main__":
    unittest.main()
