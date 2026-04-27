import time
from collections import Counter
from typing import Dict, Iterable, List, Optional, Tuple

from .constants import (
    FAILED_STATUS,
    FUTURES_RESULTS_DATASET,
    NO_DATA_STATUS,
    NOT_APPLICABLE_STATUS,
    OPTION_RESULTS_DATASET,
    PARTIAL_SUCCESS_STATUS,
    PENDING_RETRY_STATUS,
    SUCCESS_STATUS,
)
from .pregrab_state import append_pregrab_run
from .selection import CrawlSelection
from .utils import iso_timestamp, parse_trade_date
from .workflow import WorkflowRunner

EXTERNAL_PREGRAB_ISSUE_CATEGORIES = {
    "result_chain_publication_lag",
    "result_chain_source_gap",
    "historical_public_contract_gap",
    "blocked_public_source_gap",
}
_EXTERNAL_RESULT_DATASETS = {OPTION_RESULTS_DATASET, FUTURES_RESULTS_DATASET}
_PUBLICATION_LAG_MARKERS = (
    "returned an html error page instead of a pdf",
    "pending official publication",
    "not yet published",
    "publication lag",
)
_RESULT_SOURCE_GAP_MARKERS = (
    "source unavailability",
    "no official",
    "endpoint configured",
)
_HISTORICAL_GAP_MARKERS = (
    "historical public contract source unavailable",
    "historical public option quotes unavailable",
    "no public historical contract source",
)


