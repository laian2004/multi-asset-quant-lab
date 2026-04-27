from pathlib import Path
from typing import Dict, List, Optional

import duckdb

from .config import DUCKDB_PATH, EXPORT_CSV_DIR, EXPORT_JSON_DIR, EXPORT_PARQUET_DIR, NORMALIZED_ROOT, PROJECT_ROOT
from .constants import (
    ALGORITHM_OUTPUTS_DATASET,
    ANOMALY_EVENTS_DATASET,
    ARTIFACT_MANIFEST_DATASET,
    ASSET_COVERAGE_DATASET,
    BACKTEST_INPUT_QUALITY_DATASET,
    BACKTEST_EQUITY_CURVES_DATASET,
    BACKTEST_POSITIONS_DATASET,
    BACKTEST_TRADES_DATASET,
    COVERAGE_HISTORY_DATASET,
    CARBON_MARKET_SNAPSHOT_DATASET,
    BOND_ANALYTICS_DATASET,
    BOND_MASTER_DATASET,
    BOND_QUOTES_DATASET,
    CN_US_TREASURY_RATE_DATASET,
    COMMODITY_SPOT_QUOTES_DATASET,
    CONTRACTS_DATASET,
    CONVERTIBLE_BOND_SNAPSHOT_DATASET,
    CRYPTO_ASSETS_DATASET,
    CRYPTO_BITCOIN_HOLDINGS_DATASET,
    CRYPTO_CME_BITCOIN_REPORT_DATASET,
    CRYPTO_DAILY_QUOTES_DATASET,
    CRYPTO_DERIVATIVES_PUBLIC_DATASET,
    CRYPTO_GLOBAL_SNAPSHOT_DATASET,
    CRYPTO_GLOBAL_QUOTES_DATASET,
    DAILY_OHLCV_DATASET,
    DATASET_FIELD_PROFILE_DATASET,
    DATASET_INVENTORY_DATASET,
    DATASET_QUALITY_SCORES_DATASET,
    DATASET_SLA_RULES_DATASET,
    DATA_LINEAGE_DATASET,
    DERIVATIVES_DATASET,
    EQUITIES_SNAPSHOT_DATASET,
    ETF_SNAPSHOT_DATASET,
    EXPERIMENT_RUNS_DATASET,
    FUTURES_DATASET,
    FUTURES_RESULTS_DATASET,
    FUND_NAV_DATASET,
    FACTOR_EXPERIMENTS_DATASET,
    FACTOR_SIGNALS_DATASET,
    FACTOR_PERFORMANCE_DATASET,
    FX_C_SWAP_CURVE_DATASET,
    FX_PAIR_DATASET,
    FX_REFERENCE_DATASET,
    FX_QUOTES_DATASET,
    RMB_MIDDLE_RATE_DATASET,
    FX_SPOT_DATASET,
    INTERBANK_BOND_DEAL_DATASET,
    INTERBANK_BOND_QUOTE_DATASET,
    LOF_SNAPSHOT_DATASET,
    LPR_REFERENCE_DATASET,
    MONEY_FUND_SNAPSHOT_DATASET,
    MONEY_MARKET_DATASET,
    KNOWLEDGE_INDEX_DATASET,
    ML_BENCHMARKS_DATASET,
    ML_CLASSIFICATION_RESULTS_DATASET,
    ML_FEATURE_IMPORTANCE_DATASET,
    ML_FEATURE_STORE_DATASET,
    ML_VALIDATION_FOLDS_DATASET,
    ML_MODEL_RUNS_DATASET,
    ML_PREDICTIONS_DATASET,
    MODEL_DIAGNOSTICS_DATASET,
    OPEN_FUND_SNAPSHOT_DATASET,
    OPTIONS_CHAIN_VIEW,
    OPTIONS_DATASET,
    OPTION_RESULTS_DATASET,
    OPTION_ANALYTICS_DATASET,
    PRECIOUS_METAL_REFERENCE_DATASET,
    RESERVE_REFERENCE_DATASET,
    REITS_SNAPSHOT_DATASET,
    REITS_QUOTES_DATASET,
    REPO_REFERENCE_DATASET,
    REPORT_ARTIFACTS_DATASET,
    RISK_METRICS_DATASET,
    RUN_HEALTH_DATASET,
    RUN_HISTORY_DATASET,
    PAPER_PORTFOLIOS_DATASET,
    PARAMETER_SCANS_DATASET,
    PORTFOLIO_ALLOCATIONS_DATASET,
    PORTFOLIO_EXPERIMENTS_DATASET,
    PROJECT_RUNS_DATASET,
    SGE_SPOT_DAILY_DATASET,
    QUALITY_DIAGNOSTICS_DATASET,
    RESEARCH_METRICS_DATASET,
    RESEARCH_PROJECTS_DATASET,
    RESEARCH_REPORTS_DATASET,
    REPRODUCIBLE_PACKAGES_DATASET,
    SOURCE_HEALTH_DATASET,
    SOURCE_HEALTH_HISTORY_DATASET,
    SOURCE_TYPE_OVERVIEW_DATASET,
    SLA_VIOLATIONS_DATASET,
    SCHEDULER_RUNS_DATASET,
    SCENARIO_SIMULATIONS_DATASET,
    SSE_BOND_CASH_SUMMARY_DATASET,
    SSE_BOND_DEAL_SUMMARY_DATASET,
    STRATEGY_BACKTESTS_DATASET,
    STRATEGY_COMPARISONS_DATASET,
    STRATEGY_LEADERBOARD_DATASET,
    STRESS_TEST_RESULTS_DATASET,
    TRADING_CALENDAR_DATASET,
    UNDERLYING_SUMMARY_VIEW,
    INSTRUMENT_MASTER_DATASET,
    ISSUE_CATEGORY_OVERVIEW_DATASET,
    VALIDATION_RESULTS_DATASET,
    YIELD_CURVE_DATASET,
    YIELD_CURVES_PLATFORM_DATASET,
    CURVE_ANALYTICS_DATASET,
    FX_SWAP_DATASET,
    AGENT_TASKS_DATASET,
    AGENT_STEPS_DATASET,
    PLUGIN_REGISTRY_DATASET,
    PLUGIN_RUNS_DATASET,
    RESEARCH_MEMORY_DATASET,
    EXPERIMENT_NOTES_DATASET,
    DECISION_LOG_DATASET,
    QUALITY_GATES_DATASET,
    RESEARCH_READINESS_DATASET,
    INPUT_RISK_FLAGS_DATASET,
    TASK_QUEUE_DATASET,
    TASK_LOGS_DATASET,
    TASK_RETRIES_DATASET,
    REPORT_INSIGHTS_DATASET,
    RECOMMENDATION_ITEMS_DATASET,
    MODEL_REGISTRY_DATASET,
    FEATURE_VERSIONS_DATASET,
    MODEL_DRIFT_EVENTS_DATASET,
)
from .utils import ensure_directory, iso_timestamp


