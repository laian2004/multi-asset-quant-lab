import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from collections import Counter
from datetime import date, timedelta
import time
from typing import List

from . import gui as gui_module
from .agent_platform import AgentOrchestrator
from .config import PROJECT_ROOT
from .crypto_observation import CryptoObservationRunner
from .environment_health import run_environment_health_check
from .public_assets import PublicAssetSnapshotRunner
from .public_bonds import PublicBondRunner
from .public_references import PublicReferenceRunner
from .platform_metadata import PlatformMetadataRunner
from .pregrab import PregrabRunner
from .pregrab_state import append_pregrab_run
from .research_platform import ResearchPlatformRunner, SchedulerRunner
from .regression_state import write_regression_smoke_state
from .selection import CrawlSelection, parse_selection
from .source_catalog import build_source_catalog
from .storage import build_duckdb_database, export_dataset, read_dataset_manifest
from .utils import now_shanghai, parse_trade_date
from .window_state import append_window_run
from .workflow import WorkflowRunner

_EXTERNAL_REGRESSION_ISSUE_CATEGORIES = {
    "result_chain_publication_lag",
    "result_chain_source_gap",
    "historical_public_contract_gap",
    "blocked_public_source_gap",
}
_PREGRAB_TRIAL_MARKER = "FUTURES_WORKFLOW_PREGRAB_TRIAL_INNER"


def _merge_regression_statuses(statuses):
    normalized = [str(status or "").strip() for status in statuses if str(status or "").strip()]
    if not normalized:
        return ""
    if all(status == "success" for status in normalized):
        return "success"
    if any(status in {"failed", "error"} for status in normalized):
        return "partial_success" if any(status == "success" for status in normalized) else "failed"
    if any(status == "pending_retry" for status in normalized):
        return "partial_success" if any(status == "success" for status in normalized) else "pending_retry"
    if any(status == "partial_success" for status in normalized):
        return "partial_success"
    if all(status == "no_data" for status in normalized):
        return "no_data"
    if all(status == "not_applicable" for status in normalized):
        return "not_applicable"
    if any(status == "success" for status in normalized):
        return "partial_success"
    return normalized[0]


def _last_day_of_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1) - timedelta(days=1)
    return date(value.year, value.month + 1, 1) - timedelta(days=1)


def _add_months(value: date, months: int) -> date:
    month_index = (value.year * 12 + (value.month - 1)) + months
    year = month_index // 12
    month = (month_index % 12) + 1
    return date(year, month, 1)


