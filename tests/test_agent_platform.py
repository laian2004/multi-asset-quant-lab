import csv
import tempfile
import unittest
from pathlib import Path

from src.futures_workflow.agent_platform import AgentOrchestrator, PluginRegistry
from src.futures_workflow.research_platform import ResearchPlatformRunner


DAILY_OHLCV_HEADER = [
    "trade_date",
    "instrument_id",
    "asset_family",
    "market",
    "exchange",
    "instrument_type",
    "symbol",
    "name",
    "currency",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "settlement",
    "pre_settlement",
    "volume",
    "amount",
    "open_interest",
    "turnover_rate",
    "source_id",
    "source_url",
    "source_type",
    "retrieved_at",
    "raw_path",
    "parser_version",
    "checksum",
    "run_id",
]


def write_daily_ohlcv(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for index, trade_date in enumerate(["2026-04-20", "2026-04-21", "2026-04-22", "2026-04-23", "2026-04-24"], start=1):
        for symbol_index in range(5):
            symbol = f"60000{symbol_index}"
            rows.append(
                {
                "trade_date": trade_date,
                "instrument_id": f"SSE:{symbol}",
                "asset_family": "equities_funds_cn",
                "market": "cn_equities",
                "exchange": "SSE",
                "instrument_type": "stock",
                "symbol": symbol,
                "name": "浦发银行",
                "currency": "CNY",
                "open": str(10 + index / 10 + symbol_index / 100),
                "high": str(10.3 + index / 10 + symbol_index / 100),
                "low": str(9.8 + index / 10 + symbol_index / 100),
                "close": str(10.1 + index / 10 + symbol_index / 100),
                "pre_close": str(10 + (index - 1) / 10 + symbol_index / 100),
                "settlement": "",
                "pre_settlement": "",
                "volume": str(1000 + index * 100),
                "amount": str(10000 + index * 1000),
                "open_interest": "",
                "turnover_rate": "",
                "source_id": "test.source",
                "source_url": "https://example.test",
                "source_type": "fallback_online",
                "retrieved_at": "2026-04-24T15:00:00+08:00",
                "raw_path": "",
                "parser_version": "test",
                "checksum": f"c{index}-{symbol_index}",
                "run_id": "run",
            }
            )
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DAILY_OHLCV_HEADER)
        writer.writeheader()
        writer.writerows(rows)


class AgentPlatformTests(unittest.TestCase):
    def make_runner(self, root: Path) -> AgentOrchestrator:
        normalized = root / "data" / "normalized"
        research_runner = ResearchPlatformRunner(
            project_root=root,
            normalized_root=normalized,
            platform_dir=normalized / "platform",
            reports_dir=root / "reports",
        )
        return AgentOrchestrator(
            project_root=root,
            normalized_root=normalized,
            platform_dir=normalized / "platform",
            reports_dir=root / "reports",
            research_runner=research_runner,
        )

    def test_plugin_registry_lists_agent_contract(self):
        registry = PluginRegistry()
        plugins = registry.list()
        plugin_ids = {plugin.plugin_id for plugin in plugins}

        self.assertIn("agent.workflow", plugin_ids)
        self.assertIn("quality.gate", plugin_ids)
        self.assertTrue(all(plugin.inputs and plugin.outputs for plugin in plugins))

    def test_agent_plan_waits_for_confirmation_and_writes_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = self.make_runner(root)

            result = runner.agent_plan(
                goal="验证动量研究链路",
                start_date="2026-04-20",
                end_date="2026-04-24",
                dataset="daily_ohlcv",
            )

            self.assertEqual(result["status"], "awaiting_confirmation")
            self.assertEqual(result["engineering_status"], "draft")
            self.assertEqual(len(result["draft_plan"]), 8)
            self.assertTrue((root / "data" / "normalized" / "platform" / "agent_tasks" / "2026-04-24.csv").exists())
            self.assertFalse((root / "data" / "normalized" / "platform" / "plugin_runs" / "2026-04-24.csv").exists())

    def test_quality_gate_blocks_empty_and_passes_priced_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = self.make_runner(root)

            blocked = runner.quality_gate(dataset="daily_ohlcv", start_date="2026-04-20", end_date="2026-04-24")
            self.assertEqual(blocked["status"], "blocked")

            write_daily_ohlcv(root / "data" / "normalized" / "platform" / "daily_ohlcv" / "2026-04-24.csv")
            passed = runner.quality_gate(dataset="daily_ohlcv", start_date="2026-04-20", end_date="2026-04-24")
            self.assertEqual(passed["status"], "pass")
            self.assertTrue((root / "data" / "normalized" / "platform" / "quality_gates" / "2026-04-24.csv").exists())

    def test_agent_run_executes_confirmed_workflow_and_model_registry(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            write_daily_ohlcv(root / "data" / "normalized" / "platform" / "daily_ohlcv" / "2026-04-24.csv")
            runner = self.make_runner(root)
            plan = runner.agent_plan(
                goal="验证动量研究链路",
                start_date="2026-04-20",
                end_date="2026-04-24",
                dataset="daily_ohlcv",
            )

            result = runner.agent_run(task_id=plan["task_id"])
            model_registry = runner.model_registry_build(date_value="2026-04-24")
            drift = runner.model_drift_check(date_value="2026-04-24")

            self.assertIn(result["status"], {"success", "partial_success"})
            self.assertEqual(result["engineering_status"], "success")
            self.assertEqual(model_registry["status"], "success")
            self.assertEqual(drift["status"], "success")
            self.assertTrue((root / "data" / "normalized" / "platform" / "plugin_runs" / "2026-04-24.csv").exists())
            self.assertTrue((root / "data" / "normalized" / "platform" / "model_registry" / "2026-04-24.csv").exists())
            self.assertTrue((root / "data" / "normalized" / "platform" / "model_drift_events" / "2026-04-24.csv").exists())


if __name__ == "__main__":
    unittest.main()