DATASET_GLOBS = {
    FUTURES_DATASET: "daily_quotes/*.csv",
    OPTIONS_DATASET: "options/daily_quotes/*.csv",
    DERIVATIVES_DATASET: "derivatives/daily_quotes/*.csv",
    CONTRACTS_DATASET: "master/contracts/*.csv",
    OPTION_RESULTS_DATASET: "results/options_exercise/*.csv",
    FUTURES_RESULTS_DATASET: "results/futures_delivery/*.csv",
    OPTIONS_CHAIN_VIEW: "views/options_chain_matrix/*.csv",
    UNDERLYING_SUMMARY_VIEW: "views/underlying_derivatives_summary/*.csv",
    EQUITIES_SNAPSHOT_DATASET: f"public_assets/{EQUITIES_SNAPSHOT_DATASET}/*.csv",
    ETF_SNAPSHOT_DATASET: f"public_assets/{ETF_SNAPSHOT_DATASET}/*.csv",
    LOF_SNAPSHOT_DATASET: f"public_assets/{LOF_SNAPSHOT_DATASET}/*.csv",
    OPEN_FUND_SNAPSHOT_DATASET: f"public_assets/{OPEN_FUND_SNAPSHOT_DATASET}/*.csv",
    MONEY_FUND_SNAPSHOT_DATASET: f"public_assets/{MONEY_FUND_SNAPSHOT_DATASET}/*.csv",
    REITS_SNAPSHOT_DATASET: f"public_assets/{REITS_SNAPSHOT_DATASET}/*.csv",
    CONVERTIBLE_BOND_SNAPSHOT_DATASET: f"public_assets/{CONVERTIBLE_BOND_SNAPSHOT_DATASET}/*.csv",
    SGE_SPOT_DAILY_DATASET: f"public_assets/{SGE_SPOT_DAILY_DATASET}/*.csv",
    CARBON_MARKET_SNAPSHOT_DATASET: f"public_assets/{CARBON_MARKET_SNAPSHOT_DATASET}/*.csv",
    FX_REFERENCE_DATASET: f"public_references/{FX_REFERENCE_DATASET}/*.csv",
    RMB_MIDDLE_RATE_DATASET: f"public_references/{RMB_MIDDLE_RATE_DATASET}/*.csv",
    FX_SPOT_DATASET: f"public_references/{FX_SPOT_DATASET}/*.csv",
    FX_PAIR_DATASET: f"public_references/{FX_PAIR_DATASET}/*.csv",
    FX_SWAP_DATASET: f"public_references/{FX_SWAP_DATASET}/*.csv",
    FX_C_SWAP_CURVE_DATASET: f"public_references/{FX_C_SWAP_CURVE_DATASET}/*.csv",
    MONEY_MARKET_DATASET: f"public_references/{MONEY_MARKET_DATASET}/*.csv",
    RESERVE_REFERENCE_DATASET: f"public_references/{RESERVE_REFERENCE_DATASET}/*.csv",
    LPR_REFERENCE_DATASET: f"public_references/{LPR_REFERENCE_DATASET}/*.csv",
    REPO_REFERENCE_DATASET: f"public_references/{REPO_REFERENCE_DATASET}/*.csv",
    CN_US_TREASURY_RATE_DATASET: f"public_references/{CN_US_TREASURY_RATE_DATASET}/*.csv",
    PRECIOUS_METAL_REFERENCE_DATASET: f"public_references/{PRECIOUS_METAL_REFERENCE_DATASET}/*.csv",
    INTERBANK_BOND_DEAL_DATASET: f"public_bonds/{INTERBANK_BOND_DEAL_DATASET}/*.csv",
    INTERBANK_BOND_QUOTE_DATASET: f"public_bonds/{INTERBANK_BOND_QUOTE_DATASET}/*.csv",
    YIELD_CURVE_DATASET: f"public_bonds/{YIELD_CURVE_DATASET}/*.csv",
    SSE_BOND_DEAL_SUMMARY_DATASET: f"public_bonds/{SSE_BOND_DEAL_SUMMARY_DATASET}/*.csv",
    SSE_BOND_CASH_SUMMARY_DATASET: f"public_bonds/{SSE_BOND_CASH_SUMMARY_DATASET}/*.csv",
    CRYPTO_GLOBAL_SNAPSHOT_DATASET: f"crypto_global/{CRYPTO_GLOBAL_SNAPSHOT_DATASET}/*.csv",
    CRYPTO_ASSETS_DATASET: f"crypto_global/{CRYPTO_ASSETS_DATASET}/*.csv",
    CRYPTO_DAILY_QUOTES_DATASET: f"crypto_global/{CRYPTO_DAILY_QUOTES_DATASET}/*.csv",
    CRYPTO_DERIVATIVES_PUBLIC_DATASET: f"crypto_global/{CRYPTO_DERIVATIVES_PUBLIC_DATASET}/*.csv",
    CRYPTO_BITCOIN_HOLDINGS_DATASET: f"crypto_global/{CRYPTO_BITCOIN_HOLDINGS_DATASET}/*.csv",
    CRYPTO_CME_BITCOIN_REPORT_DATASET: f"crypto_global/{CRYPTO_CME_BITCOIN_REPORT_DATASET}/*.csv",
    INSTRUMENT_MASTER_DATASET: f"platform/{INSTRUMENT_MASTER_DATASET}/*.csv",
    BOND_MASTER_DATASET: f"platform/{BOND_MASTER_DATASET}/*.csv",
    BOND_QUOTES_DATASET: f"platform/{BOND_QUOTES_DATASET}/*.csv",
    FX_QUOTES_DATASET: f"platform/{FX_QUOTES_DATASET}/*.csv",
    COMMODITY_SPOT_QUOTES_DATASET: f"platform/{COMMODITY_SPOT_QUOTES_DATASET}/*.csv",
    CRYPTO_GLOBAL_QUOTES_DATASET: f"platform/{CRYPTO_GLOBAL_QUOTES_DATASET}/*.csv",
    YIELD_CURVES_PLATFORM_DATASET: f"platform/{YIELD_CURVES_PLATFORM_DATASET}/*.csv",
    DAILY_OHLCV_DATASET: f"platform/{DAILY_OHLCV_DATASET}/*.csv",
    FUND_NAV_DATASET: f"platform/{FUND_NAV_DATASET}/*.csv",
    REITS_QUOTES_DATASET: f"platform/{REITS_QUOTES_DATASET}/*.csv",
    TRADING_CALENDAR_DATASET: f"platform/{TRADING_CALENDAR_DATASET}/*.csv",
    ASSET_COVERAGE_DATASET: f"platform/{ASSET_COVERAGE_DATASET}/*.csv",
    RUN_HEALTH_DATASET: f"platform/{RUN_HEALTH_DATASET}/*.csv",
    RUN_HISTORY_DATASET: f"platform/{RUN_HISTORY_DATASET}/*.csv",
    COVERAGE_HISTORY_DATASET: f"platform/{COVERAGE_HISTORY_DATASET}/*.csv",
    VALIDATION_RESULTS_DATASET: f"platform/{VALIDATION_RESULTS_DATASET}/*.csv",
    SOURCE_HEALTH_DATASET: f"platform/{SOURCE_HEALTH_DATASET}/*.csv",
    SOURCE_HEALTH_HISTORY_DATASET: f"platform/{SOURCE_HEALTH_HISTORY_DATASET}/*.csv",
    SOURCE_TYPE_OVERVIEW_DATASET: f"platform/{SOURCE_TYPE_OVERVIEW_DATASET}/*.csv",
    ISSUE_CATEGORY_OVERVIEW_DATASET: f"platform/{ISSUE_CATEGORY_OVERVIEW_DATASET}/*.csv",
    RESEARCH_METRICS_DATASET: f"platform/{RESEARCH_METRICS_DATASET}/*.csv",
    FACTOR_SIGNALS_DATASET: f"platform/{FACTOR_SIGNALS_DATASET}/*.csv",
    STRATEGY_BACKTESTS_DATASET: f"platform/{STRATEGY_BACKTESTS_DATASET}/*.csv",
    PAPER_PORTFOLIOS_DATASET: f"platform/{PAPER_PORTFOLIOS_DATASET}/*.csv",
    QUALITY_DIAGNOSTICS_DATASET: f"platform/{QUALITY_DIAGNOSTICS_DATASET}/*.csv",
    SCHEDULER_RUNS_DATASET: f"platform/{SCHEDULER_RUNS_DATASET}/*.csv",
    RESEARCH_REPORTS_DATASET: f"platform/{RESEARCH_REPORTS_DATASET}/*.csv",
    ALGORITHM_OUTPUTS_DATASET: f"platform/{ALGORITHM_OUTPUTS_DATASET}/*.csv",
    OPTION_ANALYTICS_DATASET: f"platform/{OPTION_ANALYTICS_DATASET}/*.csv",
    BOND_ANALYTICS_DATASET: f"platform/{BOND_ANALYTICS_DATASET}/*.csv",
    CURVE_ANALYTICS_DATASET: f"platform/{CURVE_ANALYTICS_DATASET}/*.csv",
    RISK_METRICS_DATASET: f"platform/{RISK_METRICS_DATASET}/*.csv",
    PORTFOLIO_ALLOCATIONS_DATASET: f"platform/{PORTFOLIO_ALLOCATIONS_DATASET}/*.csv",
    BACKTEST_EQUITY_CURVES_DATASET: f"platform/{BACKTEST_EQUITY_CURVES_DATASET}/*.csv",
    BACKTEST_POSITIONS_DATASET: f"platform/{BACKTEST_POSITIONS_DATASET}/*.csv",
    BACKTEST_TRADES_DATASET: f"platform/{BACKTEST_TRADES_DATASET}/*.csv",
    STRATEGY_COMPARISONS_DATASET: f"platform/{STRATEGY_COMPARISONS_DATASET}/*.csv",
    ANOMALY_EVENTS_DATASET: f"platform/{ANOMALY_EVENTS_DATASET}/*.csv",
    ML_MODEL_RUNS_DATASET: f"platform/{ML_MODEL_RUNS_DATASET}/*.csv",
    ML_PREDICTIONS_DATASET: f"platform/{ML_PREDICTIONS_DATASET}/*.csv",
    ML_FEATURE_IMPORTANCE_DATASET: f"platform/{ML_FEATURE_IMPORTANCE_DATASET}/*.csv",
    MODEL_DIAGNOSTICS_DATASET: f"platform/{MODEL_DIAGNOSTICS_DATASET}/*.csv",
    BACKTEST_INPUT_QUALITY_DATASET: f"platform/{BACKTEST_INPUT_QUALITY_DATASET}/*.csv",
    EXPERIMENT_RUNS_DATASET: f"platform/{EXPERIMENT_RUNS_DATASET}/*.csv",
    FACTOR_PERFORMANCE_DATASET: f"platform/{FACTOR_PERFORMANCE_DATASET}/*.csv",
    STRESS_TEST_RESULTS_DATASET: f"platform/{STRESS_TEST_RESULTS_DATASET}/*.csv",
    ARTIFACT_MANIFEST_DATASET: f"platform/{ARTIFACT_MANIFEST_DATASET}/*.csv",
    DATASET_QUALITY_SCORES_DATASET: f"platform/{DATASET_QUALITY_SCORES_DATASET}/*.csv",
    REPORT_ARTIFACTS_DATASET: f"platform/{REPORT_ARTIFACTS_DATASET}/*.csv",
    DATASET_INVENTORY_DATASET: f"platform/{DATASET_INVENTORY_DATASET}/*.csv",
    DATASET_FIELD_PROFILE_DATASET: f"platform/{DATASET_FIELD_PROFILE_DATASET}/*.csv",
    DATA_LINEAGE_DATASET: f"platform/{DATA_LINEAGE_DATASET}/*.csv",
    DATASET_SLA_RULES_DATASET: f"platform/{DATASET_SLA_RULES_DATASET}/*.csv",
    SLA_VIOLATIONS_DATASET: f"platform/{SLA_VIOLATIONS_DATASET}/*.csv",
    KNOWLEDGE_INDEX_DATASET: f"platform/{KNOWLEDGE_INDEX_DATASET}/*.csv",
    ML_FEATURE_STORE_DATASET: f"platform/{ML_FEATURE_STORE_DATASET}/*.csv",
    ML_BENCHMARKS_DATASET: f"platform/{ML_BENCHMARKS_DATASET}/*.csv",
    ML_VALIDATION_FOLDS_DATASET: f"platform/{ML_VALIDATION_FOLDS_DATASET}/*.csv",
    ML_CLASSIFICATION_RESULTS_DATASET: f"platform/{ML_CLASSIFICATION_RESULTS_DATASET}/*.csv",
    FACTOR_EXPERIMENTS_DATASET: f"platform/{FACTOR_EXPERIMENTS_DATASET}/*.csv",
    PARAMETER_SCANS_DATASET: f"platform/{PARAMETER_SCANS_DATASET}/*.csv",
    STRATEGY_LEADERBOARD_DATASET: f"platform/{STRATEGY_LEADERBOARD_DATASET}/*.csv",
    PORTFOLIO_EXPERIMENTS_DATASET: f"platform/{PORTFOLIO_EXPERIMENTS_DATASET}/*.csv",
    SCENARIO_SIMULATIONS_DATASET: f"platform/{SCENARIO_SIMULATIONS_DATASET}/*.csv",
    RESEARCH_PROJECTS_DATASET: f"platform/{RESEARCH_PROJECTS_DATASET}/*.csv",
    PROJECT_RUNS_DATASET: f"platform/{PROJECT_RUNS_DATASET}/*.csv",
    REPRODUCIBLE_PACKAGES_DATASET: f"platform/{REPRODUCIBLE_PACKAGES_DATASET}/*.csv",
    AGENT_TASKS_DATASET: f"platform/{AGENT_TASKS_DATASET}/*.csv",
    AGENT_STEPS_DATASET: f"platform/{AGENT_STEPS_DATASET}/*.csv",
    PLUGIN_REGISTRY_DATASET: f"platform/{PLUGIN_REGISTRY_DATASET}/*.csv",
    PLUGIN_RUNS_DATASET: f"platform/{PLUGIN_RUNS_DATASET}/*.csv",
    RESEARCH_MEMORY_DATASET: f"platform/{RESEARCH_MEMORY_DATASET}/*.csv",
    EXPERIMENT_NOTES_DATASET: f"platform/{EXPERIMENT_NOTES_DATASET}/*.csv",
    DECISION_LOG_DATASET: f"platform/{DECISION_LOG_DATASET}/*.csv",
    QUALITY_GATES_DATASET: f"platform/{QUALITY_GATES_DATASET}/*.csv",
    RESEARCH_READINESS_DATASET: f"platform/{RESEARCH_READINESS_DATASET}/*.csv",
    INPUT_RISK_FLAGS_DATASET: f"platform/{INPUT_RISK_FLAGS_DATASET}/*.csv",
    TASK_QUEUE_DATASET: f"platform/{TASK_QUEUE_DATASET}/*.csv",
    TASK_LOGS_DATASET: f"platform/{TASK_LOGS_DATASET}/*.csv",
    TASK_RETRIES_DATASET: f"platform/{TASK_RETRIES_DATASET}/*.csv",
    REPORT_INSIGHTS_DATASET: f"platform/{REPORT_INSIGHTS_DATASET}/*.csv",
    RECOMMENDATION_ITEMS_DATASET: f"platform/{RECOMMENDATION_ITEMS_DATASET}/*.csv",
    MODEL_REGISTRY_DATASET: f"platform/{MODEL_REGISTRY_DATASET}/*.csv",
    FEATURE_VERSIONS_DATASET: f"platform/{FEATURE_VERSIONS_DATASET}/*.csv",
    MODEL_DRIFT_EVENTS_DATASET: f"platform/{MODEL_DRIFT_EVENTS_DATASET}/*.csv",
}


