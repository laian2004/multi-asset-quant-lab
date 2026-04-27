import json
from datetime import date
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .config import CHECKPOINT_PATH, PROJECT_ROOT, QUERY_STATE_DIR, load_sources_config
from .constants import (
    CONTRACTS_DATASET,
    DERIVATIVES_DATASET,
    ERROR_STATUS,
    FAILED_STATUS,
    FUTURES_DATASET,
    FUTURES_RESULTS_DATASET,
    NO_DATA_STATUS,
    NOT_APPLICABLE_STATUS,
    OPTIONS_CHAIN_VIEW,
    OPTIONS_DATASET,
    OPTION_RESULTS_DATASET,
    PARTIAL_SUCCESS_STATUS,
    PENDING_RETRY_STATUS,
    STANDARD_FIELDS,
    SUCCESS_STATUS,
    UNDERLYING_SUMMARY_VIEW,
)
from .delivery_results import (
    FuturesDeliveryCollector,
    _build_gfex_delivery_rows,
    _build_shfe_delivery_rows,
    _parse_delivery_payload,
)
from .exercise_results import OptionExerciseCollector, _parse_exercise_payload
from .logging_utils import append_failure_log, get_logger
from .master_data import ContractMasterCollector
from .models import RawPayload, SourceRunResult
from .platform import build_platform_rows, collect_dataset_observed_exchanges, write_contracts_latest, write_platform_outputs
from .selection import CrawlSelection
from .sources import CFFEXSource, CZCESource, DCESource, GFEXSource, SHFESource
from .sources.option_cffex import CFFEXOptionSource
from .sources.option_czce import CZCEOptionSource
from .sources.option_dce import DCEOptionSource
from .sources.option_gfex import GFEXOptionSource
from .sources.option_shfe import SHFEOptionSource
from .sources.option_sse import SSEOptionSource
from .sources.option_szse import SZSEOptionSource
from .state.checkpoints import CheckpointStore
from .trading_calendar import TradingCalendarRegistry
from .utils import compact_trade_date, decode_bytes, format_trade_date, iter_csv_rows, normalize_text, now_shanghai, parse_trade_date, relative_to_project


