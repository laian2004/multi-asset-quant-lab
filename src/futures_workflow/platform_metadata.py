import hashlib
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from .config import PLATFORM_METADATA_STATE_PATH, PLATFORM_NORMALIZED_DIR, PREGRAB_STATE_PATH, PROJECT_ROOT, WINDOW_RUNS_STATE_PATH
from .constants import (
    ALGORITHM_OUTPUTS_DATASET,
    ALGORITHM_OUTPUTS_STANDARD_FIELDS,
    ANOMALY_EVENTS_DATASET,
    ANOMALY_EVENTS_STANDARD_FIELDS,
    ARTIFACT_MANIFEST_DATASET,
    ARTIFACT_MANIFEST_STANDARD_FIELDS,
    ASSET_COVERAGE_DATASET,
    ASSET_COVERAGE_STANDARD_FIELDS,
    BACKTEST_INPUT_QUALITY_DATASET,
    BACKTEST_INPUT_QUALITY_STANDARD_FIELDS,
    BACKTEST_EQUITY_CURVES_DATASET,
    BACKTEST_EQUITY_CURVES_STANDARD_FIELDS,
    BACKTEST_POSITIONS_DATASET,
    BACKTEST_POSITIONS_STANDARD_FIELDS,
    BACKTEST_TRADES_DATASET,
    BACKTEST_TRADES_STANDARD_FIELDS,
    COVERAGE_HISTORY_DATASET,
    COVERAGE_HISTORY_STANDARD_FIELDS,
    BOND_ANALYTICS_DATASET,
    BOND_ANALYTICS_STANDARD_FIELDS,
    BOND_MASTER_DATASET,
    BOND_MASTER_STANDARD_FIELDS,
    BOND_QUOTES_DATASET,
    BOND_QUOTES_STANDARD_FIELDS,
    COMMODITY_SPOT_QUOTES_DATASET,
    COMMODITY_SPOT_QUOTES_STANDARD_FIELDS,
    CONTRACTS_DATASET,
    CRYPTO_DAILY_QUOTES_DATASET,
    CRYPTO_GLOBAL_QUOTES_DATASET,
    CRYPTO_GLOBAL_QUOTES_STANDARD_FIELDS,
    CRYPTO_GLOBAL_SNAPSHOT_DATASET,
    CURVE_ANALYTICS_DATASET,
    CURVE_ANALYTICS_STANDARD_FIELDS,
    DAILY_OHLCV_DATASET,
    DAILY_OHLCV_STANDARD_FIELDS,
    DATASET_FIELD_PROFILE_DATASET,
    DATASET_FIELD_PROFILE_STANDARD_FIELDS,
    DATASET_INVENTORY_DATASET,
    DATASET_INVENTORY_STANDARD_FIELDS,
    DATASET_QUALITY_SCORES_DATASET,
    DATASET_QUALITY_SCORES_STANDARD_FIELDS,
    DATASET_SLA_RULES_DATASET,
    DATASET_SLA_RULES_STANDARD_FIELDS,
    DATA_LINEAGE_DATASET,
    DATA_LINEAGE_STANDARD_FIELDS,
    EXPERIMENT_RUNS_DATASET,
    EXPERIMENT_RUNS_STANDARD_FIELDS,
    FACTOR_EXPERIMENTS_DATASET,
    FACTOR_EXPERIMENTS_STANDARD_FIELDS,
    FACTOR_SIGNALS_DATASET,
    FACTOR_SIGNALS_STANDARD_FIELDS,
    FACTOR_PERFORMANCE_DATASET,
    FACTOR_PERFORMANCE_STANDARD_FIELDS,
    FAILED_STATUS,
    FUND_NAV_DATASET,
    FUND_NAV_STANDARD_FIELDS,
    FX_QUOTES_DATASET,
    FX_QUOTES_STANDARD_FIELDS,
    FUTURES_DATASET,
    FUTURES_RESULTS_DATASET,
    INSTRUMENT_MASTER_DATASET,
    INSTRUMENT_MASTER_STANDARD_FIELDS,
    ISSUE_CATEGORY_OVERVIEW_DATASET,
    ISSUE_CATEGORY_OVERVIEW_STANDARD_FIELDS,
    CN_US_TREASURY_RATE_DATASET,
    KNOWLEDGE_INDEX_DATASET,
    KNOWLEDGE_INDEX_STANDARD_FIELDS,
    ML_BENCHMARKS_DATASET,
    ML_BENCHMARKS_STANDARD_FIELDS,
    ML_CLASSIFICATION_RESULTS_DATASET,
    ML_CLASSIFICATION_RESULTS_STANDARD_FIELDS,
    ML_FEATURE_IMPORTANCE_DATASET,
    ML_FEATURE_IMPORTANCE_STANDARD_FIELDS,
    ML_FEATURE_STORE_DATASET,
    ML_FEATURE_STORE_STANDARD_FIELDS,
    ML_MODEL_RUNS_DATASET,
    ML_MODEL_RUNS_STANDARD_FIELDS,
    ML_PREDICTIONS_DATASET,
    ML_PREDICTIONS_STANDARD_FIELDS,
    ML_VALIDATION_FOLDS_DATASET,
    ML_VALIDATION_FOLDS_STANDARD_FIELDS,
    MODEL_DIAGNOSTICS_DATASET,
    MODEL_DIAGNOSTICS_STANDARD_FIELDS,
    NOT_APPLICABLE_STATUS,
    NO_DATA_STATUS,
    OPTION_RESULTS_DATASET,
    OPTION_ANALYTICS_DATASET,
    OPTION_ANALYTICS_STANDARD_FIELDS,
    OPTIONS_DATASET,
    OPTIONS_CHAIN_VIEW,
    PARTIAL_SUCCESS_STATUS,
    PAPER_PORTFOLIOS_DATASET,
    PAPER_PORTFOLIOS_STANDARD_FIELDS,
    PARAMETER_SCANS_DATASET,
    PARAMETER_SCANS_STANDARD_FIELDS,
    PORTFOLIO_ALLOCATIONS_DATASET,
    PORTFOLIO_ALLOCATIONS_STANDARD_FIELDS,
    PORTFOLIO_EXPERIMENTS_DATASET,
    PORTFOLIO_EXPERIMENTS_STANDARD_FIELDS,
    PROJECT_RUNS_DATASET,
    PROJECT_RUNS_STANDARD_FIELDS,
    PENDING_RETRY_STATUS,
    QUALITY_DIAGNOSTICS_DATASET,
    QUALITY_DIAGNOSTICS_STANDARD_FIELDS,
    RESEARCH_METRICS_DATASET,
    RESEARCH_METRICS_STANDARD_FIELDS,
    RESEARCH_PROJECTS_DATASET,
    RESEARCH_PROJECTS_STANDARD_FIELDS,
    RESEARCH_REPORTS_DATASET,
    RESEARCH_REPORTS_STANDARD_FIELDS,
    REPRODUCIBLE_PACKAGES_DATASET,
    REPRODUCIBLE_PACKAGES_STANDARD_FIELDS,
    AGENT_TASKS_DATASET,
    AGENT_TASKS_STANDARD_FIELDS,
    AGENT_STEPS_DATASET,
    AGENT_STEPS_STANDARD_FIELDS,
    PLUGIN_REGISTRY_DATASET,
    PLUGIN_REGISTRY_STANDARD_FIELDS,
    PLUGIN_RUNS_DATASET,
    PLUGIN_RUNS_STANDARD_FIELDS,
    RESEARCH_MEMORY_DATASET,
    RESEARCH_MEMORY_STANDARD_FIELDS,
    EXPERIMENT_NOTES_DATASET,
    EXPERIMENT_NOTES_STANDARD_FIELDS,
    DECISION_LOG_DATASET,
    DECISION_LOG_STANDARD_FIELDS,
    QUALITY_GATES_DATASET,
    QUALITY_GATES_STANDARD_FIELDS,
    RESEARCH_READINESS_DATASET,
    RESEARCH_READINESS_STANDARD_FIELDS,
    INPUT_RISK_FLAGS_DATASET,
    INPUT_RISK_FLAGS_STANDARD_FIELDS,
    TASK_QUEUE_DATASET,
    TASK_QUEUE_STANDARD_FIELDS,
    TASK_LOGS_DATASET,
    TASK_LOGS_STANDARD_FIELDS,
    TASK_RETRIES_DATASET,
    TASK_RETRIES_STANDARD_FIELDS,
    REPORT_INSIGHTS_DATASET,
    REPORT_INSIGHTS_STANDARD_FIELDS,
    RECOMMENDATION_ITEMS_DATASET,
    RECOMMENDATION_ITEMS_STANDARD_FIELDS,
    MODEL_REGISTRY_DATASET,
    MODEL_REGISTRY_STANDARD_FIELDS,
    FEATURE_VERSIONS_DATASET,
    FEATURE_VERSIONS_STANDARD_FIELDS,
    MODEL_DRIFT_EVENTS_DATASET,
    MODEL_DRIFT_EVENTS_STANDARD_FIELDS,
    REPORT_ARTIFACTS_DATASET,
    REPORT_ARTIFACTS_STANDARD_FIELDS,
    RISK_METRICS_DATASET,
    RISK_METRICS_STANDARD_FIELDS,
    REITS_QUOTES_DATASET,
    REITS_QUOTES_STANDARD_FIELDS,
    RUN_HEALTH_DATASET,
    RUN_HEALTH_STANDARD_FIELDS,
    RUN_HISTORY_DATASET,
    RUN_HISTORY_STANDARD_FIELDS,
    SOURCE_HEALTH_DATASET,
    SOURCE_HEALTH_STANDARD_FIELDS,
    SOURCE_HEALTH_HISTORY_DATASET,
    SOURCE_HEALTH_HISTORY_STANDARD_FIELDS,
    SOURCE_TYPE_OVERVIEW_DATASET,
    SOURCE_TYPE_OVERVIEW_STANDARD_FIELDS,
    SLA_VIOLATIONS_DATASET,
    SLA_VIOLATIONS_STANDARD_FIELDS,
    SCHEDULER_RUNS_DATASET,
    SCHEDULER_RUNS_STANDARD_FIELDS,
    SCENARIO_SIMULATIONS_DATASET,
    SCENARIO_SIMULATIONS_STANDARD_FIELDS,
    SUCCESS_STATUS,
    STRATEGY_BACKTESTS_DATASET,
    STRATEGY_BACKTESTS_STANDARD_FIELDS,
    STRATEGY_COMPARISONS_DATASET,
    STRATEGY_COMPARISONS_STANDARD_FIELDS,
    STRATEGY_LEADERBOARD_DATASET,
    STRATEGY_LEADERBOARD_STANDARD_FIELDS,
    STRESS_TEST_RESULTS_DATASET,
    STRESS_TEST_RESULTS_STANDARD_FIELDS,
    TRADING_CALENDAR_DATASET,
    TRADING_CALENDAR_STANDARD_FIELDS,
    UNDERLYING_SUMMARY_VIEW,
    YIELD_CURVE_DATASET,
    YIELD_CURVES_PLATFORM_DATASET,
    YIELD_CURVES_STANDARD_FIELDS,
    VALIDATION_RESULTS_DATASET,
    VALIDATION_RESULT_STANDARD_FIELDS,
)
from .pregrab_state import read_pregrab_state
from .regression_state import read_regression_smoke_state
from .crypto_observation import CryptoObservationRunner
from .normalize.csv_utils import write_dict_rows_csv
from .public_assets import PublicAssetSnapshotRunner
from .public_bonds import PublicBondRunner
from .public_references import PublicReferenceRunner
from .registry import build_asset_family_registry, build_dataset_catalog
from .source_catalog import build_source_catalog
from .state.checkpoints import CheckpointStore
from .utils import ensure_directory, format_trade_date, iso_timestamp, iter_csv_rows, now_shanghai, normalize_text, parse_trade_date, relative_to_project, safe_json_dumps
from .window_state import read_window_state
from .workflow import WorkflowRunner


PARSER_VERSION = "platform_metadata_v1"
SCHEMA_ONLY_SUCCESS_DATASETS = {
    RESEARCH_METRICS_DATASET,
    FACTOR_SIGNALS_DATASET,
    STRATEGY_BACKTESTS_DATASET,
    PAPER_PORTFOLIOS_DATASET,
    QUALITY_DIAGNOSTICS_DATASET,
    SCHEDULER_RUNS_DATASET,
    RESEARCH_REPORTS_DATASET,
    ALGORITHM_OUTPUTS_DATASET,
    OPTION_ANALYTICS_DATASET,
    BOND_ANALYTICS_DATASET,
    CURVE_ANALYTICS_DATASET,
    RISK_METRICS_DATASET,
    PORTFOLIO_ALLOCATIONS_DATASET,
    BACKTEST_EQUITY_CURVES_DATASET,
    BACKTEST_POSITIONS_DATASET,
    BACKTEST_TRADES_DATASET,
    STRATEGY_COMPARISONS_DATASET,
    ANOMALY_EVENTS_DATASET,
    ML_MODEL_RUNS_DATASET,
    ML_PREDICTIONS_DATASET,
    ML_FEATURE_IMPORTANCE_DATASET,
    MODEL_DIAGNOSTICS_DATASET,
    BACKTEST_INPUT_QUALITY_DATASET,
    EXPERIMENT_RUNS_DATASET,
    FACTOR_PERFORMANCE_DATASET,
    STRESS_TEST_RESULTS_DATASET,
    ARTIFACT_MANIFEST_DATASET,
    DATASET_QUALITY_SCORES_DATASET,
    REPORT_ARTIFACTS_DATASET,
    DATASET_INVENTORY_DATASET,
    DATASET_FIELD_PROFILE_DATASET,
    DATA_LINEAGE_DATASET,
    DATASET_SLA_RULES_DATASET,
    SLA_VIOLATIONS_DATASET,
    KNOWLEDGE_INDEX_DATASET,
    ML_FEATURE_STORE_DATASET,
    ML_BENCHMARKS_DATASET,
    ML_VALIDATION_FOLDS_DATASET,
    ML_CLASSIFICATION_RESULTS_DATASET,
    FACTOR_EXPERIMENTS_DATASET,
    PARAMETER_SCANS_DATASET,
    STRATEGY_LEADERBOARD_DATASET,
    PORTFOLIO_EXPERIMENTS_DATASET,
    SCENARIO_SIMULATIONS_DATASET,
    RESEARCH_PROJECTS_DATASET,
    PROJECT_RUNS_DATASET,
    REPRODUCIBLE_PACKAGES_DATASET,
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
}