def build_dataset_index(normalized_root: Path = NORMALIZED_ROOT) -> Dict[str, List[Path]]:
    dataset_map: Dict[str, List[Path]] = {}
    for dataset_name, pattern in DATASET_GLOBS.items():
        csv_paths = sorted(normalized_root.glob(pattern))
        if csv_paths:
            dataset_map[dataset_name] = csv_paths
    return {key: sorted(value) for key, value in sorted(dataset_map.items())}


def build_duckdb_database(
    *,
    database_path: Path = DUCKDB_PATH,
    normalized_root: Path = NORMALIZED_ROOT,
) -> Dict[str, object]:
    dataset_index = build_dataset_index(normalized_root)
    ensure_directory(database_path.parent)
    try:
        manifest_rows = _materialize_duckdb_database(database_path=database_path, dataset_index=dataset_index)
        return {
            "database_path": _relative(database_path),
            "dataset_count": len(dataset_index),
            "datasets": manifest_rows,
            "status": "success",
            "target_locked": False,
        }
    except duckdb.IOException as exc:
        if "Could not set lock" not in str(exc):
            raise
        fallback_path = database_path.with_name(f"{database_path.stem}.rebuild{database_path.suffix}")
        manifest_rows = _materialize_duckdb_database(database_path=fallback_path, dataset_index=dataset_index)
        return {
            "database_path": _relative(fallback_path),
            "target_database_path": _relative(database_path),
            "dataset_count": len(dataset_index),
            "datasets": manifest_rows,
            "status": "pending_retry",
            "target_locked": True,
            "message": f"DuckDB 主库当前被占用，已写入备用库 {fallback_path.name}；锁释放后可重跑 build-db 覆盖正式索引。",
        }