def _quarter_start(value: date) -> date:
    quarter_month = ((value.month - 1) // 3) * 3 + 1
    return date(value.year, quarter_month, 1)


def _sample_regression_windows(*, calendar, reference_date: date, canonical_dates=None):
    def _stringify(values):
        return [item.isoformat() for item in values]

    def _calendar_dates(start: date, end: date):
        return sorted(set(calendar.candidate_dates("all", start, end)))

    canonical_values = []
    for value in canonical_dates or []:
        try:
            parsed = parse_trade_date(str(value))
        except Exception:
            continue
        if parsed <= reference_date:
            canonical_values.append(parsed)
    canonical_values = sorted(set(canonical_values))

    def _canonical_dates(start: date, end: date):
        return [item for item in canonical_values if start <= item <= end]

    latest_7 = _calendar_dates(reference_date - timedelta(days=21), reference_date)[-7:]
    latest_1m = _canonical_dates(reference_date - timedelta(days=31), reference_date) or _calendar_dates(reference_date - timedelta(days=31), reference_date)

    latest_1y_monthly = []
    current_month_start = reference_date.replace(day=1)
    for offset in range(11, -1, -1):
        month_start = _add_months(current_month_start, -offset)
        month_end = min(reference_date, _last_day_of_month(month_start))
        candidates = _canonical_dates(month_start, month_end) if canonical_values else _calendar_dates(month_start, month_end)
        if candidates:
            latest_1y_monthly.append(candidates[-1])

    latest_3y_quarterly = []
    current_quarter_start = _quarter_start(reference_date)
    for offset in range(11, -1, -1):
        quarter_start = _add_months(current_quarter_start, -(offset * 3))
        quarter_end = min(reference_date, _last_day_of_month(_add_months(quarter_start, 2)))
        candidates = _canonical_dates(quarter_start, quarter_end) if canonical_values else _calendar_dates(quarter_start, quarter_end)
        if candidates:
            latest_3y_quarterly.append(candidates[-1])

    return {
        "latest_7_trading_days": _stringify(latest_7),
        "latest_1m_trading_days": _stringify(latest_1m),
        "latest_1y_monthly_sample": _stringify(latest_1y_monthly),
        "latest_3y_quarterly_sample": _stringify(latest_3y_quarterly),
    }


def _hydrate_missing_regression_dates(*, runner: WorkflowRunner, trade_dates):
    existing_dates = set(runner.existing_canonical_dates() if hasattr(runner, "existing_canonical_dates") else [])
    selection = CrawlSelection(instrument_group="all")
    fetch_summaries = {}
    for trade_date in trade_dates:
        if trade_date in existing_dates:
            continue
        fetch_summaries[trade_date] = runner.fetch_date(trade_date, selection=selection)
        existing_dates.add(trade_date)
    return fetch_summaries


def _engineering_regression_status(
    *,
    audit_result,
    latest_platform,
    platform_validation,
    build_db_result,
    gui_summary,
    include_build_db: bool,
    include_gui_smoke: bool,
    window_results,
):
    if latest_platform.get("status") != "success" or platform_validation.get("status") != "success":
        return "partial"
    if include_build_db and build_db_result and build_db_result.get("status") != "success":
        return "partial"
    if include_gui_smoke and not bool((gui_summary or {}).get("has_yield_curves")):
        return "partial"
    if any(int((payload or {}).get("sample_count", 0) or 0) <= 0 for payload in (window_results or {}).values()):
        return "partial"
    if audit_result.get("needs_repair_dates"):
        return "partial"
    issue_categories = {str(key) for key in (audit_result.get("issue_category_counts", {}) or {})}
    if issue_categories - _EXTERNAL_REGRESSION_ISSUE_CATEGORIES:
        return "partial"
    return "success"


def _normalize_pregrab_exchanges(values):
    exchanges = []
    for raw_value in values or []:
        for piece in str(raw_value).split(","):
            text = piece.strip().upper()
            if text and text not in exchanges:
                exchanges.append(text)
    return exchanges


def _run_pregrab_trial_subprocess(*, start_date: str, end_date: str, exchanges, persist: bool):
    env = os.environ.copy()
    src_path = str(PROJECT_ROOT / "src")
    existing_pythonpath = str(env.get("PYTHONPATH", "") or "").strip()
    env["PYTHONPATH"] = src_path if not existing_pythonpath else src_path + os.pathsep + existing_pythonpath
    env[_PREGRAB_TRIAL_MARKER] = "1"
    command = [
        sys.executable,
        "-m",
        "futures_workflow",
        "pregrab-window",
        "--start",
        start_date,
        "--end",
        end_date,
        "--mode",
        "trial",
        "--no-persist",
    ]
    for exchange in exchanges:
        command.extend(["--exchange", exchange])

    temp_base = PROJECT_ROOT / ".tmp" / "pregrab"
    temp_base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fw-pregrab-", dir=str(temp_base)) as temp_name:
        temp_root = Path(temp_name)
        env["FUTURES_WORKFLOW_DATA_DIR"] = str(temp_root / "data")
        env["FUTURES_WORKFLOW_STATE_DIR"] = str(temp_root / "state")
        env["FUTURES_WORKFLOW_DB_DIR"] = str(temp_root / "data" / "db")
        env["FUTURES_WORKFLOW_DUCKDB_PATH"] = str(temp_root / "data" / "db" / "market_data.duckdb")
        env["FUTURES_WORKFLOW_EXPORTS_DIR"] = str(temp_root / "data" / "exports")
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    stdout = str(getattr(completed, "stdout", "") or "").strip()
    stderr = str(getattr(completed, "stderr", "") or "").strip()
    returncode = int(getattr(completed, "returncode", 0) or 0)
    if returncode != 0:
        raise RuntimeError(stderr or stdout or f"pregrab subprocess failed with code {returncode}")
    if not stdout:
        raise RuntimeError("pregrab subprocess returned empty stdout")
    result = json.loads(stdout)
    result["cleanup_status"] = "cleaned"
    if persist:
        append_pregrab_run(result)
    return result


def _normalize_family_values(values):
    normalized = []
    for raw_value in values or []:
        for piece in str(raw_value).split(","):
            text = piece.strip()
            if text and text not in normalized:
                normalized.append(text)
    return normalized


def _infer_window_issue_categories(status: str, payload) -> Counter:
    categories: Counter[str] = Counter()
    normalized_status = str(status or "").strip()
    if normalized_status in {"failed", "error"}:
        categories.update(["runtime_failure"])
    if normalized_status == "pending_retry":
        categories.update(["retry_or_error"])
    if not isinstance(payload, dict):
        return categories
    text = " ".join(
        str(payload.get(key, "") or "")
        for key in ("message", "blocked_reason", "no_data_reason", "not_applicable_reason")
    ).lower()
    if (
        "nodename nor servname provided" in text
        or "temporary failure in name resolution" in text
        or "name or service not known" in text
        or "failed to resolve" in text
    ):
        categories.update(["dns_failure"])
    if "proxy" in text:
        categories.update(["proxy_failure"])
    if "429" in text or "too many requests" in text or "rate limit" in text:
        categories.update(["rate_limit"])
    if "publication lag" in text or "pending official publication" in text or "not yet published" in text:
        categories.update(["result_chain_publication_lag"])
    return categories


def _run_window_sync(
    *,
    runner: WorkflowRunner,
    sync_callable,
    action_name: str,
    scope: str,
    start_date: str,
    end_date: str,
    families=None,
    force: bool = False,
    persist_state: bool = True,
    candidate_dates=None,
):
    start = parse_trade_date(start_date)
    end = parse_trade_date(end_date)
    if candidate_dates is None:
        candidate_dates = [item.isoformat() for item in runner.calendar.candidate_dates("all", start, end)]
    else:
        candidate_dates = [parse_trade_date(str(item)).isoformat() for item in candidate_dates]
    started_at = time.monotonic()
    statuses = []
    date_results = {}
    date_counts: Counter[str] = Counter()
    issue_category_counts: Counter[str] = Counter()
    blocked_issues = []

    for trade_date in candidate_dates:
        payload = sync_callable(trade_date, families=families, force=force)
        status = str((payload or {}).get("status", "") or "")
        statuses.append(status)
        date_counts.update([status or "unknown"])
        issue_category_counts.update(_infer_window_issue_categories(status, payload))
        if status in {"failed", "pending_retry"}:
            blocked_issues.append(f"{trade_date}: {status}")
        date_results[trade_date] = {
            "status": status,
            "row_counts": dict((payload or {}).get("row_counts", {}) or {}),
        }

    engineering_status = "success" if not any(status in {"failed", "error"} for status in statuses) else "partial"
    result = {
        "run_id": f"{action_name}-{int(time.time())}",
        "action_name": action_name,
        "scope": scope,
        "mode": "production",
        "target": ",".join(_normalize_family_values(families or [])) if families else "all",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "status": _merge_regression_statuses(statuses),
        "engineering_status": engineering_status,
        "elapsed_seconds": round(time.monotonic() - started_at, 3),
        "date_counts": dict(date_counts),
        "issue_category_counts": dict(issue_category_counts),
        "blocked_issues": blocked_issues,
        "details": {
            "date_results": date_results,
            "force": bool(force),
        },
        "updated_at": now_shanghai().isoformat(),
    }
    if persist_state:
        append_window_run(result)
    return result


def _history_sync_candidate_dates(*, runner: WorkflowRunner, mode: str, start_date: str, end_date: str) -> List[str]:
    start = parse_trade_date(start_date)
    end = parse_trade_date(end_date)
    all_dates = sorted(runner.calendar.candidate_dates("all", start, end))
    if mode == "1y":
        monthly = []
        current_month = None
        bucket = []
        for item in all_dates:
            month = (item.year, item.month)
            if month != current_month:
                if current_month is not None and bucket:
                    monthly.append(bucket[-1])
                current_month = month
                bucket = []
            bucket.append(item)
        if current_month is not None and bucket:
            monthly.append(bucket[-1])
        return [item.isoformat() for item in monthly[-12:]]
    if mode == "3y":
        quarterly = []
        current_quarter = None
        bucket = []
        for item in all_dates:
            quarter = (item.year, (item.month - 1) // 3)
            if quarter != current_quarter:
                if current_quarter is not None and bucket:
                    quarterly.append(bucket[-1])
                current_quarter = quarter
                bucket = []
            bucket.append(item)
        if current_quarter is not None and bucket:
            quarterly.append(bucket[-1])
        return [item.isoformat() for item in quarterly[-12:]]
    return [item.isoformat() for item in all_dates]


def run_regression_smoke(
    *,
    runner: WorkflowRunner,
    platform_runner: PlatformMetadataRunner,
    trade_dates,
    profile: str = "core",
    include_build_db: bool = True,
    include_gui_smoke: bool = True,
    state_writer=write_regression_smoke_state,
):
    unique_dates = []
    for value in trade_dates:
        text = str(value).strip()
        if text and text not in unique_dates:
            unique_dates.append(text)
    reference_date = runner.calendar.previous_trading_day("all", now_shanghai().date())
    existing_canonical_dates = list(runner.existing_canonical_dates() if hasattr(runner, "existing_canonical_dates") else [])
    window_dates = _sample_regression_windows(
        calendar=runner.calendar,
        reference_date=reference_date,
        canonical_dates=existing_canonical_dates,
    )
    validation_dates = list(unique_dates)
    for sampled_dates in window_dates.values():
        for trade_date in sampled_dates:
            if trade_date not in validation_dates:
                validation_dates.append(trade_date)
    fetch_summaries = _hydrate_missing_regression_dates(runner=runner, trade_dates=validation_dates)
    date_results = {trade_date: runner.validate(trade_date) for trade_date in validation_dates}
    representative_results = {trade_date: date_results[trade_date] for trade_date in unique_dates}
    window_results = {}
    for window_name, sampled_dates in window_dates.items():
        statuses = [
            str((date_results.get(trade_date, {}) or {}).get("checkpoint_status") or (date_results.get(trade_date, {}) or {}).get("status") or "")
            for trade_date in sampled_dates
        ]
        window_results[window_name] = {
            "status": _merge_regression_statuses(statuses),
            "sample_count": len(sampled_dates),
            "sampled_dates": list(sampled_dates),
            "status_counts": dict(Counter(status for status in statuses if status)),
        }
    audit_result = runner.audit_canonical_dates()
    latest_platform = platform_runner.sync("latest")
    platform_validation = platform_runner.validate(latest_platform["trade_date"])
    build_db_result = None
    if include_build_db:
        build_db_result = build_duckdb_database()
        build_db_result["manifest"] = read_dataset_manifest()
    gui_summary = None
    if include_gui_smoke:
        app = gui_module.DashboardApp()
        context = app.build_context(dataset_name="yield_curves", trade_date=latest_platform["trade_date"], limit=2)
        gui_summary = {
            "selected_dataset": context.get("selected_dataset"),
            "selected_date": context.get("selected_date"),
            "platform_metadata_count": len(context.get("platform_metadata", [])),
            "has_yield_curves": any(item.get("dataset") == "yield_curves" for item in context.get("platform_metadata", [])),
        }
    overall_success = all(result.get("checkpoint_status") == "success" for result in representative_results.values())
    overall_success = overall_success and all(
        str((payload or {}).get("status", "")) == "success"
        for payload in window_results.values()
        if int((payload or {}).get("sample_count", 0) or 0) > 0
    )
    if include_build_db and build_db_result:
        overall_success = overall_success and build_db_result.get("status") == "success"
    overall_success = overall_success and latest_platform.get("status") == "success" and platform_validation.get("status") == "success"
    overall_success = overall_success and not audit_result.get("needs_repair_dates")
    if include_gui_smoke and gui_summary:
        overall_success = overall_success and bool(gui_summary.get("has_yield_curves"))
    runtime_status = "success" if overall_success else "partial_success"
    engineering_status = _engineering_regression_status(
        audit_result=audit_result,
        latest_platform=latest_platform,
        platform_validation=platform_validation,
        build_db_result=build_db_result,
        gui_summary=gui_summary,
        include_build_db=include_build_db,
        include_gui_smoke=include_gui_smoke,
        window_results=window_results,
    )
    result = {
        "status": runtime_status,
        "engineering_status": engineering_status,
        "profile": profile,
        "dates": unique_dates,
        "date_results": representative_results,
        "window_results": window_results,
        "audit": audit_result,
        "platform_sync": latest_platform,
        "platform_validation": platform_validation,
        "build_db": build_db_result,
        "gui_smoke": gui_summary,
        "hydrated_dates": sorted(fetch_summaries.keys()),
    }
    if state_writer:
        state_writer(result)
    return result


def add_selection_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--instrument-group",
        default="futures",
        choices=["futures", "options", "all"],
        help="Instrument group to fetch",
    )
    parser.add_argument(
        "--exchange",
        action="append",
        default=[],
        help="Exchange filter, repeatable or comma-separated, e.g. SHFE or SHFE,CFFEX",
    )
    parser.add_argument(
        "--variety",
        action="append",
        default=[],
        help="Legacy alias for --product",
    )
    parser.add_argument(
        "--product",
        action="append",
        default=[],
        help="Product filter, repeatable or comma-separated, e.g. SHFE:CU or CU when one exchange is selected",
    )
    parser.add_argument(
        "--underlying",
        action="append",
        default=[],
        help="Underlying filter, repeatable or comma-separated, e.g. SHFE:CU2605 or SHFE:CU",
    )
    parser.add_argument(
        "--contract",
        action="append",
        default=[],
        help="Exact contract filter, repeatable or comma-separated, e.g. SHFE:CU2605 or CFFEX:HO2604-C-2500",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="中国多资产数据平台工作流")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backfill = subparsers.add_parser("backfill", help="Run historical backfill")
    backfill.add_argument("--start", required=True, help="Start date, e.g. 2026-04-01")
    backfill.add_argument("--end", required=True, help="End date, e.g. 2026-04-16")
    add_selection_args(backfill)

    fetch_date = subparsers.add_parser("fetch-date", help="Fetch and normalize one trading date")
    fetch_date.add_argument("--date", required=True, help="Trading date, e.g. 2026-04-16")
    add_selection_args(fetch_date)

    sync_daily = subparsers.add_parser("sync-daily", help="Run daily sync")
    sync_daily.add_argument("--date", default="latest", help="Trading date or latest")
    add_selection_args(sync_daily)

    validate = subparsers.add_parser("validate", help="Validate a normalized output file")
    validate.add_argument("--date", required=True, help="Trading date, e.g. 2026-04-16")
    add_selection_args(validate)

    public_sync = subparsers.add_parser("sync-public-assets", help="Sync public multi-asset snapshots")
    public_sync.add_argument("--date", default="latest", help="Snapshot date, default latest")
    public_sync.add_argument("--start", default="", help="Optional historical window start date")
    public_sync.add_argument("--end", default="", help="Optional historical window end date")
    public_sync.add_argument("--family", action="append", default=[], help="Dataset family selector, repeatable or comma-separated")
    public_sync.add_argument("--force", action="store_true", help="Ignore cached raw payloads and refetch live data")

    public_validate = subparsers.add_parser("validate-public-assets", help="Validate public multi-asset snapshots")
    public_validate.add_argument("--date", required=True, help="Snapshot date, e.g. 2026-04-19")
    public_validate.add_argument("--family", action="append", default=[], help="Dataset family selector, repeatable or comma-separated")

    reference_sync = subparsers.add_parser("sync-public-references", help="Sync public FX and money-market reference datasets")
    reference_sync.add_argument("--date", default="latest", help="Reference date, default latest")
    reference_sync.add_argument("--start", default="", help="Optional historical window start date")
    reference_sync.add_argument("--end", default="", help="Optional historical window end date")
    reference_sync.add_argument("--family", action="append", default=[], help="Dataset family selector, repeatable or comma-separated")
    reference_sync.add_argument("--force", action="store_true", help="Ignore cached raw payloads and refetch live data")

    reference_validate = subparsers.add_parser("validate-public-references", help="Validate public FX and money-market reference datasets")
    reference_validate.add_argument("--date", required=True, help="Reference date, e.g. 2026-04-19")
    reference_validate.add_argument("--family", action="append", default=[], help="Dataset family selector, repeatable or comma-separated")

    bond_sync = subparsers.add_parser("sync-public-bonds", help="Sync public bond snapshots and yield curves")
    bond_sync.add_argument("--date", default="latest", help="Bond market date, default latest")
    bond_sync.add_argument("--start", default="", help="Optional historical window start date")
    bond_sync.add_argument("--end", default="", help="Optional historical window end date")
    bond_sync.add_argument("--family", action="append", default=[], help="Dataset family selector, repeatable or comma-separated")
    bond_sync.add_argument("--force", action="store_true", help="Ignore cached raw payloads and refetch live data")

    bond_validate = subparsers.add_parser("validate-public-bonds", help="Validate public bond snapshots and yield curves")
    bond_validate.add_argument("--date", required=True, help="Bond market date, e.g. 2026-04-17")
    bond_validate.add_argument("--family", action="append", default=[], help="Dataset family selector, repeatable or comma-separated")

    crypto_sync = subparsers.add_parser("sync-crypto-observation", help="Sync global crypto observation snapshot")
    crypto_sync.add_argument("--date", default="latest", help="Snapshot date, default latest")
    crypto_sync.add_argument("--start", default="", help="Optional historical window start date")
    crypto_sync.add_argument("--end", default="", help="Optional historical window end date")
    crypto_sync.add_argument("--force", action="store_true", help="Ignore cached raw payloads and refetch live data")

    crypto_validate = subparsers.add_parser("validate-crypto-observation", help="Validate global crypto observation snapshot")
    crypto_validate.add_argument("--date", required=True, help="Snapshot date, e.g. 2026-04-19")

    platform_sync = subparsers.add_parser("sync-platform-metadata", help="Materialize unified platform metadata datasets")
    platform_sync.add_argument("--date", default="latest", help="As-of date, default latest")

    platform_validate = subparsers.add_parser("validate-platform-metadata", help="Validate unified platform metadata datasets")
    platform_validate.add_argument("--date", required=True, help="As-of date, e.g. 2026-04-19")

    list_sources = subparsers.add_parser("list-sources", help="List registered source adapters")
    list_sources.add_argument("--asset-family", default="", help="Optional asset-family filter")

    audit = subparsers.add_parser("audit", help="Audit canonical normalized outputs for a date")
    audit_group = audit.add_mutually_exclusive_group(required=True)
    audit_group.add_argument("--date", help="Trading date, e.g. 2026-04-16")
    audit_group.add_argument("--all", action="store_true", help="Audit all existing canonical dates")

    repair = subparsers.add_parser("repair", help="Repair canonical normalized outputs from preserved raw payloads")
    repair.add_argument("--date", action="append", default=[], help="Trading date selector, repeatable")
    repair.add_argument("--all", action="store_true", help="Repair all existing canonical dates")

    build_db = subparsers.add_parser("build-db", help="Build a local DuckDB index over canonical normalized outputs")

    export = subparsers.add_parser("export", help="Export one dataset from the local DuckDB index")
    export.add_argument("--dataset", required=True, help="Dataset name, e.g. options_daily_quotes")
    export.add_argument("--date", default="", help="Optional trade_date filter")
    export.add_argument("--format", required=True, choices=["csv", "json", "parquet"], help="Export format")
    export.add_argument(
        "--filter",
        action="append",
        default=[],
        help="Optional equality filters, repeatable, e.g. exchange=SSE or symbol=600000",
    )

    gui = subparsers.add_parser("gui", help="Start the local data platform GUI")
    gui.add_argument("--host", default="127.0.0.1", help="GUI bind host, default 127.0.0.1")
    gui.add_argument("--port", type=int, default=8765, help="GUI bind port, default 8765")
    serve_gui = subparsers.add_parser("serve-gui", help="Alias for gui")
    serve_gui.add_argument("--host", default="127.0.0.1", help="GUI bind host, default 127.0.0.1")
    serve_gui.add_argument("--port", type=int, default=8765, help="GUI bind port, default 8765")

    pregrab = subparsers.add_parser("pregrab-window", help="Run per-exchange pregrab validation over a date window")
    pregrab.add_argument("--start", required=True, help="Start trade date, e.g. 2026-01-21")
    pregrab.add_argument("--end", required=True, help="End trade date, e.g. 2026-04-21")
    pregrab.add_argument("--exchange", action="append", default=[], help="Exchange selector, repeatable or comma-separated")
    pregrab.add_argument("--mode", choices=["production", "trial"], default="production", help="Pregrab mode")
    pregrab.add_argument("--no-persist", action="store_true", help="Do not persist pregrab summary state")

    regression = subparsers.add_parser("regression-smoke", help="Run representative validation, audit, DuckDB and GUI smoke checks")
    regression.add_argument(
        "--date",
        action="append",
        default=[],
        help="Representative date selector, repeatable. Defaults to 2010-04-16,2015-04-16,2021-04-16,2026-04-16",
    )
    regression.add_argument("--skip-build-db", action="store_true", help="Skip DuckDB rebuild during smoke regression")
    regression.add_argument("--skip-gui-smoke", action="store_true", help="Skip GUI context smoke during smoke regression")
    regression.add_argument("--profile", choices=["core", "phase2"], default="core", help="Regression profile")

    env_check = subparsers.add_parser("environment-check", help="Run local runtime and connectivity checks")
    env_check.add_argument("--json-only", action="store_true", help="Reserved flag for GUI compatibility")

    research_run = subparsers.add_parser("research-run", help="Compute local research metrics from normalized datasets")
    research_run.add_argument("--date", default="latest", help="As-of date, default latest")
    research_run.add_argument("--start", default="", help="Optional research window start date")
    research_run.add_argument("--end", default="", help="Optional research window end date")
    research_run.add_argument("--asset-family", default="", help="Optional asset family filter")
    research_run.add_argument("--dataset", default="", help="Optional source dataset, e.g. daily_ohlcv")

    factor_run = subparsers.add_parser("factor-run", help="Generate factor signals for local research")
    factor_run.add_argument("--start", required=True, help="Factor window start date")
    factor_run.add_argument("--end", required=True, help="Factor window end date")
    factor_run.add_argument("--factor", default="momentum", help="Factor name, e.g. momentum")
    factor_run.add_argument("--asset-family", default="", help="Optional asset family filter")
    factor_run.add_argument("--dataset", default="daily_ohlcv", help="Source dataset, default daily_ohlcv")

    strategy_backtest = subparsers.add_parser("strategy-backtest", help="Run daily close paper research backtest")
    strategy_backtest.add_argument("--start", required=True, help="Backtest start date")
    strategy_backtest.add_argument("--end", required=True, help="Backtest end date")
    strategy_backtest.add_argument("--strategy", default="momentum", help="Strategy template")
    strategy_backtest.add_argument("--initial-cash", type=float, default=1_000_000.0, help="Initial cash")
    strategy_backtest.add_argument("--fee-bps", type=float, default=2.0, help="Trading cost in bps")
    strategy_backtest.add_argument("--asset-family", default="", help="Optional asset family filter")
    strategy_backtest.add_argument("--dataset", default="daily_ohlcv", help="Source dataset, default daily_ohlcv")

    paper_sim = subparsers.add_parser("paper-sim", help="Create one-day paper portfolio snapshot")
    paper_sim.add_argument("--date", default="latest", help="As-of date, default latest")
    paper_sim.add_argument("--strategy", default="momentum", help="Strategy template")
    paper_sim.add_argument("--initial-cash", type=float, default=1_000_000.0, help="Initial cash")
    paper_sim.add_argument("--asset-family", default="", help="Optional asset family filter")
    paper_sim.add_argument("--dataset", default="daily_ohlcv", help="Source dataset, default daily_ohlcv")

    quality_diagnose = subparsers.add_parser("quality-diagnose", help="Generate local quality diagnostics")
    quality_diagnose.add_argument("--date", default="latest", help="As-of date, default latest")

    scheduler_tick = subparsers.add_parser("scheduler-tick", help="Run due local scheduled jobs")
    scheduler_tick.add_argument("--schedule-id", default="", help="Optional single schedule id to run")
    scheduler_tick.add_argument("--one", action="store_true", help="Run only one due job")

    report_generate = subparsers.add_parser("report-generate", help="Generate local HTML and Markdown research operations report")
    report_generate.add_argument("--date", default="latest", help="As-of date, default latest")
    report_generate.add_argument("--report-type", default="comprehensive", choices=["daily", "factor", "backtest", "risk", "quality", "ml", "comprehensive"], help="Report type")

    algorithm_run = subparsers.add_parser("algorithm-run", help="Run a registered built-in financial algorithm template")
    algorithm_run.add_argument("--template", required=True, help="Algorithm template, e.g. momentum or black_scholes_price")
    algorithm_run.add_argument("--start", required=True, help="Window start date")
    algorithm_run.add_argument("--end", required=True, help="Window end date")
    algorithm_run.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    algorithm_run.add_argument("--asset-family", default="", help="Optional asset family filter")
    algorithm_run.add_argument("--params", default="{}", help="JSON object parameters")

    risk_run = subparsers.add_parser("risk-run", help="Run a registered portfolio risk template")
    risk_run.add_argument("--template", required=True, help="Risk template, e.g. var_cvar")
    risk_run.add_argument("--start", required=True, help="Window start date")
    risk_run.add_argument("--end", required=True, help="Window end date")
    risk_run.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    risk_run.add_argument("--asset-family", default="", help="Optional asset family filter")
    risk_run.add_argument("--params", default="{}", help="JSON object parameters")

    portfolio_optimize = subparsers.add_parser("portfolio-optimize", help="Run a registered local portfolio allocation template")
    portfolio_optimize.add_argument("--template", required=True, help="Portfolio template, e.g. risk_parity")
    portfolio_optimize.add_argument("--start", required=True, help="Window start date")
    portfolio_optimize.add_argument("--end", required=True, help="Window end date")
    portfolio_optimize.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    portfolio_optimize.add_argument("--asset-family", default="", help="Optional asset family filter")
    portfolio_optimize.add_argument("--params", default="{}", help="JSON object parameters")

    backtest_run = subparsers.add_parser("backtest-run", help="Run the detailed local backtest engine")
    backtest_run.add_argument("--strategy", required=True, help="Strategy template")
    backtest_run.add_argument("--start", required=True, help="Backtest start date")
    backtest_run.add_argument("--end", required=True, help="Backtest end date")
    backtest_run.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    backtest_run.add_argument("--initial-cash", type=float, default=1_000_000.0, help="Initial cash")
    backtest_run.add_argument("--fee-bps", type=float, default=2.0, help="Fee in basis points")
    backtest_run.add_argument("--slippage-bps", type=float, default=1.0, help="Slippage in basis points")
    backtest_run.add_argument("--asset-family", default="", help="Optional asset family filter")
    backtest_run.add_argument("--params", default="{}", help="JSON object parameters")

    ml_run = subparsers.add_parser("ml-run", help="Run a built-in local machine-learning research template")
    ml_run.add_argument("--template", required=True, help="ML template, e.g. linear_regression, ridge, random_forest")
    ml_run.add_argument("--start", required=True, help="Training/evaluation window start date")
    ml_run.add_argument("--end", required=True, help="Training/evaluation window end date")
    ml_run.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    ml_run.add_argument("--target", default="", help="Target numeric field, default auto")
    ml_run.add_argument("--features", default="", help="Comma separated numeric feature fields, default auto")
    ml_run.add_argument("--asset-family", default="", help="Optional asset family filter")
    ml_run.add_argument("--params", default="{}", help="JSON object parameters")
    ml_run.add_argument("--tune", action="store_true", help="Run a small deterministic tuning grid")

    experiment_list = subparsers.add_parser("experiment-list", help="List local research experiment runs")
    experiment_list.add_argument("--date", default="latest", help="As-of date, default latest")

    factor_performance = subparsers.add_parser("factor-performance", help="Evaluate factor performance over a local window")
    factor_performance.add_argument("--factor", required=True, help="Factor name")
    factor_performance.add_argument("--start", required=True, help="Window start date")
    factor_performance.add_argument("--end", required=True, help="Window end date")
    factor_performance.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    factor_performance.add_argument("--asset-family", default="", help="Optional asset family filter")

    stress_test = subparsers.add_parser("stress-test", help="Run a local portfolio stress test")
    stress_test.add_argument("--template", required=True, help="Stress template, e.g. equity_down")
    stress_test.add_argument("--start", required=True, help="Window start date")
    stress_test.add_argument("--end", required=True, help="Window end date")
    stress_test.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    stress_test.add_argument("--asset-family", default="", help="Optional asset family filter")
    stress_test.add_argument("--params", default="{}", help="JSON object parameters")

    quality_score = subparsers.add_parser("quality-score", help="Generate local dataset quality scores")
    quality_score.add_argument("--date", default="latest", help="As-of date, default latest")

    artifact_list = subparsers.add_parser("artifact-list", help="List local report/research artifacts")
    artifact_list.add_argument("--date", default="latest", help="As-of date, default latest")
    artifact_list.add_argument("--run-id", default="", help="Optional run_id filter")

    inventory_build = subparsers.add_parser("inventory-build", help="Build dataset inventory and field profiles")
    inventory_build.add_argument("--date", default="latest", help="As-of date, default latest")

    lineage_build = subparsers.add_parser("lineage-build", help="Build local data lineage index")
    lineage_build.add_argument("--date", default="latest", help="As-of date, default latest")

    feature_run = subparsers.add_parser("feature-run", help="Build the local ML feature store")
    feature_run.add_argument("--start", required=True, help="Feature window start date")
    feature_run.add_argument("--end", required=True, help="Feature window end date")
    feature_run.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    feature_run.add_argument("--asset-family", default="", help="Optional asset family filter")
    feature_run.add_argument("--features", default="", help="Comma separated feature names")
    feature_run.add_argument("--mode", default="incremental", choices=["incremental", "full"], help="Feature materialization mode")

    ml_benchmark = subparsers.add_parser("ml-benchmark", help="Run all registered ML benchmark templates")
    ml_benchmark.add_argument("--start", required=True, help="Benchmark window start date")
    ml_benchmark.add_argument("--end", required=True, help="Benchmark window end date")
    ml_benchmark.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    ml_benchmark.add_argument("--target", default="", help="Target numeric field")
    ml_benchmark.add_argument("--features", default="", help="Comma separated numeric features")
    ml_benchmark.add_argument("--models", default="", help="Comma separated ML model templates")
    ml_benchmark.add_argument("--asset-family", default="", help="Optional asset family filter")
    ml_benchmark.add_argument("--params", default="{}", help="JSON object parameters")

    ml_validate = subparsers.add_parser("ml-validate", help="Run walk-forward time-series validation")
    ml_validate.add_argument("--template", required=True, help="ML template")
    ml_validate.add_argument("--start", required=True, help="Validation window start date")
    ml_validate.add_argument("--end", required=True, help="Validation window end date")
    ml_validate.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    ml_validate.add_argument("--target", default="", help="Target numeric field")
    ml_validate.add_argument("--features", default="", help="Comma separated numeric features")
    ml_validate.add_argument("--method", default="expanding", choices=["expanding", "rolling", "fixed_horizon"], help="Validation method")
    ml_validate.add_argument("--asset-family", default="", help="Optional asset family filter")
    ml_validate.add_argument("--params", default="{}", help="JSON object parameters")

    factor_experiment = subparsers.add_parser("factor-experiment", help="Run factor experiment summary")
    factor_experiment.add_argument("--factor", required=True, help="Factor template")
    factor_experiment.add_argument("--start", required=True, help="Experiment window start date")
    factor_experiment.add_argument("--end", required=True, help="Experiment window end date")
    factor_experiment.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    factor_experiment.add_argument("--asset-family", default="", help="Optional asset family filter")
    factor_experiment.add_argument("--params", default="{}", help="JSON object parameters")

    parameter_scan = subparsers.add_parser("parameter-scan", help="Run deterministic parameter scan")
    parameter_scan.add_argument("--template", required=True, help="Template name")
    parameter_scan.add_argument("--start", required=True, help="Scan window start date")
    parameter_scan.add_argument("--end", required=True, help="Scan window end date")
    parameter_scan.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    parameter_scan.add_argument("--asset-family", default="", help="Optional asset family filter")
    parameter_scan.add_argument("--grid", default="{}", help="JSON parameter grid")

    strategy_leaderboard = subparsers.add_parser("strategy-leaderboard", help="Build strategy leaderboard")
    strategy_leaderboard.add_argument("--start", required=True, help="Leaderboard window start date")
    strategy_leaderboard.add_argument("--end", required=True, help="Leaderboard window end date")
    strategy_leaderboard.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")

    portfolio_run = subparsers.add_parser("portfolio-run", help="Run portfolio experiment")
    portfolio_run.add_argument("--template", required=True, help="Portfolio template")
    portfolio_run.add_argument("--start", required=True, help="Window start date")
    portfolio_run.add_argument("--end", required=True, help="Window end date")
    portfolio_run.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    portfolio_run.add_argument("--asset-family", default="", help="Optional asset family filter")
    portfolio_run.add_argument("--params", default="{}", help="JSON object parameters")

    scenario_sim = subparsers.add_parser("scenario-sim", help="Run scenario simulation")
    scenario_sim.add_argument("--template", required=True, help="Scenario template")
    scenario_sim.add_argument("--start", required=True, help="Window start date")
    scenario_sim.add_argument("--end", required=True, help="Window end date")
    scenario_sim.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    scenario_sim.add_argument("--asset-family", default="", help="Optional asset family filter")
    scenario_sim.add_argument("--params", default="{}", help="JSON object parameters")

    project_create = subparsers.add_parser("project-create", help="Create a local research project")
    project_create.add_argument("--name", required=True, help="Project name")
    project_create.add_argument("--description", default="", help="Project description")
    project_create.add_argument("--date", default="latest", help="As-of date, default latest")

    project_run = subparsers.add_parser("project-run", help="Record a project run")
    project_run.add_argument("--project-id", required=True, help="Project id")
    project_run.add_argument("--template", required=True, help="Run template")
    project_run.add_argument("--start", required=True, help="Window start date")
    project_run.add_argument("--end", required=True, help="Window end date")
    project_run.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    project_run.add_argument("--params", default="{}", help="JSON object parameters")

    package_export = subparsers.add_parser("package-export", help="Export a reproducible research package")
    package_export.add_argument("--run-id", default="", help="Optional source run id")
    package_export.add_argument("--date", default="latest", help="As-of date, default latest")

    sla_check = subparsers.add_parser("sla-check", help="Check dataset SLA rules")
    sla_check.add_argument("--date", default="latest", help="As-of date, default latest")

    knowledge_build = subparsers.add_parser("knowledge-build", help="Build local project knowledge index")
    knowledge_build.add_argument("--date", default="latest", help="As-of date, default latest")

    agent_plan = subparsers.add_parser("agent-plan", help="Create an Agent draft plan and wait for confirmation")
    agent_plan.add_argument("--goal", required=True, help="Research or operations goal")
    agent_plan.add_argument("--start", default="", help="Window start date")
    agent_plan.add_argument("--end", default="", help="Window end date")
    agent_plan.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    agent_plan.add_argument("--asset-family", default="", help="Optional asset family filter")
    agent_plan.add_argument("--mode", default="research", help="Agent run mode")
    agent_plan.add_argument("--report-type", default="comprehensive", help="Report type")

    agent_run = subparsers.add_parser("agent-run", help="Confirm and run an Agent task")
    agent_run.add_argument("--task-id", required=True, help="Agent task id")

    agent_status = subparsers.add_parser("agent-status", help="Show Agent task status")
    agent_status.add_argument("--task-id", default="", help="Optional Agent task id")
    agent_status.add_argument("--date", default="latest", help="As-of date")

    agent_cancel = subparsers.add_parser("agent-cancel", help="Cancel an Agent task")
    agent_cancel.add_argument("--task-id", required=True, help="Agent task id")

    agent_retry = subparsers.add_parser("agent-retry", help="Retry an Agent task step")
    agent_retry.add_argument("--task-id", required=True, help="Agent task id")
    agent_retry.add_argument("--step-id", required=True, help="Agent step id")

    plugin_list = subparsers.add_parser("plugin-list", help="List internal product plugins")
    plugin_list.add_argument("--date", default="latest", help="As-of date")

    plugin_run = subparsers.add_parser("plugin-run", help="Run one internal product plugin")
    plugin_run.add_argument("--plugin-id", required=True, help="Plugin id")
    plugin_run.add_argument("--params", default="{}", help="JSON object parameters")

    quality_gate = subparsers.add_parser("quality-gate", help="Run Agent input quality gate")
    quality_gate.add_argument("--dataset", default="daily_ohlcv", help="Source dataset")
    quality_gate.add_argument("--start", default="", help="Window start date")
    quality_gate.add_argument("--end", default="", help="Window end date")
    quality_gate.add_argument("--asset-family", default="", help="Optional asset family filter")

    memory_search = subparsers.add_parser("memory-search", help="Search Agent research memory")
    memory_search.add_argument("--query", required=True, help="Search text")
    memory_search.add_argument("--date", default="latest", help="As-of date")

    model_registry_build = subparsers.add_parser("model-registry-build", help="Build local model registry from ML benchmarks")
    model_registry_build.add_argument("--date", default="latest", help="As-of date")

    model_drift_check = subparsers.add_parser("model-drift-check", help="Check model drift events")
    model_drift_check.add_argument("--date", default="latest", help="As-of date")

    history_sync = subparsers.add_parser("history-sync", help="Run best-effort historical sync over existing workflows")
    history_sync.add_argument("--scope", default="public_assets", choices=["derivatives", "public_assets", "public_references", "public_bonds", "crypto_observation"], help="History sync scope")
    history_sync.add_argument("--start", default="", help="Custom start date")
    history_sync.add_argument("--end", default="", help="Custom end date")
    history_sync.add_argument("--mode", default="custom", choices=["latest", "1y", "3y", "all_available", "custom"], help="Window preset")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    pregrab_exchanges = None
    if args.command == "pregrab-window":
        pregrab_exchanges = _normalize_pregrab_exchanges(getattr(args, "exchange", []) or [])
        if not pregrab_exchanges:
            parser.error("pregrab-window requires at least one --exchange")
        if args.mode == "trial" and str(os.environ.get(_PREGRAB_TRIAL_MARKER, "") or "").strip() != "1":
            result = _run_pregrab_trial_subprocess(
                start_date=args.start,
                end_date=args.end,
                exchanges=pregrab_exchanges,
                persist=not bool(getattr(args, "no_persist", False)),
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
    runner = WorkflowRunner()
    public_runner = PublicAssetSnapshotRunner()
    bond_runner = PublicBondRunner()
    reference_runner = PublicReferenceRunner()
    crypto_runner = CryptoObservationRunner()
    platform_runner = PlatformMetadataRunner(
        workflow_runner=runner,
        checkpoint_store=runner.checkpoints,
        public_asset_runner=public_runner,
        public_reference_runner=reference_runner,
        public_bond_runner=bond_runner,
        crypto_runner=crypto_runner,
    )
    pregrab_runner = PregrabRunner(workflow_runner=runner)
    research_runner = ResearchPlatformRunner()
    scheduler_runner = SchedulerRunner()
    agent_runner = AgentOrchestrator(research_runner=research_runner)
    selection = None

    if args.command in {"backfill", "fetch-date", "sync-daily", "validate"}:
        try:
            selection = parse_selection(
                exchange_values=getattr(args, "exchange", []),
                variety_values=getattr(args, "variety", []),
                product_values=getattr(args, "product", []),
                underlying_values=getattr(args, "underlying", []),
                contract_values=getattr(args, "contract", []),
                instrument_group=getattr(args, "instrument_group", "futures"),
                known_exchanges=sorted({source.exchange for source in runner.sources + runner.option_sources}),
            )
        except ValueError as exc:
            parser.error(str(exc))

    if args.command == "backfill":
        result = runner.backfill(args.start, args.end, selection=selection)
    elif args.command == "fetch-date":
        result = runner.fetch_date(args.date, selection=selection)
    elif args.command == "sync-daily":
        result = runner.sync_daily(args.date, selection=selection)
    elif args.command == "validate":
        result = runner.validate(args.date, selection=selection)
    elif args.command == "sync-public-assets":
        if getattr(args, "start", "") and getattr(args, "end", ""):
            result = _run_window_sync(
                runner=runner,
                sync_callable=public_runner.sync,
                action_name="sync_public_assets_window",
                scope="public_assets",
                start_date=args.start,
                end_date=args.end,
                families=getattr(args, "family", []),
                force=bool(getattr(args, "force", False)),
            )
        else:
            result = public_runner.sync(args.date, families=getattr(args, "family", []), force=bool(getattr(args, "force", False)))
    elif args.command == "validate-public-assets":
        result = public_runner.validate(args.date, families=getattr(args, "family", []))
    elif args.command == "sync-public-references":
        if getattr(args, "start", "") and getattr(args, "end", ""):
            result = _run_window_sync(
                runner=runner,
                sync_callable=reference_runner.sync,
                action_name="sync_public_references_window",
                scope="public_references",
                start_date=args.start,
                end_date=args.end,
                families=getattr(args, "family", []),
                force=bool(getattr(args, "force", False)),
            )
        else:
            result = reference_runner.sync(args.date, families=getattr(args, "family", []), force=bool(getattr(args, "force", False)))
    elif args.command == "validate-public-references":
        result = reference_runner.validate(args.date, families=getattr(args, "family", []))
    elif args.command == "sync-public-bonds":
        if getattr(args, "start", "") and getattr(args, "end", ""):
            result = _run_window_sync(
                runner=runner,
                sync_callable=bond_runner.sync,
                action_name="sync_public_bonds_window",
                scope="public_bonds",
                start_date=args.start,
                end_date=args.end,
                families=getattr(args, "family", []),
                force=bool(getattr(args, "force", False)),
            )
        else:
            result = bond_runner.sync(args.date, families=getattr(args, "family", []), force=bool(getattr(args, "force", False)))
    elif args.command == "validate-public-bonds":
        result = bond_runner.validate(args.date, families=getattr(args, "family", []))
    elif args.command == "sync-crypto-observation":
        if getattr(args, "start", "") and getattr(args, "end", ""):
            result = _run_window_sync(
                runner=runner,
                sync_callable=lambda trade_date, families=None, force=False: crypto_runner.sync(trade_date, force=force),
                action_name="sync_crypto_observation_window",
                scope="crypto_global",
                start_date=args.start,
                end_date=args.end,
                families=[],
                force=bool(getattr(args, "force", False)),
            )
        else:
            result = crypto_runner.sync(args.date, force=bool(getattr(args, "force", False)))
    elif args.command == "validate-crypto-observation":
        result = crypto_runner.validate(args.date)
    elif args.command == "sync-platform-metadata":
        result = platform_runner.sync(args.date)
    elif args.command == "validate-platform-metadata":
        result = platform_runner.validate(args.date)
    elif args.command == "list-sources":
        catalog = build_source_catalog()
        asset_family = str(getattr(args, "asset_family", "") or "").strip()
        if asset_family:
            catalog = [item for item in catalog if str(item.get("asset_family", "")) == asset_family]
        result = {"sources": catalog, "source_count": len(catalog)}
    elif args.command == "audit":
        result = runner.audit_canonical_dates() if getattr(args, "all", False) else runner.audit_canonical_date(args.date)
    elif args.command == "repair":
        repair_dates = None if getattr(args, "all", False) else getattr(args, "date", [])
        result = runner.repair_canonical_outputs(repair_dates)
    elif args.command == "build-db":
        result = build_duckdb_database()
        result["manifest"] = read_dataset_manifest()
    elif args.command == "export":
        filters = {}
        for raw_filter in getattr(args, "filter", []) or []:
            text = str(raw_filter).strip()
            if not text:
                continue
            if "=" not in text:
                parser.error(f"Invalid --filter value: {text}. Expected key=value.")
            key, value = text.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key or not value:
                parser.error(f"Invalid --filter value: {text}. Expected key=value.")
            filters[key] = value
        result = export_dataset(
            dataset_name=args.dataset,
            output_format=args.format,
            trade_date=(args.date or None),
            filters=filters,
        )
    elif args.command == "pregrab-window":
        result = pregrab_runner.run_window(
            exchanges=pregrab_exchanges or [],
            start_date=args.start,
            end_date=args.end,
            mode=args.mode,
            persist=not bool(getattr(args, "no_persist", False)),
        )
    elif args.command == "environment-check":
        result = run_environment_health_check()
    elif args.command == "research-run":
        result = research_runner.run_research(
            date_value=args.date,
            start_date=getattr(args, "start", ""),
            end_date=getattr(args, "end", ""),
            asset_family=getattr(args, "asset_family", ""),
            dataset=getattr(args, "dataset", ""),
        )
    elif args.command == "factor-run":
        result = research_runner.run_factors(
            start_date=args.start,
            end_date=args.end,
            factor=getattr(args, "factor", "momentum"),
            asset_family=getattr(args, "asset_family", ""),
            dataset=getattr(args, "dataset", "daily_ohlcv"),
        )
    elif args.command == "strategy-backtest":
        result = research_runner.run_strategy_backtest(
            start_date=args.start,
            end_date=args.end,
            strategy=getattr(args, "strategy", "momentum"),
            initial_cash=float(getattr(args, "initial_cash", 1_000_000.0)),
            fee_bps=float(getattr(args, "fee_bps", 2.0)),
            asset_family=getattr(args, "asset_family", ""),
            dataset=getattr(args, "dataset", "daily_ohlcv"),
        )
    elif args.command == "paper-sim":
        result = research_runner.run_paper_sim(
            date_value=args.date,
            strategy=getattr(args, "strategy", "momentum"),
            initial_cash=float(getattr(args, "initial_cash", 1_000_000.0)),
            asset_family=getattr(args, "asset_family", ""),
            dataset=getattr(args, "dataset", "daily_ohlcv"),
        )
    elif args.command == "quality-diagnose":
        result = research_runner.quality_diagnose(date_value=args.date)
    elif args.command == "scheduler-tick":
        result = scheduler_runner.tick(
            run_all_due=not bool(getattr(args, "one", False)),
            schedule_id=getattr(args, "schedule_id", ""),
        )
    elif args.command == "report-generate":
        result = research_runner.report_generate(date_value=args.date, report_type=getattr(args, "report_type", "comprehensive"))
    elif args.command == "algorithm-run":
        result = research_runner.run_algorithm(
            template=getattr(args, "template", ""),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            asset_family=getattr(args, "asset_family", ""),
            params_json=getattr(args, "params", "{}"),
        )
    elif args.command == "risk-run":
        result = research_runner.run_risk(
            template=getattr(args, "template", ""),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            asset_family=getattr(args, "asset_family", ""),
            params_json=getattr(args, "params", "{}"),
        )
    elif args.command == "portfolio-optimize":
        result = research_runner.optimize_portfolio(
            template=getattr(args, "template", ""),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            asset_family=getattr(args, "asset_family", ""),
            params_json=getattr(args, "params", "{}"),
        )
    elif args.command == "backtest-run":
        result = research_runner.run_backtest(
            strategy=getattr(args, "strategy", ""),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            initial_cash=float(getattr(args, "initial_cash", 1_000_000.0)),
            fee_bps=float(getattr(args, "fee_bps", 2.0)),
            slippage_bps=float(getattr(args, "slippage_bps", 1.0)),
            asset_family=getattr(args, "asset_family", ""),
            params_json=getattr(args, "params", "{}"),
        )
    elif args.command == "ml-run":
        result = research_runner.run_ml(
            template=getattr(args, "template", ""),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            target=getattr(args, "target", ""),
            features=getattr(args, "features", ""),
            params_json=getattr(args, "params", "{}"),
            tune=bool(getattr(args, "tune", False)),
            asset_family=getattr(args, "asset_family", ""),
        )
    elif args.command == "experiment-list":
        result = research_runner.experiment_list(date_value=getattr(args, "date", "latest"))
    elif args.command == "factor-performance":
        result = research_runner.factor_performance(
            factor=getattr(args, "factor", "momentum"),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            asset_family=getattr(args, "asset_family", ""),
        )
    elif args.command == "stress-test":
        result = research_runner.stress_test(
            template=getattr(args, "template", ""),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            params_json=getattr(args, "params", "{}"),
            asset_family=getattr(args, "asset_family", ""),
        )
    elif args.command == "quality-score":
        result = research_runner.quality_score(date_value=getattr(args, "date", "latest"))
    elif args.command == "artifact-list":
        result = research_runner.artifact_list(run_id=getattr(args, "run_id", ""), date_value=getattr(args, "date", "latest"))
    elif args.command == "inventory-build":
        result = research_runner.inventory_build(date_value=getattr(args, "date", "latest"))
    elif args.command == "lineage-build":
        result = research_runner.lineage_build(date_value=getattr(args, "date", "latest"))
    elif args.command == "sla-check":
        result = research_runner.sla_check(date_value=getattr(args, "date", "latest"))
    elif args.command == "knowledge-build":
        result = research_runner.knowledge_build(date_value=getattr(args, "date", "latest"))
    elif args.command == "agent-plan":
        result = agent_runner.agent_plan(
            goal=getattr(args, "goal", ""),
            start_date=getattr(args, "start", ""),
            end_date=getattr(args, "end", ""),
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            asset_family=getattr(args, "asset_family", ""),
            mode=getattr(args, "mode", "research"),
            report_type=getattr(args, "report_type", "comprehensive"),
        )
    elif args.command == "agent-run":
        result = agent_runner.agent_run(task_id=getattr(args, "task_id", ""))
    elif args.command == "agent-status":
        result = agent_runner.agent_status(task_id=getattr(args, "task_id", ""), date_value=getattr(args, "date", "latest"))
    elif args.command == "agent-cancel":
        result = agent_runner.agent_cancel(task_id=getattr(args, "task_id", ""))
    elif args.command == "agent-retry":
        result = agent_runner.agent_retry(task_id=getattr(args, "task_id", ""), step_id=getattr(args, "step_id", ""))
    elif args.command == "plugin-list":
        result = agent_runner.plugin_list(date_value=getattr(args, "date", "latest"))
    elif args.command == "plugin-run":
        try:
            plugin_params = json.loads(getattr(args, "params", "{}") or "{}")
            if not isinstance(plugin_params, dict):
                parser.error("--params must be a JSON object")
        except json.JSONDecodeError as exc:
            parser.error(f"Invalid --params JSON: {exc}")
        result = agent_runner.plugin_run(plugin_id=getattr(args, "plugin_id", ""), params=plugin_params)
    elif args.command == "quality-gate":
        result = agent_runner.quality_gate(
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            start_date=getattr(args, "start", ""),
            end_date=getattr(args, "end", ""),
            asset_family=getattr(args, "asset_family", ""),
        )
    elif args.command == "memory-search":
        result = agent_runner.memory_search(query=getattr(args, "query", ""), date_value=getattr(args, "date", "latest"))
    elif args.command == "model-registry-build":
        result = agent_runner.model_registry_build(date_value=getattr(args, "date", "latest"))
    elif args.command == "model-drift-check":
        result = agent_runner.model_drift_check(date_value=getattr(args, "date", "latest"))
    elif args.command == "feature-run":
        result = research_runner.feature_run(
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            asset_family=getattr(args, "asset_family", ""),
            features=getattr(args, "features", ""),
            mode=getattr(args, "mode", "incremental"),
        )
    elif args.command == "ml-benchmark":
        result = research_runner.ml_benchmark(
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            target=getattr(args, "target", ""),
            features=getattr(args, "features", ""),
            models=getattr(args, "models", ""),
            params_json=getattr(args, "params", "{}"),
            asset_family=getattr(args, "asset_family", ""),
        )
    elif args.command == "ml-validate":
        result = research_runner.ml_validate(
            template=getattr(args, "template", ""),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            target=getattr(args, "target", ""),
            features=getattr(args, "features", ""),
            method=getattr(args, "method", "expanding"),
            params_json=getattr(args, "params", "{}"),
            asset_family=getattr(args, "asset_family", ""),
        )
    elif args.command == "factor-experiment":
        result = research_runner.factor_experiment(
            factor=getattr(args, "factor", "momentum"),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            params_json=getattr(args, "params", "{}"),
            asset_family=getattr(args, "asset_family", ""),
        )
    elif args.command == "parameter-scan":
        result = research_runner.parameter_scan(
            template=getattr(args, "template", ""),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            grid_json=getattr(args, "grid", "{}"),
            asset_family=getattr(args, "asset_family", ""),
        )
    elif args.command == "strategy-leaderboard":
        result = research_runner.strategy_leaderboard(
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
        )
    elif args.command == "portfolio-run":
        result = research_runner.portfolio_run(
            template=getattr(args, "template", ""),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            params_json=getattr(args, "params", "{}"),
            asset_family=getattr(args, "asset_family", ""),
        )
    elif args.command == "scenario-sim":
        result = research_runner.scenario_sim(
            template=getattr(args, "template", ""),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            params_json=getattr(args, "params", "{}"),
            asset_family=getattr(args, "asset_family", ""),
        )
    elif args.command == "project-create":
        result = research_runner.project_create(
            name=getattr(args, "name", ""),
            description=getattr(args, "description", ""),
            date_value=getattr(args, "date", "latest"),
        )
    elif args.command == "project-run":
        result = research_runner.project_run(
            project_id=getattr(args, "project_id", ""),
            template=getattr(args, "template", ""),
            start_date=args.start,
            end_date=args.end,
            dataset=getattr(args, "dataset", "daily_ohlcv"),
            params_json=getattr(args, "params", "{}"),
        )
    elif args.command == "package-export":
        result = research_runner.package_export(
            run_id=getattr(args, "run_id", ""),
            date_value=getattr(args, "date", "latest"),
        )
    elif args.command == "history-sync":
        end_value = getattr(args, "end", "") or runner.calendar.previous_trading_day("all", now_shanghai().date()).isoformat()
        mode = str(getattr(args, "mode", "custom") or "custom")
        if mode == "latest":
            start_value = end_value
        elif mode == "1y":
            start_value = (parse_trade_date(end_value) - timedelta(days=365)).isoformat()
        elif mode == "3y":
            start_value = (parse_trade_date(end_value) - timedelta(days=365 * 3)).isoformat()
        elif mode == "all_available":
            start_value = getattr(args, "start", "") or "2010-01-01"
        else:
            start_value = getattr(args, "start", "")
        if not start_value:
            parser.error("history-sync custom mode requires --start")
        scope = str(getattr(args, "scope", "public_assets") or "public_assets")
        candidate_dates = _history_sync_candidate_dates(
            runner=runner,
            mode=mode,
            start_date=start_value,
            end_date=end_value,
        )
        if scope == "derivatives":
            result = _run_window_sync(
                runner=runner,
                sync_callable=lambda trade_date, families=None, force=False: runner.fetch_date(
                    trade_date,
                    selection=CrawlSelection(instrument_group="all"),
                ),
                action_name="history_sync_derivatives",
                scope=scope,
                start_date=start_value,
                end_date=end_value,
                candidate_dates=candidate_dates,
            )
        elif scope == "public_references":
            result = _run_window_sync(runner=runner, sync_callable=reference_runner.sync, action_name="history_sync_public_references", scope=scope, start_date=start_value, end_date=end_value, candidate_dates=candidate_dates)
        elif scope == "public_bonds":
            result = _run_window_sync(runner=runner, sync_callable=bond_runner.sync, action_name="history_sync_public_bonds", scope=scope, start_date=start_value, end_date=end_value, candidate_dates=candidate_dates)
        elif scope == "crypto_observation":
            result = _run_window_sync(
                runner=runner,
                sync_callable=lambda trade_date, families=None, force=False: crypto_runner.sync(trade_date, force=force),
                action_name="history_sync_crypto_observation",
                scope=scope,
                start_date=start_value,
                end_date=end_value,
                candidate_dates=candidate_dates,
            )
        else:
            result = _run_window_sync(runner=runner, sync_callable=public_runner.sync, action_name="history_sync_public_assets", scope=scope, start_date=start_value, end_date=end_value, candidate_dates=candidate_dates)
    elif args.command in {"gui", "serve-gui"}:
        return gui_module.main(["--host", args.host, "--port", str(args.port)])
    elif args.command == "regression-smoke":
        dates = getattr(args, "date", []) or ["2010-04-16", "2015-04-16", "2021-04-16", "2026-04-16"]
        include_build_db = not bool(getattr(args, "skip_build_db", False))
        include_gui_smoke = not bool(getattr(args, "skip_gui_smoke", False))
        if getattr(args, "profile", "core") == "phase2":
            latest_trade_date = runner.calendar.previous_trading_day("all", now_shanghai().date()).isoformat()
            if latest_trade_date not in dates:
                dates.append(latest_trade_date)
            include_build_db = True
            include_gui_smoke = True
        result = run_regression_smoke(
            runner=runner,
            platform_runner=platform_runner,
            trade_dates=dates,
            profile=getattr(args, "profile", "core"),
            include_build_db=include_build_db,
            include_gui_smoke=include_gui_smoke,
        )
    else:  # pragma: no cover
        parser.error(f"Unsupported command: {args.command}")
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