class PlatformMetadataRunner:
    def __init__(
        self,
        *,
        workflow_runner: Optional[WorkflowRunner] = None,
        checkpoint_store: Optional[CheckpointStore] = None,
        public_asset_runner: Optional[PublicAssetSnapshotRunner] = None,
        public_reference_runner: Optional[PublicReferenceRunner] = None,
        public_bond_runner: Optional[PublicBondRunner] = None,
        crypto_runner: Optional[CryptoObservationRunner] = None,
        regression_state_reader=read_regression_smoke_state,
        pregrab_state_reader=read_pregrab_state,
        window_state_reader=read_window_state,
        state_path: Path = PLATFORM_METADATA_STATE_PATH,
        pregrab_state_path: Path = PREGRAB_STATE_PATH,
        window_state_path: Path = WINDOW_RUNS_STATE_PATH,
        project_root: Path = PROJECT_ROOT,
    ):
        self.workflow_runner = workflow_runner or WorkflowRunner()
        self.checkpoints = checkpoint_store or self.workflow_runner.checkpoints
        self.public_asset_runner = public_asset_runner or PublicAssetSnapshotRunner()
        self.public_reference_runner = public_reference_runner or PublicReferenceRunner()
        self.public_bond_runner = public_bond_runner or PublicBondRunner()
        self.crypto_runner = crypto_runner or CryptoObservationRunner()
        self.regression_state_reader = regression_state_reader
        self.pregrab_state_reader = pregrab_state_reader
        self.window_state_reader = window_state_reader
        self.state_path = state_path
        self.pregrab_state_path = pregrab_state_path
        self.window_state_path = window_state_path
        self.project_root = project_root
        ensure_directory(self.state_path.parent)
        if not self.state_path.exists():
            self.state_path.write_text(json.dumps({"dates": {}}, ensure_ascii=False, indent=2), encoding="utf-8")

    def sync(self, trade_date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_trade_date(trade_date_value)
        trade_date_str = format_trade_date(trade_date)
        run_id = hashlib.sha1(f"{trade_date_str}|{iso_timestamp()}".encode("utf-8")).hexdigest()[:12]

        instrument_rows = self._build_instrument_master_rows(trade_date_str=trade_date_str, run_id=run_id)
        bond_master_rows = self._build_bond_master_rows(run_id=run_id)
        bond_quote_rows = self._build_bond_quote_rows(run_id=run_id)
        fx_quote_rows = self._build_fx_quote_rows(run_id=run_id)
        commodity_spot_rows = self._build_commodity_spot_rows(run_id=run_id)
        crypto_quote_rows = self._build_crypto_global_quote_rows(run_id=run_id)
        yield_curve_rows = self._build_yield_curve_rows(run_id=run_id)
        daily_ohlcv_rows = self._build_daily_ohlcv_rows(trade_date_str=trade_date_str, run_id=run_id)
        fund_nav_rows = self._build_fund_nav_rows(run_id=run_id)
        reits_quote_rows = self._build_reits_quote_rows(run_id=run_id)
        trading_calendar_rows = self._build_trading_calendar_rows(trade_date_str=trade_date_str, run_id=run_id)
        run_health_rows = self._build_run_health_rows(trade_date_str=trade_date_str, run_id=run_id)
        dataset_summaries = {
            INSTRUMENT_MASTER_DATASET: self._write_dataset(
                dataset_name=INSTRUMENT_MASTER_DATASET,
                trade_date_str=trade_date_str,
                rows=instrument_rows,
                fieldnames=INSTRUMENT_MASTER_STANDARD_FIELDS,
                key_fields=["instrument_id"],
            ),
            BOND_MASTER_DATASET: self._write_dataset(
                dataset_name=BOND_MASTER_DATASET,
                trade_date_str=trade_date_str,
                rows=bond_master_rows,
                fieldnames=BOND_MASTER_STANDARD_FIELDS,
                key_fields=["instrument_id"],
            ),
            BOND_QUOTES_DATASET: self._write_dataset(
                dataset_name=BOND_QUOTES_DATASET,
                trade_date_str=trade_date_str,
                rows=bond_quote_rows,
                fieldnames=BOND_QUOTES_STANDARD_FIELDS,
                key_fields=["trade_date", "exchange", "symbol", "dataset_type", "tenor"],
            ),
            FX_QUOTES_DATASET: self._write_dataset(
                dataset_name=FX_QUOTES_DATASET,
                trade_date_str=trade_date_str,
                rows=fx_quote_rows,
                fieldnames=FX_QUOTES_STANDARD_FIELDS,
                key_fields=["trade_date", "exchange", "symbol", "quote_type", "tenor"],
            ),
            COMMODITY_SPOT_QUOTES_DATASET: self._write_dataset(
                dataset_name=COMMODITY_SPOT_QUOTES_DATASET,
                trade_date_str=trade_date_str,
                rows=commodity_spot_rows,
                fieldnames=COMMODITY_SPOT_QUOTES_STANDARD_FIELDS,
                key_fields=["trade_date", "exchange", "symbol", "commodity_type"],
            ),
            CRYPTO_GLOBAL_QUOTES_DATASET: self._write_dataset(
                dataset_name=CRYPTO_GLOBAL_QUOTES_DATASET,
                trade_date_str=trade_date_str,
                rows=crypto_quote_rows,
                fieldnames=CRYPTO_GLOBAL_QUOTES_STANDARD_FIELDS,
                key_fields=["trade_date", "exchange", "symbol", "quote_type", "contract_type"],
            ),
            YIELD_CURVES_PLATFORM_DATASET: self._write_dataset(
                dataset_name=YIELD_CURVES_PLATFORM_DATASET,
                trade_date_str=trade_date_str,
                rows=yield_curve_rows,
                fieldnames=YIELD_CURVES_STANDARD_FIELDS,
                key_fields=["trade_date", "exchange", "curve_name", "curve_type", "tenor"],
            ),
            DAILY_OHLCV_DATASET: self._write_dataset(
                dataset_name=DAILY_OHLCV_DATASET,
                trade_date_str=trade_date_str,
                rows=daily_ohlcv_rows,
                fieldnames=DAILY_OHLCV_STANDARD_FIELDS,
                key_fields=["trade_date", "instrument_id", "source_id"],
            ),
            FUND_NAV_DATASET: self._write_dataset(
                dataset_name=FUND_NAV_DATASET,
                trade_date_str=trade_date_str,
                rows=fund_nav_rows,
                fieldnames=FUND_NAV_STANDARD_FIELDS,
                key_fields=["trade_date", "instrument_id", "fund_type"],
            ),
            REITS_QUOTES_DATASET: self._write_dataset(
                dataset_name=REITS_QUOTES_DATASET,
                trade_date_str=trade_date_str,
                rows=reits_quote_rows,
                fieldnames=REITS_QUOTES_STANDARD_FIELDS,
                key_fields=["trade_date", "instrument_id"],
            ),
            TRADING_CALENDAR_DATASET: self._write_dataset(
                dataset_name=TRADING_CALENDAR_DATASET,
                trade_date_str=trade_date_str,
                rows=trading_calendar_rows,
                fieldnames=TRADING_CALENDAR_STANDARD_FIELDS,
                key_fields=["trade_date", "calendar_id"],
            ),
            RUN_HEALTH_DATASET: self._write_dataset(
                dataset_name=RUN_HEALTH_DATASET,
                trade_date_str=trade_date_str,
                rows=run_health_rows,
                fieldnames=RUN_HEALTH_STANDARD_FIELDS,
                key_fields=["trade_date", "workflow_name", "scope"],
            ),
        }
        run_history_rows = self._build_run_history_rows(trade_date_str=trade_date_str)
        dataset_summaries[RUN_HISTORY_DATASET] = self._write_dataset(
            dataset_name=RUN_HISTORY_DATASET,
            trade_date_str=trade_date_str,
            rows=run_history_rows,
            fieldnames=RUN_HISTORY_STANDARD_FIELDS,
            key_fields=["trade_date", "history_kind", "run_id", "target"],
        )
        dataset_summaries[RESEARCH_METRICS_DATASET] = self._write_dataset(
            dataset_name=RESEARCH_METRICS_DATASET,
            trade_date_str=trade_date_str,
            rows=self._load_existing_platform_dataset_rows(RESEARCH_METRICS_DATASET, trade_date_str),
            fieldnames=RESEARCH_METRICS_STANDARD_FIELDS,
            key_fields=["trade_date", "dataset", "asset_family", "metric_name"],
        )
        dataset_summaries[FACTOR_SIGNALS_DATASET] = self._write_dataset(
            dataset_name=FACTOR_SIGNALS_DATASET,
            trade_date_str=trade_date_str,
            rows=self._load_existing_platform_dataset_rows(FACTOR_SIGNALS_DATASET, trade_date_str),
            fieldnames=FACTOR_SIGNALS_STANDARD_FIELDS,
            key_fields=["trade_date", "dataset", "symbol_or_contract", "factor_name"],
        )
        dataset_summaries[STRATEGY_BACKTESTS_DATASET] = self._write_dataset(
            dataset_name=STRATEGY_BACKTESTS_DATASET,
            trade_date_str=trade_date_str,
            rows=self._load_existing_platform_dataset_rows(STRATEGY_BACKTESTS_DATASET, trade_date_str),
            fieldnames=STRATEGY_BACKTESTS_STANDARD_FIELDS,
            key_fields=["trade_date", "strategy_name", "asset_family", "dataset"],
        )
        dataset_summaries[PAPER_PORTFOLIOS_DATASET] = self._write_dataset(
            dataset_name=PAPER_PORTFOLIOS_DATASET,
            trade_date_str=trade_date_str,
            rows=self._load_existing_platform_dataset_rows(PAPER_PORTFOLIOS_DATASET, trade_date_str),
            fieldnames=PAPER_PORTFOLIOS_STANDARD_FIELDS,
            key_fields=["trade_date", "strategy_name", "portfolio_id"],
        )
        dataset_summaries[QUALITY_DIAGNOSTICS_DATASET] = self._write_dataset(
            dataset_name=QUALITY_DIAGNOSTICS_DATASET,
            trade_date_str=trade_date_str,
            rows=self._load_existing_platform_dataset_rows(QUALITY_DIAGNOSTICS_DATASET, trade_date_str),
            fieldnames=QUALITY_DIAGNOSTICS_STANDARD_FIELDS,
            key_fields=["trade_date", "diagnostic_type", "dataset", "source_id"],
        )
        dataset_summaries[SCHEDULER_RUNS_DATASET] = self._write_dataset(
            dataset_name=SCHEDULER_RUNS_DATASET,
            trade_date_str=trade_date_str,
            rows=self._load_existing_platform_dataset_rows(SCHEDULER_RUNS_DATASET, trade_date_str),
            fieldnames=SCHEDULER_RUNS_STANDARD_FIELDS,
            key_fields=["trade_date", "schedule_id", "run_id"],
        )
        dataset_summaries[RESEARCH_REPORTS_DATASET] = self._write_dataset(
            dataset_name=RESEARCH_REPORTS_DATASET,
            trade_date_str=trade_date_str,
            rows=self._load_existing_platform_dataset_rows(RESEARCH_REPORTS_DATASET, trade_date_str),
            fieldnames=RESEARCH_REPORTS_STANDARD_FIELDS,
            key_fields=["trade_date", "report_id"],
        )
        for dataset_name, fieldnames, key_fields in (
            (ALGORITHM_OUTPUTS_DATASET, ALGORITHM_OUTPUTS_STANDARD_FIELDS, ["trade_date", "dataset", "template_name", "symbol_or_contract", "metric_name"]),
            (OPTION_ANALYTICS_DATASET, OPTION_ANALYTICS_STANDARD_FIELDS, ["trade_date", "dataset", "symbol_or_contract", "model_name"]),
            (BOND_ANALYTICS_DATASET, BOND_ANALYTICS_STANDARD_FIELDS, ["trade_date", "dataset", "symbol_or_contract", "model_name"]),
            (CURVE_ANALYTICS_DATASET, CURVE_ANALYTICS_STANDARD_FIELDS, ["trade_date", "dataset", "curve_name", "model_name"]),
            (RISK_METRICS_DATASET, RISK_METRICS_STANDARD_FIELDS, ["trade_date", "dataset", "template_name", "portfolio_id", "metric_name"]),
            (PORTFOLIO_ALLOCATIONS_DATASET, PORTFOLIO_ALLOCATIONS_STANDARD_FIELDS, ["trade_date", "portfolio_id", "symbol_or_contract"]),
            (BACKTEST_EQUITY_CURVES_DATASET, BACKTEST_EQUITY_CURVES_STANDARD_FIELDS, ["trade_date", "strategy_name", "dataset"]),
            (BACKTEST_POSITIONS_DATASET, BACKTEST_POSITIONS_STANDARD_FIELDS, ["trade_date", "strategy_name", "dataset", "symbol_or_contract"]),
            (BACKTEST_TRADES_DATASET, BACKTEST_TRADES_STANDARD_FIELDS, ["trade_date", "strategy_name", "dataset", "symbol_or_contract", "side"]),
            (STRATEGY_COMPARISONS_DATASET, STRATEGY_COMPARISONS_STANDARD_FIELDS, ["trade_date", "strategy_name", "benchmark_name", "metric_name"]),
            (ANOMALY_EVENTS_DATASET, ANOMALY_EVENTS_STANDARD_FIELDS, ["trade_date", "dataset", "source_id", "event_type", "metric_name"]),
            (ML_MODEL_RUNS_DATASET, ML_MODEL_RUNS_STANDARD_FIELDS, ["trade_date", "run_id", "template_name"]),
            (ML_PREDICTIONS_DATASET, ML_PREDICTIONS_STANDARD_FIELDS, ["trade_date", "run_id", "template_name", "symbol_or_contract", "prediction_date"]),
            (ML_FEATURE_IMPORTANCE_DATASET, ML_FEATURE_IMPORTANCE_STANDARD_FIELDS, ["trade_date", "run_id", "template_name", "feature_name"]),
            (MODEL_DIAGNOSTICS_DATASET, MODEL_DIAGNOSTICS_STANDARD_FIELDS, ["trade_date", "run_id", "template_name", "diagnostic_type", "metric_name"]),
            (BACKTEST_INPUT_QUALITY_DATASET, BACKTEST_INPUT_QUALITY_STANDARD_FIELDS, ["trade_date", "run_id", "strategy_name", "dataset", "symbol_or_contract", "issue_type"]),
            (EXPERIMENT_RUNS_DATASET, EXPERIMENT_RUNS_STANDARD_FIELDS, ["trade_date", "run_id", "experiment_type", "template_name"]),
            (FACTOR_PERFORMANCE_DATASET, FACTOR_PERFORMANCE_STANDARD_FIELDS, ["trade_date", "factor_name", "dataset", "metric_name"]),
            (STRESS_TEST_RESULTS_DATASET, STRESS_TEST_RESULTS_STANDARD_FIELDS, ["trade_date", "run_id", "template_name", "scenario_name", "metric_name"]),
            (ARTIFACT_MANIFEST_DATASET, ARTIFACT_MANIFEST_STANDARD_FIELDS, ["trade_date", "run_id", "artifact_id"]),
            (DATASET_QUALITY_SCORES_DATASET, DATASET_QUALITY_SCORES_STANDARD_FIELDS, ["trade_date", "dataset"]),
            (REPORT_ARTIFACTS_DATASET, REPORT_ARTIFACTS_STANDARD_FIELDS, ["trade_date", "report_id", "artifact_id"]),
            (DATASET_INVENTORY_DATASET, DATASET_INVENTORY_STANDARD_FIELDS, ["trade_date", "dataset"]),
            (DATASET_FIELD_PROFILE_DATASET, DATASET_FIELD_PROFILE_STANDARD_FIELDS, ["trade_date", "dataset", "field_name"]),
            (DATA_LINEAGE_DATASET, DATA_LINEAGE_STANDARD_FIELDS, ["trade_date", "run_id", "artifact_id"]),
            (DATASET_SLA_RULES_DATASET, DATASET_SLA_RULES_STANDARD_FIELDS, ["trade_date", "dataset"]),
            (SLA_VIOLATIONS_DATASET, SLA_VIOLATIONS_STANDARD_FIELDS, ["trade_date", "dataset", "violation_type"]),
            (KNOWLEDGE_INDEX_DATASET, KNOWLEDGE_INDEX_STANDARD_FIELDS, ["trade_date", "knowledge_id"]),
            (ML_FEATURE_STORE_DATASET, ML_FEATURE_STORE_STANDARD_FIELDS, ["trade_date", "dataset", "symbol_or_contract", "feature_name", "window"]),
            (ML_BENCHMARKS_DATASET, ML_BENCHMARKS_STANDARD_FIELDS, ["trade_date", "run_id", "template_name"]),
            (ML_VALIDATION_FOLDS_DATASET, ML_VALIDATION_FOLDS_STANDARD_FIELDS, ["trade_date", "run_id", "template_name", "fold_index"]),
            (ML_CLASSIFICATION_RESULTS_DATASET, ML_CLASSIFICATION_RESULTS_STANDARD_FIELDS, ["trade_date", "run_id", "template_name", "task_name"]),
            (FACTOR_EXPERIMENTS_DATASET, FACTOR_EXPERIMENTS_STANDARD_FIELDS, ["trade_date", "run_id", "factor_name", "parameter_set"]),
            (PARAMETER_SCANS_DATASET, PARAMETER_SCANS_STANDARD_FIELDS, ["trade_date", "run_id", "template_name", "parameter_set", "metric_name"]),
            (STRATEGY_LEADERBOARD_DATASET, STRATEGY_LEADERBOARD_STANDARD_FIELDS, ["trade_date", "run_id", "strategy_name"]),
            (PORTFOLIO_EXPERIMENTS_DATASET, PORTFOLIO_EXPERIMENTS_STANDARD_FIELDS, ["trade_date", "run_id", "template_name", "metric_name"]),
            (SCENARIO_SIMULATIONS_DATASET, SCENARIO_SIMULATIONS_STANDARD_FIELDS, ["trade_date", "run_id", "scenario_name"]),
            (RESEARCH_PROJECTS_DATASET, RESEARCH_PROJECTS_STANDARD_FIELDS, ["trade_date", "project_id"]),
            (PROJECT_RUNS_DATASET, PROJECT_RUNS_STANDARD_FIELDS, ["trade_date", "project_id", "run_id"]),
            (REPRODUCIBLE_PACKAGES_DATASET, REPRODUCIBLE_PACKAGES_STANDARD_FIELDS, ["trade_date", "package_id"]),
            (AGENT_TASKS_DATASET, AGENT_TASKS_STANDARD_FIELDS, ["trade_date", "task_id"]),
            (AGENT_STEPS_DATASET, AGENT_STEPS_STANDARD_FIELDS, ["trade_date", "task_id", "step_id"]),
            (PLUGIN_REGISTRY_DATASET, PLUGIN_REGISTRY_STANDARD_FIELDS, ["trade_date", "plugin_id"]),
            (PLUGIN_RUNS_DATASET, PLUGIN_RUNS_STANDARD_FIELDS, ["trade_date", "run_id", "plugin_id", "step_id"]),
            (RESEARCH_MEMORY_DATASET, RESEARCH_MEMORY_STANDARD_FIELDS, ["trade_date", "memory_id"]),
            (EXPERIMENT_NOTES_DATASET, EXPERIMENT_NOTES_STANDARD_FIELDS, ["trade_date", "note_id"]),
            (DECISION_LOG_DATASET, DECISION_LOG_STANDARD_FIELDS, ["trade_date", "decision_id"]),
            (QUALITY_GATES_DATASET, QUALITY_GATES_STANDARD_FIELDS, ["trade_date", "gate_id"]),
            (RESEARCH_READINESS_DATASET, RESEARCH_READINESS_STANDARD_FIELDS, ["trade_date", "readiness_id"]),
            (INPUT_RISK_FLAGS_DATASET, INPUT_RISK_FLAGS_STANDARD_FIELDS, ["trade_date", "flag_id"]),
            (TASK_QUEUE_DATASET, TASK_QUEUE_STANDARD_FIELDS, ["trade_date", "queue_id"]),
            (TASK_LOGS_DATASET, TASK_LOGS_STANDARD_FIELDS, ["trade_date", "log_id"]),
            (TASK_RETRIES_DATASET, TASK_RETRIES_STANDARD_FIELDS, ["trade_date", "retry_id"]),
            (REPORT_INSIGHTS_DATASET, REPORT_INSIGHTS_STANDARD_FIELDS, ["trade_date", "insight_id"]),
            (RECOMMENDATION_ITEMS_DATASET, RECOMMENDATION_ITEMS_STANDARD_FIELDS, ["trade_date", "recommendation_id"]),
            (MODEL_REGISTRY_DATASET, MODEL_REGISTRY_STANDARD_FIELDS, ["trade_date", "model_id"]),
            (FEATURE_VERSIONS_DATASET, FEATURE_VERSIONS_STANDARD_FIELDS, ["trade_date", "feature_version_id"]),
            (MODEL_DRIFT_EVENTS_DATASET, MODEL_DRIFT_EVENTS_STANDARD_FIELDS, ["trade_date", "drift_id"]),
        ):
            dataset_summaries[dataset_name] = self._write_dataset(
                dataset_name=dataset_name,
                trade_date_str=trade_date_str,
                rows=self._load_existing_platform_dataset_rows(dataset_name, trade_date_str),
                fieldnames=fieldnames,
                key_fields=key_fields,
            )
        validation_rows = self._build_validation_rows(
            trade_date_str=trade_date_str,
            platform_summaries=dataset_summaries,
        )
        dataset_summaries[VALIDATION_RESULTS_DATASET] = self._write_dataset(
            dataset_name=VALIDATION_RESULTS_DATASET,
            trade_date_str=trade_date_str,
            rows=validation_rows,
            fieldnames=VALIDATION_RESULT_STANDARD_FIELDS,
            key_fields=["dataset", "source_trade_date"],
        )
        source_health_rows = self._build_source_health_rows(
            trade_date_str=trade_date_str,
            platform_summaries=dataset_summaries,
        )
        dataset_summaries[SOURCE_HEALTH_DATASET] = self._write_dataset(
            dataset_name=SOURCE_HEALTH_DATASET,
            trade_date_str=trade_date_str,
            rows=source_health_rows,
            fieldnames=SOURCE_HEALTH_STANDARD_FIELDS,
            key_fields=["source_id", "dataset"],
        )
        source_type_overview_rows = self._build_source_type_overview_rows(
            trade_date_str=trade_date_str,
            source_health_rows=source_health_rows,
            run_id=run_id,
        )
        dataset_summaries[SOURCE_TYPE_OVERVIEW_DATASET] = self._write_dataset(
            dataset_name=SOURCE_TYPE_OVERVIEW_DATASET,
            trade_date_str=trade_date_str,
            rows=source_type_overview_rows,
            fieldnames=SOURCE_TYPE_OVERVIEW_STANDARD_FIELDS,
            key_fields=["trade_date", "source_type"],
        )
        issue_category_overview_rows = self._build_issue_category_overview_rows(
            trade_date_str=trade_date_str,
            source_health_rows=source_health_rows,
            run_id=run_id,
        )
        dataset_summaries[ISSUE_CATEGORY_OVERVIEW_DATASET] = self._write_dataset(
            dataset_name=ISSUE_CATEGORY_OVERVIEW_DATASET,
            trade_date_str=trade_date_str,
            rows=issue_category_overview_rows,
            fieldnames=ISSUE_CATEGORY_OVERVIEW_STANDARD_FIELDS,
            key_fields=["trade_date", "issue_category"],
        )
        asset_coverage_rows = self._build_asset_coverage_rows(
            trade_date_str=trade_date_str,
            platform_summaries=dataset_summaries,
            run_id=run_id,
            source_health_rows=source_health_rows,
        )
        dataset_summaries[ASSET_COVERAGE_DATASET] = self._write_dataset(
            dataset_name=ASSET_COVERAGE_DATASET,
            trade_date_str=trade_date_str,
            rows=asset_coverage_rows,
            fieldnames=ASSET_COVERAGE_STANDARD_FIELDS,
            key_fields=["trade_date", "asset_family"],
        )
        coverage_history_rows = self._build_coverage_history_rows(trade_date_str=trade_date_str)
        dataset_summaries[COVERAGE_HISTORY_DATASET] = self._write_dataset(
            dataset_name=COVERAGE_HISTORY_DATASET,
            trade_date_str=trade_date_str,
            rows=coverage_history_rows,
            fieldnames=COVERAGE_HISTORY_STANDARD_FIELDS,
            key_fields=["trade_date", "asset_family"],
        )
        source_health_history_rows = self._build_source_health_history_rows(trade_date_str=trade_date_str)
        dataset_summaries[SOURCE_HEALTH_HISTORY_DATASET] = self._write_dataset(
            dataset_name=SOURCE_HEALTH_HISTORY_DATASET,
            trade_date_str=trade_date_str,
            rows=source_health_history_rows,
            fieldnames=SOURCE_HEALTH_HISTORY_STANDARD_FIELDS,
            key_fields=["trade_date", "source_id", "dataset"],
        )
        validation_rows = self._build_validation_rows(
            trade_date_str=trade_date_str,
            platform_summaries=dataset_summaries,
        )
        dataset_summaries[VALIDATION_RESULTS_DATASET] = self._write_dataset(
            dataset_name=VALIDATION_RESULTS_DATASET,
            trade_date_str=trade_date_str,
            rows=validation_rows,
            fieldnames=VALIDATION_RESULT_STANDARD_FIELDS,
            key_fields=["dataset", "source_trade_date"],
        )
        source_health_rows = self._build_source_health_rows(
            trade_date_str=trade_date_str,
            platform_summaries=dataset_summaries,
        )
        dataset_summaries[SOURCE_HEALTH_DATASET] = self._write_dataset(
            dataset_name=SOURCE_HEALTH_DATASET,
            trade_date_str=trade_date_str,
            rows=source_health_rows,
            fieldnames=SOURCE_HEALTH_STANDARD_FIELDS,
            key_fields=["source_id", "dataset"],
        )
        source_type_overview_rows = self._build_source_type_overview_rows(
            trade_date_str=trade_date_str,
            source_health_rows=source_health_rows,
            run_id=run_id,
        )
        dataset_summaries[SOURCE_TYPE_OVERVIEW_DATASET] = self._write_dataset(
            dataset_name=SOURCE_TYPE_OVERVIEW_DATASET,
            trade_date_str=trade_date_str,
            rows=source_type_overview_rows,
            fieldnames=SOURCE_TYPE_OVERVIEW_STANDARD_FIELDS,
            key_fields=["trade_date", "source_type"],
        )
        issue_category_overview_rows = self._build_issue_category_overview_rows(
            trade_date_str=trade_date_str,
            source_health_rows=source_health_rows,
            run_id=run_id,
        )
        dataset_summaries[ISSUE_CATEGORY_OVERVIEW_DATASET] = self._write_dataset(
            dataset_name=ISSUE_CATEGORY_OVERVIEW_DATASET,
            trade_date_str=trade_date_str,
            rows=issue_category_overview_rows,
            fieldnames=ISSUE_CATEGORY_OVERVIEW_STANDARD_FIELDS,
            key_fields=["trade_date", "issue_category"],
        )
        asset_coverage_rows = self._build_asset_coverage_rows(
            trade_date_str=trade_date_str,
            platform_summaries=dataset_summaries,
            run_id=run_id,
            source_health_rows=source_health_rows,
        )
        dataset_summaries[ASSET_COVERAGE_DATASET] = self._write_dataset(
            dataset_name=ASSET_COVERAGE_DATASET,
            trade_date_str=trade_date_str,
            rows=asset_coverage_rows,
            fieldnames=ASSET_COVERAGE_STANDARD_FIELDS,
            key_fields=["trade_date", "asset_family"],
        )
        overall_status = self._merge_statuses([summary.get("status", "") for summary in dataset_summaries.values()])
        self._update_state(trade_date_str, overall_status, dataset_summaries)
        return {
            "trade_date": trade_date_str,
            "status": overall_status,
            "datasets": dataset_summaries,
            "run_id": run_id,
        }

    def validate(self, trade_date_value: str) -> Dict[str, object]:
        trade_date = self._resolve_trade_date(trade_date_value)
        trade_date_str = format_trade_date(trade_date)
        state = self._load_state().get("dates", {}).get(trade_date_str, {})
        datasets = {}
        statuses: List[str] = []
        for dataset_name, fieldnames in (
            (INSTRUMENT_MASTER_DATASET, INSTRUMENT_MASTER_STANDARD_FIELDS),
            (BOND_MASTER_DATASET, BOND_MASTER_STANDARD_FIELDS),
            (BOND_QUOTES_DATASET, BOND_QUOTES_STANDARD_FIELDS),
            (FX_QUOTES_DATASET, FX_QUOTES_STANDARD_FIELDS),
            (COMMODITY_SPOT_QUOTES_DATASET, COMMODITY_SPOT_QUOTES_STANDARD_FIELDS),
            (CRYPTO_GLOBAL_QUOTES_DATASET, CRYPTO_GLOBAL_QUOTES_STANDARD_FIELDS),
            (YIELD_CURVES_PLATFORM_DATASET, YIELD_CURVES_STANDARD_FIELDS),
            (DAILY_OHLCV_DATASET, DAILY_OHLCV_STANDARD_FIELDS),
            (FUND_NAV_DATASET, FUND_NAV_STANDARD_FIELDS),
            (REITS_QUOTES_DATASET, REITS_QUOTES_STANDARD_FIELDS),
            (TRADING_CALENDAR_DATASET, TRADING_CALENDAR_STANDARD_FIELDS),
            (ASSET_COVERAGE_DATASET, ASSET_COVERAGE_STANDARD_FIELDS),
            (RUN_HEALTH_DATASET, RUN_HEALTH_STANDARD_FIELDS),
            (RUN_HISTORY_DATASET, RUN_HISTORY_STANDARD_FIELDS),
            (COVERAGE_HISTORY_DATASET, COVERAGE_HISTORY_STANDARD_FIELDS),
            (VALIDATION_RESULTS_DATASET, VALIDATION_RESULT_STANDARD_FIELDS),
            (SOURCE_HEALTH_DATASET, SOURCE_HEALTH_STANDARD_FIELDS),
            (SOURCE_HEALTH_HISTORY_DATASET, SOURCE_HEALTH_HISTORY_STANDARD_FIELDS),
            (SOURCE_TYPE_OVERVIEW_DATASET, SOURCE_TYPE_OVERVIEW_STANDARD_FIELDS),
            (ISSUE_CATEGORY_OVERVIEW_DATASET, ISSUE_CATEGORY_OVERVIEW_STANDARD_FIELDS),
            (RESEARCH_METRICS_DATASET, RESEARCH_METRICS_STANDARD_FIELDS),
            (FACTOR_SIGNALS_DATASET, FACTOR_SIGNALS_STANDARD_FIELDS),
            (STRATEGY_BACKTESTS_DATASET, STRATEGY_BACKTESTS_STANDARD_FIELDS),
            (PAPER_PORTFOLIOS_DATASET, PAPER_PORTFOLIOS_STANDARD_FIELDS),
            (QUALITY_DIAGNOSTICS_DATASET, QUALITY_DIAGNOSTICS_STANDARD_FIELDS),
            (SCHEDULER_RUNS_DATASET, SCHEDULER_RUNS_STANDARD_FIELDS),
            (RESEARCH_REPORTS_DATASET, RESEARCH_REPORTS_STANDARD_FIELDS),
            (ALGORITHM_OUTPUTS_DATASET, ALGORITHM_OUTPUTS_STANDARD_FIELDS),
            (OPTION_ANALYTICS_DATASET, OPTION_ANALYTICS_STANDARD_FIELDS),
            (BOND_ANALYTICS_DATASET, BOND_ANALYTICS_STANDARD_FIELDS),
            (CURVE_ANALYTICS_DATASET, CURVE_ANALYTICS_STANDARD_FIELDS),
            (RISK_METRICS_DATASET, RISK_METRICS_STANDARD_FIELDS),
            (PORTFOLIO_ALLOCATIONS_DATASET, PORTFOLIO_ALLOCATIONS_STANDARD_FIELDS),
            (BACKTEST_EQUITY_CURVES_DATASET, BACKTEST_EQUITY_CURVES_STANDARD_FIELDS),
            (BACKTEST_POSITIONS_DATASET, BACKTEST_POSITIONS_STANDARD_FIELDS),
            (BACKTEST_TRADES_DATASET, BACKTEST_TRADES_STANDARD_FIELDS),
            (STRATEGY_COMPARISONS_DATASET, STRATEGY_COMPARISONS_STANDARD_FIELDS),
            (ANOMALY_EVENTS_DATASET, ANOMALY_EVENTS_STANDARD_FIELDS),
            (ML_MODEL_RUNS_DATASET, ML_MODEL_RUNS_STANDARD_FIELDS),
            (ML_PREDICTIONS_DATASET, ML_PREDICTIONS_STANDARD_FIELDS),
            (ML_FEATURE_IMPORTANCE_DATASET, ML_FEATURE_IMPORTANCE_STANDARD_FIELDS),
            (MODEL_DIAGNOSTICS_DATASET, MODEL_DIAGNOSTICS_STANDARD_FIELDS),
            (BACKTEST_INPUT_QUALITY_DATASET, BACKTEST_INPUT_QUALITY_STANDARD_FIELDS),
            (EXPERIMENT_RUNS_DATASET, EXPERIMENT_RUNS_STANDARD_FIELDS),
            (FACTOR_PERFORMANCE_DATASET, FACTOR_PERFORMANCE_STANDARD_FIELDS),
            (STRESS_TEST_RESULTS_DATASET, STRESS_TEST_RESULTS_STANDARD_FIELDS),
            (ARTIFACT_MANIFEST_DATASET, ARTIFACT_MANIFEST_STANDARD_FIELDS),
            (DATASET_QUALITY_SCORES_DATASET, DATASET_QUALITY_SCORES_STANDARD_FIELDS),
            (REPORT_ARTIFACTS_DATASET, REPORT_ARTIFACTS_STANDARD_FIELDS),
            (DATASET_INVENTORY_DATASET, DATASET_INVENTORY_STANDARD_FIELDS),
            (DATASET_FIELD_PROFILE_DATASET, DATASET_FIELD_PROFILE_STANDARD_FIELDS),
            (DATA_LINEAGE_DATASET, DATA_LINEAGE_STANDARD_FIELDS),
            (DATASET_SLA_RULES_DATASET, DATASET_SLA_RULES_STANDARD_FIELDS),
            (SLA_VIOLATIONS_DATASET, SLA_VIOLATIONS_STANDARD_FIELDS),
            (KNOWLEDGE_INDEX_DATASET, KNOWLEDGE_INDEX_STANDARD_FIELDS),
            (ML_FEATURE_STORE_DATASET, ML_FEATURE_STORE_STANDARD_FIELDS),
            (ML_BENCHMARKS_DATASET, ML_BENCHMARKS_STANDARD_FIELDS),
            (ML_VALIDATION_FOLDS_DATASET, ML_VALIDATION_FOLDS_STANDARD_FIELDS),
            (ML_CLASSIFICATION_RESULTS_DATASET, ML_CLASSIFICATION_RESULTS_STANDARD_FIELDS),
            (FACTOR_EXPERIMENTS_DATASET, FACTOR_EXPERIMENTS_STANDARD_FIELDS),
            (PARAMETER_SCANS_DATASET, PARAMETER_SCANS_STANDARD_FIELDS),
            (STRATEGY_LEADERBOARD_DATASET, STRATEGY_LEADERBOARD_STANDARD_FIELDS),
            (PORTFOLIO_EXPERIMENTS_DATASET, PORTFOLIO_EXPERIMENTS_STANDARD_FIELDS),
            (SCENARIO_SIMULATIONS_DATASET, SCENARIO_SIMULATIONS_STANDARD_FIELDS),
            (RESEARCH_PROJECTS_DATASET, RESEARCH_PROJECTS_STANDARD_FIELDS),
            (PROJECT_RUNS_DATASET, PROJECT_RUNS_STANDARD_FIELDS),
            (REPRODUCIBLE_PACKAGES_DATASET, REPRODUCIBLE_PACKAGES_STANDARD_FIELDS),
            (AGENT_TASKS_DATASET, AGENT_TASKS_STANDARD_FIELDS),
            (AGENT_STEPS_DATASET, AGENT_STEPS_STANDARD_FIELDS),
            (PLUGIN_REGISTRY_DATASET, PLUGIN_REGISTRY_STANDARD_FIELDS),
            (PLUGIN_RUNS_DATASET, PLUGIN_RUNS_STANDARD_FIELDS),
            (RESEARCH_MEMORY_DATASET, RESEARCH_MEMORY_STANDARD_FIELDS),
            (EXPERIMENT_NOTES_DATASET, EXPERIMENT_NOTES_STANDARD_FIELDS),
            (DECISION_LOG_DATASET, DECISION_LOG_STANDARD_FIELDS),
            (QUALITY_GATES_DATASET, QUALITY_GATES_STANDARD_FIELDS),
            (RESEARCH_READINESS_DATASET, RESEARCH_READINESS_STANDARD_FIELDS),
            (INPUT_RISK_FLAGS_DATASET, INPUT_RISK_FLAGS_STANDARD_FIELDS),
            (TASK_QUEUE_DATASET, TASK_QUEUE_STANDARD_FIELDS),
            (TASK_LOGS_DATASET, TASK_LOGS_STANDARD_FIELDS),
            (TASK_RETRIES_DATASET, TASK_RETRIES_STANDARD_FIELDS),
            (REPORT_INSIGHTS_DATASET, REPORT_INSIGHTS_STANDARD_FIELDS),
            (RECOMMENDATION_ITEMS_DATASET, RECOMMENDATION_ITEMS_STANDARD_FIELDS),
            (MODEL_REGISTRY_DATASET, MODEL_REGISTRY_STANDARD_FIELDS),
            (FEATURE_VERSIONS_DATASET, FEATURE_VERSIONS_STANDARD_FIELDS),
            (MODEL_DRIFT_EVENTS_DATASET, MODEL_DRIFT_EVENTS_STANDARD_FIELDS),
        ):
            summary = state.get("datasets", {}).get(dataset_name, {})
            output_path = str(summary.get("output_path", "")).strip()
            csv_path = self.project_root / output_path if output_path else None
            validation = {
                "csv_exists": bool(csv_path and csv_path.exists()),
                "schema_ok": False,
                "row_count": 0,
                "missing_raw_paths": [],
            }
            if csv_path and csv_path.exists():
                rows = list(iter_csv_rows(csv_path))
                validation["row_count"] = len(rows)
                actual_fields = list(rows[0].keys()) if rows else fieldnames
                validation["schema_ok"] = actual_fields == fieldnames
                for row in rows:
                    raw_path = normalize_text(row.get("raw_path"))
                    if raw_path and not (self.project_root / raw_path).exists():
                        validation["missing_raw_paths"].append(raw_path)
            summary_status = str(summary.get("status", ""))
            if summary_status in {NO_DATA_STATUS, NOT_APPLICABLE_STATUS, PENDING_RETRY_STATUS, FAILED_STATUS}:
                statuses.append(summary_status)
            elif validation["csv_exists"] and validation["schema_ok"] and not validation["missing_raw_paths"]:
                statuses.append(SUCCESS_STATUS)
            else:
                statuses.append(FAILED_STATUS)
            datasets[dataset_name] = validation
        return {
            "trade_date": trade_date_str,
            "status": self._merge_statuses(statuses),
            "datasets": datasets,
        }

    def latest_summaries(self) -> Dict[str, Dict[str, object]]:
        state = self._load_state().get("dates", {})
        if not state:
            return {}
        latest_by_dataset: Dict[str, Dict[str, object]] = {}
        fallback_by_dataset: Dict[str, Dict[str, object]] = {}
        for trade_date in sorted(state.keys(), reverse=True):
            datasets = state[trade_date].get("datasets", {})
            for dataset_name, summary in datasets.items():
                fallback_by_dataset.setdefault(dataset_name, summary)
                status = str(summary.get("status", ""))
                row_count = int(summary.get("row_count", 0) or 0)
                if dataset_name not in latest_by_dataset and status == SUCCESS_STATUS and row_count >= 0:
                    latest_by_dataset[dataset_name] = summary
        for dataset_name, summary in fallback_by_dataset.items():
            latest_by_dataset.setdefault(dataset_name, summary)
        return latest_by_dataset

    def _build_instrument_master_rows(self, *, trade_date_str: str, run_id: str) -> List[Dict[str, str]]:
        rows_by_id: Dict[str, Dict[str, str]] = {}
        derivative_rows = self._load_derivative_contract_rows(trade_date_str)
        for row in derivative_rows:
            instrument_id = f"{normalize_text(row.get('exchange'))}:{normalize_text(row.get('contract'))}"
            rows_by_id[instrument_id] = self._instrument_row(
                trade_date_str=trade_date_str,
                instrument_id=instrument_id,
                asset_family="exchange_derivatives_cn",
                market="cn_derivatives",
                exchange=row.get("exchange", ""),
                instrument_type=row.get("instrument_type", ""),
                symbol=row.get("contract", ""),
                name=row.get("product_name", ""),
                currency="CNY",
                listing_date=row.get("list_date", ""),
                delisting_date="",
                status=row.get("contract_status", ""),
                underlying_id=self._underlying_id_from_contract_row(row),
                contract_multiplier=row.get("contract_multiplier", ""),
                price_tick=row.get("price_tick", ""),
                quote_unit=row.get("quote_unit", ""),
                trading_unit="",
                delivery_type=row.get("delivery_type", ""),
                exercise_type=row.get("exercise_type", ""),
                option_type=row.get("option_type", ""),
                strike_price=row.get("strike_price", ""),
                expire_date=row.get("expire_date", ""),
                last_trade_date=row.get("last_trade_date", ""),
                source_id=f"{normalize_text(row.get('exchange')).lower()}.contracts_snapshot",
                source_url=row.get("source_url", ""),
                source_type=row.get("source_type", ""),
                retrieved_at=row.get("retrieved_at", ""),
                raw_path=row.get("raw_path", ""),
                run_id=run_id,
            )

        for row in self._load_rows_from_latest_summaries(self.public_asset_runner.latest_summaries()):
            instrument_id = f"{normalize_text(row.get('exchange'))}:{normalize_text(row.get('symbol'))}"
            rows_by_id.setdefault(
                instrument_id,
                self._instrument_row(
                    trade_date_str=trade_date_str,
                    instrument_id=instrument_id,
                    asset_family=row.get("asset_family", ""),
                    market=row.get("market", ""),
                    exchange=row.get("exchange", ""),
                    instrument_type=row.get("asset_type", ""),
                    symbol=row.get("symbol", ""),
                    name=row.get("name", ""),
                    currency="CNY",
                    listing_date="",
                    delisting_date="",
                    status="active",
                    underlying_id="",
                    contract_multiplier="",
                    price_tick="",
                    quote_unit="",
                    trading_unit="",
                    delivery_type="",
                    exercise_type="",
                    option_type="",
                    strike_price="",
                    expire_date="",
                    last_trade_date="",
                    source_id=row.get("source_id", ""),
                    source_url=row.get("source_url", ""),
                    source_type=row.get("source_type", ""),
                    retrieved_at=row.get("retrieved_at", ""),
                    raw_path=row.get("raw_path", ""),
                    run_id=run_id,
                ),
            )

        for row in self._load_rows_from_latest_summaries(self.public_bond_runner.latest_summaries()):
            symbol = normalize_text(row.get("symbol")) or normalize_text(row.get("curve_name")) or normalize_text(row.get("name"))
            exchange = normalize_text(row.get("exchange")) or "CN_BONDS"
            if not symbol:
                continue
            instrument_id = f"{exchange}:{symbol}:{normalize_text(row.get('tenor'))}".rstrip(":")
            rows_by_id.setdefault(
                instrument_id,
                self._instrument_row(
                    trade_date_str=trade_date_str,
                    instrument_id=instrument_id,
                    asset_family=row.get("asset_family", ""),
                    market=row.get("market", ""),
                    exchange=exchange,
                    instrument_type=row.get("dataset_type", ""),
                    symbol=symbol,
                    name=row.get("name", "") or row.get("curve_name", ""),
                    currency="CNY",
                    listing_date="",
                    delisting_date="",
                    status="active",
                    underlying_id="",
                    contract_multiplier="",
                    price_tick="",
                    quote_unit="",
                    trading_unit="",
                    delivery_type="",
                    exercise_type="",
                    option_type="",
                    strike_price="",
                    expire_date="",
                    last_trade_date="",
                    source_id=row.get("source_id", ""),
                    source_url=row.get("source_url", ""),
                    source_type=row.get("source_type", ""),
                    retrieved_at=row.get("retrieved_at", ""),
                    raw_path=row.get("raw_path", ""),
                    run_id=run_id,
                ),
            )

        for row in self._load_rows_from_latest_summaries(self.public_reference_runner.latest_summaries()):
            symbol = normalize_text(row.get("symbol"))
            exchange = normalize_text(row.get("exchange"))
            if not symbol:
                continue
            instrument_id = f"{exchange}:{symbol}:{normalize_text(row.get('tenor'))}".rstrip(":")
            rows_by_id.setdefault(
                instrument_id,
                self._instrument_row(
                    trade_date_str=trade_date_str,
                    instrument_id=instrument_id,
                    asset_family=row.get("asset_family", ""),
                    market=row.get("market", ""),
                    exchange=exchange,
                    instrument_type=row.get("reference_type", ""),
                    symbol=symbol,
                    name=row.get("name", ""),
                    currency=row.get("quote_currency", "") or row.get("base_currency", ""),
                    listing_date="",
                    delisting_date="",
                    status="active",
                    underlying_id="",
                    contract_multiplier="",
                    price_tick="",
                    quote_unit=row.get("unit", ""),
                    trading_unit="",
                    delivery_type="",
                    exercise_type="",
                    option_type="",
                    strike_price="",
                    expire_date="",
                    last_trade_date="",
                    source_id=row.get("source_id", ""),
                    source_url=row.get("source_url", ""),
                    source_type=row.get("source_type", ""),
                    retrieved_at=row.get("retrieved_at", ""),
                    raw_path=row.get("raw_path", ""),
                    run_id=run_id,
                ),
            )

        crypto_rows = self._load_rows_from_latest_summaries(self.crypto_runner.latest_summaries())
        for row in crypto_rows:
            symbol = normalize_text(row.get("symbol"))
            if not symbol:
                continue
            instrument_id = f"COINGECKO:{symbol}"
            rows_by_id.setdefault(
                instrument_id,
                self._instrument_row(
                    trade_date_str=trade_date_str,
                    instrument_id=instrument_id,
                    asset_family=row.get("asset_family", ""),
                    market=row.get("market", ""),
                    exchange=row.get("exchange", ""),
                    instrument_type="crypto_asset",
                    symbol=symbol,
                    name=row.get("name", ""),
                    currency="USD",
                    listing_date="",
                    delisting_date="",
                    status="active",
                    underlying_id="",
                    contract_multiplier="",
                    price_tick="",
                    quote_unit="USD",
                    trading_unit="",
                    delivery_type="",
                    exercise_type="",
                    option_type="",
                    strike_price="",
                    expire_date="",
                    last_trade_date="",
                    source_id=row.get("source_id", ""),
                    source_url=row.get("source_url", ""),
                    source_type=row.get("source_type", ""),
                    retrieved_at=row.get("retrieved_at", ""),
                    raw_path=row.get("raw_path", ""),
                    run_id=run_id,
                ),
            )
        return list(rows_by_id.values())

    def _build_bond_master_rows(self, *, run_id: str) -> List[Dict[str, str]]:
        rows_by_id: Dict[str, Dict[str, str]] = {}
        for row in self._load_rows_from_latest_summaries(self.public_bond_runner.latest_summaries()):
            symbol = normalize_text(row.get("symbol")) or normalize_text(row.get("curve_name")) or normalize_text(row.get("name"))
            exchange = normalize_text(row.get("exchange")) or "CN_BONDS"
            tenor = normalize_text(row.get("tenor"))
            if not symbol:
                continue
            instrument_id = f"{exchange}:{symbol}:{tenor}".rstrip(":")
            rows_by_id.setdefault(
                instrument_id,
                {
                    "trade_date": normalize_text(row.get("trade_date")),
                    "instrument_id": instrument_id,
                    "asset_family": normalize_text(row.get("asset_family")) or "bonds_rates_cn",
                    "market": normalize_text(row.get("market")),
                    "exchange": exchange,
                    "symbol": symbol,
                    "name": normalize_text(row.get("name")) or normalize_text(row.get("curve_name")) or symbol,
                    "dataset_type": normalize_text(row.get("dataset_type")),
                    "bond_type": self._infer_bond_type(row),
                    "issuer": "",
                    "tenor": tenor,
                    "currency": "CNY",
                    "maturity_date": "",
                    "status": "active",
                    "source_id": normalize_text(row.get("source_id")),
                    "source_url": normalize_text(row.get("source_url")),
                    "source_type": normalize_text(row.get("source_type")),
                    "retrieved_at": normalize_text(row.get("retrieved_at")) or iso_timestamp(),
                    "raw_path": normalize_text(row.get("raw_path")),
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(instrument_id=instrument_id, source_id=normalize_text(row.get("source_id"))),
                    "run_id": run_id,
                },
            )
        return list(rows_by_id.values())

    def _build_bond_quote_rows(self, *, run_id: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for row in self._load_rows_from_latest_summaries(self.public_bond_runner.latest_summaries()):
            symbol = normalize_text(row.get("symbol")) or normalize_text(row.get("curve_name")) or normalize_text(row.get("name"))
            if not symbol:
                continue
            rows.append(
                {
                    "trade_date": normalize_text(row.get("trade_date")),
                    "asset_family": normalize_text(row.get("asset_family")) or "bonds_rates_cn",
                    "market": normalize_text(row.get("market")),
                    "exchange": normalize_text(row.get("exchange")) or "CN_BONDS",
                    "symbol": symbol,
                    "name": normalize_text(row.get("name")) or normalize_text(row.get("curve_name")) or symbol,
                    "dataset_type": normalize_text(row.get("dataset_type")),
                    "tenor": normalize_text(row.get("tenor")),
                    "price": normalize_text(row.get("price")),
                    "bid_price": normalize_text(row.get("bid_price")),
                    "ask_price": normalize_text(row.get("ask_price")),
                    "yield": normalize_text(row.get("yield")),
                    "bid_yield": normalize_text(row.get("bid_yield")),
                    "ask_yield": normalize_text(row.get("ask_yield")),
                    "weighted_yield": normalize_text(row.get("weighted_yield")),
                    "change_bp": normalize_text(row.get("change_bp")),
                    "volume": normalize_text(row.get("volume")),
                    "source_id": normalize_text(row.get("source_id")),
                    "source_url": normalize_text(row.get("source_url")),
                    "source_type": normalize_text(row.get("source_type")),
                    "retrieved_at": normalize_text(row.get("retrieved_at")) or iso_timestamp(),
                    "raw_path": normalize_text(row.get("raw_path")),
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(
                        instrument_id=f"{normalize_text(row.get('exchange'))}:{symbol}:{normalize_text(row.get('dataset_type'))}:{normalize_text(row.get('tenor'))}",
                        source_id=normalize_text(row.get("source_id")),
                    ),
                    "run_id": run_id,
                }
            )
        return rows

    def _build_fx_quote_rows(self, *, run_id: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for row in self._load_rows_from_latest_summaries(self.public_reference_runner.latest_summaries()):
            if normalize_text(row.get("asset_family")) != "fx_money_market_cn":
                continue
            symbol = normalize_text(row.get("symbol"))
            if not symbol:
                continue
            value = normalize_text(row.get("value"))
            rows.append(
                {
                    "trade_date": normalize_text(row.get("trade_date")),
                    "asset_family": "fx_money_market_cn",
                    "market": normalize_text(row.get("market")),
                    "exchange": normalize_text(row.get("exchange")),
                    "symbol": symbol,
                    "name": normalize_text(row.get("name")) or symbol,
                    "quote_type": normalize_text(row.get("reference_type")),
                    "base_currency": normalize_text(row.get("base_currency")),
                    "quote_currency": normalize_text(row.get("quote_currency")),
                    "tenor": normalize_text(row.get("tenor")),
                    "value": value,
                    "bid": "",
                    "ask": "",
                    "mid": value,
                    "unit": normalize_text(row.get("unit")),
                    "source_id": normalize_text(row.get("source_id")),
                    "source_url": normalize_text(row.get("source_url")),
                    "source_type": normalize_text(row.get("source_type")),
                    "retrieved_at": normalize_text(row.get("retrieved_at")) or iso_timestamp(),
                    "raw_path": normalize_text(row.get("raw_path")),
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(instrument_id=f"{normalize_text(row.get('exchange'))}:{symbol}:{normalize_text(row.get('tenor'))}", source_id=normalize_text(row.get("source_id"))),
                    "run_id": run_id,
                }
            )
        return rows

    def _build_commodity_spot_rows(self, *, run_id: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for row in self._load_rows_from_latest_summaries(self.public_asset_runner.latest_summaries()):
            market = normalize_text(row.get("market"))
            if market not in {"cn_sge_spot", "cn_carbon"}:
                continue
            symbol = normalize_text(row.get("symbol"))
            if not symbol:
                continue
            rows.append(
                {
                    "trade_date": normalize_text(row.get("trade_date")),
                    "asset_family": normalize_text(row.get("asset_family")) or "commodity_energy_cn",
                    "market": market,
                    "exchange": normalize_text(row.get("exchange")),
                    "symbol": symbol,
                    "name": normalize_text(row.get("name")) or symbol,
                    "commodity_type": "carbon" if market == "cn_carbon" else "precious_metal_spot",
                    "price": normalize_text(row.get("last_price")),
                    "change_amount": normalize_text(row.get("change_amount")),
                    "change_pct": normalize_text(row.get("change_pct")),
                    "high": normalize_text(row.get("high")),
                    "low": normalize_text(row.get("low")),
                    "volume": normalize_text(row.get("volume")),
                    "unit": "",
                    "source_id": normalize_text(row.get("source_id")),
                    "source_url": normalize_text(row.get("source_url")),
                    "source_type": normalize_text(row.get("source_type")),
                    "retrieved_at": normalize_text(row.get("retrieved_at")) or iso_timestamp(),
                    "raw_path": normalize_text(row.get("raw_path")),
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(instrument_id=f"{normalize_text(row.get('exchange'))}:{symbol}:{market}", source_id=normalize_text(row.get("source_id"))),
                    "run_id": run_id,
                }
            )
        for row in self._load_rows_from_latest_summaries(self.public_reference_runner.latest_summaries()):
            if normalize_text(row.get("asset_family")) != "precious_metals_spot_cn":
                continue
            symbol = normalize_text(row.get("symbol"))
            if not symbol:
                continue
            value = normalize_text(row.get("value"))
            rows.append(
                {
                    "trade_date": normalize_text(row.get("trade_date")),
                    "asset_family": "precious_metals_spot_cn",
                    "market": normalize_text(row.get("market")),
                    "exchange": normalize_text(row.get("exchange")),
                    "symbol": symbol,
                    "name": normalize_text(row.get("name")) or symbol,
                    "commodity_type": "precious_metal_reference",
                    "price": value,
                    "change_amount": "",
                    "change_pct": "",
                    "high": "",
                    "low": "",
                    "volume": "",
                    "unit": normalize_text(row.get("unit")),
                    "source_id": normalize_text(row.get("source_id")),
                    "source_url": normalize_text(row.get("source_url")),
                    "source_type": normalize_text(row.get("source_type")),
                    "retrieved_at": normalize_text(row.get("retrieved_at")) or iso_timestamp(),
                    "raw_path": normalize_text(row.get("raw_path")),
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(instrument_id=f"{normalize_text(row.get('exchange'))}:{symbol}:{normalize_text(row.get('market'))}", source_id=normalize_text(row.get("source_id"))),
                    "run_id": run_id,
                }
            )
        return rows

    def _build_yield_curve_rows(self, *, run_id: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for row in self._load_rows_from_latest_summaries(self.public_bond_runner.latest_summaries()):
            dataset_type = normalize_text(row.get("dataset_type"))
            if dataset_type != YIELD_CURVE_DATASET:
                continue
            curve_name = normalize_text(row.get("curve_name")) or normalize_text(row.get("name")) or "中债收益率曲线"
            tenor = normalize_text(row.get("tenor"))
            if not tenor:
                continue
            rows.append(
                {
                    "trade_date": normalize_text(row.get("trade_date")),
                    "asset_family": normalize_text(row.get("asset_family")) or "bonds_rates_cn",
                    "market": normalize_text(row.get("market")) or "cn_yield_curve",
                    "exchange": normalize_text(row.get("exchange")) or "CHINABOND",
                    "curve_name": curve_name,
                    "curve_type": "china_bond",
                    "tenor": tenor,
                    "tenor_years": self._tenor_years(tenor),
                    "yield": normalize_text(row.get("yield")),
                    "change_bp": normalize_text(row.get("change_bp")),
                    "source_id": normalize_text(row.get("source_id")),
                    "source_url": normalize_text(row.get("source_url")),
                    "source_type": normalize_text(row.get("source_type")),
                    "retrieved_at": normalize_text(row.get("retrieved_at")) or iso_timestamp(),
                    "raw_path": normalize_text(row.get("raw_path")),
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(
                        instrument_id=f"{normalize_text(row.get('exchange'))}:{curve_name}:{tenor}",
                        source_id=normalize_text(row.get("source_id")),
                    ),
                    "run_id": run_id,
                }
            )

        for row in self._load_rows_from_latest_summaries(self.public_reference_runner.latest_summaries()):
            if normalize_text(row.get("source_id")) != CN_US_TREASURY_RATE_DATASET:
                continue
            tenor = normalize_text(row.get("tenor"))
            symbol = normalize_text(row.get("symbol"))
            if not tenor or not symbol:
                continue
            curve_type = "cn_treasury" if symbol.startswith("CN_GOVT_") else "us_treasury"
            curve_name = "China Government Yield Curve" if curve_type == "cn_treasury" else "US Treasury Yield Curve"
            rows.append(
                {
                    "trade_date": normalize_text(row.get("trade_date")),
                    "asset_family": "bonds_rates_cn",
                    "market": normalize_text(row.get("market")) or "cross_market_treasury_yield",
                    "exchange": normalize_text(row.get("exchange")) or "EASTMONEY",
                    "curve_name": curve_name,
                    "curve_type": curve_type,
                    "tenor": tenor,
                    "tenor_years": self._tenor_years(tenor),
                    "yield": normalize_text(row.get("value")),
                    "change_bp": normalize_text(row.get("change_bp")),
                    "source_id": normalize_text(row.get("source_id")),
                    "source_url": normalize_text(row.get("source_url")),
                    "source_type": normalize_text(row.get("source_type")),
                    "retrieved_at": normalize_text(row.get("retrieved_at")) or iso_timestamp(),
                    "raw_path": normalize_text(row.get("raw_path")),
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(
                        instrument_id=f"{normalize_text(row.get('exchange'))}:{curve_name}:{tenor}",
                        source_id=normalize_text(row.get("source_id")),
                    ),
                    "run_id": run_id,
                }
            )
        return rows

    def _build_crypto_global_quote_rows(self, *, run_id: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for row in self._load_rows_from_latest_summaries(self.crypto_runner.latest_summaries()):
            symbol = normalize_text(row.get("symbol"))
            if not symbol:
                continue
            if normalize_text(row.get("market")) == "crypto_derivatives_public":
                rows.append(
                    {
                        "trade_date": normalize_text(row.get("trade_date")),
                        "asset_family": normalize_text(row.get("asset_family")) or "crypto_global_observation",
                        "market": normalize_text(row.get("market")),
                        "exchange": normalize_text(row.get("exchange")),
                        "symbol": symbol,
                        "name": symbol,
                        "quote_type": "derivatives_public",
                        "contract_type": normalize_text(row.get("contract_type")),
                        "price_usd": normalize_text(row.get("price_usd")),
                        "market_cap": "",
                        "total_volume": normalize_text(row.get("volume_24h_usd")),
                        "high_24h": "",
                        "low_24h": "",
                        "change_pct_24h": "",
                        "source_id": normalize_text(row.get("source_id")),
                        "source_url": normalize_text(row.get("source_url")),
                        "source_type": normalize_text(row.get("source_type")),
                        "retrieved_at": normalize_text(row.get("retrieved_at")) or iso_timestamp(),
                        "raw_path": normalize_text(row.get("raw_path")),
                        "parser_version": PARSER_VERSION,
                        "checksum": self._row_checksum(instrument_id=f"{normalize_text(row.get('exchange'))}:{symbol}:{normalize_text(row.get('contract_type'))}", source_id=normalize_text(row.get("source_id"))),
                        "run_id": run_id,
                        "legal_note": normalize_text(row.get("legal_note")),
                    }
                )
                continue
            rows.append(
                {
                    "trade_date": normalize_text(row.get("trade_date")),
                    "asset_family": normalize_text(row.get("asset_family")) or "crypto_global_observation",
                    "market": normalize_text(row.get("market")),
                    "exchange": normalize_text(row.get("exchange")),
                    "symbol": symbol,
                    "name": normalize_text(row.get("name")) or symbol,
                    "quote_type": "spot",
                    "contract_type": "",
                    "price_usd": normalize_text(row.get("price_usd")),
                    "market_cap": normalize_text(row.get("market_cap")),
                    "total_volume": normalize_text(row.get("total_volume")),
                    "high_24h": normalize_text(row.get("high_24h")),
                    "low_24h": normalize_text(row.get("low_24h")),
                    "change_pct_24h": normalize_text(row.get("change_pct_24h")),
                    "source_id": normalize_text(row.get("source_id")),
                    "source_url": normalize_text(row.get("source_url")),
                    "source_type": normalize_text(row.get("source_type")),
                    "retrieved_at": normalize_text(row.get("retrieved_at")) or iso_timestamp(),
                    "raw_path": normalize_text(row.get("raw_path")),
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(instrument_id=f"{normalize_text(row.get('exchange'))}:{symbol}:spot", source_id=normalize_text(row.get("source_id"))),
                    "run_id": run_id,
                    "legal_note": normalize_text(row.get("legal_note")),
                }
            )
        return rows

    def _build_daily_ohlcv_rows(self, *, trade_date_str: str, run_id: str) -> List[Dict[str, str]]:
        rows_by_key: Dict[str, Dict[str, str]] = {}
        derivative_trade_date = self._resolve_derivative_trade_date(trade_date_str)
        if derivative_trade_date:
            derivative_day = self.checkpoints.get_day(derivative_trade_date)
            for dataset_name, instrument_type in ((FUTURES_DATASET, "future"), (OPTIONS_DATASET, "option")):
                output_path = normalize_text(derivative_day.get("outputs", {}).get(dataset_name))
                if not output_path:
                    continue
                csv_path = self.project_root / output_path
                if not csv_path.exists():
                    continue
                for row in iter_csv_rows(csv_path):
                    exchange = normalize_text(row.get("exchange"))
                    symbol = normalize_text(row.get("contract"))
                    if not exchange or not symbol:
                        continue
                    key = f"{normalize_text(row.get('trade_date'))}|{exchange}:{symbol}|{dataset_name}"
                    rows_by_key[key] = self._daily_ohlcv_row(
                        trade_date=normalize_text(row.get("trade_date")),
                        instrument_id=f"{exchange}:{symbol}",
                        asset_family="exchange_derivatives_cn",
                        market="cn_derivatives",
                        exchange=exchange,
                        instrument_type=instrument_type,
                        symbol=symbol,
                        name=normalize_text(row.get("variety_name")) or normalize_text(row.get("product_name")) or symbol,
                        currency="CNY",
                        open_value=row.get("open"),
                        high_value=row.get("high"),
                        low_value=row.get("low"),
                        close_value=row.get("close"),
                        pre_close=row.get("prev_close"),
                        settlement=row.get("settlement"),
                        pre_settlement=row.get("prev_settlement"),
                        volume=row.get("volume"),
                        amount=row.get("turnover"),
                        open_interest=row.get("open_interest"),
                        turnover_rate=row.get("turnover_rate"),
                        source_id=f"{exchange.lower()}.{dataset_name}",
                        source_url=row.get("source_url"),
                        source_type=row.get("source_type"),
                        retrieved_at=row.get("retrieved_at"),
                        raw_path=row.get("raw_path"),
                        run_id=run_id,
                    )

        latest_asset_rows = self._load_rows_from_latest_summaries(self.public_asset_runner.latest_summaries())
        supported_asset_types = {"stock", "etf", "lof", "reits", "convertible_bond"}
        for row in latest_asset_rows:
            asset_type = normalize_text(row.get("asset_type"))
            if asset_type not in supported_asset_types:
                continue
            exchange = normalize_text(row.get("exchange")) or "CN_MARKET"
            symbol = normalize_text(row.get("symbol"))
            if not symbol:
                continue
            key = f"{normalize_text(row.get('trade_date'))}|{exchange}:{symbol}|public_assets"
            rows_by_key[key] = self._daily_ohlcv_row(
                trade_date=normalize_text(row.get("trade_date")),
                instrument_id=f"{exchange}:{symbol}",
                asset_family=normalize_text(row.get("asset_family")) or "equities_funds_cn",
                market=normalize_text(row.get("market")),
                exchange=exchange,
                instrument_type=asset_type,
                symbol=symbol,
                name=normalize_text(row.get("name")) or symbol,
                currency="CNY",
                open_value=row.get("open"),
                high_value=row.get("high"),
                low_value=row.get("low"),
                close_value=row.get("last_price"),
                pre_close=row.get("prev_close"),
                settlement="",
                pre_settlement="",
                volume=row.get("volume"),
                amount=row.get("amount"),
                open_interest="",
                turnover_rate="",
                source_id=row.get("source_id"),
                source_url=row.get("source_url"),
                source_type=row.get("source_type"),
                retrieved_at=row.get("retrieved_at"),
                raw_path=row.get("raw_path"),
                run_id=run_id,
            )

        crypto_summaries = self.crypto_runner.latest_summaries()
        preferred_crypto_outputs: List[str] = []
        for dataset_name in (CRYPTO_DAILY_QUOTES_DATASET, CRYPTO_GLOBAL_SNAPSHOT_DATASET):
            output_path = normalize_text(crypto_summaries.get(dataset_name, {}).get("output_path"))
            if output_path:
                preferred_crypto_outputs.append(output_path)
        for output_path in preferred_crypto_outputs:
            csv_path = self.project_root / output_path
            if not csv_path.exists():
                continue
            for row in iter_csv_rows(csv_path):
                if normalize_text(row.get("market")) == "crypto_derivatives_public":
                    continue
                exchange = normalize_text(row.get("exchange")) or "COINGECKO"
                symbol = normalize_text(row.get("symbol"))
                if not symbol:
                    continue
                key = f"{normalize_text(row.get('trade_date'))}|{exchange}:{symbol}|crypto"
                rows_by_key.setdefault(
                    key,
                    self._daily_ohlcv_row(
                        trade_date=normalize_text(row.get("trade_date")),
                        instrument_id=f"{exchange}:{symbol}",
                        asset_family=normalize_text(row.get("asset_family")) or "crypto_global_observation",
                        market=normalize_text(row.get("market")) or "global_crypto",
                        exchange=exchange,
                        instrument_type="crypto_asset",
                        symbol=symbol,
                        name=normalize_text(row.get("name")) or symbol,
                        currency="USD",
                        open_value="",
                        high_value=row.get("high_24h"),
                        low_value=row.get("low_24h"),
                        close_value=row.get("price_usd"),
                        pre_close="",
                        settlement="",
                        pre_settlement="",
                        volume=row.get("total_volume"),
                        amount=row.get("total_volume"),
                        open_interest="",
                        turnover_rate="",
                        source_id=row.get("source_id"),
                        source_url=row.get("source_url"),
                        source_type=row.get("source_type"),
                        retrieved_at=row.get("retrieved_at"),
                        raw_path=row.get("raw_path"),
                        run_id=run_id,
                    ),
                )

        return list(rows_by_key.values())

    def _build_fund_nav_rows(self, *, run_id: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for row in self._load_rows_from_latest_summaries(self.public_asset_runner.latest_summaries()):
            asset_type = normalize_text(row.get("asset_type"))
            if asset_type not in {"open_fund", "money_fund"}:
                continue
            exchange = normalize_text(row.get("exchange")) or "CN_FUNDS"
            symbol = normalize_text(row.get("symbol"))
            if not symbol:
                continue
            rows.append(
                {
                    "trade_date": normalize_text(row.get("trade_date")),
                    "instrument_id": f"{exchange}:{symbol}",
                    "asset_family": normalize_text(row.get("asset_family")) or "equities_funds_cn",
                    "market": normalize_text(row.get("market")) or "cn_funds",
                    "exchange": exchange,
                    "symbol": symbol,
                    "name": normalize_text(row.get("name")) or symbol,
                    "fund_type": asset_type,
                    "nav": normalize_text(row.get("last_price")),
                    "nav_change": normalize_text(row.get("change_amount")),
                    "nav_change_pct": normalize_text(row.get("change_pct")),
                    "nav_date": normalize_text(row.get("trade_date")),
                    "source_id": normalize_text(row.get("source_id")),
                    "source_url": normalize_text(row.get("source_url")),
                    "source_type": normalize_text(row.get("source_type")),
                    "retrieved_at": normalize_text(row.get("retrieved_at")) or iso_timestamp(),
                    "raw_path": normalize_text(row.get("raw_path")),
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(
                        instrument_id=f"{exchange}:{symbol}:{asset_type}",
                        source_id=normalize_text(row.get("source_id")),
                    ),
                    "run_id": run_id,
                }
            )
        return rows

    def _build_reits_quote_rows(self, *, run_id: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for row in self._load_rows_from_latest_summaries(self.public_asset_runner.latest_summaries()):
            if normalize_text(row.get("asset_type")) != "reits":
                continue
            exchange = normalize_text(row.get("exchange")) or "CN_REITS"
            symbol = normalize_text(row.get("symbol"))
            if not symbol:
                continue
            rows.append(
                {
                    "trade_date": normalize_text(row.get("trade_date")),
                    "instrument_id": f"{exchange}:{symbol}",
                    "asset_family": normalize_text(row.get("asset_family")) or "equities_funds_cn",
                    "market": normalize_text(row.get("market")) or "cn_reits",
                    "exchange": exchange,
                    "symbol": symbol,
                    "name": normalize_text(row.get("name")) or symbol,
                    "open": normalize_text(row.get("open")),
                    "high": normalize_text(row.get("high")),
                    "low": normalize_text(row.get("low")),
                    "close": normalize_text(row.get("last_price")),
                    "pre_close": normalize_text(row.get("prev_close")),
                    "volume": normalize_text(row.get("volume")),
                    "amount": normalize_text(row.get("amount")),
                    "source_id": normalize_text(row.get("source_id")),
                    "source_url": normalize_text(row.get("source_url")),
                    "source_type": normalize_text(row.get("source_type")),
                    "retrieved_at": normalize_text(row.get("retrieved_at")) or iso_timestamp(),
                    "raw_path": normalize_text(row.get("raw_path")),
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(
                        instrument_id=f"{exchange}:{symbol}:reits",
                        source_id=normalize_text(row.get("source_id")),
                    ),
                    "run_id": run_id,
                }
            )
        return rows

    def _build_trading_calendar_rows(self, *, trade_date_str: str, run_id: str) -> List[Dict[str, str]]:
        rows_by_id: Dict[str, Dict[str, str]] = {}
        derivative_trade_date = self._resolve_derivative_trade_date(trade_date_str)
        if derivative_trade_date:
            day = self.checkpoints.get_day(derivative_trade_date)
            rows_by_id["cn_derivatives"] = self._trading_calendar_row(
                trade_date=derivative_trade_date,
                calendar_id="cn_derivatives",
                asset_family="exchange_derivatives_cn",
                market="cn_derivatives",
                exchange="MULTI",
                day_status=normalize_text(day.get("status")) or SUCCESS_STATUS,
                source_trade_date=derivative_trade_date,
                source_id="platform.derivatives_calendar",
                source_url="state/checkpoints.json",
                source_type="official",
                raw_path="state/checkpoints.json",
                run_id=run_id,
            )
        for calendar_id, asset_family, market, source_id, summaries in (
            ("cn_equities", "equities_funds_cn", "cn_equities", "platform.public_assets_calendar", self.public_asset_runner.latest_summaries()),
            ("cn_fx_rates", "fx_money_market_cn", "cn_fx_reference", "platform.public_references_calendar", self.public_reference_runner.latest_summaries()),
            ("cn_bonds_rates", "bonds_rates_cn", "cn_interbank_bond", "platform.public_bonds_calendar", self.public_bond_runner.latest_summaries()),
            ("crypto_global", "crypto_global_observation", "global_crypto", "platform.crypto_calendar", self.crypto_runner.latest_summaries()),
        ):
            trade_dates = [normalize_text(summary.get("trade_date")) for summary in summaries.values() if normalize_text(summary.get("trade_date"))]
            if not trade_dates:
                continue
            latest_trade_date = sorted(trade_dates)[-1]
            latest_summary = next((summary for summary in summaries.values() if normalize_text(summary.get("trade_date")) == latest_trade_date), {})
            rows_by_id[calendar_id] = self._trading_calendar_row(
                trade_date=latest_trade_date,
                calendar_id=calendar_id,
                asset_family=asset_family,
                market=market,
                exchange=normalize_text(latest_summary.get("exchange")) or "MULTI",
                day_status=normalize_text(latest_summary.get("status")) or SUCCESS_STATUS,
                source_trade_date=latest_trade_date,
                source_id=source_id,
                source_url=normalize_text(latest_summary.get("source_url")) or normalize_text(latest_summary.get("output_path")),
                source_type=normalize_text(latest_summary.get("source_type")) or "fallback_online",
                raw_path=normalize_text(latest_summary.get("raw_path")),
                run_id=run_id,
            )
        return list(rows_by_id.values())

    def _build_run_health_rows(self, *, trade_date_str: str, run_id: str) -> List[Dict[str, str]]:
        payload = self.regression_state_reader() or {}
        result = payload.get("result", {}) or {}
        if not result:
            return []
        audit = result.get("audit", {}) or {}
        issue_category_counts = dict(audit.get("issue_category_counts", {}) or {})
        blocked_issues = list(audit.get("blocked_issues", []) or [])
        blocked_issue_count = len(blocked_issues)
        if not blocked_issue_count:
            blocked_issue_count = sum(int(value or 0) for value in issue_category_counts.values())
        return [
            {
                "trade_date": trade_date_str,
                "workflow_name": "regression_smoke",
                "scope": "platform_release_gate",
                "status": normalize_text(result.get("status")) or FAILED_STATUS,
                "engineering_status": normalize_text(result.get("engineering_status")) or "",
                "updated_at": normalize_text(payload.get("updated_at")),
                "checked_dates": ",".join(str(item) for item in (result.get("dates", []) or [])),
                "date_statuses": safe_json_dumps(result.get("date_statuses", {}) or {}),
                "window_statuses": safe_json_dumps(
                    {
                        str(window_name): str((window_payload or {}).get("status", ""))
                        for window_name, window_payload in ((result.get("window_results", {}) or {}).items())
                    }
                ),
                "window_sample_counts": safe_json_dumps(
                    {
                        str(window_name): int((window_payload or {}).get("sample_count", 0) or 0)
                        for window_name, window_payload in ((result.get("window_results", {}) or {}).items())
                    }
                ),
                "window_sampled_dates": safe_json_dumps(
                    {
                        str(window_name): list((window_payload or {}).get("sampled_dates", []) or [])
                        for window_name, window_payload in ((result.get("window_results", {}) or {}).items())
                    }
                ),
                "needs_repair_dates": ",".join(str(item) for item in (audit.get("needs_repair_dates", []) or [])),
                "issue_category_counts": safe_json_dumps(issue_category_counts),
                "blocked_issue_count": str(blocked_issue_count),
                "blocked_issues": " | ".join(blocked_issues),
                "platform_sync_status": normalize_text(result.get("platform_sync_status")),
                "platform_validation_status": normalize_text(result.get("platform_validation_status")),
                "build_db_status": normalize_text(result.get("build_db_status")),
                "gui_smoke_status": "success" if bool((result.get("gui_smoke", {}) or {}).get("has_yield_curves")) else "",
                "source_id": "platform.regression_smoke",
                "source_url": "state/regression_smoke.json",
                "source_type": "derived",
                "retrieved_at": iso_timestamp(),
                "raw_path": "state/regression_smoke.json",
                "parser_version": PARSER_VERSION,
                "checksum": self._row_checksum(instrument_id=f"regression_smoke:{trade_date_str}", source_id="platform.regression_smoke"),
                "run_id": run_id,
            }
        ]

    def _build_run_history_rows(self, *, trade_date_str: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        regression_payload = self.regression_state_reader() or {}
        regression_result = regression_payload.get("result", {}) or {}
        if regression_result:
            date_statuses = dict(regression_result.get("date_statuses", {}) or {})
            success_count = sum(1 for status in date_statuses.values() if normalize_text(status) == SUCCESS_STATUS)
            blocked_issues = list((regression_result.get("audit", {}) or {}).get("blocked_issues", []) or [])
            issue_category_counts = dict((regression_result.get("audit", {}) or {}).get("issue_category_counts", {}) or {})
            rows.append(
                self._run_history_row(
                    trade_date=trade_date_str,
                    history_kind="regression_smoke",
                    run_id=f"regression-smoke:{normalize_text(regression_payload.get('updated_at')) or trade_date_str}",
                    scope="platform_release_gate",
                    action_name="regression_smoke",
                    mode=normalize_text(regression_result.get("profile")) or "core",
                    target="platform_release_gate",
                    window_start="",
                    window_end="",
                    status=normalize_text(regression_result.get("status")) or FAILED_STATUS,
                    engineering_status=normalize_text(regression_result.get("engineering_status")),
                    elapsed_seconds="",
                    item_count=str(len(date_statuses)),
                    success_count=str(success_count),
                    non_success_count=str(max(len(date_statuses) - success_count, 0)),
                    blocked_issue_count=str(len(blocked_issues) or sum(int(value or 0) for value in issue_category_counts.values())),
                    issue_category_counts=safe_json_dumps(issue_category_counts),
                    blocked_issues=" | ".join(blocked_issues),
                    updated_at=normalize_text(regression_payload.get("updated_at")),
                    source_id="platform.run_history",
                    source_url="state/regression_smoke.json",
                    source_type="derived",
                    raw_path="state/regression_smoke.json",
                )
            )

        pregrab_payload = self._read_optional_state(self.pregrab_state_reader, self.pregrab_state_path)
        for run in list(pregrab_payload.get("runs", []) or []):
            exchange_results = run.get("exchange_results", {}) or {}
            for exchange, summary in exchange_results.items():
                blocked_issues = list((summary or {}).get("blocked_issues", []) or [])
                rows.append(
                    self._run_history_row(
                        trade_date=normalize_text(run.get("window_end")) or trade_date_str,
                        history_kind="pregrab_window",
                        run_id=normalize_text(run.get("run_id")) or f"pregrab:{exchange}:{normalize_text(run.get('window_end'))}",
                        scope="exchange_pregrab",
                        action_name="pregrab_window",
                        mode=normalize_text(run.get("mode")) or "production",
                        target=normalize_text(summary.get("exchange")) or normalize_text(exchange),
                        window_start=normalize_text(run.get("window_start")),
                        window_end=normalize_text(run.get("window_end")),
                        status=normalize_text(summary.get("status")) or FAILED_STATUS,
                        engineering_status=normalize_text(summary.get("engineering_status")),
                        elapsed_seconds=str(summary.get("elapsed_seconds", "")),
                        item_count=str(summary.get("day_count", 0) or 0),
                        success_count=str(summary.get("success_count", 0) or 0),
                        non_success_count=str(
                            int(summary.get("no_data_count", 0) or 0)
                            + int(summary.get("not_applicable_count", 0) or 0)
                            + int(summary.get("blocked_external_count", 0) or 0)
                            + int(summary.get("failed_count", 0) or 0)
                        ),
                        blocked_issue_count=str(len(blocked_issues) or int(summary.get("blocked_external_count", 0) or 0)),
                        issue_category_counts=safe_json_dumps(summary.get("issue_category_counts", {}) or {}),
                        blocked_issues=" | ".join(blocked_issues),
                        updated_at=normalize_text(pregrab_payload.get("updated_at")) or normalize_text(run.get("updated_at")),
                        source_id="platform.run_history",
                        source_url="state/pregrab_runs.json",
                        source_type="derived",
                        raw_path="state/pregrab_runs.json",
                    )
                )

        window_payload = self._read_optional_state(self.window_state_reader, self.window_state_path)
        for run in list(window_payload.get("runs", []) or []):
            date_counts = dict(run.get("date_counts", {}) or {})
            total_items = sum(int(value or 0) for value in date_counts.values())
            rows.append(
                self._run_history_row(
                    trade_date=normalize_text(run.get("window_end")) or normalize_text(run.get("updated_at"))[:10] or trade_date_str,
                    history_kind="window_sync",
                    run_id=normalize_text(run.get("run_id")) or f"window:{normalize_text(run.get('action_name'))}:{normalize_text(run.get('window_end'))}",
                    scope=normalize_text(run.get("scope")) or "window_sync",
                    action_name=normalize_text(run.get("action_name")) or "window_sync",
                    mode=normalize_text(run.get("mode")) or "production",
                    target=normalize_text(run.get("target")) or "all",
                    window_start=normalize_text(run.get("window_start")),
                    window_end=normalize_text(run.get("window_end")),
                    status=normalize_text(run.get("status")) or FAILED_STATUS,
                    engineering_status=normalize_text(run.get("engineering_status")),
                    elapsed_seconds=str(run.get("elapsed_seconds", "")),
                    item_count=str(total_items),
                    success_count=str(int(date_counts.get(SUCCESS_STATUS, 0) or 0)),
                    non_success_count=str(max(total_items - int(date_counts.get(SUCCESS_STATUS, 0) or 0), 0)),
                    blocked_issue_count=str(len(run.get("blocked_issues", []) or [])),
                    issue_category_counts=safe_json_dumps(run.get("issue_category_counts", {}) or {}),
                    blocked_issues=" | ".join(str(item) for item in (run.get("blocked_issues", []) or [])),
                    updated_at=normalize_text(run.get("updated_at")) or normalize_text(window_payload.get("updated_at")),
                    source_id="platform.run_history",
                    source_url="state/window_runs.json",
                    source_type="derived",
                    raw_path="state/window_runs.json",
                )
            )
        return rows

    def _build_coverage_history_rows(self, *, trade_date_str: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for csv_path in self._platform_dataset_paths(ASSET_COVERAGE_DATASET):
            relative_path = relative_to_project(csv_path, self.project_root)
            for row in iter_csv_rows(csv_path):
                asset_family = normalize_text(row.get("asset_family"))
                if not asset_family:
                    continue
                rows.append(
                    {
                        "trade_date": normalize_text(row.get("trade_date")) or trade_date_str,
                        "asset_family": asset_family,
                        "family_label": normalize_text(row.get("family_label")),
                        "engineering_status": normalize_text(row.get("engineering_status")),
                        "runtime_status": normalize_text(row.get("runtime_status")),
                        "coverage_ratio": normalize_text(row.get("coverage_ratio")),
                        "success_dataset_count": normalize_text(row.get("success_dataset_count")),
                        "non_success_dataset_count": normalize_text(row.get("non_success_dataset_count")),
                        "blocked_issue_count": normalize_text(row.get("blocked_issue_count")),
                        "external_issue_count": normalize_text(row.get("external_issue_count")),
                        "internal_issue_count": normalize_text(row.get("internal_issue_count")),
                        "total_row_count": normalize_text(row.get("total_row_count")),
                        "issue_root_cause_counts": normalize_text(row.get("issue_root_cause_counts")),
                        "source_id": "platform.coverage_history",
                        "source_url": f"platform://{ASSET_COVERAGE_DATASET}",
                        "source_type": "derived",
                        "retrieved_at": normalize_text(row.get("retrieved_at")) or iso_timestamp(),
                        "raw_path": relative_path,
                        "parser_version": PARSER_VERSION,
                        "checksum": self._row_checksum(
                            instrument_id=f"coverage_history:{normalize_text(row.get('trade_date'))}:{asset_family}",
                            source_id="platform.coverage_history",
                        ),
                    }
                )
        return rows

    def _build_source_health_history_rows(self, *, trade_date_str: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for csv_path in self._platform_dataset_paths(SOURCE_HEALTH_DATASET):
            relative_path = relative_to_project(csv_path, self.project_root)
            for row in iter_csv_rows(csv_path):
                source_id = normalize_text(row.get("source_id"))
                dataset = normalize_text(row.get("dataset"))
                if not source_id or not dataset:
                    continue
                rows.append(
                    {
                        "trade_date": normalize_text(row.get("trade_date")) or trade_date_str,
                        "source_id": source_id,
                        "dataset": dataset,
                        "asset_family": normalize_text(row.get("asset_family")),
                        "market": normalize_text(row.get("market")),
                        "exchange": normalize_text(row.get("exchange")),
                        "source_type": normalize_text(row.get("source_type")),
                        "last_status": normalize_text(row.get("last_status")),
                        "issue_category": normalize_text(row.get("issue_category")),
                        "issue_root_cause": normalize_text(row.get("issue_root_cause")),
                        "is_external_blocker": normalize_text(row.get("is_external_blocker")),
                        "blocked_reason": normalize_text(row.get("blocked_reason")),
                        "message": normalize_text(row.get("message")),
                        "output_path": normalize_text(row.get("output_path")),
                        "recorded_at": normalize_text(row.get("trade_date")) or trade_date_str,
                        "source_url": normalize_text(row.get("source_url")),
                        "raw_path": relative_path,
                        "parser_version": PARSER_VERSION,
                        "checksum": self._row_checksum(
                            instrument_id=f"source_health_history:{normalize_text(row.get('trade_date'))}:{source_id}:{dataset}",
                            source_id="platform.source_health_history",
                        ),
                    }
                )
        return rows

    def _run_history_row(
        self,
        *,
        trade_date: str,
        history_kind: str,
        run_id: str,
        scope: str,
        action_name: str,
        mode: str,
        target: str,
        window_start: str,
        window_end: str,
        status: str,
        engineering_status: str,
        elapsed_seconds: str,
        item_count: str,
        success_count: str,
        non_success_count: str,
        blocked_issue_count: str,
        issue_category_counts: str,
        blocked_issues: str,
        updated_at: str,
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
    ) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "history_kind": history_kind,
            "run_id": run_id,
            "scope": scope,
            "action_name": action_name,
            "mode": mode,
            "target": target,
            "window_start": window_start,
            "window_end": window_end,
            "status": status,
            "engineering_status": engineering_status,
            "elapsed_seconds": elapsed_seconds,
            "item_count": item_count,
            "success_count": success_count,
            "non_success_count": non_success_count,
            "blocked_issue_count": blocked_issue_count,
            "issue_category_counts": issue_category_counts,
            "blocked_issues": blocked_issues,
            "updated_at": updated_at or iso_timestamp(),
            "source_id": source_id,
            "source_url": source_url,
            "source_type": source_type,
            "retrieved_at": iso_timestamp(),
            "raw_path": raw_path,
            "parser_version": PARSER_VERSION,
            "checksum": self._row_checksum(
                instrument_id=f"run_history:{history_kind}:{trade_date}:{target}:{run_id}",
                source_id=source_id,
            ),
        }

    def _build_asset_coverage_rows(
        self,
        *,
        trade_date_str: str,
        platform_summaries: Dict[str, Dict[str, object]],
        run_id: str,
        source_health_rows: Optional[List[Dict[str, str]]] = None,
    ) -> List[Dict[str, str]]:
        summary_map = self._collect_latest_summary_by_dataset(
            trade_date_str=trade_date_str,
            platform_summaries=platform_summaries,
        )
        catalog_by_family: Dict[str, List[Dict[str, object]]] = {}
        for item in build_dataset_catalog():
            dataset_name = str(item.get("dataset", ""))
            if not dataset_name or dataset_name == ASSET_COVERAGE_DATASET:
                continue
            family_id = str(item.get("family_id", ""))
            if not family_id:
                continue
            catalog_by_family.setdefault(family_id, []).append(item)

        rows: List[Dict[str, str]] = []
        for family in build_asset_family_registry():
            family_items = catalog_by_family.get(family.family_id, [])
            dataset_names = [str(item.get("dataset", "")) for item in family_items if str(item.get("dataset", ""))]
            observed_summaries = [summary_map[name] for name in dataset_names if name in summary_map]
            family_source_rows = [
                row
                for row in (source_health_rows or [])
                if normalize_text(row.get("asset_family")) == family.family_id
                and normalize_text(row.get("dataset")) in dataset_names
            ]
            statuses = [normalize_text(item.get("status")) for item in observed_summaries if normalize_text(item.get("status"))]
            missing_datasets = [name for name in dataset_names if name not in summary_map]
            status_counts: Dict[str, int] = {}
            issue_root_cause_counts: Dict[str, int] = {}
            total_row_count = 0
            latest_trade_date = ""
            latest_success_trade_date = ""
            success_dataset_count = 0
            for summary in observed_summaries:
                status = normalize_text(summary.get("status"))
                if status:
                    status_counts[status] = status_counts.get(status, 0) + 1
                if status == SUCCESS_STATUS:
                    success_dataset_count += 1
                total_row_count += int(summary.get("row_count", 0) or 0)
                candidate_trade_date = normalize_text(summary.get("trade_date"))
                if candidate_trade_date and candidate_trade_date > latest_trade_date:
                    latest_trade_date = candidate_trade_date
                if status == SUCCESS_STATUS and candidate_trade_date and candidate_trade_date > latest_success_trade_date:
                    latest_success_trade_date = candidate_trade_date
            observed_dataset_count = len(observed_summaries)
            expected_dataset_count = len(dataset_names)
            non_success_dataset_count = observed_dataset_count - success_dataset_count
            runtime_status = self._merge_statuses(statuses) if statuses else NO_DATA_STATUS
            if missing_datasets and runtime_status == SUCCESS_STATUS:
                runtime_status = PARTIAL_SUCCESS_STATUS
            blocked_issue_count = 0
            external_issue_count = 0
            internal_issue_count = 0
            for row in family_source_rows:
                root_cause = normalize_text(row.get("issue_root_cause"))
                last_status = normalize_text(row.get("last_status"))
                if root_cause:
                    issue_root_cause_counts[root_cause] = issue_root_cause_counts.get(root_cause, 0) + 1
                if normalize_text(row.get("issue_category")) == "blocked_issue" or normalize_text(row.get("blocked_reason")):
                    blocked_issue_count += 1
                if last_status == SUCCESS_STATUS:
                    success_trade_date = normalize_text(row.get("last_success_trade_date"))
                    if success_trade_date and success_trade_date > latest_success_trade_date:
                        latest_success_trade_date = success_trade_date
                if self._is_external_root_cause(root_cause):
                    external_issue_count += 1
                elif root_cause and root_cause not in {"healthy", "no_data", "not_applicable"}:
                    internal_issue_count += 1
            coverage_ratio = f"{observed_dataset_count}/{expected_dataset_count}" if expected_dataset_count else ""
            engineering_status = "done"
            if expected_dataset_count and observed_dataset_count == 0:
                engineering_status = "pending"
            elif missing_datasets or internal_issue_count > 0:
                engineering_status = "partial"
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": family.family_id,
                    "family_label": family.label,
                    "phase": family.phase,
                    "registry_status": family.status,
                    "engineering_status": engineering_status,
                    "runtime_status": runtime_status,
                    "latest_trade_date": latest_trade_date,
                    "latest_success_trade_date": latest_success_trade_date,
                    "expected_dataset_count": str(expected_dataset_count),
                    "observed_dataset_count": str(observed_dataset_count),
                    "success_dataset_count": str(success_dataset_count),
                    "non_success_dataset_count": str(non_success_dataset_count),
                    "blocked_issue_count": str(blocked_issue_count),
                    "external_issue_count": str(external_issue_count),
                    "internal_issue_count": str(internal_issue_count),
                    "total_row_count": str(total_row_count),
                    "coverage_ratio": coverage_ratio,
                    "datasets": safe_json_dumps(dataset_names),
                    "missing_datasets": safe_json_dumps(missing_datasets),
                    "status_counts": safe_json_dumps(status_counts),
                    "issue_root_cause_counts": safe_json_dumps(issue_root_cause_counts),
                    "markets": safe_json_dumps(family.markets),
                    "notes": family.notes,
                    "source_id": "platform.asset_coverage",
                    "source_url": "state/platform_metadata.json",
                    "source_type": "derived",
                    "retrieved_at": iso_timestamp(),
                    "raw_path": "state/platform_metadata.json",
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(
                        instrument_id=f"asset_coverage:{family.family_id}:{trade_date_str}",
                        source_id="platform.asset_coverage",
                    ),
                    "run_id": run_id,
                }
            )
        return rows

    def _build_validation_rows(
        self,
        *,
        trade_date_str: str,
        platform_summaries: Optional[Dict[str, Dict[str, object]]] = None,
    ) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        validated_at = iso_timestamp()
        derivative_trade_date = self._resolve_derivative_trade_date(trade_date_str)
        derivative_audit = self.workflow_runner.audit_canonical_date(derivative_trade_date) if derivative_trade_date else {}
        blocked_issues_by_dataset = self._index_blocked_issues(derivative_audit.get("blocked_issues", []))
        if derivative_trade_date:
            derivative_validation = self.workflow_runner.validate(derivative_trade_date)
            for dataset_name, result in derivative_validation.get("datasets", {}).items():
                dataset_blocked_issues = blocked_issues_by_dataset.get(dataset_name, [])
                rows.append(
                    {
                        "trade_date": trade_date_str,
                        "scope": "derivatives_canonical",
                        "dataset": dataset_name,
                        "source_trade_date": derivative_trade_date,
                        "status": str(result.get("status", derivative_validation.get("checkpoint_status", ""))),
                        "row_count": str(result.get("row_count", 0) or 0),
                        "schema_ok": str(bool(result.get("schema_ok", False))).lower(),
                        "duplicate_keys": str(result.get("duplicate_keys", 0) or 0),
                        "missing_raw_paths_count": str(len(result.get("missing_raw_paths", []))),
                        "completeness_ok": str(bool(result.get("completeness_ok", False))).lower(),
                        "master_data_completeness": str(bool(result.get("master_data_completeness", True))).lower(),
                        "result_chain_semantics_ok": str(bool(result.get("result_chain_semantics_ok", True))).lower(),
                        "contracts_latest_consistency_ok": str(bool(result.get("contracts_latest_consistency_ok", derivative_validation.get("contracts_latest", {}).get("matches_source_snapshot", False)))).lower()
                        if dataset_name == CONTRACTS_DATASET
                        else "",
                        "source_provenance_ok": str(not result.get("missing_raw_paths", [])).lower(),
                        "expected_markets": ",".join(result.get("expected_exchanges", [])),
                        "observed_markets": ",".join(result.get("observed_exchanges", [])),
                        "blocked_issue_count": str(len(dataset_blocked_issues)),
                        "blocked_issues": " | ".join(dataset_blocked_issues),
                        "no_data_reason": str(result.get("no_data_reason", "")),
                        "not_applicable_reason": str(result.get("not_applicable_reason", "")),
                        "output_path": self._get_derivative_output_path(derivative_trade_date, dataset_name),
                        "validated_at": validated_at,
                    }
                )

        for scope, runner, summaries_getter in (
            ("public_assets", self.public_asset_runner, self.public_asset_runner.latest_summaries),
            ("public_references", self.public_reference_runner, self.public_reference_runner.latest_summaries),
            ("public_bonds", self.public_bond_runner, self.public_bond_runner.latest_summaries),
        ):
            summaries = summaries_getter()
            for dataset_name, summary in summaries.items():
                source_trade_date = str(summary.get("trade_date", ""))
                validation = runner.validate(source_trade_date, families=[dataset_name]) if source_trade_date else {"families": {}, "status": FAILED_STATUS}
                result = validation.get("families", {}).get(dataset_name, {})
                rows.append(
                    {
                        "trade_date": trade_date_str,
                        "scope": scope,
                        "dataset": dataset_name,
                        "source_trade_date": source_trade_date,
                        "status": str(summary.get("status", validation.get("status", ""))),
                        "row_count": str(result.get("row_count", 0) or 0),
                        "schema_ok": str(bool(result.get("schema_ok", False))).lower(),
                        "duplicate_keys": "0",
                        "missing_raw_paths_count": str(len(result.get("missing_raw_paths", []))),
                        "completeness_ok": "true",
                        "master_data_completeness": "true",
                        "result_chain_semantics_ok": "true",
                        "contracts_latest_consistency_ok": "",
                        "source_provenance_ok": str(not result.get("missing_raw_paths", [])).lower(),
                        "expected_markets": "",
                        "observed_markets": "",
                        "blocked_issue_count": "0",
                        "blocked_issues": "",
                        "no_data_reason": str(summary.get("message", "")) if summary.get("status") == NO_DATA_STATUS else "",
                        "not_applicable_reason": str(summary.get("message", "")) if summary.get("status") == NOT_APPLICABLE_STATUS else "",
                        "output_path": str(summary.get("output_path", "")),
                        "validated_at": validated_at,
                    }
                )

        crypto_summaries = self.crypto_runner.latest_summaries()
        for dataset_name, summary in crypto_summaries.items():
            source_trade_date = str(summary.get("trade_date", ""))
            validation = self.crypto_runner.validate(source_trade_date) if source_trade_date else {"datasets": {}, "status": FAILED_STATUS}
            result = validation.get("datasets", {}).get(dataset_name, {})
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "scope": "crypto_global",
                    "dataset": dataset_name,
                    "source_trade_date": source_trade_date,
                    "status": str(summary.get("status", validation.get("status", ""))),
                    "row_count": str(result.get("row_count", 0) or 0),
                    "schema_ok": str(bool(result.get("schema_ok", False))).lower(),
                    "duplicate_keys": "0",
                    "missing_raw_paths_count": str(len(result.get("missing_raw_paths", []))),
                    "completeness_ok": "true",
                    "master_data_completeness": "true",
                    "result_chain_semantics_ok": "true",
                    "contracts_latest_consistency_ok": "",
                    "source_provenance_ok": str(not result.get("missing_raw_paths", [])).lower(),
                    "expected_markets": "",
                    "observed_markets": "",
                    "blocked_issue_count": "0",
                    "blocked_issues": "",
                    "no_data_reason": str(summary.get("message", "")) if summary.get("status") == NO_DATA_STATUS else "",
                    "not_applicable_reason": str(summary.get("message", "")) if summary.get("status") == NOT_APPLICABLE_STATUS else "",
                    "output_path": str(summary.get("output_path", "")),
                    "validated_at": validated_at,
                }
            )

        for dataset_name, summary in (platform_summaries or {}).items():
            if dataset_name == VALIDATION_RESULTS_DATASET:
                continue
            output_path = normalize_text(summary.get("output_path"))
            csv_path = self.project_root / output_path if output_path else None
            row_count = int(summary.get("row_count", 0) or 0)
            missing_raw_paths = []
            schema_ok = False
            if csv_path and csv_path.exists():
                platform_rows = list(iter_csv_rows(csv_path))
                row_count = len(platform_rows)
                schema_ok = True
                for row in platform_rows:
                    raw_path = normalize_text(row.get("raw_path"))
                    if raw_path and not (self.project_root / raw_path).exists():
                        missing_raw_paths.append(raw_path)
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "scope": "platform_derived",
                    "dataset": dataset_name,
                    "source_trade_date": trade_date_str,
                    "status": str(summary.get("status", "")),
                    "row_count": str(row_count),
                    "schema_ok": str(schema_ok).lower(),
                    "duplicate_keys": "0",
                    "missing_raw_paths_count": str(len(missing_raw_paths)),
                    "completeness_ok": "true",
                    "master_data_completeness": "true",
                    "result_chain_semantics_ok": "true",
                    "contracts_latest_consistency_ok": "",
                    "source_provenance_ok": str(not missing_raw_paths).lower(),
                    "expected_markets": "",
                    "observed_markets": "",
                    "blocked_issue_count": "0",
                    "blocked_issues": "",
                    "no_data_reason": str(summary.get("message", "")) if summary.get("status") == NO_DATA_STATUS else "",
                    "not_applicable_reason": str(summary.get("message", "")) if summary.get("status") == NOT_APPLICABLE_STATUS else "",
                    "output_path": output_path,
                    "validated_at": validated_at,
                }
            )

        for dataset_name, summary in (platform_summaries or {}).items():
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "scope": "platform_metadata",
                    "dataset": dataset_name,
                    "source_trade_date": trade_date_str,
                    "status": str(summary.get("status", "")),
                    "row_count": str(summary.get("row_count", 0) or 0),
                    "schema_ok": "true",
                    "duplicate_keys": "0",
                    "missing_raw_paths_count": "0",
                    "completeness_ok": "true",
                    "master_data_completeness": "true" if dataset_name != CONTRACTS_DATASET else "",
                    "result_chain_semantics_ok": "true",
                    "contracts_latest_consistency_ok": "",
                    "source_provenance_ok": "true",
                    "expected_markets": "",
                    "observed_markets": "",
                    "blocked_issue_count": "0",
                    "blocked_issues": "",
                    "no_data_reason": "",
                    "not_applicable_reason": "",
                    "output_path": str(summary.get("output_path", "")),
                    "validated_at": validated_at,
                }
            )
        return rows

    def _build_source_health_rows(
        self,
        *,
        trade_date_str: str,
        platform_summaries: Optional[Dict[str, Dict[str, object]]] = None,
    ) -> List[Dict[str, str]]:
        rows = []
        excluded_platform_datasets = {
            SOURCE_HEALTH_DATASET,
            SOURCE_TYPE_OVERVIEW_DATASET,
            ISSUE_CATEGORY_OVERVIEW_DATASET,
        }
        latest_derivative_trade_date = self._resolve_latest_recorded_derivative_trade_date(trade_date_str)
        derivative_day = self.checkpoints.get_day(latest_derivative_trade_date) if latest_derivative_trade_date else {}
        derivative_audit = self.workflow_runner.audit_canonical_date(latest_derivative_trade_date) if latest_derivative_trade_date else {}
        latest_public_assets = self._latest_runtime_summaries(self.public_asset_runner)
        latest_public_references = self._latest_runtime_summaries(self.public_reference_runner)
        latest_public_bonds = self._latest_runtime_summaries(self.public_bond_runner)
        latest_crypto = self._latest_runtime_summaries(self.crypto_runner)
        latest_platform = platform_summaries or self.latest_summaries()

        for entry in build_source_catalog():
            dataset = str(entry.get("dataset", ""))
            if dataset in excluded_platform_datasets:
                continue
            exchange = str(entry.get("exchange", ""))
            summary = self._resolve_source_health_summary(
                entry=entry,
                derivative_day=derivative_day,
                derivative_audit=derivative_audit,
                public_assets=latest_public_assets,
                public_references=latest_public_references,
                public_bonds=latest_public_bonds,
                crypto=latest_crypto,
                platform=latest_platform,
            )
            issue_root_cause = self._issue_root_cause(
                status=str(summary.get("status", "")),
                issue_category=str(summary.get("issue_category", "")),
                blocked_reason=str(summary.get("blocked_reason", "")),
                message=str(summary.get("message", "")),
            )
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "source_id": str(entry.get("source_id", "")),
                    "asset_family": str(entry.get("asset_family", "")),
                    "market": str(entry.get("market", "")),
                    "exchange": exchange,
                    "dataset": dataset,
                    "source_type": str(entry.get("source_type", "")),
                    "priority": str(entry.get("priority", "")),
                    "source_url": str(summary.get("source_url") or entry.get("url", "")),
                    "last_status": str(summary.get("status", "")),
                    "last_trade_date": str(summary.get("trade_date", "")),
                    "last_success_trade_date": str(summary.get("trade_date", "")) if summary.get("status") == SUCCESS_STATUS else "",
                    "output_path": str(summary.get("output_path", "")),
                    "issue_category": str(summary.get("issue_category", "")),
                    "issue_root_cause": issue_root_cause,
                    "is_external_blocker": str(self._is_external_root_cause(issue_root_cause)).lower(),
                    "blocked_reason": str(summary.get("blocked_reason", "")),
                    "message": str(summary.get("message", "")),
                }
            )
        return rows

    def _build_source_type_overview_rows(
        self,
        *,
        trade_date_str: str,
        source_health_rows: List[Dict[str, str]],
        run_id: str,
    ) -> List[Dict[str, str]]:
        grouped: Dict[str, Dict[str, object]] = {}
        for row in source_health_rows:
            source_type = normalize_text(row.get("source_type")) or "unknown"
            bucket = grouped.setdefault(
                source_type,
                {
                    "source_ids": set(),
                    "datasets": set(),
                    "success_count": 0,
                    "non_success_count": 0,
                    "blocked_issue_count": 0,
                    "latest_trade_date": "",
                    "status_counts": {},
                },
            )
            source_id = normalize_text(row.get("source_id"))
            dataset = normalize_text(row.get("dataset"))
            last_status = normalize_text(row.get("last_status"))
            latest_trade_date = normalize_text(row.get("last_trade_date"))
            issue_category = normalize_text(row.get("issue_category"))
            blocked_reason = normalize_text(row.get("blocked_reason"))
            if source_id:
                bucket["source_ids"].add(source_id)
            if dataset:
                bucket["datasets"].add(dataset)
            if last_status == SUCCESS_STATUS:
                bucket["success_count"] += 1
            elif last_status:
                bucket["non_success_count"] += 1
            if issue_category == "blocked_issue" or blocked_reason:
                bucket["blocked_issue_count"] += 1
            if latest_trade_date and latest_trade_date > str(bucket["latest_trade_date"]):
                bucket["latest_trade_date"] = latest_trade_date
            if last_status:
                status_counts = bucket["status_counts"]
                status_counts[last_status] = int(status_counts.get(last_status, 0)) + 1

        rows: List[Dict[str, str]] = []
        for source_type in sorted(grouped.keys()):
            bucket = grouped[source_type]
            source_ids = sorted(bucket["source_ids"])
            dataset_names = sorted(bucket["datasets"])
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "source_type": source_type,
                    "source_count": str(len(source_ids)),
                    "dataset_count": str(len(dataset_names)),
                    "success_count": str(bucket["success_count"]),
                    "non_success_count": str(bucket["non_success_count"]),
                    "blocked_issue_count": str(bucket["blocked_issue_count"]),
                    "latest_trade_date": str(bucket["latest_trade_date"]),
                    "status_counts": safe_json_dumps(bucket["status_counts"]),
                    "source_ids": safe_json_dumps(source_ids),
                    "source_id": "platform.source_type_overview",
                    "source_url": "state/platform_metadata.json",
                    "source_type_origin": "derived",
                    "retrieved_at": iso_timestamp(),
                    "raw_path": "state/platform_metadata.json",
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(
                        instrument_id=f"source_type_overview:{source_type}:{trade_date_str}",
                        source_id="platform.source_type_overview",
                    ),
                    "run_id": run_id,
                }
            )
        return rows

    def _build_issue_category_overview_rows(
        self,
        *,
        trade_date_str: str,
        source_health_rows: List[Dict[str, str]],
        run_id: str,
    ) -> List[Dict[str, str]]:
        grouped: Dict[str, Dict[str, object]] = {}
        for row in source_health_rows:
            issue_category = normalize_text(row.get("issue_category"))
            blocked_reason = normalize_text(row.get("blocked_reason"))
            last_status = normalize_text(row.get("last_status"))
            source_type = normalize_text(row.get("source_type")) or "unknown"
            latest_trade_date = normalize_text(row.get("last_trade_date"))
            if not issue_category:
                if blocked_reason:
                    issue_category = "blocked_issue"
                elif last_status and last_status != SUCCESS_STATUS:
                    issue_category = "uncategorized_non_success"
                else:
                    issue_category = "healthy"
            bucket = grouped.setdefault(
                issue_category,
                {
                    "source_ids": set(),
                    "datasets": set(),
                    "blocked_issue_count": 0,
                    "latest_trade_date": "",
                    "status_counts": {},
                    "source_type_counts": {},
                },
            )
            source_id = normalize_text(row.get("source_id"))
            dataset = normalize_text(row.get("dataset"))
            if source_id:
                bucket["source_ids"].add(source_id)
            if dataset:
                bucket["datasets"].add(dataset)
            if issue_category == "blocked_issue" or blocked_reason:
                bucket["blocked_issue_count"] += 1
            if latest_trade_date and latest_trade_date > str(bucket["latest_trade_date"]):
                bucket["latest_trade_date"] = latest_trade_date
            if last_status:
                status_counts = bucket["status_counts"]
                status_counts[last_status] = int(status_counts.get(last_status, 0)) + 1
            source_type_counts = bucket["source_type_counts"]
            source_type_counts[source_type] = int(source_type_counts.get(source_type, 0)) + 1

        rows: List[Dict[str, str]] = []
        for issue_category in sorted(grouped.keys()):
            bucket = grouped[issue_category]
            source_ids = sorted(bucket["source_ids"])
            dataset_names = sorted(bucket["datasets"])
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "issue_category": issue_category,
                    "source_count": str(len(source_ids)),
                    "dataset_count": str(len(dataset_names)),
                    "blocked_issue_count": str(bucket["blocked_issue_count"]),
                    "latest_trade_date": str(bucket["latest_trade_date"]),
                    "status_counts": safe_json_dumps(bucket["status_counts"]),
                    "source_type_counts": safe_json_dumps(bucket["source_type_counts"]),
                    "source_ids": safe_json_dumps(source_ids),
                    "datasets": safe_json_dumps(dataset_names),
                    "source_id": "platform.issue_category_overview",
                    "source_url": "state/platform_metadata.json",
                    "source_type": "derived",
                    "retrieved_at": iso_timestamp(),
                    "raw_path": "state/platform_metadata.json",
                    "parser_version": PARSER_VERSION,
                    "checksum": self._row_checksum(
                        instrument_id=f"issue_category_overview:{issue_category}:{trade_date_str}",
                        source_id="platform.issue_category_overview",
                    ),
                    "run_id": run_id,
                }
            )
        return rows

    def _resolve_source_health_summary(
        self,
        *,
        entry: Dict[str, object],
        derivative_day: Dict[str, object],
        derivative_audit: Dict[str, object],
        public_assets: Dict[str, Dict[str, object]],
        public_references: Dict[str, Dict[str, object]],
        public_bonds: Dict[str, Dict[str, object]],
        crypto: Dict[str, Dict[str, object]],
        platform: Dict[str, Dict[str, object]],
    ) -> Dict[str, object]:
        dataset = str(entry.get("dataset", ""))
        exchange = str(entry.get("exchange", ""))
        if dataset in {FUTURES_DATASET, OPTIONS_DATASET, FUTURES_RESULTS_DATASET, OPTION_RESULTS_DATASET}:
            dataset_bucket = derivative_day.get("datasets", {}).get(dataset, {})
            exchange_bucket = dataset_bucket.get("exchanges", {}).get(exchange, {})
            blocked_reason = self._match_blocked_reason(derivative_audit.get("blocked_issues", []), dataset, exchange)
            if exchange_bucket:
                return {
                    "trade_date": exchange_bucket.get("trade_date", ""),
                    "status": exchange_bucket.get("status", dataset_bucket.get("status", "")),
                    "source_url": exchange_bucket.get("source_url", ""),
                    "output_path": derivative_day.get("outputs", {}).get(dataset, ""),
                    "issue_category": self._issue_category_for_status(
                        str(exchange_bucket.get("status", dataset_bucket.get("status", ""))),
                        blocked_reason,
                        str(exchange_bucket.get("message", "")),
                    ),
                    "blocked_reason": blocked_reason,
                    "message": exchange_bucket.get("message", ""),
                }
            return {
                "trade_date": "",
                "status": dataset_bucket.get("status", ""),
                "source_url": str(entry.get("url", "")),
                "output_path": derivative_day.get("outputs", {}).get(dataset, ""),
                "issue_category": self._issue_category_for_status(str(dataset_bucket.get("status", "")), blocked_reason, blocked_reason),
                "blocked_reason": blocked_reason,
                "message": blocked_reason,
            }
        if dataset in public_assets:
            summary = dict(public_assets[dataset])
            summary.setdefault("issue_category", self._issue_category_for_status(str(summary.get("status", "")), "", str(summary.get("message", ""))))
            summary.setdefault("blocked_reason", "")
            return summary
        if dataset in public_references:
            summary = dict(public_references[dataset])
            summary.setdefault("issue_category", self._issue_category_for_status(str(summary.get("status", "")), "", str(summary.get("message", ""))))
            summary.setdefault("blocked_reason", "")
            return summary
        if dataset in public_bonds:
            summary = dict(public_bonds[dataset])
            summary.setdefault("issue_category", self._issue_category_for_status(str(summary.get("status", "")), "", str(summary.get("message", ""))))
            summary.setdefault("blocked_reason", "")
            return summary
        if dataset in crypto:
            summary = dict(crypto[dataset])
            summary.setdefault("issue_category", self._issue_category_for_status(str(summary.get("status", "")), "", str(summary.get("message", ""))))
            summary.setdefault("blocked_reason", "")
            return summary
        if dataset in platform:
            summary = dict(platform[dataset])
            summary.setdefault(
                "issue_category",
                self._issue_category_for_status(str(summary.get("status", "")), "", str(summary.get("message", ""))),
            )
            summary.setdefault("blocked_reason", "")
            return summary
        return {
            "trade_date": "",
            "status": "",
            "source_url": str(entry.get("url", "")),
            "output_path": "",
            "issue_category": "",
            "blocked_reason": "",
            "message": "",
        }

    @staticmethod
    def _index_blocked_issues(blocked_issues: Iterable[str]) -> Dict[str, List[str]]:
        issues_by_dataset: Dict[str, List[str]] = {}
        for issue in blocked_issues:
            text = normalize_text(issue)
            if not text:
                continue
            dataset, _, message = text.partition(":")
            dataset_name = normalize_text(dataset)
            if not dataset_name:
                continue
            issues_by_dataset.setdefault(dataset_name, []).append(text)
        return issues_by_dataset

    @staticmethod
    def _match_blocked_reason(blocked_issues: Iterable[str], dataset: str, exchange: str) -> str:
        normalized_dataset = normalize_text(dataset)
        normalized_exchange = normalize_text(exchange)
        for issue in blocked_issues:
            text = normalize_text(issue)
            if not text.startswith(f"{normalized_dataset}:"):
                continue
            if normalized_exchange and normalized_exchange not in text:
                continue
            return text
        return ""

    @staticmethod
    def _issue_category_for_status(status: str, blocked_reason: str, message: str = "") -> str:
        normalized_status = normalize_text(status)
        normalized_message = normalize_text(message)
        if blocked_reason or normalized_message.startswith("No official"):
            return "blocked_issue"
        if normalized_status in {FAILED_STATUS, PENDING_RETRY_STATUS}:
            return "retry_or_error"
        if normalized_status == NO_DATA_STATUS:
            return "no_data"
        if normalized_status == NOT_APPLICABLE_STATUS:
            return "not_applicable"
        if normalized_status == SUCCESS_STATUS:
            return "healthy"
        if normalized_status == PARTIAL_SUCCESS_STATUS:
            return "partial"
        return ""

    @staticmethod
    def _issue_root_cause(status: str, issue_category: str, blocked_reason: str, message: str) -> str:
        normalized_status = normalize_text(status)
        normalized_issue_category = normalize_text(issue_category)
        text = " ".join(part for part in (normalize_text(blocked_reason), normalize_text(message)) if part).lower()
        if not text and normalized_status == SUCCESS_STATUS:
            return "healthy"
        if "pending official publication" in text or "publication lag" in text or "not yet published" in text:
            return "publication_lag"
        if "historical_public_contract_gap" in text or ("historical" in text and "contract" in text and "gap" in text):
            return "historical_public_contract_gap"
        if "result_chain_source_gap" in text or "source unavailability" in text or "endpoint configured" in text:
            return "official_source_gap"
        if "coverage_gap" in text or "coverage gap" in text:
            return "coverage_gap"
        if "schema_mismatch" in text or "schema mismatch" in text:
            return "schema_mismatch"
        if "missing csv" in text or "missing_csv" in text:
            return "missing_csv"
        if "proxy" in text:
            return "proxy_failure"
        if (
            "nodename nor servname provided" in text
            or "name or service not known" in text
            or "temporary failure in name resolution" in text
            or "failed to resolve" in text
        ):
            return "dns_failure"
        if "429" in text or "too many requests" in text or "rate limit" in text:
            return "rate_limit"
        if (
            "timeout" in text
            or "timed out" in text
            or "upstream down" in text
            or "remote end closed connection" in text
            or "connection reset" in text
            or "max retries exceeded" in text
        ):
            return "upstream_unavailable"
        if normalized_status == NO_DATA_STATUS:
            return "no_data"
        if normalized_status == NOT_APPLICABLE_STATUS:
            return "not_applicable"
        if normalized_issue_category == "blocked_issue":
            return "blocked_issue"
        if normalized_status in {FAILED_STATUS, PENDING_RETRY_STATUS}:
            return "retry_or_error"
        if normalized_status == PARTIAL_SUCCESS_STATUS:
            return "partial"
        if normalized_status == SUCCESS_STATUS:
            return "healthy"
        return ""

    @staticmethod
    def _is_external_root_cause(root_cause: str) -> bool:
        return normalize_text(root_cause) in {
            "publication_lag",
            "proxy_failure",
            "dns_failure",
            "rate_limit",
            "upstream_unavailable",
        }

    def _collect_latest_summary_by_dataset(
        self,
        *,
        trade_date_str: str,
        platform_summaries: Optional[Dict[str, Dict[str, object]]] = None,
    ) -> Dict[str, Dict[str, object]]:
        combined: Dict[str, Dict[str, object]] = {}
        for summary_map in (
            self._latest_derivative_summaries(trade_date_str),
            self._latest_runtime_summaries(self.public_asset_runner),
            self._latest_runtime_summaries(self.public_reference_runner),
            self._latest_runtime_summaries(self.public_bond_runner),
            self._latest_runtime_summaries(self.crypto_runner),
            platform_summaries or self.latest_summaries(),
        ):
            for dataset_name, summary in summary_map.items():
                combined[str(dataset_name)] = dict(summary)
        return combined

    @staticmethod
    def _latest_runtime_summaries(runner) -> Dict[str, Dict[str, object]]:
        method = getattr(runner, "latest_recorded_summaries", None)
        if callable(method):
            return method()
        return runner.latest_summaries()

    def _latest_derivative_summaries(self, trade_date_str: str) -> Dict[str, Dict[str, object]]:
        latest_trade_date = self._resolve_latest_recorded_derivative_trade_date(trade_date_str)
        if not latest_trade_date:
            return {}
        day = self.checkpoints.get_day(latest_trade_date)
        datasets = day.get("datasets", {})
        outputs = day.get("outputs", {})
        results: Dict[str, Dict[str, object]] = {}
        for dataset_name in (
            FUTURES_DATASET,
            OPTIONS_DATASET,
            CONTRACTS_DATASET,
            OPTION_RESULTS_DATASET,
            FUTURES_RESULTS_DATASET,
            OPTIONS_CHAIN_VIEW,
            UNDERLYING_SUMMARY_VIEW,
            "derivatives_daily_quotes",
        ):
            bucket = dict(datasets.get(dataset_name, {}) or {})
            output_path = normalize_text(outputs.get(dataset_name))
            row_count = int(bucket.get("row_count", 0) or 0)
            if output_path:
                csv_path = self.project_root / output_path
                if csv_path.exists():
                    row_count = sum(1 for _ in iter_csv_rows(csv_path))
            if bucket or output_path:
                results[dataset_name] = {
                    "dataset": dataset_name,
                    "status": normalize_text(bucket.get("status")) or normalize_text(day.get("status")),
                    "row_count": row_count,
                    "trade_date": latest_trade_date,
                    "output_path": output_path,
                }
        return results

    def _write_dataset(
        self,
        *,
        dataset_name: str,
        trade_date_str: str,
        rows: List[Dict[str, str]],
        fieldnames: List[str],
        key_fields: List[str],
    ) -> Dict[str, object]:
        output_path = self._output_path(dataset_name, trade_date_str)
        write_dict_rows_csv(output_path, rows, fieldnames, key_fields)
        status = SUCCESS_STATUS if rows or dataset_name in SCHEMA_ONLY_SUCCESS_DATASETS else NO_DATA_STATUS
        summary = {
            "dataset": dataset_name,
            "trade_date": trade_date_str,
            "status": status,
            "row_count": len(rows),
            "output_path": relative_to_project(output_path, self.project_root),
        }
        if not rows:
            summary["message"] = "dataset currently has no materialized rows"
        return summary

    def _load_derivative_contract_rows(self, trade_date_str: str) -> List[Dict[str, str]]:
        derivative_trade_date = self._resolve_derivative_trade_date(trade_date_str)
        if not derivative_trade_date:
            return []
        day = self.checkpoints.get_day(derivative_trade_date)
        relative_path = str(day.get("outputs", {}).get(CONTRACTS_DATASET, ""))
        if not relative_path:
            return []
        csv_path = self.project_root / relative_path
        if not csv_path.exists():
            return []
        return list(iter_csv_rows(csv_path))

    def _resolve_derivative_trade_date(self, trade_date_str: str) -> str:
        day = self.checkpoints.get_day(trade_date_str)
        if day.get("status") == SUCCESS_STATUS and day.get("outputs", {}).get(CONTRACTS_DATASET):
            return trade_date_str
        return self.checkpoints.get_last_fully_successful_trade_date() or ""

    def _resolve_latest_recorded_derivative_trade_date(self, trade_date_str: str) -> str:
        day = self.checkpoints.get_day(trade_date_str)
        if day.get("outputs"):
            return trade_date_str
        dates = sorted(self.checkpoints.data.get("dates", {}).keys(), reverse=True)
        for candidate in dates:
            candidate_day = self.checkpoints.get_day(candidate)
            if candidate_day.get("outputs"):
                return candidate
        return self._resolve_derivative_trade_date(trade_date_str)

    def _load_rows_from_latest_summaries(self, summaries: Dict[str, Dict[str, object]]) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for summary in summaries.values():
            output_path = normalize_text(summary.get("output_path"))
            if not output_path:
                continue
            csv_path = self.project_root / output_path
            if not csv_path.exists():
                continue
            rows.extend(iter_csv_rows(csv_path))
        return rows

    def _load_existing_platform_dataset_rows(self, dataset_name: str, trade_date_str: str) -> List[Dict[str, str]]:
        csv_path = self._output_path(dataset_name, trade_date_str)
        if not csv_path.exists():
            return []
        return [dict(row) for row in iter_csv_rows(csv_path)]

    @staticmethod
    def _read_optional_state(reader, path: Path) -> Dict[str, object]:
        try:
            return reader(state_path=path) or {}
        except TypeError:
            return reader() or {}

    def _platform_dataset_paths(self, dataset_name: str) -> List[Path]:
        dataset_dir = PLATFORM_NORMALIZED_DIR / dataset_name
        if not dataset_dir.exists():
            return []
        return sorted(dataset_dir.glob("*.csv"))

    def _get_derivative_output_path(self, trade_date_str: str, dataset_name: str) -> str:
        day = self.checkpoints.get_day(trade_date_str)
        return str(day.get("outputs", {}).get(dataset_name, ""))

    def _instrument_row(
        self,
        *,
        trade_date_str: str,
        instrument_id: str,
        asset_family: str,
        market: str,
        exchange: str,
        instrument_type: str,
        symbol: str,
        name: str,
        currency: str,
        listing_date: str,
        delisting_date: str,
        status: str,
        underlying_id: str,
        contract_multiplier: str,
        price_tick: str,
        quote_unit: str,
        trading_unit: str,
        delivery_type: str,
        exercise_type: str,
        option_type: str,
        strike_price: str,
        expire_date: str,
        last_trade_date: str,
        source_id: str,
        source_url: str,
        source_type: str,
        retrieved_at: str,
        raw_path: str,
        run_id: str,
    ) -> Dict[str, str]:
        checksum_payload = safe_json_dumps(
            {
                "instrument_id": instrument_id,
                "asset_family": asset_family,
                "symbol": symbol,
                "source_id": source_id,
            }
        ).encode("utf-8")
        return {
            "trade_date": trade_date_str,
            "instrument_id": instrument_id,
            "asset_family": normalize_text(asset_family),
            "market": normalize_text(market),
            "exchange": normalize_text(exchange),
            "instrument_type": normalize_text(instrument_type),
            "symbol": normalize_text(symbol),
            "name": normalize_text(name),
            "currency": normalize_text(currency),
            "listing_date": normalize_text(listing_date),
            "delisting_date": normalize_text(delisting_date),
            "status": normalize_text(status) or "active",
            "underlying_id": normalize_text(underlying_id),
            "contract_multiplier": normalize_text(contract_multiplier),
            "price_tick": normalize_text(price_tick),
            "quote_unit": normalize_text(quote_unit),
            "trading_unit": normalize_text(trading_unit),
            "delivery_type": normalize_text(delivery_type),
            "exercise_type": normalize_text(exercise_type),
            "option_type": normalize_text(option_type),
            "strike_price": normalize_text(strike_price),
            "expire_date": normalize_text(expire_date),
            "last_trade_date": normalize_text(last_trade_date),
            "source_id": normalize_text(source_id),
            "source_url": normalize_text(source_url),
            "source_type": normalize_text(source_type),
            "retrieved_at": normalize_text(retrieved_at) or iso_timestamp(),
            "raw_path": normalize_text(raw_path),
            "parser_version": PARSER_VERSION,
            "checksum": hashlib.sha1(checksum_payload).hexdigest(),
            "run_id": run_id,
        }

    @staticmethod
    def _infer_bond_type(row: Dict[str, str]) -> str:
        dataset_type = normalize_text(row.get("dataset_type"))
        name = normalize_text(row.get("name"))
        if "国债" in name:
            return "government_bond"
        if "可转债" in name:
            return "convertible_bond"
        if "收益率曲线" in dataset_type or normalize_text(row.get("curve_name")):
            return "yield_curve"
        if dataset_type:
            return dataset_type
        return "bond"

    @staticmethod
    def _tenor_years(tenor: str) -> str:
        value = normalize_text(tenor).upper()
        if not value:
            return ""
        if value.endswith("M"):
            number = normalize_text(value[:-1])
            try:
                return str(round(float(number) / 12.0, 6))
            except ValueError:
                return ""
        if value.endswith("Y"):
            number = normalize_text(value[:-1])
            try:
                return str(float(number)).rstrip("0").rstrip(".")
            except ValueError:
                return ""
        return ""

    @staticmethod
    def _row_checksum(*, instrument_id: str, source_id: str) -> str:
        checksum_payload = safe_json_dumps(
            {
                "instrument_id": normalize_text(instrument_id),
                "source_id": normalize_text(source_id),
            }
        ).encode("utf-8")
        return hashlib.sha1(checksum_payload).hexdigest()

    def _daily_ohlcv_row(
        self,
        *,
        trade_date: str,
        instrument_id: str,
        asset_family: str,
        market: str,
        exchange: str,
        instrument_type: str,
        symbol: str,
        name: str,
        currency: str,
        open_value: object,
        high_value: object,
        low_value: object,
        close_value: object,
        pre_close: object,
        settlement: object,
        pre_settlement: object,
        volume: object,
        amount: object,
        open_interest: object,
        turnover_rate: object,
        source_id: object,
        source_url: object,
        source_type: object,
        retrieved_at: object,
        raw_path: object,
        run_id: str,
    ) -> Dict[str, str]:
        return {
            "trade_date": normalize_text(trade_date),
            "instrument_id": normalize_text(instrument_id),
            "asset_family": normalize_text(asset_family),
            "market": normalize_text(market),
            "exchange": normalize_text(exchange),
            "instrument_type": normalize_text(instrument_type),
            "symbol": normalize_text(symbol),
            "name": normalize_text(name),
            "currency": normalize_text(currency),
            "open": normalize_text(open_value),
            "high": normalize_text(high_value),
            "low": normalize_text(low_value),
            "close": normalize_text(close_value),
            "pre_close": normalize_text(pre_close),
            "settlement": normalize_text(settlement),
            "pre_settlement": normalize_text(pre_settlement),
            "volume": normalize_text(volume),
            "amount": normalize_text(amount),
            "open_interest": normalize_text(open_interest),
            "turnover_rate": normalize_text(turnover_rate),
            "source_id": normalize_text(source_id),
            "source_url": normalize_text(source_url),
            "source_type": normalize_text(source_type),
            "retrieved_at": normalize_text(retrieved_at) or iso_timestamp(),
            "raw_path": normalize_text(raw_path),
            "parser_version": PARSER_VERSION,
            "checksum": self._row_checksum(instrument_id=instrument_id, source_id=normalize_text(source_id)),
            "run_id": run_id,
        }

    def _trading_calendar_row(
        self,
        *,
        trade_date: str,
        calendar_id: str,
        asset_family: str,
        market: str,
        exchange: str,
        day_status: str,
        source_trade_date: str,
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
        run_id: str,
    ) -> Dict[str, str]:
        normalized_status = normalize_text(day_status)
        return {
            "trade_date": normalize_text(trade_date),
            "calendar_id": normalize_text(calendar_id),
            "asset_family": normalize_text(asset_family),
            "market": normalize_text(market),
            "exchange": normalize_text(exchange),
            "is_trading_day": str(normalized_status not in {NO_DATA_STATUS, NOT_APPLICABLE_STATUS, FAILED_STATUS}).lower(),
            "day_status": normalized_status or SUCCESS_STATUS,
            "source_trade_date": normalize_text(source_trade_date),
            "source_id": normalize_text(source_id),
            "source_url": normalize_text(source_url),
            "source_type": normalize_text(source_type),
            "retrieved_at": iso_timestamp(),
            "raw_path": normalize_text(raw_path),
            "parser_version": PARSER_VERSION,
            "checksum": self._row_checksum(instrument_id=f"{calendar_id}:{trade_date}", source_id=source_id),
            "run_id": run_id,
        }

    def _underlying_id_from_contract_row(self, row: Dict[str, str]) -> str:
        underlying_contract = normalize_text(row.get("underlying_contract"))
        underlying_exchange = normalize_text(row.get("underlying_exchange"))
        underlying_product_code = normalize_text(row.get("underlying_product_code"))
        if underlying_contract:
            return f"{underlying_exchange}:{underlying_contract}"
        if underlying_product_code:
            return f"{underlying_exchange}:{underlying_product_code}"
        return ""

    def _output_path(self, dataset_name: str, trade_date_str: str) -> Path:
        return PLATFORM_NORMALIZED_DIR / dataset_name / f"{trade_date_str}.csv"

    def _update_state(self, trade_date_str: str, status: str, datasets: Dict[str, Dict[str, object]]) -> None:
        payload = self._load_state()
        payload.setdefault("dates", {})[trade_date_str] = {
            "status": status,
            "datasets": datasets,
            "updated_at": iso_timestamp(),
        }
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_state(self) -> Dict[str, object]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    @staticmethod
    def _resolve_trade_date(trade_date_value: str):
        if trade_date_value == "latest":
            return now_shanghai().date()
        return parse_trade_date(trade_date_value)

    @staticmethod
    def _merge_statuses(statuses: Iterable[str]) -> str:
        status_set = {normalize_text(status) for status in statuses if normalize_text(status)}
        if not status_set:
            return NO_DATA_STATUS
        if status_set == {SUCCESS_STATUS}:
            return SUCCESS_STATUS
        if FAILED_STATUS in status_set:
            return FAILED_STATUS
        if PENDING_RETRY_STATUS in status_set:
            return PENDING_RETRY_STATUS
        if NOT_APPLICABLE_STATUS in status_set and len(status_set) == 1:
            return NOT_APPLICABLE_STATUS
        if NO_DATA_STATUS in status_set and len(status_set) == 1:
            return NO_DATA_STATUS
        if SUCCESS_STATUS in status_set:
            return PARTIAL_SUCCESS_STATUS
        return PARTIAL_SUCCESS_STATUS