class WorkflowRunner:
    def __init__(self):
        self.settings = load_sources_config()
        self.logger = get_logger()
        self.checkpoints = CheckpointStore(CHECKPOINT_PATH)
        self.calendar = TradingCalendarRegistry(self.settings, self.logger)
        self.sources = [
            SHFESource(self.settings, self.logger),
            CFFEXSource(self.settings, self.logger),
            CZCESource(self.settings, self.logger),
            GFEXSource(self.settings, self.logger),
            DCESource(self.settings, self.logger),
        ]
        self.option_sources = [
            SHFEOptionSource(self.settings, self.logger),
            CFFEXOptionSource(self.settings, self.logger),
            CZCEOptionSource(self.settings, self.logger),
            GFEXOptionSource(self.settings, self.logger),
            DCEOptionSource(self.settings, self.logger),
            SSEOptionSource(self.settings, self.logger),
            SZSEOptionSource(self.settings, self.logger),
        ]
        self.delivery_collector = FuturesDeliveryCollector(self.settings, self.logger)
        self.exercise_collector = OptionExerciseCollector(self.settings, self.logger)
        self.master_data_collector = ContractMasterCollector(self.settings, self.logger)

    def fetch_date(self, trade_date_value: str, selection: Optional[CrawlSelection] = None) -> Dict[str, object]:
        trade_date = parse_trade_date(trade_date_value)
        trade_date_str = format_trade_date(trade_date)
        requested_datasets = self._requested_datasets(selection)
        checkpoint_store, selection_id, query_mode = self._resolve_checkpoint_store(selection, requested_datasets)
        selection_summary = selection.to_summary() if selection else {}

        exchange_summaries: Dict[str, Dict[str, object]] = {}
        futures_rows = []
        options_rows = []
        source_results: List[SourceRunResult] = []

        active_futures_sources = self._select_sources(self.sources, selection, "futures")
        active_option_sources = self._select_sources(self.option_sources, selection, "options")

        for dataset_name, active_sources in (
            (FUTURES_DATASET, active_futures_sources),
            (OPTIONS_DATASET, active_option_sources),
        ):
            if not active_sources:
                continue
            dataset_bucket = exchange_summaries.setdefault(dataset_name, {})
            for source in active_sources:
                result = source.run(trade_date)
                result = self._apply_selection(result, selection)
                checkpoint_store.update_exchange_result(result)
                dataset_bucket[source.exchange] = result.to_summary()
                source_results.append(result)
                if result.status == SUCCESS_STATUS:
                    if result.dataset == FUTURES_DATASET:
                        futures_rows.extend(result.rows)
                    elif result.dataset == OPTIONS_DATASET:
                        options_rows.extend(result.rows)
                elif result.status in {ERROR_STATUS, PENDING_RETRY_STATUS}:
                    append_failure_log(result.to_summary())

        delivery_rows: List[Dict[str, str]] = []
        delivery_summaries: Dict[str, Dict[str, object]] = {}
        if FUTURES_RESULTS_DATASET in requested_datasets and active_futures_sources:
            collected_rows, collected_summaries = self.delivery_collector.collect(trade_date, futures_rows=futures_rows)
            allowed_exchanges = {source.exchange for source in active_futures_sources}
            delivery_rows = [row for row in collected_rows if row.get("exchange") in allowed_exchanges]
            if selection and selection.has_row_filters and delivery_rows:
                delivery_rows = self._filter_dict_rows(delivery_rows, selection)
            for exchange, summary in collected_summaries.items():
                if exchange not in allowed_exchanges:
                    continue
                delivery_summaries[exchange] = summary
                checkpoint_store.update_exchange_result(self._summary_to_result(summary))
            if delivery_summaries:
                exchange_summaries[FUTURES_RESULTS_DATASET] = delivery_summaries

        option_result_rows: List[Dict[str, str]] = []
        option_result_summaries: Dict[str, Dict[str, object]] = {}
        if OPTION_RESULTS_DATASET in requested_datasets and active_option_sources:
            collected_rows, collected_summaries = self.exercise_collector.collect(trade_date, option_rows=options_rows)
            allowed_exchanges = {source.exchange for source in active_option_sources}
            option_result_rows = [row for row in collected_rows if row.get("exchange") in allowed_exchanges]
            if selection and selection.has_row_filters and option_result_rows:
                option_result_rows = self._filter_dict_rows(option_result_rows, selection)
            for exchange, summary in collected_summaries.items():
                if exchange not in allowed_exchanges:
                    continue
                option_result_summaries[exchange] = summary
                checkpoint_store.update_exchange_result(self._summary_to_result(summary))
            if option_result_summaries:
                exchange_summaries[OPTION_RESULTS_DATASET] = option_result_summaries

        master_metadata = self.master_data_collector.collect(
            trade_date,
            futures_rows=futures_rows,
            options_rows=options_rows,
        )

        dataset_rows = build_platform_rows(
            futures_rows=futures_rows,
            options_rows=options_rows,
            option_result_rows=option_result_rows,
            futures_result_rows=delivery_rows,
            master_metadata=master_metadata,
        )
        outputs, row_counts = write_platform_outputs(
            trade_date=trade_date_str,
            dataset_rows=dataset_rows,
            include_datasets=requested_datasets,
            selection_id=selection_id,
            selection_summary=selection_summary,
            update_contracts_latest=False,
        )

        dataset_states = self._build_dataset_states(
            selection=selection,
            requested_datasets=requested_datasets,
            source_results=source_results,
            dataset_rows=dataset_rows,
            delivery_summaries=delivery_summaries,
            option_result_summaries=option_result_summaries,
        )
        for dataset_name, state in dataset_states.items():
            checkpoint_store.update_dataset_state(
                trade_date_str,
                dataset_name,
                status=str(state["status"]),
                expected_exchanges=list(state["expected_exchanges"]),
                observed_exchanges=list(state["observed_exchanges"]),
                completeness_ok=bool(state["completeness_ok"]),
                selection_match_ok=bool(state["selection_match_ok"]),
            )

        status = self._aggregate_status(source_results, dataset_states, requested_datasets)
        self._update_contracts_latest_if_needed(
            trade_date_str=trade_date_str,
            status=status,
            selection=selection,
            query_mode=query_mode,
            outputs=outputs,
            dataset_rows=dataset_rows,
        )
        checkpoint_store.finalize_day(
            trade_date_str,
            status=status,
            outputs=outputs,
            row_counts=row_counts,
            selection=selection_summary,
        )
        checkpoint_store.save()

        summary = {
            "trade_date": trade_date_str,
            "status": status,
            "csv_path": outputs.get(FUTURES_DATASET, ""),
            "row_count": row_counts.get(FUTURES_DATASET, 0),
            "outputs": outputs,
            "row_counts": row_counts,
            "exchange_summaries": exchange_summaries,
            "query_mode": query_mode,
        }
        if selection and selection.active:
            summary["selection"] = selection_summary
        if selection_id:
            summary["selection_id"] = selection_id
        self.logger.info("Processed %s -> %s futures=%s options=%s", trade_date_str, status, len(futures_rows), len(options_rows))
        return summary

    def backfill(self, start_value: str, end_value: str, selection: Optional[CrawlSelection] = None) -> Dict[str, object]:
        start_date = parse_trade_date(start_value)
        end_date = parse_trade_date(end_value)
        candidate_dates = self.calendar.candidate_dates(self._calendar_name(selection), start_date, end_date)
        summaries = []
        for trade_date in candidate_dates:
            summaries.append(self.fetch_date(format_trade_date(trade_date), selection=selection))
        result = {
            "start": format_trade_date(start_date),
            "end": format_trade_date(end_date),
            "candidate_dates": len(candidate_dates),
            "processed_dates": len(summaries),
            "summaries": summaries,
        }
        if selection and selection.active:
            result["selection"] = selection.to_summary()
        return result

    def sync_daily(self, date_value: str = "latest", selection: Optional[CrawlSelection] = None) -> Dict[str, object]:
        if date_value == "latest":
            now = now_shanghai()
            reference = now.date()
            target_date = self.calendar.previous_trading_day(self._calendar_name(selection), reference)
        else:
            target_date = parse_trade_date(date_value)
        summary = self.fetch_date(format_trade_date(target_date), selection=selection)
        if not selection or not selection.has_row_filters:
            if summary["status"] == NO_DATA_STATUS:
                last_success = self.checkpoints.get_last_successful_trade_date()
                if last_success and last_success != format_trade_date(target_date):
                    summary["fallback_trade_date"] = last_success
        return summary

    def validate(self, trade_date_value: str, selection: Optional[CrawlSelection] = None) -> Dict[str, object]:
        trade_date = parse_trade_date(trade_date_value)
        trade_date_str = format_trade_date(trade_date)
        requested_datasets = self._requested_datasets(selection)
        checkpoint_store, selection_id, query_mode = self._resolve_checkpoint_store(selection, requested_datasets)
        checkpoint_day = checkpoint_store.get_day(trade_date_str)
        validation = {
            "trade_date": trade_date_str,
            "checkpoint_status": checkpoint_day.get("status", ""),
            "datasets": {},
            "query_mode": query_mode,
            "contracts_latest": {},
        }
        if selection and selection.active:
            validation["selection"] = selection.to_summary()
        if selection_id:
            validation["selection_id"] = selection_id

        outputs = dict(checkpoint_day.get("outputs", {}))
        if not outputs and not query_mode:
            legacy_path = PROJECT_ROOT / "data" / "normalized" / "daily_quotes" / f"{trade_date_str}.csv"
            if legacy_path.exists():
                outputs[FUTURES_DATASET] = str(legacy_path.relative_to(PROJECT_ROOT))

        for dataset_name, relative_path in outputs.items():
            csv_path = PROJECT_ROOT / relative_path
            dataset_state = checkpoint_day.get("datasets", {}).get(dataset_name, {})
            has_explicit_state = bool(dataset_state)
            dataset_validation = {
                "status": str(dataset_state.get("status", checkpoint_day.get("status", ""))),
                "csv_exists": csv_path.exists(),
                "schema_ok": False,
                "row_count": 0,
                "duplicate_keys": 0,
                "missing_raw_paths": [],
                "source_provenance_ok": False,
                "expected_exchanges": list(dataset_state.get("expected_exchanges", [])),
                "observed_exchanges": list(dataset_state.get("observed_exchanges", [])),
                "completeness_ok": bool(dataset_state.get("completeness_ok", False)),
                "selection_match_ok": bool(dataset_state.get("selection_match_ok", True)),
                "master_data_completeness": True,
                "result_chain_semantics_ok": True,
                "no_data_reason": self._dataset_reason(checkpoint_day, dataset_name, NO_DATA_STATUS),
                "not_applicable_reason": self._dataset_reason(checkpoint_day, dataset_name, NOT_APPLICABLE_STATUS),
            }
            if not csv_path.exists():
                if (
                    not dataset_validation["expected_exchanges"]
                    and not (dataset_name in {OPTION_RESULTS_DATASET, FUTURES_RESULTS_DATASET} and dataset_validation["status"] in {NO_DATA_STATUS, NOT_APPLICABLE_STATUS})
                ):
                    dataset_validation["expected_exchanges"] = self._fallback_expected_exchanges(checkpoint_day, dataset_name)
                if dataset_validation["status"] == NO_DATA_STATUS:
                    if (
                        dataset_name in {OPTION_RESULTS_DATASET, FUTURES_RESULTS_DATASET}
                        and not dataset_validation["expected_exchanges"]
                    ):
                        dataset_validation["no_data_reason"] = self._default_no_data_reason(dataset_name, dataset_validation)
                    elif not dataset_validation["no_data_reason"]:
                        dataset_validation["no_data_reason"] = self._default_no_data_reason(dataset_name, dataset_validation)
                else:
                    dataset_validation["no_data_reason"] = ""
                dataset_validation["source_provenance_ok"] = not dataset_validation["missing_raw_paths"]
                dataset_validation["master_data_completeness"] = self._master_data_completeness(dataset_name, [])
                dataset_validation["result_chain_semantics_ok"] = self._result_chain_semantics_ok(
                    dataset_name=dataset_name,
                    dataset_state=dataset_state,
                    row_count=0,
                    no_data_reason=dataset_validation["no_data_reason"],
                    not_applicable_reason=dataset_validation["not_applicable_reason"],
                )
                if not has_explicit_state:
                    dataset_validation["status"] = self._derive_validated_dataset_status(dataset_validation)
                validation["datasets"][dataset_name] = dataset_validation
                continue
            rows = list(iter_csv_rows(csv_path))
            dataset_validation["row_count"] = len(rows)
            expected_fields = self._expected_fields(dataset_name)
            fieldnames = list(rows[0].keys()) if rows else expected_fields
            dataset_validation["schema_ok"] = fieldnames == expected_fields
            dataset_validation["observed_exchanges"] = sorted({row.get("exchange", "") for row in rows if row.get("exchange", "")})
            if rows:
                dataset_validation["duplicate_keys"] = self._duplicate_key_count(dataset_name, rows)
            if rows and "raw_path" in rows[0]:
                for row in rows:
                    raw_path = str(row.get("raw_path", "")).strip()
                    if not raw_path:
                        continue
                    candidate = PROJECT_ROOT / raw_path
                    if not candidate.exists():
                        dataset_validation["missing_raw_paths"].append(raw_path)
            dataset_validation["source_provenance_ok"] = not dataset_validation["missing_raw_paths"]
            if (
                not dataset_validation["expected_exchanges"]
                and not (dataset_name in {OPTION_RESULTS_DATASET, FUTURES_RESULTS_DATASET} and dataset_validation["status"] in {NO_DATA_STATUS, NOT_APPLICABLE_STATUS})
            ):
                dataset_validation["expected_exchanges"] = self._fallback_expected_exchanges(checkpoint_day, dataset_name)
            if not dataset_validation["expected_exchanges"]:
                dataset_validation["expected_exchanges"] = list(dataset_validation["observed_exchanges"])
            if dataset_validation["status"] == NO_DATA_STATUS:
                if (
                    dataset_name in {OPTION_RESULTS_DATASET, FUTURES_RESULTS_DATASET}
                    and not dataset_validation["expected_exchanges"]
                ):
                    dataset_validation["no_data_reason"] = self._default_no_data_reason(dataset_name, dataset_validation)
                elif not dataset_validation["no_data_reason"]:
                    dataset_validation["no_data_reason"] = self._default_no_data_reason(dataset_name, dataset_validation)
            else:
                dataset_validation["no_data_reason"] = ""
            dataset_validation["completeness_ok"] = self._validation_completeness_ok(
                dataset_name=dataset_name,
                dataset_state=dataset_state,
                observed_exchanges=dataset_validation["observed_exchanges"],
                expected_exchanges=dataset_validation["expected_exchanges"],
                row_count=len(rows),
            )
            dataset_validation["master_data_completeness"] = self._master_data_completeness(dataset_name, rows)
            dataset_validation["result_chain_semantics_ok"] = self._result_chain_semantics_ok(
                dataset_name=dataset_name,
                dataset_state=dataset_state,
                row_count=len(rows),
                no_data_reason=dataset_validation["no_data_reason"],
                not_applicable_reason=dataset_validation["not_applicable_reason"],
            )
            if not has_explicit_state:
                dataset_validation["status"] = self._derive_validated_dataset_status(dataset_validation)
            validation["datasets"][dataset_name] = dataset_validation
        if not query_mode:
            validation["contracts_latest"] = self._validate_contracts_latest(trade_date_str, outputs)
            if CONTRACTS_DATASET in validation["datasets"]:
                validation["datasets"][CONTRACTS_DATASET]["contracts_latest_consistency_ok"] = bool(
                    validation["contracts_latest"].get("matches_source_snapshot", False)
                )
        validation["checkpoint_status"] = self._aggregate_validation_status(validation["datasets"])
        return validation

    def audit_canonical_date(self, trade_date_value: str) -> Dict[str, object]:
        trade_date_str = format_trade_date(parse_trade_date(trade_date_value))
        day = self.checkpoints.get_day(trade_date_str)
        validation = self.validate(trade_date_str)
        issues = []
        blocked_issues = []
        for dataset_name, dataset_validation in validation["datasets"].items():
            if not dataset_validation.get("csv_exists", False):
                issues.append(f"{dataset_name}: missing csv")
                continue
            if not dataset_validation.get("schema_ok", False):
                issues.append(f"{dataset_name}: schema mismatch")
            if not dataset_validation.get("completeness_ok", False):
                explained_issue = self._explained_unavailability_issue(day, dataset_name, dataset_validation)
                if explained_issue:
                    blocked_issues.append(explained_issue)
                else:
                    issues.append(f"{dataset_name}: observed exchanges do not match expected exchanges")
        issue_categories = self._summarize_audit_issue_categories(issues, blocked_issues)
        return {
            "trade_date": trade_date_str,
            "needs_repair": bool(issues),
            "issues": issues,
            "blocked_issues": blocked_issues,
            "issue_categories": issue_categories,
            "outputs": day.get("outputs", {}),
        }

    def audit_canonical_dates(self, trade_dates: Optional[Iterable[str]] = None) -> Dict[str, object]:
        dates = [format_trade_date(parse_trade_date(value)) for value in (trade_dates or self._existing_canonical_dates())]
        audits = [self.audit_canonical_date(trade_date_str) for trade_date_str in dates]
        needs_repair = [item["trade_date"] for item in audits if item.get("needs_repair")]
        aggregated_categories: Dict[str, int] = {}
        aggregated_issues: List[str] = []
        aggregated_blocked_issues: List[str] = []
        for audit in audits:
            for category, count in audit.get("issue_categories", {}).items():
                aggregated_categories[category] = aggregated_categories.get(category, 0) + int(count or 0)
            aggregated_issues.extend(str(item) for item in (audit.get("issues", []) or []))
            aggregated_blocked_issues.extend(str(item) for item in (audit.get("blocked_issues", []) or []))
        return {
            "checked_dates": dates,
            "needs_repair_dates": needs_repair,
            "audits": audits,
            "issue_category_counts": aggregated_categories,
            "issues": aggregated_issues,
            "blocked_issues": aggregated_blocked_issues,
        }

    def repair_canonical_outputs(self, trade_dates: Optional[Iterable[str]] = None) -> Dict[str, object]:
        explicit_dates = list(trade_dates or [])
        dates = [format_trade_date(parse_trade_date(value)) for value in (explicit_dates or self._existing_canonical_dates())]
        repaired = []
        forced = bool(explicit_dates)
        for trade_date_str in dates:
            audit = self.audit_canonical_date(trade_date_str)
            if not forced and not audit["needs_repair"]:
                continue
            self._rebuild_canonical_from_raw(trade_date_str)
            repaired.append(trade_date_str)
        return {"checked_dates": dates, "repaired_dates": repaired, "forced": forced}

    def _select_sources(self, candidates: List[object], selection: Optional[CrawlSelection], instrument_group: str) -> List[object]:
        if selection is not None and not selection.includes_instrument_group(instrument_group):
            return []
        if selection is None or not selection.exchanges:
            return list(candidates)
        selected = [source for source in candidates if selection.includes_exchange(source.exchange)]
        if not selected:
            return []
        return selected

    def _apply_selection(self, result, selection: Optional[CrawlSelection]):
        if selection is None or not selection.active or result.status != SUCCESS_STATUS:
            return result
        if not selection.has_filters_for_exchange(result.exchange):
            return result
        filtered_rows = selection.filter_rows(result.exchange, result.rows)
        result.rows = filtered_rows
        result.row_count = len(filtered_rows)
        if not filtered_rows:
            result.status = NO_DATA_STATUS
            result.message = f"Selection matched no rows for {result.exchange}."
        return result

    @staticmethod
    def _summarize_audit_issue_categories(issues: Iterable[str], blocked_issues: Iterable[str]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for issue in issues:
            category = WorkflowRunner._classify_audit_issue(issue, blocked=False)
            counts[category] = counts.get(category, 0) + 1
        for issue in blocked_issues:
            category = WorkflowRunner._classify_audit_issue(issue, blocked=True)
            counts[category] = counts.get(category, 0) + 1
        return counts

    @staticmethod
    def _classify_audit_issue(issue: str, *, blocked: bool) -> str:
        text = normalize_text(issue)
        if blocked:
            if "pending official publication" in text:
                return "result_chain_publication_lag"
            if "result-chain source unavailability" in text:
                return "result_chain_source_gap"
            if "historical public contract source unavailable" in text or "public historical source unavailability" in text:
                return "historical_public_contract_gap"
            return "blocked_public_source_gap"
        if "missing csv" in text:
            return "missing_csv"
        if "schema mismatch" in text:
            return "schema_mismatch"
        if "observed exchanges do not match expected exchanges" in text:
            return "coverage_gap"
        return "other_issue"

    def _build_dataset_states(
        self,
        *,
        selection: Optional[CrawlSelection],
        requested_datasets: List[str],
        source_results: List[SourceRunResult],
        dataset_rows: Dict[str, List[object]],
        delivery_summaries: Dict[str, Dict[str, object]],
        option_result_summaries: Dict[str, Dict[str, object]],
    ) -> Dict[str, Dict[str, object]]:
        observed_exchanges = collect_dataset_observed_exchanges(dataset_rows)
        query_mode = bool(selection and selection.has_row_filters)
        futures_results = [item for item in source_results if item.dataset == FUTURES_DATASET and item.status != NOT_APPLICABLE_STATUS]
        options_results = [item for item in source_results if item.dataset == OPTIONS_DATASET and item.status != NOT_APPLICABLE_STATUS]
        applicable_map = {
            FUTURES_DATASET: futures_results,
            OPTIONS_DATASET: options_results,
        }
        expected_primary = {
            FUTURES_DATASET: sorted(item.exchange for item in futures_results),
            OPTIONS_DATASET: sorted(item.exchange for item in options_results),
        }
        success_primary = {
            FUTURES_DATASET: sorted(item.exchange for item in futures_results if item.status == SUCCESS_STATUS),
            OPTIONS_DATASET: sorted(item.exchange for item in options_results if item.status == SUCCESS_STATUS),
        }
        result_expected = self._result_expected_exchanges(
            dataset_rows=dataset_rows,
            observed_exchanges=observed_exchanges,
        )
        states: Dict[str, Dict[str, object]] = {}

        for dataset_name in requested_datasets:
            rows = dataset_rows.get(dataset_name, [])
            observed = observed_exchanges.get(dataset_name, [])
            if dataset_name in result_expected:
                expected = result_expected[dataset_name]
            else:
                expected = self._expected_exchanges_for_dataset(dataset_name, expected_primary)
            selection_match_ok = self._selection_match_ok(dataset_name, rows, selection) if query_mode else True
            row_count = len(rows)

            if dataset_name in {FUTURES_DATASET, OPTIONS_DATASET}:
                applicable = applicable_map[dataset_name]
                all_success = bool(applicable) and all(item.status == SUCCESS_STATUS for item in applicable)
                has_error = any(item.status in {ERROR_STATUS, PENDING_RETRY_STATUS} for item in applicable)
                has_no_data = any(item.status == NO_DATA_STATUS for item in applicable)
                completeness_ok = bool(expected) and observed == expected and all_success and selection_match_ok and row_count > 0
                if all_success and completeness_ok:
                    status = SUCCESS_STATUS
                elif not expected:
                    status = NO_DATA_STATUS
                elif has_error:
                    status = PARTIAL_SUCCESS_STATUS if row_count else FAILED_STATUS
                elif has_no_data:
                    status = PARTIAL_SUCCESS_STATUS if row_count else NO_DATA_STATUS
                else:
                    status = PARTIAL_SUCCESS_STATUS if row_count else FAILED_STATUS
            elif dataset_name in {OPTION_RESULTS_DATASET, FUTURES_RESULTS_DATASET}:
                result_summaries = delivery_summaries if dataset_name == FUTURES_RESULTS_DATASET else option_result_summaries
                status, completeness_ok = self._build_result_dataset_state(
                    dataset_name=dataset_name,
                    expected_exchanges=expected,
                    observed_exchanges=observed,
                    row_count=row_count,
                    selection_match_ok=selection_match_ok,
                    summaries=result_summaries,
                )
            else:
                completeness_ok = selection_match_ok and (set(observed) == set(expected))
                if not expected:
                    status = NO_DATA_STATUS
                elif completeness_ok and row_count > 0:
                    status = SUCCESS_STATUS
                elif row_count > 0:
                    status = PARTIAL_SUCCESS_STATUS
                else:
                    status = FAILED_STATUS

            states[dataset_name] = {
                "status": status,
                "expected_exchanges": expected,
                "observed_exchanges": observed,
                "completeness_ok": completeness_ok,
                "selection_match_ok": selection_match_ok,
                "row_count": row_count,
            }
        return states

    def _result_expected_exchanges(
        self,
        *,
        dataset_rows: Dict[str, List[object]],
        observed_exchanges: Dict[str, List[str]],
    ) -> Dict[str, List[str]]:
        contracts_rows = dataset_rows.get(CONTRACTS_DATASET, [])
        if not contracts_rows:
            return {}
        trade_date = ""
        for row in contracts_rows:
            trade_date = str(getattr(row, "trade_date", "") if not isinstance(row, dict) else row.get("trade_date", "")).strip()
            if trade_date:
                break
        if not trade_date:
            return {}

        option_due: set[str] = set()
        futures_due: set[str] = set()
        for row in contracts_rows:
            if isinstance(row, dict):
                instrument_type = str(row.get("instrument_type", "")).strip()
                exchange = str(row.get("exchange", "")).strip()
                expire_date = str(row.get("expire_date", "")).strip()
                last_trade_date = str(row.get("last_trade_date", "")).strip()
            else:
                instrument_type = str(getattr(row, "instrument_type", "")).strip()
                exchange = str(getattr(row, "exchange", "")).strip()
                expire_date = str(getattr(row, "expire_date", "")).strip()
                last_trade_date = str(getattr(row, "last_trade_date", "")).strip()
            if not exchange:
                continue
            if instrument_type == "option" and trade_date in {expire_date, last_trade_date}:
                option_due.add(exchange)
            if instrument_type == "future" and trade_date in {expire_date, last_trade_date}:
                futures_due.add(exchange)

        option_expected = sorted(option_due | set(observed_exchanges.get(OPTION_RESULTS_DATASET, [])))
        futures_expected = sorted(futures_due | set(observed_exchanges.get(FUTURES_RESULTS_DATASET, [])))
        return {
            OPTION_RESULTS_DATASET: option_expected,
            FUTURES_RESULTS_DATASET: futures_expected,
        }

    def _aggregate_status(
        self,
        source_results: List[SourceRunResult],
        dataset_states: Dict[str, Dict[str, object]],
        requested_datasets: List[str],
    ) -> str:
        primary = [item for item in source_results if item.dataset in {FUTURES_DATASET, OPTIONS_DATASET} and item.status != NOT_APPLICABLE_STATUS]
        if not primary:
            return NO_DATA_STATUS
        if all(item.status == NO_DATA_STATUS for item in primary):
            return NO_DATA_STATUS

        required_datasets = self._required_datasets(requested_datasets)
        primary_all_success = all(item.status == SUCCESS_STATUS for item in primary)
        required_complete = all(dataset_states.get(dataset_name, {}).get("completeness_ok", False) for dataset_name in required_datasets)
        has_errors = any(item.status in {ERROR_STATUS, PENDING_RETRY_STATUS} for item in primary)
        any_rows = any(dataset_states.get(dataset_name, {}).get("row_count", 0) > 0 for dataset_name in requested_datasets)

        if primary_all_success and required_complete:
            return SUCCESS_STATUS
        if has_errors or not required_complete:
            return PARTIAL_SUCCESS_STATUS if any_rows or any(item.status == SUCCESS_STATUS for item in primary) else FAILED_STATUS
        return NO_DATA_STATUS if not any_rows else PARTIAL_SUCCESS_STATUS

    def _calendar_name(self, selection: Optional[CrawlSelection]) -> str:
        if selection is None:
            return "futures_cn"
        if selection.instrument_group in {"options", "all"}:
            return "all"
        return "futures_cn"

    def _expected_fields(self, dataset_name: str) -> List[str]:
        from .constants import (
            CONTRACTS_STANDARD_FIELDS,
            DERIVATIVES_STANDARD_FIELDS,
            FUTURES_RESULTS_STANDARD_FIELDS,
            OPTIONS_CHAIN_MATRIX_FIELDS,
            OPTIONS_STANDARD_FIELDS,
            OPTION_RESULTS_STANDARD_FIELDS,
            UNDERLYING_SUMMARY_FIELDS,
        )

        mapping = {
            FUTURES_DATASET: STANDARD_FIELDS,
            OPTIONS_DATASET: OPTIONS_STANDARD_FIELDS,
            DERIVATIVES_DATASET: DERIVATIVES_STANDARD_FIELDS,
            CONTRACTS_DATASET: CONTRACTS_STANDARD_FIELDS,
            OPTION_RESULTS_DATASET: OPTION_RESULTS_STANDARD_FIELDS,
            FUTURES_RESULTS_DATASET: FUTURES_RESULTS_STANDARD_FIELDS,
            OPTIONS_CHAIN_VIEW: OPTIONS_CHAIN_MATRIX_FIELDS,
            UNDERLYING_SUMMARY_VIEW: UNDERLYING_SUMMARY_FIELDS,
        }
        return mapping.get(dataset_name, STANDARD_FIELDS)

    def _requested_datasets(self, selection: Optional[CrawlSelection]) -> List[str]:
        instrument_group = selection.instrument_group if selection is not None else "futures"
        if instrument_group == "options":
            return [OPTIONS_DATASET, OPTION_RESULTS_DATASET, OPTIONS_CHAIN_VIEW]
        if instrument_group == "all":
            return [
                FUTURES_DATASET,
                OPTIONS_DATASET,
                CONTRACTS_DATASET,
                FUTURES_RESULTS_DATASET,
                OPTION_RESULTS_DATASET,
                DERIVATIVES_DATASET,
                OPTIONS_CHAIN_VIEW,
                UNDERLYING_SUMMARY_VIEW,
            ]
        return [FUTURES_DATASET, FUTURES_RESULTS_DATASET]

    def _required_datasets(self, requested_datasets: List[str]) -> List[str]:
        return list(requested_datasets)

    def _expected_exchanges_for_dataset(self, dataset_name: str, expected_primary: Dict[str, List[str]]) -> List[str]:
        if dataset_name in {FUTURES_DATASET, FUTURES_RESULTS_DATASET}:
            return list(expected_primary[FUTURES_DATASET])
        if dataset_name in {OPTIONS_DATASET, OPTION_RESULTS_DATASET, OPTIONS_CHAIN_VIEW, UNDERLYING_SUMMARY_VIEW}:
            return list(expected_primary[OPTIONS_DATASET])
        if dataset_name in {DERIVATIVES_DATASET, CONTRACTS_DATASET}:
            return sorted(set(expected_primary[FUTURES_DATASET]) | set(expected_primary[OPTIONS_DATASET]))
        return []

    def _selection_match_ok(self, dataset_name: str, rows: List[object], selection: Optional[CrawlSelection]) -> bool:
        if selection is None or not selection.has_row_filters:
            return True
        if dataset_name in {OPTION_RESULTS_DATASET, FUTURES_RESULTS_DATASET, OPTIONS_CHAIN_VIEW, UNDERLYING_SUMMARY_VIEW}:
            return True
        for row in rows:
            exchange = getattr(row, "exchange", "") if not isinstance(row, dict) else str(row.get("exchange", ""))
            if not exchange:
                continue
            if selection.filter_rows(exchange, [row]):
                continue
            return False
        return True

    def _resolve_checkpoint_store(
        self,
        selection: Optional[CrawlSelection],
        requested_datasets: List[str],
    ) -> Tuple[CheckpointStore, Optional[str], bool]:
        if selection is None or not selection.has_row_filters:
            return self.checkpoints, None, False
        selection_id = selection.selection_id(requested_datasets)
        return CheckpointStore(QUERY_STATE_DIR / f"{selection_id}.json"), selection_id, True

    def _fallback_expected_exchanges(self, checkpoint_day: Dict[str, object], dataset_name: str) -> List[str]:
        datasets = checkpoint_day.get("datasets", {})
        futures_expected = sorted(
            exchange
            for exchange, summary in datasets.get(FUTURES_DATASET, {}).get("exchanges", {}).items()
            if summary.get("status") != NOT_APPLICABLE_STATUS
        )
        options_expected = sorted(
            exchange
            for exchange, summary in datasets.get(OPTIONS_DATASET, {}).get("exchanges", {}).items()
            if summary.get("status") != NOT_APPLICABLE_STATUS
        )
        if dataset_name in {FUTURES_DATASET, FUTURES_RESULTS_DATASET}:
            return futures_expected
        if dataset_name in {OPTIONS_DATASET, OPTION_RESULTS_DATASET, OPTIONS_CHAIN_VIEW, UNDERLYING_SUMMARY_VIEW}:
            return options_expected
        if dataset_name in {DERIVATIVES_DATASET, CONTRACTS_DATASET}:
            return sorted(set(futures_expected) | set(options_expected))
        return []

    def _should_update_contracts_latest(self, selection: Optional[CrawlSelection], query_mode: bool) -> bool:
        return not query_mode and (selection is None or selection.instrument_group == "all")

    def _duplicate_key_count(self, dataset_name: str, rows: List[Dict[str, str]]) -> int:
        if dataset_name in {FUTURES_DATASET, OPTIONS_DATASET, DERIVATIVES_DATASET, CONTRACTS_DATASET, OPTION_RESULTS_DATASET, FUTURES_RESULTS_DATASET}:
            keys = [(row.get("trade_date", ""), row.get("exchange", ""), row.get("contract", ""), row.get("instrument_type", "")) for row in rows]
            return len(keys) - len(set(keys))
        if dataset_name == OPTIONS_CHAIN_VIEW:
            keys = [
                (
                    row.get("trade_date", ""),
                    row.get("exchange", ""),
                    row.get("underlying_contract", ""),
                    row.get("expire_date", ""),
                    row.get("strike_price", "") or row.get("call_contract", "") or row.get("put_contract", ""),
                )
                for row in rows
            ]
            return len(keys) - len(set(keys))
        if dataset_name == UNDERLYING_SUMMARY_VIEW:
            keys = [(row.get("trade_date", ""), row.get("exchange", ""), row.get("underlying_contract", "")) for row in rows]
            return len(keys) - len(set(keys))
        return 0

    def _validation_completeness_ok(
        self,
        *,
        dataset_name: str,
        dataset_state: Dict[str, object],
        observed_exchanges: List[str],
        expected_exchanges: List[str],
        row_count: int,
    ) -> bool:
        if dataset_state.get("status") == NO_DATA_STATUS:
            return True
        if dataset_name in {OPTION_RESULTS_DATASET, FUTURES_RESULTS_DATASET}:
            if "completeness_ok" in dataset_state:
                return bool(dataset_state.get("completeness_ok"))
            return set(observed_exchanges).issubset(set(expected_exchanges))
        if row_count == 0:
            return False
        return set(observed_exchanges) == set(expected_exchanges)

    def _build_result_dataset_state(
        self,
        *,
        dataset_name: str,
        expected_exchanges: List[str],
        observed_exchanges: List[str],
        row_count: int,
        selection_match_ok: bool,
        summaries: Dict[str, Dict[str, object]],
    ) -> Tuple[str, bool]:
        relevant_summaries = [summaries[exchange] for exchange in expected_exchanges if exchange in summaries]
        statuses = [str(summary.get("status", "")) for summary in relevant_summaries]
        has_pending = any(status in {ERROR_STATUS, PENDING_RETRY_STATUS} for status in statuses)
        has_blocked_no_data = any(self._result_summary_uses_unconfigured_endpoint(summary) for summary in relevant_summaries)

        if has_pending:
            status = PARTIAL_SUCCESS_STATUS if row_count > 0 else PENDING_RETRY_STATUS
            return status, False

        if has_blocked_no_data:
            status = PARTIAL_SUCCESS_STATUS if row_count > 0 else FAILED_STATUS
            return status, False

        if row_count > 0:
            allowed_statuses = {SUCCESS_STATUS, NO_DATA_STATUS, NOT_APPLICABLE_STATUS}
            completeness_ok = (
                selection_match_ok
                and set(observed_exchanges).issubset(set(expected_exchanges))
                and all(status in allowed_statuses for status in statuses)
            )
            return (SUCCESS_STATUS if completeness_ok else PARTIAL_SUCCESS_STATUS), completeness_ok

        if relevant_summaries and all(status == NOT_APPLICABLE_STATUS for status in statuses):
            return NOT_APPLICABLE_STATUS, bool(selection_match_ok)

        if relevant_summaries and all(status in {NO_DATA_STATUS, NOT_APPLICABLE_STATUS} for status in statuses):
            status = NO_DATA_STATUS if any(status == NO_DATA_STATUS for status in statuses) else NOT_APPLICABLE_STATUS
            return status, bool(selection_match_ok)

        if not expected_exchanges and not relevant_summaries:
            return NO_DATA_STATUS, bool(selection_match_ok)

        if not expected_exchanges and row_count == 0:
            return NO_DATA_STATUS, bool(selection_match_ok)

        return FAILED_STATUS, False

    def _default_no_data_reason(self, dataset_name: str, dataset_validation: Dict[str, object]) -> str:
        if dataset_name == OPTION_RESULTS_DATASET and not dataset_validation.get("expected_exchanges"):
            return "No option contracts expire or exercise on this trade date."
        if dataset_name == FUTURES_RESULTS_DATASET and not dataset_validation.get("expected_exchanges"):
            return "No futures delivery results are expected on this trade date."
        return ""

    def _dataset_reason(self, checkpoint_day: Dict[str, object], dataset_name: str, target_status: str) -> str:
        dataset_bucket = checkpoint_day.get("datasets", {}).get(dataset_name, {})
        exchanges = dataset_bucket.get("exchanges", {})
        messages: List[str] = []
        for summary in exchanges.values():
            if str(summary.get("status", "")) != target_status:
                continue
            message = str(summary.get("message", "")).strip() or str(summary.get("error", "")).strip()
            if message and message not in messages:
                messages.append(message)
        return " | ".join(messages)

    def _explained_unavailability_issue(
        self,
        checkpoint_day: Dict[str, object],
        dataset_name: str,
        dataset_validation: Dict[str, object],
    ) -> str:
        dataset_bucket = checkpoint_day.get("datasets", {}).get(dataset_name, {}).get("exchanges", {})
        expected = set(dataset_validation.get("expected_exchanges", []))
        observed = set(dataset_validation.get("observed_exchanges", []))
        missing = sorted(exchange for exchange in expected - observed if exchange)
        if not missing:
            return ""
        if dataset_name in {OPTION_RESULTS_DATASET, FUTURES_RESULTS_DATASET}:
            publication_lag_markers = (
                "not yet published",
                "returned an html error page instead of a pdf",
            )
            markers = (
                "no official delivery result endpoint configured",
                "no official exercise result endpoint configured",
                "official delivery result is not published",
                "official exercise result is not published",
                "monthly exercise report did not contain recognizable rows",
                "returned an html error page instead of a pdf",
            )
            publication_lag = True
            for exchange in missing:
                summary = dataset_bucket.get(exchange, {})
                if self._exchange_has_explained_unavailability(summary, publication_lag_markers):
                    continue
                publication_lag = False
                if self._exchange_has_explained_unavailability(summary, markers):
                    continue
                return ""
            exchanges_text = ", ".join(missing)
            if publication_lag:
                return f"{dataset_name}: missing exchanges [{exchanges_text}] are pending official publication"
            return f"{dataset_name}: missing exchanges [{exchanges_text}] are blocked by official result-chain source unavailability"
        markers = (
            "historical public contract source unavailable",
            "historical public option quotes unavailable",
            "no public historical contract source",
        )
        for exchange in missing:
            if self._exchange_has_explained_unavailability(dataset_bucket.get(exchange, {}), markers):
                continue
            if dataset_name in {DERIVATIVES_DATASET, CONTRACTS_DATASET, OPTIONS_CHAIN_VIEW, UNDERLYING_SUMMARY_VIEW}:
                option_bucket = checkpoint_day.get("datasets", {}).get(OPTIONS_DATASET, {}).get("exchanges", {})
                if self._exchange_has_explained_unavailability(option_bucket.get(exchange, {}), markers):
                    continue
            return ""
        exchanges_text = ", ".join(missing)
        return f"{dataset_name}: missing exchanges [{exchanges_text}] are blocked by public historical source unavailability"

    def _exchange_has_explained_unavailability(self, summary: Dict[str, object], markers: Tuple[str, ...]) -> bool:
        status = str(summary.get("status", ""))
        message = str(summary.get("message", "")).strip() or str(summary.get("error", "")).strip()
        if status not in {NO_DATA_STATUS, PENDING_RETRY_STATUS}:
            return False
        lowered = message.lower()
        return any(marker in lowered for marker in markers)

    def _master_data_completeness(self, dataset_name: str, rows: List[Dict[str, str]]) -> bool:
        if dataset_name != CONTRACTS_DATASET:
            return True
        if not rows:
            return False
        required_base = ("trade_date", "instrument_type", "exchange", "contract", "product_code", "product_name", "source_url", "source_type", "raw_path")
        for row in rows:
            if any(not str(row.get(field, "")).strip() for field in required_base):
                return False
            instrument_type = str(row.get("instrument_type", "")).strip()
            if instrument_type == "option":
                if not str(row.get("option_type", "")).strip():
                    return False
                if not str(row.get("underlying_contract", "")).strip():
                    return False
            if instrument_type == "future":
                if not str(row.get("underlying_contract", "")).strip():
                    return False
        return True

    def _result_chain_semantics_ok(
        self,
        *,
        dataset_name: str,
        dataset_state: Dict[str, object],
        row_count: int,
        no_data_reason: str,
        not_applicable_reason: str,
    ) -> bool:
        if dataset_name not in {OPTION_RESULTS_DATASET, FUTURES_RESULTS_DATASET}:
            return True
        status = str(dataset_state.get("status", ""))
        if row_count > 0:
            return status in {SUCCESS_STATUS, PARTIAL_SUCCESS_STATUS}
        if status == NO_DATA_STATUS:
            return bool(no_data_reason)
        if status == NOT_APPLICABLE_STATUS:
            return bool(not_applicable_reason)
        return False

    def _derive_validated_dataset_status(self, dataset_validation: Dict[str, object]) -> str:
        if not bool(dataset_validation.get("csv_exists")):
            if dataset_validation.get("status") in {NO_DATA_STATUS, NOT_APPLICABLE_STATUS, PENDING_RETRY_STATUS, FAILED_STATUS}:
                return str(dataset_validation.get("status", FAILED_STATUS))
            return FAILED_STATUS
        row_count = int(dataset_validation.get("row_count", 0) or 0)
        if row_count > 0:
            checks = [
                bool(dataset_validation.get("schema_ok")),
                int(dataset_validation.get("duplicate_keys", 0) or 0) == 0,
                not list(dataset_validation.get("missing_raw_paths", [])),
                bool(dataset_validation.get("source_provenance_ok")),
                bool(dataset_validation.get("completeness_ok")),
                bool(dataset_validation.get("selection_match_ok", True)),
                bool(dataset_validation.get("master_data_completeness", True)),
                bool(dataset_validation.get("result_chain_semantics_ok", True)),
            ]
            return SUCCESS_STATUS if all(checks) else PARTIAL_SUCCESS_STATUS
        if dataset_validation.get("status") == NOT_APPLICABLE_STATUS or dataset_validation.get("not_applicable_reason"):
            return NOT_APPLICABLE_STATUS
        if dataset_validation.get("status") == PENDING_RETRY_STATUS:
            return PENDING_RETRY_STATUS
        if dataset_validation.get("status") == PARTIAL_SUCCESS_STATUS:
            return PARTIAL_SUCCESS_STATUS
        if dataset_validation.get("status") == NO_DATA_STATUS or dataset_validation.get("no_data_reason"):
            return NO_DATA_STATUS
        return FAILED_STATUS

    def _aggregate_validation_status(self, dataset_validations: Dict[str, Dict[str, object]]) -> str:
        if not dataset_validations:
            return NO_DATA_STATUS
        statuses = [str(item.get("status", "")) for item in dataset_validations.values()]
        if any(status in {FAILED_STATUS, PENDING_RETRY_STATUS, PARTIAL_SUCCESS_STATUS, ERROR_STATUS} for status in statuses):
            return PARTIAL_SUCCESS_STATUS
        if any(status == SUCCESS_STATUS for status in statuses):
            return SUCCESS_STATUS
        if statuses and all(status == NOT_APPLICABLE_STATUS for status in statuses):
            return NOT_APPLICABLE_STATUS
        if statuses and all(status in {NO_DATA_STATUS, NOT_APPLICABLE_STATUS} for status in statuses):
            return NO_DATA_STATUS if any(status == NO_DATA_STATUS for status in statuses) else NOT_APPLICABLE_STATUS
        return PARTIAL_SUCCESS_STATUS

    def _result_summary_uses_unconfigured_endpoint(self, summary: Dict[str, object]) -> bool:
        if str(summary.get("status", "")) != NO_DATA_STATUS:
            return False
        message = str(summary.get("message", "")).strip() or str(summary.get("error", "")).strip()
        lowered = message.lower()
        return "no official" in lowered and "endpoint configured" in lowered

    def _validate_contracts_latest(self, trade_date_str: str, outputs: Dict[str, str]) -> Dict[str, object]:
        latest_path = PROJECT_ROOT / "data" / "normalized" / "master" / "contracts_latest.csv"
        source_trade_date = self._latest_contracts_source_trade_date()
        snapshot_relative = ""
        snapshot_path = None
        if source_trade_date:
            snapshot_relative = self.checkpoints.get_day(source_trade_date).get("outputs", {}).get(CONTRACTS_DATASET, "")
            snapshot_path = PROJECT_ROOT / snapshot_relative if snapshot_relative else None
        latest_validation = {
            "csv_exists": latest_path.exists(),
            "schema_ok": False,
            "row_count": 0,
            "source_trade_date": source_trade_date or "",
            "matches_source_snapshot": False,
            "current_trade_date_is_latest_source": bool(source_trade_date and source_trade_date == trade_date_str),
        }
        if not latest_path.exists():
            return latest_validation
        latest_rows = list(iter_csv_rows(latest_path))
        latest_validation["row_count"] = len(latest_rows)
        latest_validation["schema_ok"] = list(latest_rows[0].keys()) == self._expected_fields(CONTRACTS_DATASET) if latest_rows else True
        if snapshot_path and snapshot_path.exists():
            snapshot_rows = list(iter_csv_rows(snapshot_path))
            latest_validation["matches_source_snapshot"] = latest_rows == snapshot_rows
        return latest_validation

    def _latest_contracts_source_trade_date(self) -> Optional[str]:
        for trade_date in sorted(self.checkpoints.data.get("dates", {}), reverse=True):
            day = self.checkpoints.data["dates"][trade_date]
            if day.get("status") != SUCCESS_STATUS:
                continue
            if CONTRACTS_DATASET not in day.get("outputs", {}):
                continue
            selection = day.get("selection", {})
            if selection and selection.get("instrument_group") != "all":
                continue
            return trade_date
        return None

    def _update_contracts_latest_if_needed(
        self,
        *,
        trade_date_str: str,
        status: str,
        selection: Optional[CrawlSelection],
        query_mode: bool,
        outputs: Dict[str, str],
        dataset_rows: Dict[str, List[object]],
    ) -> None:
        if status != SUCCESS_STATUS:
            return
        if not self._should_update_contracts_latest(selection, query_mode):
            return
        if CONTRACTS_DATASET not in outputs:
            return
        latest_source_trade_date = self._latest_contracts_source_trade_date()
        if latest_source_trade_date and trade_date_str < latest_source_trade_date:
            return
        contract_rows = dataset_rows.get(CONTRACTS_DATASET, [])
        if not contract_rows:
            return
        snapshot_relative = outputs.get(CONTRACTS_DATASET, "")
        snapshot_path = PROJECT_ROOT / snapshot_relative if snapshot_relative else None
        write_contracts_latest(contract_rows, snapshot_path=snapshot_path if snapshot_path and snapshot_path.exists() else None)

    def _filter_dict_rows(self, rows: List[Dict[str, str]], selection: CrawlSelection) -> List[Dict[str, str]]:
        by_exchange: Dict[str, List[Dict[str, str]]] = {}
        for row in rows:
            exchange = str(row.get("exchange", "")).upper()
            by_exchange.setdefault(exchange, []).append(row)
        filtered: List[Dict[str, str]] = []
        for exchange, exchange_rows in by_exchange.items():
            filtered.extend(selection.filter_rows(exchange, exchange_rows))
        return filtered

    def _summary_to_result(self, summary: Dict[str, object]) -> SourceRunResult:
        raw_path_value = str(summary.get("raw_path", "")).strip()
        return SourceRunResult(
            exchange=str(summary.get("exchange", "")),
            trade_date=str(summary.get("trade_date", "")),
            status=str(summary.get("status", "")),
            dataset=str(summary.get("dataset", FUTURES_RESULTS_DATASET)),
            source_url=str(summary.get("source_url", "")),
            source_type=str(summary.get("source_type", "official")),
            raw_path=Path(raw_path_value) if raw_path_value else None,
            row_count=int(summary.get("row_count", 0) or 0),
            message=str(summary.get("message", "")),
            error=str(summary.get("error", "")),
        )

    def _existing_canonical_dates(self) -> List[str]:
        dates = set()
        patterns = [
            PROJECT_ROOT / "data" / "normalized" / "daily_quotes" / "*.csv",
            PROJECT_ROOT / "data" / "normalized" / "options" / "daily_quotes" / "*.csv",
            PROJECT_ROOT / "data" / "normalized" / "derivatives" / "daily_quotes" / "*.csv",
        ]
        for pattern in patterns:
            for path in pattern.parent.glob(pattern.name):
                dates.add(path.stem)
        return sorted(dates)

    def existing_canonical_dates(self) -> List[str]:
        return list(self._existing_canonical_dates())

    def _rebuild_canonical_from_raw(self, trade_date_value: str) -> None:
        trade_date = parse_trade_date(trade_date_value)
        trade_date_str = format_trade_date(trade_date)
        day = self.checkpoints.get_day(trade_date_str)
        if not day:
            return

        futures_rows = self._rows_from_checkpoint_raw(day, trade_date, FUTURES_DATASET, self.sources)
        options_rows = self._rows_from_checkpoint_raw(day, trade_date, OPTIONS_DATASET, self.option_sources)
        delivery_rows, delivery_summaries = self._rows_from_checkpoint_result_raw(
            day,
            trade_date,
            FUTURES_RESULTS_DATASET,
            futures_rows=futures_rows,
            option_rows=options_rows,
        )
        option_result_rows, option_result_summaries = self._rows_from_checkpoint_result_raw(
            day,
            trade_date,
            OPTION_RESULTS_DATASET,
            futures_rows=futures_rows,
            option_rows=options_rows,
        )
        master_metadata = self.master_data_collector.collect(
            trade_date,
            futures_rows=futures_rows,
            options_rows=options_rows,
        )
        dataset_rows = build_platform_rows(
            futures_rows=futures_rows,
            options_rows=options_rows,
            option_result_rows=option_result_rows,
            futures_result_rows=delivery_rows,
            master_metadata=master_metadata,
        )

        requested_datasets = self._requested_datasets(self._selection_for_day(day))
        outputs, row_counts = write_platform_outputs(
            trade_date=trade_date_str,
            dataset_rows=dataset_rows,
            include_datasets=requested_datasets,
            update_contracts_latest=False,
        )
        source_results = self._recover_primary_results(day, trade_date)
        for result in source_results:
            self.checkpoints.update_exchange_result(result)
        for summary in delivery_summaries.values():
            self.checkpoints.update_exchange_result(self._summary_to_result(summary))
        for summary in option_result_summaries.values():
            self.checkpoints.update_exchange_result(self._summary_to_result(summary))
        dataset_states = self._build_dataset_states(
            selection=self._selection_for_day(day),
            requested_datasets=requested_datasets,
            source_results=source_results,
            dataset_rows=dataset_rows,
            delivery_summaries=delivery_summaries,
            option_result_summaries=option_result_summaries,
        )
        for dataset_name, state in dataset_states.items():
            self.checkpoints.update_dataset_state(
                trade_date_str,
                dataset_name,
                status=str(state["status"]),
                expected_exchanges=list(state["expected_exchanges"]),
                observed_exchanges=list(state["observed_exchanges"]),
                completeness_ok=bool(state["completeness_ok"]),
                selection_match_ok=bool(state["selection_match_ok"]),
            )
        status = self._aggregate_status(source_results, dataset_states, requested_datasets)
        self._update_contracts_latest_if_needed(
            trade_date_str=trade_date_str,
            status=status,
            selection=self._selection_for_day(day),
            query_mode=False,
            outputs=outputs,
            dataset_rows=dataset_rows,
        )
        self.checkpoints.finalize_day(trade_date_str, status=status, outputs=outputs, row_counts=row_counts, selection=day.get("selection", {}))
        self.checkpoints.save()

    def _rows_from_checkpoint_raw(self, day: Dict[str, object], trade_date: date, dataset_name: str, sources: List[object]) -> List[object]:
        dataset_state = day.get("datasets", {}).get(dataset_name, {})
        dataset_bucket = dataset_state.get("exchanges", {})
        source_lookup = {source.exchange: source for source in sources}
        rows: List[object] = []
        for exchange in self._dataset_exchange_names(dataset_state):
            source = source_lookup.get(exchange)
            if source is None:
                continue
            summary = dataset_bucket.get(exchange, {})
            cached = self._load_cached_raw_payload(
                exchange=exchange,
                trade_date=trade_date,
                dataset_name=dataset_name,
                raw_path_value=str(summary.get("raw_path", "")),
                source_url=str(summary.get("source_url", "")),
                source_type=str(summary.get("source_type", "official")),
            )
            if cached is None:
                continue
            raw_path, payload = cached
            rows.extend(source.parse_raw(trade_date, payload, raw_path))
        return rows

    def _stored_primary_results(self, day: Dict[str, object]) -> List[SourceRunResult]:
        results: List[SourceRunResult] = []
        for dataset_name in (FUTURES_DATASET, OPTIONS_DATASET):
            exchanges = day.get("datasets", {}).get(dataset_name, {}).get("exchanges", {})
            for summary in exchanges.values():
                results.append(self._summary_to_result(summary))
        return results

    def _recover_primary_results(self, day: Dict[str, object], trade_date: date) -> List[SourceRunResult]:
        recovered: List[SourceRunResult] = []
        dataset_to_rows = {
            FUTURES_DATASET: self._rows_from_checkpoint_raw(day, trade_date, FUTURES_DATASET, self.sources),
            OPTIONS_DATASET: self._rows_from_checkpoint_raw(day, trade_date, OPTIONS_DATASET, self.option_sources),
        }
        source_lookup = {
            FUTURES_DATASET: {source.exchange: source for source in self.sources},
            OPTIONS_DATASET: {source.exchange: source for source in self.option_sources},
        }
        for dataset_name, rows in dataset_to_rows.items():
            dataset_state = day.get("datasets", {}).get(dataset_name, {})
            dataset_bucket = dataset_state.get("exchanges", {})
            rows_by_exchange: Dict[str, List[object]] = {}
            for row in rows:
                exchange = getattr(row, "exchange", "")
                rows_by_exchange.setdefault(exchange, []).append(row)
            for exchange in self._dataset_exchange_names(dataset_state):
                summary = dataset_bucket.get(exchange, {})
                exchange_rows = rows_by_exchange.get(exchange, [])
                if exchange_rows:
                    first_row = exchange_rows[0]
                    raw_path_value = str(getattr(first_row, "raw_path", summary.get("raw_path", ""))).strip()
                    recovered.append(
                        SourceRunResult(
                            exchange=exchange,
                            trade_date=format_trade_date(trade_date),
                            dataset=dataset_name,
                            status=SUCCESS_STATUS,
                            source_url=str(getattr(first_row, "source_url", summary.get("source_url", ""))),
                            source_type=str(getattr(first_row, "source_type", summary.get("source_type", "official"))),
                            raw_path=Path(raw_path_value) if raw_path_value else None,
                            row_count=len(exchange_rows),
                            rows=list(exchange_rows),
                            message="",
                            error="",
                        )
                    )
                    continue
                probe_source = source_lookup.get(dataset_name, {}).get(exchange)
                if summary and probe_source is not None and str(summary.get("status", "")) != SUCCESS_STATUS:
                    probe_result = probe_source.run(trade_date)
                    if probe_result.status != SUCCESS_STATUS:
                        recovered.append(probe_result)
                        continue
                if summary:
                    recovered.append(self._summary_to_result(summary))
        return recovered

    def _rows_from_checkpoint_result_raw(
        self,
        day: Dict[str, object],
        trade_date: date,
        dataset_name: str,
        *,
        futures_rows: Optional[List[object]] = None,
        option_rows: Optional[List[object]] = None,
    ) -> Tuple[List[Dict[str, str]], Dict[str, Dict[str, object]]]:
        dataset_bucket = day.get("datasets", {}).get(dataset_name, {}).get("exchanges", {})
        rows: List[Dict[str, str]] = []
        summaries: Dict[str, Dict[str, object]] = {}
        dataset_state = day.get("datasets", {}).get(dataset_name, {})
        for exchange in self._dataset_exchange_names(dataset_state):
            summary = dataset_bucket.get(exchange, {})
            copied = dict(summary)
            summaries[exchange] = copied
            cached = self._load_cached_raw_payload(
                exchange=exchange,
                trade_date=trade_date,
                dataset_name=dataset_name,
                raw_path_value=str(copied.get("raw_path", "")),
                source_url=str(copied.get("source_url", "")),
                source_type=str(copied.get("source_type", "official")),
            )
            if cached is None:
                refreshed_summary = self._recover_result_summary_without_raw(
                    dataset_name=dataset_name,
                    exchange=exchange,
                    trade_date=trade_date,
                    summary=copied,
                    futures_rows=futures_rows or [],
                    option_rows=option_rows or [],
                )
                if refreshed_summary is not None:
                    summaries[exchange] = refreshed_summary
                continue
            raw_path, payload = cached
            raw_text = payload.content
            relative_raw = relative_to_project(raw_path, PROJECT_ROOT)
            if dataset_name == FUTURES_RESULTS_DATASET:
                parsed_rows = self._parse_delivery_rows_from_checkpoint_raw(
                    exchange=exchange,
                    raw_text=raw_text,
                    trade_date=trade_date,
                    raw_path=relative_raw,
                    source_url=payload.url,
                    source_type=payload.source_type,
                )
            else:
                parsed_rows = (
                    _parse_exercise_payload(
                        exchange=exchange,
                        raw_text=raw_text,
                        trade_date=trade_date,
                        raw_path=relative_raw,
                        source_url=payload.url,
                        source_type=payload.source_type,
                    )
                )
            if parsed_rows:
                copied.update(
                    {
                        "status": SUCCESS_STATUS,
                        "source_url": payload.url,
                        "source_type": payload.source_type,
                        "raw_path": str(raw_path),
                        "row_count": len(parsed_rows),
                        "message": "",
                        "error": "",
                    }
                )
                summaries[exchange] = copied
                rows.extend(parsed_rows)
        return rows, summaries

    def _recover_result_summary_without_raw(
        self,
        *,
        dataset_name: str,
        exchange: str,
        trade_date: date,
        summary: Dict[str, object],
        futures_rows: List[object],
        option_rows: List[object],
    ) -> Optional[Dict[str, object]]:
        if dataset_name == FUTURES_RESULTS_DATASET:
            local_summary = self.delivery_collector.summarize_without_fetch(
                exchange,
                trade_date,
                futures_rows=futures_rows,
            )
        else:
            local_summary = self.exercise_collector.summarize_without_fetch(
                exchange,
                trade_date,
                option_rows=option_rows,
            )
        if local_summary is None:
            return None
        refreshed = dict(summary)
        refreshed.update(
            {
                "dataset": dataset_name,
                "exchange": exchange,
                "trade_date": format_trade_date(trade_date),
                "status": local_summary.get("status", refreshed.get("status", "")),
                "source_url": local_summary.get("source_url", refreshed.get("source_url", "")),
                "source_type": local_summary.get("source_type", refreshed.get("source_type", "official")),
                "raw_path": str(local_summary.get("raw_path", refreshed.get("raw_path", "")) or ""),
                "row_count": int(local_summary.get("row_count", refreshed.get("row_count", 0)) or 0),
                "message": str(local_summary.get("message", refreshed.get("message", ""))),
                "error": str(local_summary.get("error", refreshed.get("error", ""))),
            }
        )
        return refreshed

    def _dataset_exchange_names(self, dataset_state: Dict[str, object]) -> List[str]:
        dataset_bucket = dataset_state.get("exchanges", {})
        names = set(dataset_bucket.keys())
        names.update(dataset_state.get("expected_exchanges", []))
        return sorted(name for name in names if name)

    def _load_cached_raw_payload(
        self,
        *,
        exchange: str,
        trade_date: date,
        dataset_name: str,
        raw_path_value: str,
        source_url: str,
        source_type: str,
    ) -> Optional[Tuple[Path, RawPayload]]:
        candidate_paths: List[Path] = []
        if raw_path_value:
            candidate_paths.append(Path(raw_path_value))
        raw_root = PROJECT_ROOT / "data" / "raw"
        cache_dir = raw_root / exchange.lower() / self._raw_subdir_for_dataset(dataset_name)
        compact = trade_date.strftime("%Y%m%d")
        if cache_dir.exists():
            candidate_paths.extend(sorted(path for path in cache_dir.glob(f"{compact}.*") if not path.name.endswith(".meta.json")))
        seen: set[str] = set()
        for raw_path in candidate_paths:
            raw_path = raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
            raw_key = str(raw_path)
            if raw_key in seen or not raw_path.exists():
                continue
            seen.add(raw_key)
            meta = self._load_raw_meta(raw_path)
            extension = str(meta.get("extension") or raw_path.suffix.lstrip("."))
            if extension.lower() == "pdf":
                content = raw_path.read_bytes().decode("latin1")
            else:
                content = decode_bytes(raw_path.read_bytes())
            resolved_url = str(meta.get("source_url") or source_url)
            if dataset_name == OPTION_RESULTS_DATASET and exchange == "CFFEX" and extension.lower() == "pdf":
                monthly_template = str(self.settings.get("exchanges", {}).get("CFFEX", {}).get("monthly_exercise_report_url", "")).strip()
                if monthly_template:
                    resolved_url = monthly_template.format(
                        trade_date=compact_trade_date(trade_date),
                        year=trade_date.year,
                        month=f"{trade_date.month:02d}",
                        day=f"{trade_date.day:02d}",
                        year_month=f"{trade_date.year}{trade_date.month:02d}",
                    )
            payload = RawPayload(
                content=content,
                url=resolved_url,
                extension=extension,
                source_type=str(meta.get("source_type") or source_type),
                meta=dict(meta.get("meta", {})),
            )
            return raw_path, payload
        return None

    def _load_raw_meta(self, raw_path: Path) -> Dict[str, object]:
        meta_path = raw_path.with_name(f"{raw_path.stem}.meta.json")
        if not meta_path.exists():
            return {}
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _raw_subdir_for_dataset(self, dataset_name: str) -> str:
        mapping = {
            FUTURES_DATASET: "daily_quotes",
            OPTIONS_DATASET: OPTIONS_DATASET,
            FUTURES_RESULTS_DATASET: FUTURES_RESULTS_DATASET,
            OPTION_RESULTS_DATASET: OPTION_RESULTS_DATASET,
        }
        return mapping.get(dataset_name, dataset_name)

    def _parse_delivery_rows_from_checkpoint_raw(
        self,
        *,
        exchange: str,
        raw_text: str,
        trade_date: date,
        raw_path: str,
        source_url: str,
        source_type: str,
    ) -> List[Dict[str, str]]:
        payload = None
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError:
            payload = None

        rows: List[Dict[str, str]] = []
        if isinstance(payload, dict):
            if exchange == "SHFE" and "delivery_params" in payload and "monthly_delivery_results" in payload:
                rows = _build_shfe_delivery_rows(
                    trade_date=trade_date,
                    daily_payload=payload.get("delivery_params", {}),
                    monthly_payload=payload.get("monthly_delivery_results", {}),
                    raw_path=raw_path,
                    source_url=source_url,
                    source_type=source_type,
                )
            elif exchange == "GFEX" and "response_payload" in payload:
                rows = _build_gfex_delivery_rows(
                    trade_date=trade_date,
                    payload=payload.get("response_payload", {}),
                    raw_path=raw_path,
                    source_url=source_url,
                    source_type=source_type,
                )
            if rows:
                for row in rows:
                    row["raw_path"] = raw_path
                return rows

        return _parse_delivery_payload(
            exchange=exchange,
            raw_text=raw_text,
            trade_date=trade_date,
            raw_path=raw_path,
            source_url=source_url,
            source_type=source_type,
        )

    def _selection_for_day(self, day: Dict[str, object]) -> Optional[CrawlSelection]:
        selection_summary = day.get("selection", {})
        if not selection_summary:
            instrument_group = "all" if day.get("datasets", {}).get(OPTIONS_DATASET, {}).get("exchanges") else "futures"
            return CrawlSelection(instrument_group=instrument_group)
        return CrawlSelection(
            instrument_group=str(selection_summary.get("instrument_group", "futures")),
            exchanges=list(selection_summary.get("exchanges", [])),
            varieties_by_exchange={key: set(value) for key, value in selection_summary.get("varieties", {}).items()},
            underlyings_by_exchange={key: set(value) for key, value in selection_summary.get("underlyings", {}).items()},
            contracts_by_exchange={key: set(value) for key, value in selection_summary.get("contracts", {}).items()},
        )