def _materialize_duckdb_database(*, database_path: Path, dataset_index: Dict[str, List[Path]]) -> List[Dict[str, object]]:
    connection = duckdb.connect(str(database_path))
    connection.execute("CREATE SCHEMA IF NOT EXISTS normalized")
    connection.execute("CREATE SCHEMA IF NOT EXISTS meta")
    manifest_rows = []

    for dataset_name, csv_paths in dataset_index.items():
        quoted_paths = ", ".join(_sql_quote(str(path)) for path in csv_paths)
        relation = f"read_csv_auto([{quoted_paths}], header=true, union_by_name=true, all_varchar=true)"
        connection.execute(
            f'CREATE OR REPLACE VIEW normalized."{dataset_name}" AS SELECT * FROM {relation}'
        )
        row_count = connection.execute(
            f'SELECT COUNT(*) FROM normalized."{dataset_name}"'
        ).fetchone()[0]
        manifest_rows.append(
            {
                "dataset": dataset_name,
                "file_count": len(csv_paths),
                "row_count": int(row_count),
                "built_at": iso_timestamp(),
            }
        )

    connection.execute("DROP TABLE IF EXISTS meta.dataset_manifest")
    connection.execute(
        "CREATE TABLE meta.dataset_manifest(dataset VARCHAR, file_count BIGINT, row_count BIGINT, built_at VARCHAR)"
    )
    if manifest_rows:
        connection.executemany(
            "INSERT INTO meta.dataset_manifest VALUES (?, ?, ?, ?)",
            [
                (row["dataset"], row["file_count"], row["row_count"], row["built_at"])
                for row in manifest_rows
            ],
        )
    connection.close()
    return manifest_rows