class PregrabRunner:
    def __init__(self, *, workflow_runner: Optional[WorkflowRunner] = None, state_writer=append_pregrab_run):
        self.runner = workflow_runner or WorkflowRunner()
        self.state_writer = state_writer

    def run_window(
        self,
        *,
        exchanges: Iterable[str],
        start_date: str,
        end_date: str,
        mode: str = "production",
        persist: bool = True,
    ) -> Dict[str, object]:
        normalized_exchanges = [str(value).strip().upper() for value in exchanges if str(value).strip()]
        if not normalized_exchanges:
            raise ValueError("pregrab window requires at least one exchange")
        start = parse_trade_date(start_date)
        end = parse_trade_date(end_date)
        candidate_dates = [item.isoformat() for item in self.runner.calendar.candidate_dates("all", start, end)]
        started_at = time.monotonic()
        exchange_results: Dict[str, Dict[str, object]] = {}
        aggregated_categories: Counter[str] = Counter()
        aggregated_blocked_issues: List[str] = []
        day_counts: Counter[str] = Counter()

        for exchange in normalized_exchanges:
            summary = self._run_exchange_window(exchange=exchange, trade_dates=candidate_dates)
            exchange_results[exchange] = summary
            aggregated_categories.update(summary.get("issue_category_counts", {}) or {})
            aggregated_blocked_issues.extend(str(item) for item in (summary.get("blocked_issues", []) or []))
            day_counts.update({
                "success": int(summary.get("success_count", 0) or 0),
                "no_data": int(summary.get("no_data_count", 0) or 0),
                "not_applicable": int(summary.get("not_applicable_count", 0) or 0),
                "blocked_issue": int(summary.get("blocked_external_count", 0) or 0),
                "failed": int(summary.get("failed_count", 0) or 0),
            })

        statuses = [str((payload or {}).get("status", "") or "") for payload in exchange_results.values()]
        engineering_statuses = [str((payload or {}).get("engineering_status", "") or "") for payload in exchange_results.values()]
        result = {
            "run_id": f"pregrab-{int(time.time())}",
            "mode": mode,
            "exchanges": normalized_exchanges,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "status": _merge_statuses(statuses),
            "engineering_status": _merge_engineering_statuses(engineering_statuses),
            "elapsed_seconds": round(time.monotonic() - started_at, 3),
            "date_counts": dict(day_counts),
            "issue_category_counts": dict(aggregated_categories),
            "blocked_issues": aggregated_blocked_issues,
            "exchange_results": exchange_results,
            "cleanup_status": "retained" if mode == "production" else "pending_cleanup",
            "updated_at": iso_timestamp(),
        }
        if persist and self.state_writer:
            self.state_writer(result)
        return result

    def _run_exchange_window(self, *, exchange: str, trade_dates: List[str]) -> Dict[str, object]:
        selection = CrawlSelection(instrument_group="all", exchanges=[exchange])
        started_at = time.monotonic()
        daily_results: List[Dict[str, object]] = []
        category_counts: Counter[str] = Counter()
        blocked_issues: List[str] = []
        blocked_days: List[str] = []
        failed_days: List[str] = []
        counts: Counter[str] = Counter()

        for trade_date in trade_dates:
            fetch_result = self.runner.fetch_date(trade_date, selection=selection)
            validation = self.runner.validate(trade_date, selection=selection)
            day_summary = self._summarize_day(exchange=exchange, trade_date=trade_date, fetch_result=fetch_result, validation=validation)
            daily_results.append(day_summary)
            counts.update([str(day_summary.get("status", ""))])
            category_counts.update(day_summary.get("issue_category_counts", {}) or {})
            blocked_issues.extend(str(item) for item in (day_summary.get("blocked_issues", []) or []))
            if day_summary.get("status") == "blocked_issue":
                blocked_days.append(trade_date)
            if day_summary.get("status") == FAILED_STATUS:
                failed_days.append(trade_date)

        failed_count = int(counts.get(FAILED_STATUS, 0) or 0)
        blocked_external_count = int(counts.get("blocked_issue", 0) or 0)
        status = SUCCESS_STATUS
        if failed_count:
            status = FAILED_STATUS
        elif blocked_external_count:
            status = PARTIAL_SUCCESS_STATUS
        engineering_status = SUCCESS_STATUS if failed_count == 0 else "partial"
        return {
            "exchange": exchange,
            "status": status,
            "engineering_status": engineering_status,
            "elapsed_seconds": round(time.monotonic() - started_at, 3),
            "day_count": len(trade_dates),
            "success_count": int(counts.get(SUCCESS_STATUS, 0) or 0),
            "no_data_count": int(counts.get(NO_DATA_STATUS, 0) or 0),
            "not_applicable_count": int(counts.get(NOT_APPLICABLE_STATUS, 0) or 0),
            "blocked_external_count": blocked_external_count,
            "failed_count": failed_count,
            "passed": failed_count == 0 and blocked_external_count == 0,
            "engineering_passed": failed_count == 0,
            "issue_category_counts": dict(category_counts),
            "blocked_issues": blocked_issues,
            "blocked_days": blocked_days,
            "failed_days": failed_days,
            "daily_results": daily_results,
        }

    def _summarize_day(self, *, exchange: str, trade_date: str, fetch_result: Dict[str, object], validation: Dict[str, object]) -> Dict[str, object]:
        validation_status = str(validation.get("checkpoint_status", "") or "")
        if validation_status == SUCCESS_STATUS:
            return self._base_day_summary(trade_date=trade_date, status=SUCCESS_STATUS, fetch_status=str(fetch_result.get("status", "") or ""), validation_status=validation_status)
        if validation_status == NO_DATA_STATUS:
            return self._base_day_summary(trade_date=trade_date, status=NO_DATA_STATUS, fetch_status=str(fetch_result.get("status", "") or ""), validation_status=validation_status)
        if validation_status == NOT_APPLICABLE_STATUS:
            return self._base_day_summary(trade_date=trade_date, status=NOT_APPLICABLE_STATUS, fetch_status=str(fetch_result.get("status", "") or ""), validation_status=validation_status)

        problematic_datasets = [
            dataset_name
            for dataset_name, payload in (validation.get("datasets", {}) or {}).items()
            if str((payload or {}).get("status", "") or "") not in {SUCCESS_STATUS, NO_DATA_STATUS, NOT_APPLICABLE_STATUS}
        ]
        issue_categories = Counter()
        blocked_issues: List[str] = []

        external_issue = self._summarize_external_blocked_issue(exchange=exchange, fetch_result=fetch_result, problematic_datasets=problematic_datasets)
        if external_issue and not self._has_material_validation_failure(validation, allowed_external_datasets=set(problematic_datasets)):
            issue_categories.update([external_issue[0]])
            blocked_issues.append(external_issue[1])
            return self._base_day_summary(
                trade_date=trade_date,
                status="blocked_issue",
                fetch_status=str(fetch_result.get("status", "") or ""),
                validation_status=validation_status,
                issue_category_counts=dict(issue_categories),
                blocked_issues=blocked_issues,
            )

        issue_categories.update(self._infer_internal_issue_categories(fetch_result, validation))
        return self._base_day_summary(
            trade_date=trade_date,
            status=FAILED_STATUS,
            fetch_status=str(fetch_result.get("status", "") or ""),
            validation_status=validation_status,
            issue_category_counts=dict(issue_categories) or {"coverage_gap": 1},
            blocked_issues=blocked_issues,
        )

    def _base_day_summary(self, *, trade_date: str, status: str, fetch_status: str, validation_status: str, issue_category_counts: Optional[Dict[str, int]] = None, blocked_issues: Optional[List[str]] = None) -> Dict[str, object]:
        return {
            "trade_date": trade_date,
            "status": status,
            "fetch_status": fetch_status,
            "validation_status": validation_status,
            "issue_category_counts": dict(issue_category_counts or {}),
            "blocked_issues": list(blocked_issues or []),
        }

    def _summarize_external_blocked_issue(self, *, exchange: str, fetch_result: Dict[str, object], problematic_datasets: List[str]) -> Optional[Tuple[str, str]]:
        if not problematic_datasets or not set(problematic_datasets).issubset(_EXTERNAL_RESULT_DATASETS):
            return None
        exchange_summaries = fetch_result.get("exchange_summaries", {}) or {}
        for dataset_name in problematic_datasets:
            summary = ((exchange_summaries.get(dataset_name, {}) or {}).get(exchange, {}) or {})
            message = self._summary_message(summary)
            lowered = message.lower()
            if any(marker in lowered for marker in _PUBLICATION_LAG_MARKERS):
                return (
                    "result_chain_publication_lag",
                    f"{dataset_name}: {exchange} official result is pending publication on this trade date",
                )
            if any(marker in lowered for marker in _RESULT_SOURCE_GAP_MARKERS):
                return (
                    "result_chain_source_gap",
                    f"{dataset_name}: {exchange} official result-chain source remains unavailable on this trade date",
                )
        return None

    def _infer_internal_issue_categories(self, fetch_result: Dict[str, object], validation: Dict[str, object]) -> Counter:
        categories: Counter[str] = Counter()
        exchange_summaries = fetch_result.get("exchange_summaries", {}) or {}
        for dataset_bucket in exchange_summaries.values():
            for summary in (dataset_bucket or {}).values():
                lowered = self._summary_message(summary).lower()
                if any(marker in lowered for marker in _HISTORICAL_GAP_MARKERS):
                    categories.update(["historical_public_contract_gap"])
        for payload in (validation.get("datasets", {}) or {}).values():
            dataset = payload or {}
            if not bool(dataset.get("csv_exists", False)) and str(dataset.get("status", "")) not in {NO_DATA_STATUS, NOT_APPLICABLE_STATUS, PENDING_RETRY_STATUS}:
                categories.update(["missing_csv"])
            if bool(dataset.get("csv_exists", False)) and not bool(dataset.get("schema_ok", False)):
                categories.update(["schema_mismatch"])
            if not bool(dataset.get("completeness_ok", True)):
                categories.update(["coverage_gap"])
            if int(dataset.get("duplicate_keys", 0) or 0) > 0:
                categories.update(["schema_mismatch"])
            if list(dataset.get("missing_raw_paths", []) or []):
                categories.update(["missing_csv"])
            if not bool(dataset.get("result_chain_semantics_ok", True)):
                categories.update(["coverage_gap"])
            if not bool(dataset.get("master_data_completeness", True)):
                categories.update(["coverage_gap"])
            if not bool(dataset.get("selection_match_ok", True)):
                categories.update(["coverage_gap"])
        return categories

    def _has_material_validation_failure(
        self,
        validation: Dict[str, object],
        *,
        allowed_external_datasets: Optional[set[str]] = None,
    ) -> bool:
        allowed_external_datasets = set(allowed_external_datasets or set())
        for dataset_name, payload in (validation.get("datasets", {}) or {}).items():
            dataset = payload or {}
            status = str(dataset.get("status", "") or "")
            if status in {SUCCESS_STATUS, NO_DATA_STATUS, NOT_APPLICABLE_STATUS}:
                continue
            if bool(dataset.get("csv_exists", False)) and not bool(dataset.get("schema_ok", False)):
                return True
            if int(dataset.get("duplicate_keys", 0) or 0) > 0:
                return True
            if list(dataset.get("missing_raw_paths", []) or []):
                return True
            if not bool(dataset.get("selection_match_ok", True)):
                return True
            if str(dataset_name) in allowed_external_datasets:
                continue
            if not bool(dataset.get("completeness_ok", True)):
                return True
            if not bool(dataset.get("result_chain_semantics_ok", True)):
                return True
            if not bool(dataset.get("master_data_completeness", True)):
                return True
        return False

    @staticmethod
    def _summary_message(summary: Dict[str, object]) -> str:
        return str(summary.get("message", "")).strip() or str(summary.get("error", "")).strip()


def _merge_statuses(statuses: Iterable[str]) -> str:
    normalized = [str(item).strip() for item in statuses if str(item).strip()]
    if not normalized:
        return ""
    if all(item == SUCCESS_STATUS for item in normalized):
        return SUCCESS_STATUS
    if any(item == FAILED_STATUS for item in normalized):
        return FAILED_STATUS
    if any(item == PARTIAL_SUCCESS_STATUS for item in normalized):
        return PARTIAL_SUCCESS_STATUS
    if any(item == PENDING_RETRY_STATUS for item in normalized):
        return PENDING_RETRY_STATUS
    return normalized[0]


def _merge_engineering_statuses(statuses: Iterable[str]) -> str:
    normalized = [str(item).strip() for item in statuses if str(item).strip()]
    if not normalized:
        return ""
    if all(item == SUCCESS_STATUS for item in normalized):
        return SUCCESS_STATUS
    return "partial"
