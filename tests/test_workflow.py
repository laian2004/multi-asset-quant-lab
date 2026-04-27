import csv
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow import platform as platform_module
from src.futures_workflow import workflow as workflow_module
from src.futures_workflow.constants import (
    CONTRACTS_DATASET,
    FUTURES_DATASET,
    FUTURES_RESULTS_DATASET,
    NO_DATA_STATUS,
    OPTION_RESULTS_DATASET,
    OPTIONS_DATASET,
    PARTIAL_SUCCESS_STATUS,
    PENDING_RETRY_STATUS,
    SUCCESS_STATUS,
)
from src.futures_workflow.models import QuoteRow, SourceRunResult
from src.futures_workflow.normalize.daily_quotes import write_daily_quotes_csv
from src.futures_workflow.platform import build_platform_rows, write_platform_outputs
from src.futures_workflow.state.checkpoints import CheckpointStore
from src.futures_workflow.workflow import WorkflowRunner


class WorkflowSupportTests(unittest.TestCase):
    def test_write_contracts_latest_can_copy_snapshot_verbatim(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_root = platform_module.NORMALIZED_ROOT
            platform_module.NORMALIZED_ROOT = Path(tmpdir) / "normalized"
            try:
                snapshot_path = Path(tmpdir) / "contracts.csv"
                snapshot_path.write_text(
                    "instrument_type,exchange,contract\n"
                    "option,SSE,510050C2604M02650\n"
                    "future,SHFE,CU2605\n",
                    encoding="utf-8",
                )

                latest_path = platform_module.write_contracts_latest([], snapshot_path=snapshot_path)

                self.assertEqual(latest_path.read_text(encoding="utf-8"), snapshot_path.read_text(encoding="utf-8"))
            finally:
                platform_module.NORMALIZED_ROOT = original_root

    def test_csv_writer_uses_expected_columns(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "2026-04-16.csv"
            row = QuoteRow(
                trade_date="2026-04-16",
                exchange="SHFE",
                variety_code="CU",
                variety_name="铜",
                contract="CU2605",
                delivery_month="2605",
                open="1",
                high="2",
                low="0.5",
                close="1.5",
                prev_settlement="1.2",
                settlement="1.4",
                change_close="0.3",
                change_settlement="0.2",
                volume="10",
                open_interest="20",
                open_interest_change="2",
                turnover="30",
                source_url="u",
                source_type="official",
                retrieved_at="2026-04-17T00:00:00+08:00",
                raw_path="data/raw/shfe/daily_quotes/20260416.json",
            )
            write_daily_quotes_csv(path, [row])
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["contract"], "CU2605")

    def test_checkpoint_store_tracks_retry_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(Path(tmpdir) / "checkpoints.json")
            store.update_exchange_result(
                SourceRunResult(
                    exchange="DCE",
                    trade_date="2026-04-16",
                    status="pending_retry",
                    error="challenge",
                )
            )
            store.save()
            self.assertEqual(len(store.data["retry_queue"]), 1)

    def test_checkpoint_store_does_not_retry_not_applicable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = CheckpointStore(Path(tmpdir) / "checkpoints.json")
            store.update_exchange_result(
                SourceRunResult(
                    exchange="GFEX",
                    trade_date="2021-04-16",
                    status="pending_retry",
                    error="bootstrap",
                )
            )
            store.update_exchange_result(
                SourceRunResult(
                    exchange="GFEX",
                    trade_date="2021-04-16",
                    status="not_applicable",
                    message="pre-launch",
                )
            )
            self.assertEqual(store.data["retry_queue"], [])

    def test_query_outputs_do_not_overwrite_canonical_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            future = QuoteRow(
                trade_date="2026-04-16",
                exchange="SHFE",
                variety_code="CU",
                variety_name="铜",
                contract="CU2605",
                delivery_month="2605",
                open="1",
                high="2",
                low="0.5",
                close="1.5",
                prev_settlement="1.2",
                settlement="1.4",
                change_close="0.3",
                change_settlement="0.2",
                volume="10",
                open_interest="20",
                open_interest_change="2",
                turnover="30",
                source_url="u",
                source_type="official",
                retrieved_at="2026-04-17T00:00:00+08:00",
                raw_path="data/raw/shfe/daily_quotes/20260416.json",
            )
            dataset_rows = build_platform_rows(futures_rows=[future], options_rows=[], futures_result_rows=[])
            with mock.patch.object(platform_module, "PROJECT_ROOT", root), mock.patch.object(platform_module, "NORMALIZED_ROOT", root / "data" / "normalized"), mock.patch.object(platform_module, "NORMALIZED_DIR", root / "data" / "normalized" / "daily_quotes"), mock.patch.object(platform_module, "QUERY_NORMALIZED_DIR", root / "data" / "normalized" / "queries"):
                canonical_outputs, _ = write_platform_outputs(
                    trade_date="2026-04-16",
                    dataset_rows=dataset_rows,
                    include_datasets=["futures_daily_quotes"],
                )
                canonical_path = root / canonical_outputs["futures_daily_quotes"]
                original_bytes = canonical_path.read_bytes()
                query_outputs, _ = write_platform_outputs(
                    trade_date="2026-04-16",
                    dataset_rows=dataset_rows,
                    include_datasets=["futures_daily_quotes"],
                    selection_id="query1234",
                    selection_summary={"instrument_group": "futures", "exchanges": ["SHFE"]},
                )
                self.assertEqual(canonical_path.read_bytes(), original_bytes)
                self.assertNotEqual(query_outputs["futures_daily_quotes"], canonical_outputs["futures_daily_quotes"])
                self.assertTrue((root / query_outputs["futures_daily_quotes"]).exists())

    def test_validate_flags_incomplete_exchange_coverage(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_path = root / "data" / "normalized" / "daily_quotes" / "2026-04-16.csv"
            write_daily_quotes_csv(
                output_path,
                [
                    QuoteRow(
                        trade_date="2026-04-16",
                        exchange="SHFE",
                        variety_code="CU",
                        variety_name="铜",
                        contract="CU2605",
                        delivery_month="2605",
                        open="1",
                        high="2",
                        low="0.5",
                        close="1.5",
                        prev_settlement="1.2",
                        settlement="1.4",
                        change_close="0.3",
                        change_settlement="0.2",
                        volume="10",
                        open_interest="20",
                        open_interest_change="2",
                        turnover="30",
                        source_url="u",
                        source_type="official",
                        retrieved_at="2026-04-17T00:00:00+08:00",
                        raw_path="data/raw/shfe/daily_quotes/20260416.json",
                    )
                ],
            )
            store = CheckpointStore(root / "state" / "checkpoints.json")
            store.update_dataset_state(
                "2026-04-16",
                "futures_daily_quotes",
                status="partial_success",
                expected_exchanges=["CFFEX", "SHFE"],
                observed_exchanges=["SHFE"],
                completeness_ok=False,
                selection_match_ok=True,
            )
            store.finalize_day(
                "2026-04-16",
                status="partial_success",
                outputs={"futures_daily_quotes": "data/normalized/daily_quotes/2026-04-16.csv"},
                row_counts={"futures_daily_quotes": 1},
            )
            store.save()

            runner = WorkflowRunner()
            runner.checkpoints = store
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root):
                validation = runner.validate("2026-04-16")
            self.assertFalse(validation["datasets"]["futures_daily_quotes"]["completeness_ok"])
            self.assertEqual(validation["datasets"]["futures_daily_quotes"]["expected_exchanges"], ["CFFEX", "SHFE"])

    def test_validate_reports_result_chain_no_data_reason(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_path = root / "data" / "normalized" / "results" / "futures_delivery" / "2026-04-16.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "trade_date,exchange,contract,delivery_month,expire_date,final_settlement_price,delivery_volume,delivery_amount,warehouse_delivery_quantity,result_status,source_url,source_type,retrieved_at,raw_path\n",
                encoding="utf-8-sig",
            )
            store = CheckpointStore(root / "state" / "checkpoints.json")
            store.update_exchange_result(
                SourceRunResult(
                    exchange="SHFE",
                    trade_date="2026-04-16",
                    dataset="futures_delivery_results",
                    status="no_data",
                    source_url="official://shfe/delivery",
                    source_type="official",
                    message="Official delivery result is not published for this trade date.",
                )
            )
            store.update_dataset_state(
                "2026-04-16",
                "futures_delivery_results",
                status="no_data",
                expected_exchanges=["SHFE"],
                observed_exchanges=[],
                completeness_ok=True,
                selection_match_ok=True,
            )
            store.finalize_day(
                "2026-04-16",
                status="partial_success",
                outputs={"futures_delivery_results": "data/normalized/results/futures_delivery/2026-04-16.csv"},
                row_counts={"futures_delivery_results": 0},
            )
            store.save()

            runner = WorkflowRunner()
            runner.checkpoints = store
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root):
                validation = runner.validate("2026-04-16")
            self.assertEqual(validation["datasets"]["futures_delivery_results"]["status"], "no_data")
            self.assertTrue(validation["datasets"]["futures_delivery_results"]["result_chain_semantics_ok"])
            self.assertIn("not published", validation["datasets"]["futures_delivery_results"]["no_data_reason"])

    def test_validate_clears_result_chain_no_data_reason_when_dataset_is_success(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_path = root / "data" / "raw" / "gfex" / "futures_delivery_results" / "20260416.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text("{}", encoding="utf-8")
            output_path = root / "data" / "normalized" / "results" / "futures_delivery" / "2026-04-16.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "trade_date,exchange,contract,delivery_month,expire_date,final_settlement_price,delivery_volume,delivery_amount,warehouse_delivery_quantity,result_status,source_url,source_type,retrieved_at,raw_path\n"
                "2026-04-16,GFEX,si2605,2605,,20000,15,300000,,reported,official://gfex/delivery,official,2026-04-17T00:00:00+08:00,data/raw/gfex/futures_delivery_results/20260416.json\n",
                encoding="utf-8-sig",
            )
            store = CheckpointStore(root / "state" / "checkpoints.json")
            store.update_exchange_result(
                SourceRunResult(
                    exchange="GFEX",
                    trade_date="2026-04-16",
                    dataset="futures_delivery_results",
                    status="success",
                    source_url="official://gfex/delivery",
                    source_type="official",
                    raw_path="data/raw/gfex/futures_delivery_results/20260416.json",
                    row_count=1,
                )
            )
            store.update_exchange_result(
                SourceRunResult(
                    exchange="CFFEX",
                    trade_date="2026-04-16",
                    dataset="futures_delivery_results",
                    status="no_data",
                    source_url="",
                    source_type="official",
                    message="No official delivery result endpoint configured.",
                )
            )
            store.update_dataset_state(
                "2026-04-16",
                "futures_delivery_results",
                status="success",
                expected_exchanges=["GFEX"],
                observed_exchanges=["GFEX"],
                completeness_ok=True,
                selection_match_ok=True,
            )
            store.finalize_day(
                "2026-04-16",
                status="success",
                outputs={"futures_delivery_results": "data/normalized/results/futures_delivery/2026-04-16.csv"},
                row_counts={"futures_delivery_results": 1},
            )
            store.save()

            runner = WorkflowRunner()
            runner.checkpoints = store
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root):
                validation = runner.validate("2026-04-16")
            self.assertEqual(validation["datasets"]["futures_delivery_results"]["status"], "success")
            self.assertEqual(validation["datasets"]["futures_delivery_results"]["no_data_reason"], "")

    def test_validate_preserves_pending_retry_for_zero_row_result_dataset(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            output_path = root / "data" / "normalized" / "results" / "options_exercise" / "2026-04-17.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                "trade_date,exchange,contract,underlying_contract,option_type,strike_price,expire_date,exercise_volume,assignment_volume,cash_settlement_amount,delivery_quantity,result_status,source_url,source_type,retrieved_at,raw_path\n",
                encoding="utf-8-sig",
            )
            raw_path = root / "data" / "raw" / "cffex" / "options_exercise_results" / "20260417.html"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text("<html>error</html>", encoding="utf-8")
            store = CheckpointStore(root / "state" / "checkpoints.json")
            store.update_exchange_result(
                SourceRunResult(
                    exchange="CFFEX",
                    trade_date="2026-04-17",
                    dataset="options_exercise_results",
                    status="pending_retry",
                    source_url="official://cffex/monthly",
                    source_type="official",
                    raw_path="data/raw/cffex/options_exercise_results/20260417.html",
                    message="Official CFFEX monthly exercise report returned an HTML error page instead of a PDF.",
                )
            )
            store.update_dataset_state(
                "2026-04-17",
                "options_exercise_results",
                status="pending_retry",
                expected_exchanges=["CFFEX"],
                observed_exchanges=[],
                completeness_ok=False,
                selection_match_ok=True,
            )
            store.finalize_day(
                "2026-04-17",
                status="partial_success",
                outputs={"options_exercise_results": "data/normalized/results/options_exercise/2026-04-17.csv"},
                row_counts={"options_exercise_results": 0},
            )
            store.save()

            runner = WorkflowRunner()
            runner.checkpoints = store
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root):
                validation = runner.validate("2026-04-17")
            self.assertEqual(validation["datasets"]["options_exercise_results"]["status"], "pending_retry")
            self.assertFalse(validation["datasets"]["options_exercise_results"]["result_chain_semantics_ok"])

    def test_repair_canonical_outputs_rebuilds_polluted_date(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_path = root / "data" / "raw" / "shfe" / "daily_quotes" / "20260416.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(
                json.dumps(
                    {
                        "o_curinstrument": [
                            {
                                "PRODUCTCLASS": "1",
                                "PRODUCTGROUPID": "CU",
                                "PRODUCTNAME": "铜",
                                "DELIVERYMONTH": "2605",
                                "OPENPRICE": "1",
                                "HIGHESTPRICE": "2",
                                "LOWESTPRICE": "0.5",
                                "CLOSEPRICE": "1.5",
                                "PRESETTLEMENTPRICE": "1.2",
                                "SETTLEMENTPRICE": "1.4",
                                "ZD1_CHG": "0.3",
                                "ZD2_CHG": "0.2",
                                "VOLUME": "10",
                                "OPENINTEREST": "20",
                                "OPENINTERESTCHG": "2",
                                "TURNOVER": "30",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output_path = root / "data" / "normalized" / "daily_quotes" / "2026-04-16.csv"
            write_daily_quotes_csv(output_path, [])

            store = CheckpointStore(root / "state" / "checkpoints.json")
            store.update_exchange_result(
                SourceRunResult(
                    exchange="SHFE",
                    trade_date="2026-04-16",
                    status="success",
                    dataset="futures_daily_quotes",
                    source_url="official://shfe",
                    source_type="official",
                    raw_path=raw_path,
                    row_count=1,
                )
            )
            store.update_dataset_state(
                "2026-04-16",
                "futures_daily_quotes",
                status="partial_success",
                expected_exchanges=["CFFEX", "SHFE"],
                observed_exchanges=[],
                completeness_ok=False,
                selection_match_ok=True,
            )
            store.finalize_day(
                "2026-04-16",
                status="partial_success",
                outputs={"futures_daily_quotes": "data/normalized/daily_quotes/2026-04-16.csv"},
                row_counts={"futures_daily_quotes": 0},
            )
            store.save()

            runner = WorkflowRunner()
            runner.checkpoints = store
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root), mock.patch.object(platform_module, "PROJECT_ROOT", root), mock.patch.object(platform_module, "NORMALIZED_ROOT", root / "data" / "normalized"), mock.patch.object(platform_module, "NORMALIZED_DIR", root / "data" / "normalized" / "daily_quotes"), mock.patch.object(platform_module, "QUERY_NORMALIZED_DIR", root / "data" / "normalized" / "queries"):
                audit = runner.audit_canonical_date("2026-04-16")
                repaired = runner.repair_canonical_outputs(["2026-04-16"])
                validation = runner.validate("2026-04-16")

            self.assertTrue(audit["needs_repair"])
            self.assertEqual(repaired["repaired_dates"], ["2026-04-16"])
            self.assertTrue(validation["datasets"]["futures_daily_quotes"]["completeness_ok"])
            self.assertEqual(validation["datasets"]["futures_daily_quotes"]["row_count"], 1)

    def test_repair_reuses_stored_result_chain_summaries_without_live_fetch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_path = root / "data" / "raw" / "shfe" / "daily_quotes" / "20260416.json"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_text(
                json.dumps(
                    {
                        "o_curinstrument": [
                            {
                                "PRODUCTCLASS": "1",
                                "PRODUCTGROUPID": "CU",
                                "PRODUCTNAME": "铜",
                                "DELIVERYMONTH": "2605",
                                "OPENPRICE": "1",
                                "HIGHESTPRICE": "2",
                                "LOWESTPRICE": "0.5",
                                "CLOSEPRICE": "1.5",
                                "PRESETTLEMENTPRICE": "1.2",
                                "SETTLEMENTPRICE": "1.4",
                                "ZD1_CHG": "0.3",
                                "ZD2_CHG": "0.2",
                                "VOLUME": "10",
                                "OPENINTEREST": "20",
                                "OPENINTERESTCHG": "2",
                                "TURNOVER": "30",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            result_raw_path = root / "data" / "raw" / "gfex" / "futures_delivery_results" / "20260416.json"
            result_raw_path.parent.mkdir(parents=True, exist_ok=True)
            result_raw_path.write_text(
                json.dumps(
                    {
                        "source_url": "official://gfex",
                        "request_payload": {},
                        "response_payload": {
                            "data": [
                                {
                                    "contractId": "si2605",
                                    "deliveryDate": "20260416",
                                    "deliveryQty": 15,
                                    "deliveryAmt": 300000,
                                    "deliveryPrice": "20000",
                                }
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            output_path = root / "data" / "normalized" / "daily_quotes" / "2026-04-16.csv"
            write_daily_quotes_csv(output_path, [])

            store = CheckpointStore(root / "state" / "checkpoints.json")
            store.update_exchange_result(
                SourceRunResult(
                    exchange="SHFE",
                    trade_date="2026-04-16",
                    status="success",
                    dataset="futures_daily_quotes",
                    source_url="official://shfe",
                    source_type="official",
                    raw_path=raw_path,
                    row_count=1,
                )
            )
            store.update_exchange_result(
                SourceRunResult(
                    exchange="GFEX",
                    trade_date="2026-04-16",
                    status="success",
                    dataset="futures_delivery_results",
                    source_url="official://gfex",
                    source_type="official",
                    raw_path=result_raw_path,
                    row_count=1,
                )
            )
            store.update_dataset_state(
                "2026-04-16",
                "futures_daily_quotes",
                status="partial_success",
                expected_exchanges=["SHFE"],
                observed_exchanges=[],
                completeness_ok=False,
                selection_match_ok=True,
            )
            store.update_dataset_state(
                "2026-04-16",
                "futures_delivery_results",
                status="success",
                expected_exchanges=["GFEX"],
                observed_exchanges=["GFEX"],
                completeness_ok=True,
                selection_match_ok=True,
            )
            store.finalize_day(
                "2026-04-16",
                status="partial_success",
                outputs={"futures_daily_quotes": "data/normalized/daily_quotes/2026-04-16.csv"},
                row_counts={"futures_daily_quotes": 0},
            )
            store.save()

            runner = WorkflowRunner()
            runner.checkpoints = store
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root), mock.patch.object(platform_module, "PROJECT_ROOT", root), mock.patch.object(platform_module, "NORMALIZED_ROOT", root / "data" / "normalized"), mock.patch.object(platform_module, "NORMALIZED_DIR", root / "data" / "normalized" / "daily_quotes"), mock.patch.object(platform_module, "QUERY_NORMALIZED_DIR", root / "data" / "normalized" / "queries"), mock.patch.object(
                runner.delivery_collector,
                "collect",
                side_effect=AssertionError("repair should reuse stored result-chain raw instead of live collecting"),
            ), mock.patch.object(
                runner.exercise_collector,
                "collect",
                side_effect=AssertionError("repair should reuse stored result-chain summaries instead of live collecting"),
            ):
                repaired = runner.repair_canonical_outputs(["2026-04-16"])
                delivery_validation = runner.validate("2026-04-16")["datasets"]["futures_delivery_results"]

            self.assertEqual(repaired["repaired_dates"], ["2026-04-16"])
            self.assertEqual(delivery_validation["row_count"], 1)
            self.assertTrue(delivery_validation["result_chain_semantics_ok"])

    def test_result_repair_refreshes_delivery_summary_without_result_raw(self):
        runner = WorkflowRunner()
        rows, summaries = runner._rows_from_checkpoint_result_raw(
            {
                "datasets": {
                    FUTURES_RESULTS_DATASET: {
                        "expected_exchanges": ["DCE"],
                        "exchanges": {
                            "DCE": {
                                "dataset": FUTURES_RESULTS_DATASET,
                                "exchange": "DCE",
                                "trade_date": "2026-04-16",
                                "status": NO_DATA_STATUS,
                                "source_url": "",
                                "source_type": "official",
                                "raw_path": "",
                                "row_count": 0,
                                "message": "No official delivery result endpoint configured.",
                                "error": "",
                            }
                        },
                    }
                }
            },
            date(2026, 4, 16),
            FUTURES_RESULTS_DATASET,
            futures_rows=[
                {
                    "exchange": "DCE",
                    "contract": "M2609",
                    "metadata": {
                        "expire_date": "2026-09-15",
                        "last_trade_date": "2026-09-15",
                    },
                }
            ],
        )
        self.assertEqual(rows, [])
        self.assertEqual(summaries["DCE"]["status"], NO_DATA_STATUS)
        self.assertIn("No expiring DCE futures contracts found", summaries["DCE"]["message"])
        self.assertTrue(summaries["DCE"]["source_url"])
        self.assertIn("dce.com.cn", summaries["DCE"]["source_url"])
        self.assertEqual(summaries["DCE"]["error"], "")

    def test_result_repair_refreshes_option_summary_without_result_raw(self):
        runner = WorkflowRunner()
        rows, summaries = runner._rows_from_checkpoint_result_raw(
            {
                "datasets": {
                    OPTION_RESULTS_DATASET: {
                        "expected_exchanges": ["DCE"],
                        "exchanges": {
                            "DCE": {
                                "dataset": OPTION_RESULTS_DATASET,
                                "exchange": "DCE",
                                "trade_date": "2026-04-16",
                                "status": NO_DATA_STATUS,
                                "source_url": "",
                                "source_type": "official",
                                "raw_path": "",
                                "row_count": 0,
                                "message": "No official exercise result endpoint configured.",
                                "error": "",
                            }
                        },
                    }
                }
            },
            date(2026, 4, 16),
            OPTION_RESULTS_DATASET,
            option_rows=[
                {
                    "exchange": "DCE",
                    "contract": "M2609-C-2600",
                    "expire_date": "2026-09-15",
                    "last_trade_date": "2026-09-15",
                    "metadata": {},
                }
            ],
        )
        self.assertEqual(rows, [])
        self.assertEqual(summaries["DCE"]["status"], NO_DATA_STATUS)
        self.assertIn("No expiring DCE option contracts found", summaries["DCE"]["message"])
        self.assertTrue(summaries["DCE"]["source_url"])
        self.assertIn("dce.com.cn", summaries["DCE"]["source_url"])
        self.assertEqual(summaries["DCE"]["error"], "")

    def test_load_cached_raw_payload_decodes_non_utf8_text_payload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            raw_path = root / "data" / "raw" / "dce" / "options_exercise_results" / "20260417.html"
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            raw_path.write_bytes("大连商品交易所".encode("gb18030"))
            meta_path = raw_path.with_name("20260417.meta.json")
            meta_path.write_text(
                json.dumps(
                    {
                        "extension": "html",
                        "source_url": "http://www.dce.com.cn/example.html",
                        "source_type": "official",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            runner = WorkflowRunner()
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root):
                cached = runner._load_cached_raw_payload(
                    exchange="DCE",
                    trade_date=date(2026, 4, 17),
                    dataset_name=OPTION_RESULTS_DATASET,
                    raw_path_value=str(raw_path),
                    source_url="",
                    source_type="official",
                )

            self.assertIsNotNone(cached)
            _, payload = cached
            self.assertIn("大连商品交易所", payload.content)
            self.assertEqual(payload.url, "http://www.dce.com.cn/example.html")

    def test_result_dataset_state_is_success_with_legitimate_no_data_exchanges(self):
        runner = WorkflowRunner()
        states = runner._build_dataset_states(
            selection=None,
            requested_datasets=[FUTURES_RESULTS_DATASET],
            source_results=[
                SourceRunResult(exchange="SHFE", trade_date="2026-04-16", dataset=FUTURES_DATASET, status=SUCCESS_STATUS),
                SourceRunResult(exchange="CFFEX", trade_date="2026-04-16", dataset=FUTURES_DATASET, status=SUCCESS_STATUS),
            ],
            dataset_rows={
                FUTURES_RESULTS_DATASET: [
                    {
                        "trade_date": "2026-04-16",
                        "exchange": "SHFE",
                        "contract": "CU2604",
                    }
                ]
            },
            delivery_summaries={
                "SHFE": {
                    "dataset": FUTURES_RESULTS_DATASET,
                    "exchange": "SHFE",
                    "trade_date": "2026-04-16",
                    "status": SUCCESS_STATUS,
                    "row_count": 1,
                    "message": "",
                },
                "CFFEX": {
                    "dataset": FUTURES_RESULTS_DATASET,
                    "exchange": "CFFEX",
                    "trade_date": "2026-04-16",
                    "status": NO_DATA_STATUS,
                    "row_count": 0,
                    "message": "Official delivery result is not published for this trade date.",
                },
            },
            option_result_summaries={},
        )
        self.assertEqual(states[FUTURES_RESULTS_DATASET]["status"], SUCCESS_STATUS)
        self.assertTrue(states[FUTURES_RESULTS_DATASET]["completeness_ok"])

    def test_result_dataset_state_is_partial_with_pending_retry_exchange(self):
        runner = WorkflowRunner()
        states = runner._build_dataset_states(
            selection=None,
            requested_datasets=[FUTURES_RESULTS_DATASET],
            source_results=[
                SourceRunResult(exchange="SHFE", trade_date="2026-04-16", dataset=FUTURES_DATASET, status=SUCCESS_STATUS),
                SourceRunResult(exchange="CFFEX", trade_date="2026-04-16", dataset=FUTURES_DATASET, status=SUCCESS_STATUS),
            ],
            dataset_rows={
                FUTURES_RESULTS_DATASET: [
                    {
                        "trade_date": "2026-04-16",
                        "exchange": "SHFE",
                        "contract": "CU2604",
                    }
                ]
            },
            delivery_summaries={
                "SHFE": {
                    "dataset": FUTURES_RESULTS_DATASET,
                    "exchange": "SHFE",
                    "trade_date": "2026-04-16",
                    "status": SUCCESS_STATUS,
                    "row_count": 1,
                    "message": "",
                },
                "CFFEX": {
                    "dataset": FUTURES_RESULTS_DATASET,
                    "exchange": "CFFEX",
                    "trade_date": "2026-04-16",
                    "status": PENDING_RETRY_STATUS,
                    "row_count": 0,
                    "message": "Official delivery result unavailable: timeout",
                },
            },
            option_result_summaries={},
        )
        self.assertEqual(states[FUTURES_RESULTS_DATASET]["status"], PARTIAL_SUCCESS_STATUS)
        self.assertFalse(states[FUTURES_RESULTS_DATASET]["completeness_ok"])

    def test_result_dataset_state_is_no_data_when_no_contracts_are_due(self):
        runner = WorkflowRunner()
        states = runner._build_dataset_states(
            selection=None,
            requested_datasets=[OPTION_RESULTS_DATASET],
            source_results=[
                SourceRunResult(exchange="SSE", trade_date="2026-04-16", dataset=OPTIONS_DATASET, status=SUCCESS_STATUS),
                SourceRunResult(exchange="SZSE", trade_date="2026-04-16", dataset=OPTIONS_DATASET, status=SUCCESS_STATUS),
            ],
            dataset_rows={
                OPTION_RESULTS_DATASET: [],
                CONTRACTS_DATASET: [
                    {
                        "trade_date": "2026-04-16",
                        "instrument_type": "option",
                        "exchange": "SSE",
                        "contract": "510050C2604M02650",
                        "expire_date": "2026-04-22",
                        "last_trade_date": "2026-04-22",
                    },
                    {
                        "trade_date": "2026-04-16",
                        "instrument_type": "option",
                        "exchange": "SZSE",
                        "contract": "159919C2604M04000A",
                        "expire_date": "2026-04-22",
                        "last_trade_date": "2026-04-22",
                    },
                ],
            },
            delivery_summaries={},
            option_result_summaries={
                "SSE": {
                    "dataset": OPTION_RESULTS_DATASET,
                    "exchange": "SSE",
                    "trade_date": "2026-04-16",
                    "status": NO_DATA_STATUS,
                    "row_count": 0,
                    "message": "No official exercise result endpoint configured.",
                },
                "SZSE": {
                    "dataset": OPTION_RESULTS_DATASET,
                    "exchange": "SZSE",
                    "trade_date": "2026-04-16",
                    "status": NO_DATA_STATUS,
                    "row_count": 0,
                    "message": "No official exercise result endpoint configured.",
                },
            },
        )
        self.assertEqual(states[OPTION_RESULTS_DATASET]["status"], "no_data")
        self.assertTrue(states[OPTION_RESULTS_DATASET]["completeness_ok"])

    def test_result_dataset_state_uses_observed_exchanges_when_delivery_rows_exist(self):
        runner = WorkflowRunner()
        states = runner._build_dataset_states(
            selection=None,
            requested_datasets=[FUTURES_RESULTS_DATASET],
            source_results=[
                SourceRunResult(exchange="SHFE", trade_date="2026-04-16", dataset=FUTURES_DATASET, status=SUCCESS_STATUS),
                SourceRunResult(exchange="GFEX", trade_date="2026-04-16", dataset=FUTURES_DATASET, status=SUCCESS_STATUS),
            ],
            dataset_rows={
                FUTURES_RESULTS_DATASET: [
                    {
                        "trade_date": "2026-04-16",
                        "exchange": "SHFE",
                        "contract": "CU2604",
                    },
                    {
                        "trade_date": "2026-04-16",
                        "exchange": "GFEX",
                        "contract": "SI2605",
                    },
                ],
                CONTRACTS_DATASET: [
                    {
                        "trade_date": "2026-04-16",
                        "instrument_type": "future",
                        "exchange": "SHFE",
                        "contract": "CU2604",
                        "expire_date": "",
                        "last_trade_date": "",
                    },
                    {
                        "trade_date": "2026-04-16",
                        "instrument_type": "future",
                        "exchange": "GFEX",
                        "contract": "SI2605",
                        "expire_date": "",
                        "last_trade_date": "",
                    },
                ],
            },
            delivery_summaries={
                "SHFE": {"dataset": FUTURES_RESULTS_DATASET, "exchange": "SHFE", "trade_date": "2026-04-16", "status": SUCCESS_STATUS, "row_count": 1, "message": ""},
                "GFEX": {"dataset": FUTURES_RESULTS_DATASET, "exchange": "GFEX", "trade_date": "2026-04-16", "status": SUCCESS_STATUS, "row_count": 1, "message": ""},
            },
            option_result_summaries={},
        )
        self.assertEqual(states[FUTURES_RESULTS_DATASET]["status"], SUCCESS_STATUS)
        self.assertEqual(states[FUTURES_RESULTS_DATASET]["expected_exchanges"], ["GFEX", "SHFE"])
        self.assertTrue(states[FUTURES_RESULTS_DATASET]["completeness_ok"])

    def test_aggregate_status_treats_legal_result_no_data_as_success(self):
        runner = WorkflowRunner()
        status = runner._aggregate_status(
            source_results=[
                SourceRunResult(exchange="SHFE", trade_date="2026-04-16", dataset=FUTURES_DATASET, status=SUCCESS_STATUS),
            ],
            dataset_states={
                FUTURES_DATASET: {
                    "status": SUCCESS_STATUS,
                    "row_count": 10,
                    "completeness_ok": True,
                },
                FUTURES_RESULTS_DATASET: {
                    "status": NO_DATA_STATUS,
                    "row_count": 0,
                    "completeness_ok": True,
                },
            },
            requested_datasets=[FUTURES_DATASET, FUTURES_RESULTS_DATASET],
        )
        self.assertEqual(status, SUCCESS_STATUS)

    def test_aggregate_status_is_partial_when_result_dataset_is_partial(self):
        runner = WorkflowRunner()
        status = runner._aggregate_status(
            source_results=[
                SourceRunResult(exchange="SHFE", trade_date="2026-04-16", dataset=FUTURES_DATASET, status=SUCCESS_STATUS),
                SourceRunResult(exchange="CFFEX", trade_date="2026-04-16", dataset=FUTURES_DATASET, status=SUCCESS_STATUS),
            ],
            dataset_states={
                FUTURES_DATASET: {
                    "status": SUCCESS_STATUS,
                    "row_count": 10,
                    "completeness_ok": True,
                },
                FUTURES_RESULTS_DATASET: {
                    "status": PARTIAL_SUCCESS_STATUS,
                    "row_count": 1,
                    "completeness_ok": False,
                },
            },
            requested_datasets=[FUTURES_DATASET, FUTURES_RESULTS_DATASET],
        )
        self.assertEqual(status, PARTIAL_SUCCESS_STATUS)

    def test_audit_canonical_dates_scans_all_existing_dates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            normalized_dir = root / "data" / "normalized" / "daily_quotes"
            normalized_dir.mkdir(parents=True, exist_ok=True)
            (normalized_dir / "2026-04-16.csv").write_text("trade_date,exchange\n2026-04-16,SHFE\n", encoding="utf-8-sig")
            (normalized_dir / "2026-04-17.csv").write_text("trade_date,exchange\n2026-04-17,SHFE\n", encoding="utf-8-sig")

            store = CheckpointStore(root / "state" / "checkpoints.json")
            store.finalize_day("2026-04-16", status="success", outputs={}, row_counts={})
            store.finalize_day("2026-04-17", status="success", outputs={}, row_counts={})
            store.save()

            runner = WorkflowRunner()
            runner.checkpoints = store
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root), mock.patch.object(
                runner,
                "audit_canonical_date",
                side_effect=[
                    {"trade_date": "2026-04-16", "needs_repair": False, "issues": [], "outputs": {}},
                    {"trade_date": "2026-04-17", "needs_repair": True, "issues": ["broken"], "outputs": {}},
                ],
            ):
                audit = runner.audit_canonical_dates()

            self.assertEqual(audit["checked_dates"], ["2026-04-16", "2026-04-17"])
            self.assertEqual(audit["needs_repair_dates"], ["2026-04-17"])

    def test_explicit_repair_forces_rebuild_even_without_needs_repair(self):
        runner = WorkflowRunner()
        with mock.patch.object(
            runner,
            "audit_canonical_date",
            return_value={"trade_date": "2026-04-16", "needs_repair": False, "issues": [], "blocked_issues": [], "outputs": {}},
        ), mock.patch.object(runner, "_rebuild_canonical_from_raw") as rebuild:
            repaired = runner.repair_canonical_outputs(["2026-04-16"])

        self.assertTrue(repaired["forced"])
        self.assertEqual(repaired["repaired_dates"], ["2026-04-16"])
        rebuild.assert_called_once_with("2026-04-16")

    def test_audit_canonical_date_classifies_explained_historical_unavailability(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            options_path = root / "data" / "normalized" / "options" / "daily_quotes" / "2021-04-16.csv"
            options_path.parent.mkdir(parents=True, exist_ok=True)
            options_path.write_text(
                (
                    "trade_date,exchange,product_code,product_name,contract,underlying_exchange,underlying_kind,"
                    "underlying_product_code,underlying_contract,option_type,strike_price,exercise_type,expire_date,"
                    "last_trade_date,open,high,low,close,prev_settlement,settlement,change_close,change_settlement,"
                    "volume,open_interest,open_interest_change,turnover,delta,implied_volatility,exercise_volume,"
                    "source_url,source_type,retrieved_at,raw_path\n"
                    "2021-04-16,SSE,510050,上证50ETF期权,510050C2104M03500,SSE,etf,510050,510050,call,3.5000,"
                    "european,2021-04-28,2021-04-28,0.1,0.1,0.1,0.1,0.1,,0,,,1,,,0,0,,official://sse,fallback_online,"
                    "2021-04-17T00:00:00+08:00,data/raw/sse/options_daily_quotes/20210416.json\n"
                ),
                encoding="utf-8-sig",
            )
            store = CheckpointStore(root / "state" / "checkpoints.json")
            store.update_exchange_result(
                SourceRunResult(
                    exchange="SSE",
                    trade_date="2021-04-16",
                    status="success",
                    dataset="options_daily_quotes",
                    source_url="official://sse",
                    source_type="fallback_online",
                    row_count=1,
                )
            )
            store.update_exchange_result(
                SourceRunResult(
                    exchange="SZSE",
                    trade_date="2021-04-16",
                    status="no_data",
                    dataset="options_daily_quotes",
                    source_url="",
                    source_type="fallback_online",
                    message="SZSE historical public contract source unavailable for 2021-04-16.",
                    error="SZSE historical public contract source unavailable for 2021-04-16.",
                )
            )
            store.update_dataset_state(
                "2021-04-16",
                "options_daily_quotes",
                status="partial_success",
                expected_exchanges=["SSE", "SZSE"],
                observed_exchanges=["SSE"],
                completeness_ok=False,
                selection_match_ok=True,
            )
            store.finalize_day(
                "2021-04-16",
                status="partial_success",
                outputs={"options_daily_quotes": "data/normalized/options/daily_quotes/2021-04-16.csv"},
                row_counts={"options_daily_quotes": 1},
                selection={"instrument_group": "options"},
            )
            store.save()

            runner = WorkflowRunner()
            runner.checkpoints = store
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root):
                audit = runner.audit_canonical_date("2021-04-16")

            self.assertFalse(audit["needs_repair"])
            self.assertEqual(audit["issues"], [])
            self.assertEqual(
                audit["blocked_issues"],
                [
                    "options_daily_quotes: missing exchanges [SZSE] are blocked by public historical source unavailability"
                ],
            )
            self.assertEqual(audit["issue_categories"], {"historical_public_contract_gap": 1})

    def test_audit_canonical_date_classifies_result_chain_source_gaps_as_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            delivery_path = root / "data" / "normalized" / "results" / "futures_delivery" / "2026-04-16.csv"
            delivery_path.parent.mkdir(parents=True, exist_ok=True)
            delivery_path.write_text(
                (
                    "trade_date,exchange,contract,delivery_month,expire_date,final_settlement_price,delivery_volume,"
                    "delivery_amount,warehouse_delivery_quantity,result_status,source_url,source_type,retrieved_at,raw_path\n"
                    "2026-04-16,GFEX,SI2605,2605,2026-04-16,20000,15,300000,,reported,official://gfex,official,"
                    "2026-04-17T00:00:00+08:00,data/raw/gfex/futures_delivery_results/20260416.json\n"
                ),
                encoding="utf-8-sig",
            )
            store = CheckpointStore(root / "state" / "checkpoints.json")
            store.update_exchange_result(
                SourceRunResult(
                    exchange="GFEX",
                    trade_date="2026-04-16",
                    status="success",
                    dataset="futures_delivery_results",
                    source_url="official://gfex",
                    source_type="official",
                    row_count=1,
                )
            )
            for exchange in ("CFFEX", "CZCE", "DCE", "SHFE"):
                store.update_exchange_result(
                    SourceRunResult(
                        exchange=exchange,
                        trade_date="2026-04-16",
                        status="no_data",
                        dataset="futures_delivery_results",
                        source_url="official://missing",
                        source_type="official",
                        message="No official delivery result endpoint configured.",
                    )
                )
            store.update_dataset_state(
                "2026-04-16",
                "futures_delivery_results",
                status="partial_success",
                expected_exchanges=["CFFEX", "CZCE", "DCE", "GFEX", "SHFE"],
                observed_exchanges=["GFEX"],
                completeness_ok=False,
                selection_match_ok=True,
            )
            store.finalize_day(
                "2026-04-16",
                status="success",
                outputs={"futures_delivery_results": "data/normalized/results/futures_delivery/2026-04-16.csv"},
                row_counts={"futures_delivery_results": 1},
            )
            store.save()

            runner = WorkflowRunner()
            runner.checkpoints = store
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root):
                audit = runner.audit_canonical_date("2026-04-16")

            self.assertFalse(audit["needs_repair"])
            self.assertEqual(audit["issues"], [])
            self.assertEqual(
                audit["blocked_issues"],
                [
                    "futures_delivery_results: missing exchanges [CFFEX, CZCE, DCE, SHFE] are blocked by official result-chain source unavailability"
                ],
            )
            self.assertEqual(audit["issue_categories"], {"result_chain_source_gap": 1})

    def test_audit_canonical_date_classifies_result_chain_pending_retry_as_blocked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            result_path = root / "data" / "normalized" / "results" / "options_exercise" / "2026-04-17.csv"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(
                "trade_date,exchange,contract,underlying_contract,option_type,strike_price,expire_date,exercise_volume,assignment_volume,cash_settlement_amount,delivery_quantity,result_status,source_url,source_type,retrieved_at,raw_path\n",
                encoding="utf-8-sig",
            )
            store = CheckpointStore(root / "state" / "checkpoints.json")
            store.update_exchange_result(
                SourceRunResult(
                    exchange="CFFEX",
                    trade_date="2026-04-17",
                    status="pending_retry",
                    dataset="options_exercise_results",
                    source_url="official://cffex/monthly",
                    source_type="official",
                    message="Official CFFEX monthly exercise report returned an HTML error page instead of a PDF.",
                    raw_path="data/raw/cffex/options_exercise_results/20260417.html",
                )
            )
            store.update_dataset_state(
                "2026-04-17",
                "options_exercise_results",
                status="pending_retry",
                expected_exchanges=["CFFEX"],
                observed_exchanges=[],
                completeness_ok=False,
                selection_match_ok=True,
            )
            store.finalize_day(
                "2026-04-17",
                status="partial_success",
                outputs={"options_exercise_results": "data/normalized/results/options_exercise/2026-04-17.csv"},
                row_counts={"options_exercise_results": 0},
            )
            store.save()

            runner = WorkflowRunner()
            runner.checkpoints = store
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root):
                audit = runner.audit_canonical_date("2026-04-17")

            self.assertFalse(audit["needs_repair"])
            self.assertEqual(audit["issues"], [])
            self.assertEqual(
                audit["blocked_issues"],
                [
                    "options_exercise_results: missing exchanges [CFFEX] are pending official publication"
                ],
            )
            self.assertEqual(audit["issue_categories"], {"result_chain_publication_lag": 1})

    def test_audit_canonical_dates_aggregates_issue_categories(self):
        runner = WorkflowRunner()
        with mock.patch.object(
            runner,
            "audit_canonical_date",
            side_effect=[
                {
                    "trade_date": "2021-04-16",
                    "needs_repair": False,
                    "issues": [],
                    "blocked_issues": ["options_daily_quotes: missing exchanges [SZSE] are blocked by public historical source unavailability"],
                    "issue_categories": {"historical_public_contract_gap": 1},
                    "outputs": {},
                },
                {
                    "trade_date": "2026-04-16",
                    "needs_repair": False,
                    "issues": [],
                    "blocked_issues": ["futures_delivery_results: missing exchanges [CFFEX] are pending official publication"],
                    "issue_categories": {"result_chain_publication_lag": 1},
                    "outputs": {},
                },
            ],
        ):
            audit = runner.audit_canonical_dates(["2021-04-16", "2026-04-16"])
        self.assertEqual(audit["needs_repair_dates"], [])
        self.assertEqual(audit["issue_category_counts"], {"historical_public_contract_gap": 1, "result_chain_publication_lag": 1})
        self.assertEqual(
            audit["blocked_issues"],
            [
                "options_daily_quotes: missing exchanges [SZSE] are blocked by public historical source unavailability",
                "futures_delivery_results: missing exchanges [CFFEX] are pending official publication",
            ],
        )

    def test_validate_reports_contracts_latest_consistency(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            contracts_dir = root / "data" / "normalized" / "master"
            contracts_dir.mkdir(parents=True, exist_ok=True)
            snapshot_path = contracts_dir / "contracts" / "2026-04-16.csv"
            snapshot_path.parent.mkdir(parents=True, exist_ok=True)
            header = (
                "trade_date,instrument_type,exchange,product_code,product_name,contract,contract_status,list_date,"
                "expire_date,last_trade_date,contract_multiplier,quote_unit,price_tick,delivery_type,exercise_type,"
                "option_type,strike_price,underlying_exchange,underlying_kind,underlying_product_code,underlying_contract,"
                "source_url,source_type,retrieved_at,raw_path\n"
            )
            row = (
                "2026-04-16,option,SZSE,159919,沪深300ETF期权,159919C2604M04000A,trading,,2026-04-22,2026-04-22,10000,,,"
                "cash,european,call,4.0000,SZSE,etf,159919,159919,official://szse,official,2026-04-18T00:00:00+08:00,data/raw/szse/contracts_snapshot/20260416.json\n"
            )
            snapshot_path.write_text(header + row, encoding="utf-8-sig")
            latest_path = contracts_dir / "contracts_latest.csv"
            latest_path.write_text(header + row, encoding="utf-8-sig")

            store = CheckpointStore(root / "state" / "checkpoints.json")
            store.finalize_day(
                "2026-04-16",
                status="success",
                outputs={"contracts_snapshot": "data/normalized/master/contracts/2026-04-16.csv"},
                row_counts={"contracts_snapshot": 1},
            )
            store.save()

            runner = WorkflowRunner()
            runner.checkpoints = store
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root):
                validation = runner.validate("2026-04-16")
            self.assertTrue(validation["contracts_latest"]["csv_exists"])
            self.assertTrue(validation["contracts_latest"]["schema_ok"])
            self.assertEqual(validation["contracts_latest"]["source_trade_date"], "2026-04-16")
            self.assertTrue(validation["contracts_latest"]["matches_source_snapshot"])
            self.assertTrue(validation["datasets"]["contracts_snapshot"]["master_data_completeness"])
            self.assertTrue(validation["datasets"]["contracts_snapshot"]["contracts_latest_consistency_ok"])

    def test_validate_contracts_latest_ignores_newer_partial_scope_days(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            contracts_dir = root / "data" / "normalized" / "master"
            contracts_dir.mkdir(parents=True, exist_ok=True)
            snapshot_2026 = contracts_dir / "contracts" / "2026-04-16.csv"
            snapshot_2021 = contracts_dir / "contracts" / "2021-04-16.csv"
            snapshot_2026.parent.mkdir(parents=True, exist_ok=True)
            header = (
                "trade_date,instrument_type,exchange,product_code,product_name,contract,contract_status,list_date,"
                "expire_date,last_trade_date,contract_multiplier,quote_unit,price_tick,delivery_type,exercise_type,"
                "option_type,strike_price,underlying_exchange,underlying_kind,underlying_product_code,underlying_contract,"
                "source_url,source_type,retrieved_at,raw_path\n"
            )
            row_2026 = (
                "2026-04-16,option,SZSE,159919,沪深300ETF期权,159919C2604M04000A,trading,,2026-04-22,2026-04-22,10000,,,"
                "cash,european,call,4.0000,SZSE,etf,159919,159919,official://szse,official,2026-04-18T00:00:00+08:00,data/raw/szse/contracts_snapshot/20260416.json\n"
            )
            row_2021 = (
                "2021-04-16,option,SHFE,CU,铜期权,CU2105-C-70000,trading,,2021-04-26,2021-04-26,,,,american,call,70000,SHFE,futures,CU,CU2105,official://shfe,official,2021-04-17T00:00:00+08:00,data/raw/shfe/contracts_snapshot/20210416.json\n"
            )
            snapshot_2026.write_text(header + row_2026, encoding="utf-8-sig")
            snapshot_2021.write_text(header + row_2021, encoding="utf-8-sig")
            latest_path = contracts_dir / "contracts_latest.csv"
            latest_path.write_text(header + row_2026, encoding="utf-8-sig")

            store = CheckpointStore(root / "state" / "checkpoints.json")
            store.finalize_day(
                "2026-04-16",
                status="success",
                outputs={"contracts_snapshot": "data/normalized/master/contracts/2026-04-16.csv"},
                row_counts={"contracts_snapshot": 1},
                selection={"instrument_group": "all"},
            )
            store.finalize_day(
                "2021-04-16",
                status="partial_success",
                outputs={"contracts_snapshot": "data/normalized/master/contracts/2021-04-16.csv"},
                row_counts={"contracts_snapshot": 1},
                selection={"instrument_group": "all"},
            )
            store.save()

            runner = WorkflowRunner()
            runner.checkpoints = store
            with mock.patch.object(workflow_module, "PROJECT_ROOT", root):
                validation = runner.validate("2021-04-16")
            self.assertEqual(validation["contracts_latest"]["source_trade_date"], "2026-04-16")
            self.assertTrue(validation["contracts_latest"]["matches_source_snapshot"])
            self.assertFalse(validation["contracts_latest"]["current_trade_date_is_latest_source"])

    def test_older_successful_all_scope_day_does_not_overwrite_contracts_latest(self):
        store = CheckpointStore(Path(tempfile.gettempdir()) / "contracts-latest-checkpoints.json")
        store.data = {
            "dates": {
                "2026-04-17": {
                    "status": "success",
                    "outputs": {"contracts_snapshot": "data/normalized/master/contracts/2026-04-17.csv"},
                    "selection": {"instrument_group": "all"},
                }
            }
        }
        runner = WorkflowRunner()
        runner.checkpoints = store
        with mock.patch.object(workflow_module, "write_contracts_latest") as write_latest:
            runner._update_contracts_latest_if_needed(
                trade_date_str="2026-04-15",
                status="success",
                selection=None,
                query_mode=False,
                outputs={"contracts_snapshot": "data/normalized/master/contracts/2026-04-15.csv"},
                dataset_rows={"contracts_snapshot": [{"contract": "OLD"}]},
            )

        write_latest.assert_not_called()


if __name__ == "__main__":
    unittest.main()