def export_dataset(
    *,
    dataset_name: str,
    output_format: str,
    trade_date: Optional[str] = None,
    filters: Optional[Dict[str, str]] = None,
    database_path: Path = DUCKDB_PATH,
    output_path: Optional[Path] = None,
) -> Dict[str, object]:
    ensure_directory(database_path.parent)
    if not database_path.exists():
        build_duckdb_database(database_path=database_path)
    connection = duckdb.connect(str(database_path), read_only=True)
    available_columns = {
        str(row[0])
        for row in connection.execute(
            f'DESCRIBE SELECT * FROM normalized."{dataset_name}"'
        ).fetchall()
    }
    where_parts: List[str] = []
    params: List[object] = []
    if trade_date and "trade_date" in available_columns:
        where_parts.append("trade_date = ?")
        params.append(trade_date)
    for field, value in sorted((filters or {}).items()):
        normalized_value = str(value or "").strip()
        if not normalized_value or field not in available_columns:
            continue
        where_parts.append(f'"{field}" = ?')
        params.append(normalized_value)

    where_clause = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""
    relation = connection.execute(
        f'SELECT * FROM normalized."{dataset_name}"{where_clause}',
        params,
    ).fetchdf()
    connection.close()

    if output_path is None:
        suffix = {"csv": ".csv", "json": ".json", "parquet": ".parquet"}[output_format]
        base_dir = {
            "csv": EXPORT_CSV_DIR,
            "json": EXPORT_JSON_DIR,
            "parquet": EXPORT_PARQUET_DIR,
        }[output_format]
        ensure_directory(base_dir / dataset_name)
        suffix_prefix = trade_date or "latest"
        output_path = base_dir / dataset_name / f"{suffix_prefix}{suffix}"
    else:
        ensure_directory(output_path.parent)

    if output_format == "csv":
        relation.to_csv(output_path, index=False, encoding="utf-8-sig")
    elif output_format == "json":
        output_path.write_text(
            relation.to_json(orient="records", force_ascii=False, indent=2),
            encoding="utf-8",
        )
    elif output_format == "parquet":
        relation.to_parquet(output_path, index=False)
    else:
        raise ValueError(f"Unsupported export format: {output_format}")

    return {
        "dataset": dataset_name,
        "trade_date": trade_date or "",
        "filters": {key: str(value) for key, value in sorted((filters or {}).items()) if str(value or "").strip()},
        "output_format": output_format,
        "row_count": int(len(relation)),
        "output_path": _relative(output_path),
    }


def read_dataset_manifest(database_path: Path = DUCKDB_PATH) -> List[Dict[str, object]]:
    if not database_path.exists():
        return []
    connection = duckdb.connect(str(database_path), read_only=True)
    try:
        rows = connection.execute(
            "SELECT dataset, file_count, row_count, built_at FROM meta.dataset_manifest ORDER BY dataset"
        ).fetchall()
    finally:
        connection.close()
    return [
        {
            "dataset": row[0],
            "file_count": int(row[1]),
            "row_count": int(row[2]),
            "built_at": row[3],
        }
        for row in rows
    ]


def _relative(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
