import argparse
import html
import json
import os
import subprocess
import sys
import tempfile
import threading
from datetime import timedelta
from itertools import count
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlencode
from wsgiref.simple_server import make_server

from .agent_platform import AgentOrchestrator
from .crypto_observation import CryptoObservationRunner
from .environment_health import run_environment_health_check
from .platform_metadata import PlatformMetadataRunner
from .config import DUCKDB_PATH, PREGRAB_STATE_PATH, PROJECT_ROOT, QUERY_STATE_DIR, REPORTS_DIR, SCHEDULER_RUNS_STATE_PATH, SCHEDULES_STATE_PATH, WINDOW_RUNS_STATE_PATH
from .public_assets import PublicAssetSnapshotRunner
from .public_bonds import PublicBondRunner
from .public_references import PublicReferenceRunner
from .pregrab_state import append_pregrab_run, read_pregrab_state
from .research_platform import AlgorithmRegistry, ResearchPlatformRunner, SchedulerRunner
from .regression_state import read_regression_smoke_state
from .registry import build_asset_family_registry, build_dataset_catalog, family_status_counts
from .selection import CrawlSelection
from .source_catalog import build_source_catalog
from .state.checkpoints import CheckpointStore
from .storage import build_duckdb_database, export_dataset, read_dataset_manifest
from .utils import iter_csv_rows, iso_timestamp, now_shanghai, parse_trade_date
from .window_state import read_window_state
from .workflow import WorkflowRunner


DATASET_LABELS = {
    "futures_daily_quotes": "期货日行情",
    "options_daily_quotes": "期权日行情",
    "derivatives_daily_quotes": "统一衍生品总表",
    "contracts_snapshot": "合约主数据快照",
    "options_exercise_results": "期权行权结果",
    "futures_delivery_results": "期货交割结果",
    "options_chain_matrix": "期权链矩阵视图",
    "underlying_derivatives_summary": "标的衍生品汇总视图",
}

GUI_FILTER_FIELDS = (
    ("asset_family", "资产族"),
    ("market", "市场"),
    ("exchange", "交易所"),
    ("instrument_type", "品种类型"),
    ("symbol", "代码"),
    ("contract", "合约"),
    ("currency", "币种"),
    ("tenor", "期限"),
)

GUI_SELECT_FILTER_FIELDS = {
    "asset_family",
    "market",
    "exchange",
    "instrument_type",
    "currency",
    "tenor",
}

GUI_SUGGEST_FILTER_FIELDS = {
    "symbol",
    "contract",
}

GUI_FILTER_SCAN_ROW_LIMIT = 5000
GUI_FILTER_OPTION_LIMIT = 200

GUI_ACTION_DEFINITIONS = (
    ("fetch_date", "单日抓取（衍生品）"),
    ("backfill", "区间回补（衍生品）"),
    ("window_sync", "历史窗口同步"),
    ("sync_public_assets", "同步公开资产"),
    ("sync_public_references", "同步公开参考"),
    ("sync_public_bonds", "同步公开债券"),
    ("sync_crypto_observation", "同步 crypto 观察"),
    ("sync_platform_metadata", "同步平台元数据"),
    ("build_db", "重建 DuckDB"),
    ("environment_check", "环境健康检查"),
    ("full_latest", "一键 latest 全平台同步"),
    ("pregrab_window", "逐交易所预抓"),
    ("research_run", "研究指标计算"),
    ("factor_run", "因子信号生成"),
    ("algorithm_run", "算法模板运行"),
    ("risk_run", "组合风险计算"),
    ("portfolio_optimize", "组合配置优化"),
    ("backtest_run", "正式回测引擎"),
    ("ml_run", "机器学习研究"),
    ("feature_run", "Feature Store 生成"),
    ("ml_benchmark", "ML Benchmark"),
    ("ml_validate", "时间序列验证"),
    ("factor_experiment", "因子实验"),
    ("parameter_scan", "参数扫描"),
    ("strategy_leaderboard", "策略排行榜"),
    ("factor_performance", "因子表现评估"),
    ("stress_test", "压力测试"),
    ("portfolio_run", "组合研究"),
    ("scenario_sim", "情景推演"),
    ("project_create", "创建研究项目"),
    ("project_run", "运行研究项目"),
    ("package_export", "导出可复现包"),
    ("inventory_build", "构建数据资产地图"),
    ("lineage_build", "构建数据血缘"),
    ("sla_check", "SLA 检查"),
    ("knowledge_build", "构建知识库"),
    ("agent_plan", "生成 Agent 研究计划"),
    ("agent_run", "确认并运行 Agent 任务"),
    ("quality_gate", "Agent 质量守门"),
    ("plugin_list", "刷新插件注册表"),
    ("quality_score", "数据质量评分"),
    ("strategy_backtest", "策略回测"),
    ("paper_sim", "模拟交易"),
    ("quality_diagnose", "质量诊断"),
    ("scheduler_tick", "本地调度 tick"),
    ("scheduler_toggle", "启停调度任务"),
    ("scheduler_run_one", "手动运行调度任务"),
    ("report_generate", "生成研究运营报告"),
)

RESEARCH_DATASET_OPTIONS = (
    ("daily_ohlcv", "股票/ETF/基金/REITs 日频价格"),
    ("fund_nav", "基金净值"),
    ("reits_quotes", "REITs 行情"),
    ("yield_curves", "收益率曲线"),
    ("fx_quotes", "外汇报价"),
    ("bond_quotes", "债券行情"),
    ("commodity_spot_quotes", "商品现货"),
    ("crypto_global_quotes", "Crypto 全球观察"),
)

FACTOR_TEMPLATE_OPTIONS = (
    ("momentum", "动量因子"),
    ("mean_reversion", "均值回归因子"),
    ("volatility_filter", "波动率过滤因子"),
    ("volume_turnover", "成交量/换手因子"),
    ("term_structure_slope", "期限结构斜率"),
    ("basis_spread", "基差/价差因子"),
    ("cross_asset_rank", "多资产横截面排序"),
)

STRATEGY_TEMPLATE_OPTIONS = (
    ("momentum", "动量日频模拟"),
    ("mean_reversion", "均值回归日频模拟"),
    ("volatility_filter", "波动率过滤日频模拟"),
)

ALGORITHM_TEMPLATE_OPTIONS = tuple(AlgorithmRegistry.options(categories={"factor", "option_math", "bond_math", "curve_math", "futures_math"}))
RISK_TEMPLATE_OPTIONS = tuple(AlgorithmRegistry.options(categories={"risk"}))
PORTFOLIO_TEMPLATE_OPTIONS = tuple(AlgorithmRegistry.options(categories={"portfolio"}))
BACKTEST_TEMPLATE_OPTIONS = (
    ("momentum", "动量策略"),
    ("mean_reversion", "均值回归策略"),
    ("risk_parity", "风险平价再平衡"),
)
ML_TEMPLATE_OPTIONS = tuple(AlgorithmRegistry.options(categories={"ml"}))
STRESS_TEMPLATE_OPTIONS = tuple(AlgorithmRegistry.options(categories={"stress"}))
REPORT_TYPE_OPTIONS = (
    ("comprehensive", "综合报告"),
    ("daily", "每日市场概览"),
    ("factor", "因子表现报告"),
    ("backtest", "策略回测报告"),
    ("risk", "风险暴露报告"),
    ("quality", "数据质量报告"),
    ("ml", "ML 结果摘要"),
)

ALLOWED_REPORT_FILES = {
    "daily_report.html",
    "daily_report.md",
    "quality_diagnostics.md",
}


class DashboardApp:
    def __init__(
        self,
        *,
        runner: Optional[WorkflowRunner] = None,
        checkpoint_store: Optional[CheckpointStore] = None,
        public_asset_runner: Optional[PublicAssetSnapshotRunner] = None,
        public_bond_runner: Optional[PublicBondRunner] = None,
        public_reference_runner: Optional[PublicReferenceRunner] = None,
        crypto_runner: Optional[CryptoObservationRunner] = None,
        platform_metadata_runner: Optional[PlatformMetadataRunner] = None,
        manifest_reader=read_dataset_manifest,
        regression_state_reader=read_regression_smoke_state,
        pregrab_state_reader=read_pregrab_state,
        window_state_reader=read_window_state,
        pregrab_state_writer=append_pregrab_run,
        subprocess_runner=subprocess.run,
        research_runner: Optional[ResearchPlatformRunner] = None,
        scheduler_runner: Optional[SchedulerRunner] = None,
        agent_runner: Optional[AgentOrchestrator] = None,
        duckdb_path: Path = DUCKDB_PATH,
        project_root: Path = PROJECT_ROOT,
        query_state_dir: Path = QUERY_STATE_DIR,
        window_state_path: Path = WINDOW_RUNS_STATE_PATH,
        reports_dir: Path = REPORTS_DIR,
        environment_check_runner=run_environment_health_check,
        run_jobs_async: bool = True,
    ):
        self.runner = runner or WorkflowRunner()
        self.checkpoints = checkpoint_store or self.runner.checkpoints
        self.public_asset_runner = public_asset_runner or PublicAssetSnapshotRunner()
        self.public_bond_runner = public_bond_runner or PublicBondRunner()
        self.public_reference_runner = public_reference_runner or PublicReferenceRunner()
        self.crypto_runner = crypto_runner or CryptoObservationRunner()
        self.platform_metadata_runner = platform_metadata_runner or PlatformMetadataRunner(
            workflow_runner=self.runner,
            checkpoint_store=self.checkpoints,
            public_asset_runner=self.public_asset_runner,
            public_reference_runner=self.public_reference_runner,
            public_bond_runner=self.public_bond_runner,
            crypto_runner=self.crypto_runner,
        )
        self.manifest_reader = manifest_reader
        self.regression_state_reader = regression_state_reader
        self.pregrab_state_reader = pregrab_state_reader
        self.window_state_reader = window_state_reader
        self.pregrab_state_writer = pregrab_state_writer
        self.subprocess_runner = subprocess_runner
        self.research_runner = research_runner or ResearchPlatformRunner(
            project_root=project_root,
            normalized_root=project_root / "data" / "normalized",
            platform_dir=project_root / "data" / "normalized" / "platform",
            reports_dir=reports_dir,
            duckdb_path=duckdb_path,
        )
        self.scheduler_runner = scheduler_runner or SchedulerRunner(
            project_root=project_root,
            schedules_path=project_root / "state" / "schedules.json",
            runs_path=project_root / "state" / "scheduler_runs.json",
            platform_dir=project_root / "data" / "normalized" / "platform",
            subprocess_runner=subprocess_runner,
        )
        self.agent_runner = agent_runner or AgentOrchestrator(
            project_root=project_root,
            normalized_root=project_root / "data" / "normalized",
            platform_dir=project_root / "data" / "normalized" / "platform",
            reports_dir=reports_dir,
            research_runner=self.research_runner,
        )
        self.duckdb_path = duckdb_path
        self.project_root = project_root
        self.pregrab_state_path = self.project_root / "state" / "pregrab_runs.json"
        self.query_state_dir = query_state_dir
        self.window_state_path = window_state_path
        self.reports_dir = reports_dir
        self.environment_check_runner = environment_check_runner
        self.run_jobs_async = run_jobs_async
        self.job_lock = threading.Lock()
        self.job_counter = count(1)
        self.jobs: List[Dict[str, object]] = []

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "/")
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        params = parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=False)
        filters = self._collect_filter_params(params)

        if path == "/healthz":
            return self._respond_text(start_response, "200 OK", "ok")
        if path == "/api/jobs.json":
            return self._respond_json(start_response, {"jobs": self._job_rows()})
        if path == "/api/summary.json":
            context = self.build_context(
                trade_date=self._single_param(params, "date"),
                dataset_name=self._single_param(params, "dataset"),
                limit=self._int_param(params, "limit", 20),
                filters=filters,
            )
            return self._respond_json(start_response, self._api_summary_payload(context))
        if path == "/crawl":
            context = self.build_context(
                trade_date=self._single_param(params, "date"),
                dataset_name=self._single_param(params, "dataset"),
                limit=self._int_param(params, "limit", 20),
                filters=filters,
            )
            html_text = self.render_crawl_html(context)
            return self._respond_html(start_response, html_text)
        if path == "/history":
            context = self.build_context(
                trade_date=self._single_param(params, "date"),
                dataset_name=self._single_param(params, "dataset"),
                limit=self._int_param(params, "limit", 50),
                filters=filters,
            )
            html_text = self.render_history_html(context)
            return self._respond_html(start_response, html_text)
        if path == "/quality":
            page_date = self._single_param(params, "date") or self._default_page_date("quality")
            context = self.build_context(
                trade_date=page_date,
                dataset_name=self._single_param(params, "dataset"),
                limit=self._int_param(params, "limit", 50),
                filters=filters,
            )
            context["page_selected_date"] = page_date
            html_text = self.render_quality_html(context)
            return self._respond_html(start_response, html_text)
        if path == "/strategies":
            page_date = self._single_param(params, "date") or self._default_page_date("strategies")
            context = self.build_context(
                trade_date=page_date,
                dataset_name=self._single_param(params, "dataset"),
                limit=self._int_param(params, "limit", 50),
                filters=filters,
            )
            context["page_selected_date"] = page_date
            context["strategy_start_date"] = self._single_param(params, "start_date") or page_date
            context["strategy_end_date"] = self._single_param(params, "end_date") or page_date
            html_text = self.render_strategies_html(context)
            return self._respond_html(start_response, html_text)
        if path == "/scheduler":
            context = self.build_context(
                trade_date=self._single_param(params, "date"),
                dataset_name=self._single_param(params, "dataset"),
                limit=self._int_param(params, "limit", 50),
                filters=filters,
            )
            html_text = self.render_scheduler_html(context)
            return self._respond_html(start_response, html_text)
        if path == "/reports":
            page_date = self._single_param(params, "date") or self._default_page_date("reports")
            context = self.build_context(
                trade_date=page_date,
                dataset_name=self._single_param(params, "dataset"),
                limit=self._int_param(params, "limit", 50),
                filters=filters,
            )
            context["page_selected_date"] = page_date
            html_text = self.render_reports_html(context)
            return self._respond_html(start_response, html_text)
        if path == "/data-map":
            context = self.build_context(trade_date=self._single_param(params, "date"), dataset_name=self._single_param(params, "dataset"), limit=self._int_param(params, "limit", 50), filters=filters)
            return self._respond_html(start_response, self.render_data_map_html(context))
        if path == "/lineage":
            context = self.build_context(trade_date=self._single_param(params, "date"), dataset_name=self._single_param(params, "dataset"), limit=self._int_param(params, "limit", 50), filters=filters)
            return self._respond_html(start_response, self.render_lineage_html(context))
        if path == "/factor-lab":
            page_date = self._single_param(params, "date") or self._default_page_date("strategies")
            context = self.build_context(trade_date=page_date, dataset_name=self._single_param(params, "dataset"), limit=self._int_param(params, "limit", 50), filters=filters)
            context["page_selected_date"] = page_date
            context["strategy_start_date"] = self._single_param(params, "start_date") or page_date
            context["strategy_end_date"] = self._single_param(params, "end_date") or page_date
            return self._respond_html(start_response, self.render_factor_lab_html(context))
        if path == "/portfolio":
            page_date = self._single_param(params, "date") or self._default_page_date("strategies")
            context = self.build_context(trade_date=page_date, dataset_name=self._single_param(params, "dataset"), limit=self._int_param(params, "limit", 50), filters=filters)
            context["page_selected_date"] = page_date
            context["strategy_start_date"] = self._single_param(params, "start_date") or page_date
            context["strategy_end_date"] = self._single_param(params, "end_date") or page_date
            return self._respond_html(start_response, self.render_portfolio_html(context))
        if path == "/projects":
            page_date = self._single_param(params, "date") or self._default_page_date("strategies")
            context = self.build_context(trade_date=page_date, dataset_name=self._single_param(params, "dataset"), limit=self._int_param(params, "limit", 50), filters=filters)
            context["page_selected_date"] = page_date
            context["strategy_start_date"] = self._single_param(params, "start_date") or page_date
            context["strategy_end_date"] = self._single_param(params, "end_date") or page_date
            return self._respond_html(start_response, self.render_projects_html(context))
        if path == "/knowledge":
            context = self.build_context(trade_date=self._single_param(params, "date"), dataset_name=self._single_param(params, "dataset"), limit=self._int_param(params, "limit", 50), filters=filters)
            return self._respond_html(start_response, self.render_knowledge_html(context))
        if path == "/agent":
            page_date = self._single_param(params, "date") or self._default_page_date("strategies")
            context = self.build_context(trade_date=page_date, dataset_name=self._single_param(params, "dataset"), limit=self._int_param(params, "limit", 50), filters=filters)
            context["page_selected_date"] = page_date
            context["strategy_start_date"] = self._single_param(params, "start_date") or page_date
            context["strategy_end_date"] = self._single_param(params, "end_date") or page_date
            return self._respond_html(start_response, self.render_agent_html(context))
        if path == "/reports/file":
            return self._handle_report_file(params, start_response)
        if path == "/run" and method == "POST":
            post_params = self._parse_post_params(environ)
            action = self._single_param(post_params, "action_name")
            if not action:
                return self._respond_text(start_response, "400 Bad Request", "missing action_name")
            self._start_job(action=action, params=post_params)
            return_path = str(self._single_param(post_params, "return_path") or "").strip()
            if return_path in {"/crawl", "/strategies", "/scheduler", "/reports", "/quality", "/history", "/data-map", "/lineage", "/factor-lab", "/portfolio", "/projects", "/knowledge", "/agent"}:
                start_response("303 See Other", [("Location", self._return_location(return_path, post_params))])
                return [b""]
            redirect_query = urlencode(
                {
                    "date": self._single_param(post_params, "date") or self._single_param(params, "date"),
                    "dataset": self._single_param(post_params, "dataset") or self._single_param(params, "dataset"),
                    "limit": self._single_param(post_params, "limit") or self._single_param(params, "limit") or "20",
                }
            )
            start_response("303 See Other", [("Location", f"/?{redirect_query}")])
            return [b""]
        if path == "/download":
            return self._handle_download(params, start_response)
        if path == "/":
            context = self.build_context(
                trade_date=self._single_param(params, "date"),
                dataset_name=self._single_param(params, "dataset"),
                limit=self._int_param(params, "limit", 20),
                filters=filters,
            )
            html_text = self.render_html(context)
            return self._respond_html(start_response, html_text)

        return self._respond_text(start_response, "404 Not Found", "not found")

    def build_context(
        self,
        trade_date: str = "",
        dataset_name: str = "",
        limit: int = 20,
        filters: Optional[Dict[str, str]] = None,
    ) -> Dict[str, object]:
        latest_success = ""
        if hasattr(self.checkpoints, "get_last_fully_successful_trade_date"):
            latest_success = self.checkpoints.get_last_fully_successful_trade_date() or ""
        if not latest_success:
            latest_success = self.checkpoints.get_last_successful_trade_date() or ""
        selected_date = trade_date or latest_success or ""
        validation = self.runner.validate(selected_date) if selected_date else {"trade_date": "", "datasets": {}, "checkpoint_status": ""}
        audit = (
            self.runner.audit_canonical_date(selected_date)
            if selected_date
            else {"issues": [], "blocked_issues": [], "needs_repair": False, "issue_categories": {}}
        )
        day = self.checkpoints.get_day(selected_date) if selected_date else {}
        outputs = dict(day.get("outputs", {}))
        dataset_cards = []
        for item in build_dataset_catalog():
            dataset = str(item["dataset"])
            dataset_validation = validation.get("datasets", {}).get(dataset, {})
            dataset_cards.append(
                {
                    "dataset": dataset,
                    "label": item["label"],
                    "scope": item["scope"],
                    "trade_date": selected_date,
                    "row_count": int(dataset_validation.get("row_count", 0) or 0),
                    "csv_exists": bool(dataset_validation.get("csv_exists", False)),
                    "schema_ok": bool(dataset_validation.get("schema_ok", False)),
                    "completeness_ok": bool(dataset_validation.get("completeness_ok", False)),
                    "expected_exchanges": list(dataset_validation.get("expected_exchanges", [])),
                    "observed_exchanges": list(dataset_validation.get("observed_exchanges", [])),
                    "path": outputs.get(dataset, ""),
                }
            )

        selected_dataset = dataset_name or self._default_dataset(outputs)
        preview = (
            self._load_preview(outputs.get(selected_dataset, ""), limit=limit, filters=filters or {})
            if selected_dataset
            else {"columns": [], "rows": []}
        )
        recent_days = self._recent_days(limit=12)
        query_runs = self._recent_query_runs(limit=8)
        families = [item.to_summary() for item in build_asset_family_registry()]
        public_assets = self._public_asset_cards()
        public_bonds = self._public_bond_cards()
        public_references = self._public_reference_cards()
        crypto_observation = self._crypto_observation_cards()
        platform_metadata = self._platform_metadata_cards()
        duckdb_manifest = self._duckdb_manifest_cards()
        regression_smoke = self._regression_smoke_summary()
        source_catalog = self._source_catalog_cards()
        source_type_counts = self._source_type_counts(source_catalog)
        source_health_rows = self._source_health_rows()
        source_type_overview_rows = self._source_type_overview_rows()
        issue_category_overview_rows = self._issue_category_overview_rows()
        asset_coverage_rows = self._asset_coverage_rows()
        asset_coverage_status_counts = self._asset_coverage_status_counts(asset_coverage_rows)
        asset_coverage_engineering_counts = self._asset_coverage_engineering_counts(asset_coverage_rows)
        pregrab_runs = self._pregrab_rows()
        window_runs = self._window_run_rows()
        run_history_rows = self._run_history_rows()
        coverage_history_rows = self._coverage_history_rows()
        source_health_history_rows = self._source_health_history_rows()
        research_metric_rows = self._platform_history_rows("research_metrics", limit=60)
        factor_signal_rows = self._platform_history_rows("factor_signals", limit=60)
        strategy_backtest_rows = self._platform_history_rows("strategy_backtests", limit=60)
        paper_portfolio_rows = self._platform_history_rows("paper_portfolios", limit=20)
        quality_diagnostic_rows = self._platform_history_rows("quality_diagnostics", limit=60)
        algorithm_output_rows = self._platform_history_rows("algorithm_outputs", limit=80)
        option_analytics_rows = self._platform_history_rows("option_analytics", limit=40)
        bond_analytics_rows = self._platform_history_rows("bond_analytics", limit=40)
        curve_analytics_rows = self._platform_history_rows("curve_analytics", limit=40)
        risk_metric_rows = self._platform_history_rows("risk_metrics", limit=80)
        portfolio_allocation_rows = self._platform_history_rows("portfolio_allocations", limit=80)
        backtest_equity_rows = self._platform_history_rows("backtest_equity_curves", limit=80)
        backtest_position_rows = self._platform_history_rows("backtest_positions", limit=80)
        backtest_trade_rows = self._platform_history_rows("backtest_trades", limit=80)
        strategy_comparison_rows = self._platform_history_rows("strategy_comparisons", limit=80)
        anomaly_event_rows = self._platform_history_rows("anomaly_events", limit=80)
        ml_model_rows = self._platform_history_rows("ml_model_runs", limit=80)
        ml_prediction_rows = self._platform_history_rows("ml_predictions", limit=80)
        ml_feature_rows = self._platform_history_rows("ml_feature_importance", limit=80)
        model_diagnostic_rows = self._platform_history_rows("model_diagnostics", limit=80)
        backtest_input_quality_rows = self._platform_history_rows("backtest_input_quality", limit=80)
        experiment_run_rows = self._platform_history_rows("experiment_runs", limit=80)
        factor_performance_rows = self._platform_history_rows("factor_performance", limit=80)
        stress_test_rows = self._platform_history_rows("stress_test_results", limit=80)
        dataset_quality_score_rows = self._platform_history_rows("dataset_quality_scores", limit=80)
        report_artifact_rows = self._platform_history_rows("report_artifacts", limit=80)
        artifact_manifest_rows = self._platform_history_rows("artifact_manifest", limit=80)
        dataset_inventory_rows = self._platform_history_rows("dataset_inventory", limit=120)
        dataset_field_profile_rows = self._platform_history_rows("dataset_field_profile", limit=120)
        data_lineage_rows = self._platform_history_rows("data_lineage", limit=120)
        dataset_sla_rule_rows = self._platform_history_rows("dataset_sla_rules", limit=120)
        sla_violation_rows = self._platform_history_rows("sla_violations", limit=120)
        knowledge_index_rows = self._platform_history_rows("knowledge_index", limit=120)
        ml_feature_store_rows = self._platform_history_rows("ml_feature_store", limit=120)
        ml_benchmark_rows = self._platform_history_rows("ml_benchmarks", limit=120)
        ml_validation_fold_rows = self._platform_history_rows("ml_validation_folds", limit=120)
        ml_classification_result_rows = self._platform_history_rows("ml_classification_results", limit=120)
        factor_experiment_rows = self._platform_history_rows("factor_experiments", limit=120)
        parameter_scan_rows = self._platform_history_rows("parameter_scans", limit=120)
        strategy_leaderboard_rows = self._platform_history_rows("strategy_leaderboard", limit=120)
        portfolio_experiment_rows = self._platform_history_rows("portfolio_experiments", limit=120)
        scenario_simulation_rows = self._platform_history_rows("scenario_simulations", limit=120)
        research_project_rows = self._platform_history_rows("research_projects", limit=120)
        project_run_rows = self._platform_history_rows("project_runs", limit=120)
        reproducible_package_rows = self._platform_history_rows("reproducible_packages", limit=120)
        agent_task_rows = self._platform_history_rows("agent_tasks", limit=120)
        agent_step_rows = self._platform_history_rows("agent_steps", limit=160)
        plugin_registry_rows = self._platform_history_rows("plugin_registry", limit=120)
        plugin_run_rows = self._platform_history_rows("plugin_runs", limit=120)
        research_memory_rows = self._platform_history_rows("research_memory", limit=120)
        experiment_note_rows = self._platform_history_rows("experiment_notes", limit=120)
        decision_log_rows = self._platform_history_rows("decision_log", limit=120)
        quality_gate_rows = self._platform_history_rows("quality_gates", limit=120)
        research_readiness_rows = self._platform_history_rows("research_readiness", limit=120)
        input_risk_flag_rows = self._platform_history_rows("input_risk_flags", limit=120)
        task_queue_rows = self._platform_history_rows("task_queue", limit=120)
        task_log_rows = self._platform_history_rows("task_logs", limit=160)
        task_retry_rows = self._platform_history_rows("task_retries", limit=120)
        report_insight_rows = self._platform_history_rows("report_insights", limit=120)
        recommendation_item_rows = self._platform_history_rows("recommendation_items", limit=120)
        model_registry_rows = self._platform_history_rows("model_registry", limit=120)
        feature_version_rows = self._platform_history_rows("feature_versions", limit=120)
        model_drift_event_rows = self._platform_history_rows("model_drift_events", limit=120)
        scheduler_schedules = self._scheduler_schedules()
        scheduler_run_rows = self._scheduler_run_rows()
        report_rows = self._report_rows()
        preview_options = self._preview_options(
            dataset_cards=dataset_cards,
            public_assets=public_assets,
            public_bonds=public_bonds,
            public_references=public_references,
            crypto_observation=crypto_observation,
            platform_metadata=platform_metadata,
        )
        preview_paths = {item["dataset"]: item["path"] for item in preview_options}
        if selected_dataset and selected_dataset not in preview_paths:
            selected_dataset = self._default_preview_dataset(preview_options)
        elif not selected_dataset:
            selected_dataset = self._default_preview_dataset(preview_options)
        preview = (
            self._load_preview(preview_paths.get(selected_dataset, ""), limit=limit, filters=filters or {})
            if selected_dataset
            else {"columns": [], "rows": []}
        )
        selected_preview = next((item for item in preview_options if item.get("dataset") == selected_dataset), {})
        filter_options = self._filter_option_map(preview_paths.get(selected_dataset, ""), filters=filters or {})

        return {
            "selected_date": selected_date,
            "selected_dataset": selected_dataset,
            "selected_dataset_trade_date": str(selected_preview.get("trade_date", selected_date)),
            "selected_limit": limit,
            "latest_successful_trade_date": latest_success,
            "checkpoint_status": validation.get("checkpoint_status", ""),
            "audit": audit,
            "contracts_latest": validation.get("contracts_latest", {}),
            "dataset_cards": dataset_cards,
            "asset_families": families,
            "asset_family_status_counts": family_status_counts(build_asset_family_registry()),
            "preview": preview,
            "recent_days": recent_days,
            "query_runs": query_runs,
            "public_assets": public_assets,
            "public_bonds": public_bonds,
            "public_references": public_references,
            "crypto_observation": crypto_observation,
            "platform_metadata": platform_metadata,
            "duckdb_manifest": duckdb_manifest,
            "duckdb_dataset_count": len(duckdb_manifest),
            "duckdb_database_path": self._relative_display_path(self.duckdb_path),
            "regression_smoke": regression_smoke,
            "source_catalog": source_catalog,
            "source_type_counts": source_type_counts,
            "source_health_rows": source_health_rows,
            "source_type_overview_rows": source_type_overview_rows,
            "issue_category_overview_rows": issue_category_overview_rows,
            "asset_coverage_rows": asset_coverage_rows,
            "asset_coverage_status_counts": asset_coverage_status_counts,
            "asset_coverage_engineering_counts": asset_coverage_engineering_counts,
            "preview_options": preview_options,
            "selected_filters": dict(filters or {}),
            "filter_options": filter_options,
            "crawl_jobs": self._job_rows(),
            "pregrab_runs": pregrab_runs,
            "window_runs": window_runs,
            "run_history_rows": run_history_rows,
            "coverage_history_rows": coverage_history_rows,
            "source_health_history_rows": source_health_history_rows,
            "research_metric_rows": research_metric_rows,
            "factor_signal_rows": factor_signal_rows,
            "strategy_backtest_rows": strategy_backtest_rows,
            "paper_portfolio_rows": paper_portfolio_rows,
            "quality_diagnostic_rows": quality_diagnostic_rows,
            "algorithm_output_rows": algorithm_output_rows,
            "option_analytics_rows": option_analytics_rows,
            "bond_analytics_rows": bond_analytics_rows,
            "curve_analytics_rows": curve_analytics_rows,
            "risk_metric_rows": risk_metric_rows,
            "portfolio_allocation_rows": portfolio_allocation_rows,
            "backtest_equity_rows": backtest_equity_rows,
            "backtest_position_rows": backtest_position_rows,
            "backtest_trade_rows": backtest_trade_rows,
            "strategy_comparison_rows": strategy_comparison_rows,
            "anomaly_event_rows": anomaly_event_rows,
            "ml_model_rows": ml_model_rows,
            "ml_prediction_rows": ml_prediction_rows,
            "ml_feature_rows": ml_feature_rows,
            "model_diagnostic_rows": model_diagnostic_rows,
            "backtest_input_quality_rows": backtest_input_quality_rows,
            "experiment_run_rows": experiment_run_rows,
            "factor_performance_rows": factor_performance_rows,
            "stress_test_rows": stress_test_rows,
            "dataset_quality_score_rows": dataset_quality_score_rows,
            "report_artifact_rows": report_artifact_rows,
            "artifact_manifest_rows": artifact_manifest_rows,
            "dataset_inventory_rows": dataset_inventory_rows,
            "dataset_field_profile_rows": dataset_field_profile_rows,
            "data_lineage_rows": data_lineage_rows,
            "dataset_sla_rule_rows": dataset_sla_rule_rows,
            "sla_violation_rows": sla_violation_rows,
            "knowledge_index_rows": knowledge_index_rows,
            "ml_feature_store_rows": ml_feature_store_rows,
            "ml_benchmark_rows": ml_benchmark_rows,
            "ml_validation_fold_rows": ml_validation_fold_rows,
            "ml_classification_result_rows": ml_classification_result_rows,
            "factor_experiment_rows": factor_experiment_rows,
            "parameter_scan_rows": parameter_scan_rows,
            "strategy_leaderboard_rows": strategy_leaderboard_rows,
            "portfolio_experiment_rows": portfolio_experiment_rows,
            "scenario_simulation_rows": scenario_simulation_rows,
            "research_project_rows": research_project_rows,
            "project_run_rows": project_run_rows,
            "reproducible_package_rows": reproducible_package_rows,
            "agent_task_rows": agent_task_rows,
            "agent_step_rows": agent_step_rows,
            "plugin_registry_rows": plugin_registry_rows,
            "plugin_run_rows": plugin_run_rows,
            "research_memory_rows": research_memory_rows,
            "experiment_note_rows": experiment_note_rows,
            "decision_log_rows": decision_log_rows,
            "quality_gate_rows": quality_gate_rows,
            "research_readiness_rows": research_readiness_rows,
            "input_risk_flag_rows": input_risk_flag_rows,
            "task_queue_rows": task_queue_rows,
            "task_log_rows": task_log_rows,
            "task_retry_rows": task_retry_rows,
            "report_insight_rows": report_insight_rows,
            "recommendation_item_rows": recommendation_item_rows,
            "model_registry_rows": model_registry_rows,
            "feature_version_rows": feature_version_rows,
            "model_drift_event_rows": model_drift_event_rows,
            "scheduler_schedules": scheduler_schedules,
            "scheduler_due_schedules": self._due_schedules(scheduler_schedules),
            "scheduler_run_rows": scheduler_run_rows,
            "report_rows": report_rows,
            "crawl_action_options": list(GUI_ACTION_DEFINITIONS),
            "research_dataset_options": list(RESEARCH_DATASET_OPTIONS),
            "factor_template_options": list(FACTOR_TEMPLATE_OPTIONS),
            "strategy_template_options": list(STRATEGY_TEMPLATE_OPTIONS),
            "algorithm_template_options": list(ALGORITHM_TEMPLATE_OPTIONS),
            "risk_template_options": list(RISK_TEMPLATE_OPTIONS),
            "portfolio_template_options": list(PORTFOLIO_TEMPLATE_OPTIONS),
            "backtest_template_options": list(BACKTEST_TEMPLATE_OPTIONS),
            "ml_template_options": list(ML_TEMPLATE_OPTIONS),
            "stress_template_options": list(STRESS_TEMPLATE_OPTIONS),
            "report_type_options": list(REPORT_TYPE_OPTIONS),
        }

    @staticmethod
    def _api_summary_payload(context: Dict[str, object]) -> Dict[str, object]:
        payload = dict(context)
        list_limits = {
            "dataset_inventory_rows": 50,
            "dataset_field_profile_rows": 50,
            "dataset_sla_rule_rows": 50,
            "dataset_quality_score_rows": 50,
            "knowledge_index_rows": 50,
            "portfolio_allocation_rows": 50,
            "source_catalog": 220,
            "source_health_rows": 120,
            "source_health_history_rows": 50,
            "ml_feature_store_rows": 40,
            "factor_signal_rows": 40,
            "backtest_position_rows": 40,
            "backtest_trade_rows": 40,
            "ml_prediction_rows": 40,
            "model_diagnostic_rows": 40,
            "coverage_history_rows": 50,
            "preview_options": 80,
        }
        truncated: Dict[str, int] = {}
        for key, limit in list_limits.items():
            value = payload.get(key)
            if isinstance(value, list) and len(value) > limit:
                truncated[key] = len(value) - limit
                payload[key] = value[:limit]
        for key, value in list(payload.items()):
            if key in list_limits:
                continue
            if isinstance(value, list) and len(value) > 120:
                truncated.setdefault(key, len(value) - 120)
                payload[key] = value[:120]

        filter_options = payload.get("filter_options")
        if isinstance(filter_options, dict):
            compact_options: Dict[str, object] = {}
            for field, meta in filter_options.items():
                if not isinstance(meta, dict):
                    compact_options[field] = meta
                    continue
                compact_meta = dict(meta)
                choices = compact_meta.get("choices")
                if isinstance(choices, list) and len(choices) > 80:
                    truncated[f"filter_options.{field}"] = len(choices) - 80
                    compact_meta["choices"] = choices[:80]
                compact_options[field] = compact_meta
            payload["filter_options"] = compact_options
        payload["api_truncated_counts"] = truncated
        return payload

    def render_html(self, context: Dict[str, object]) -> str:
        title = "多资产数据平台 GUI"
        selected_date = str(context.get("selected_date", ""))
        selected_dataset = str(context.get("selected_dataset", ""))
        selected_dataset_trade_date = str(context.get("selected_dataset_trade_date", selected_date))
        selected_limit = int(context.get("selected_limit", 20) or 20)
        selected_filters = {str(key): str(value) for key, value in (context.get("selected_filters", {}) or {}).items() if str(value).strip()}
        filter_options = context.get("filter_options", {}) or {}
        dataset_options = []
        for card in context.get("preview_options", []):
            dataset = str(card["dataset"])
            label = str(card["label"])
            selected_attr = " selected" if dataset == selected_dataset else ""
            dataset_options.append(f'<option value="{html.escape(dataset)}"{selected_attr}>{html.escape(label)}</option>')
        filter_inputs = []
        for field, label in GUI_FILTER_FIELDS:
            filter_inputs.append(self._render_filter_input(field, label, selected_filters.get(field, ""), filter_options.get(field, {})))
        download_links = ""
        if selected_dataset:
            query_base = {"dataset": selected_dataset, "date": selected_dataset_trade_date}
            query_base.update(selected_filters)
            download_links = " ".join(
                f'<a class="download-link" href="/download?{html.escape(urlencode({**query_base, "format": output_format}))}">导出 {output_format.upper()}</a>'
                for output_format in ("csv", "json", "parquet")
            )

        cards_html = "".join(self._render_dataset_card(card) for card in context.get("dataset_cards", []))
        family_rows = "".join(self._render_family_row(item) for item in context.get("asset_families", []))
        recent_rows = "".join(self._render_recent_row(item) for item in context.get("recent_days", []))
        query_rows = "".join(self._render_query_row(item) for item in context.get("query_runs", []))
        public_rows = "".join(self._render_public_row(item) for item in context.get("public_assets", []))
        bond_rows = "".join(self._render_public_row(item) for item in context.get("public_bonds", []))
        reference_rows = "".join(self._render_public_row(item) for item in context.get("public_references", []))
        crypto_rows = "".join(self._render_public_row(item) for item in context.get("crypto_observation", []))
        platform_rows = "".join(self._render_public_row(item) for item in context.get("platform_metadata", []))
        duckdb_rows = "".join(self._render_duckdb_row(item) for item in context.get("duckdb_manifest", []))
        crawl_jobs_rows = "".join(self._render_crawl_job_row(item) for item in context.get("crawl_jobs", []))
        pregrab_rows = "".join(self._render_pregrab_row(item) for item in context.get("pregrab_runs", []))
        regression_smoke = context.get("regression_smoke", {}) or {}
        source_catalog_rows = "".join(self._render_source_catalog_row(item) for item in context.get("source_catalog", []))
        source_type_rows = "".join(
            self._render_issue_category_row(category, count)
            for category, count in sorted((context.get("source_type_counts", {}) or {}).items())
        )
        source_health_detail_rows = "".join(
            self._render_source_health_row(item) for item in context.get("source_health_rows", [])
        )
        source_type_overview_table_rows = "".join(
            self._render_source_type_overview_row(item) for item in context.get("source_type_overview_rows", [])
        )
        issue_category_overview_table_rows = "".join(
            self._render_issue_category_overview_row(item) for item in context.get("issue_category_overview_rows", [])
        )
        asset_coverage_table_rows = "".join(
            self._render_asset_coverage_row(item) for item in context.get("asset_coverage_rows", [])
        )
        asset_coverage_summary = ", ".join(
            f"{html.escape(str(status))}:{html.escape(str(count))}"
            for status, count in sorted((context.get("asset_coverage_status_counts", {}) or {}).items())
        )
        asset_coverage_engineering_summary = ", ".join(
            f"{html.escape(str(status))}:{html.escape(str(count))}"
            for status, count in sorted((context.get("asset_coverage_engineering_counts", {}) or {}).items())
        )
        latest_pregrab = next(iter(context.get("pregrab_runs", []) or []), {})
        regression_date_rows = "".join(
            self._render_regression_date_row(trade_date, status)
            for trade_date, status in (regression_smoke.get("date_statuses", {}) or {}).items()
        )
        regression_window_rows = "".join(
            (
                f"<tr><td>{html.escape(str(window_name))}</td>"
                f"<td>{html.escape(str((payload or {}).get('status', '')))}</td>"
                f"<td>{html.escape(str((payload or {}).get('sample_count', 0)))}</td>"
                f"<td>{html.escape(json.dumps((payload or {}).get('status_counts', {}) or {}, ensure_ascii=False, sort_keys=True))}</td>"
                f"<td>{html.escape(', '.join(str(item) for item in ((payload or {}).get('sampled_dates', []) or [])))}</td></tr>"
            )
            for window_name, payload in (regression_smoke.get("window_results", {}) or {}).items()
        )
        regression_issue_rows = "".join(
            self._render_issue_category_row(category, count)
            for category, count in sorted((regression_smoke.get("audit", {}).get("issue_category_counts", {}) or {}).items())
        )
        preview_html = self._render_preview(context.get("preview", {}))
        audit = context.get("audit", {}) or {}
        audit_rows = "".join(self._render_issue_row("需修复", item) for item in audit.get("issues", []))
        blocked_rows = "".join(self._render_issue_row("公开源阻塞", item) for item in audit.get("blocked_issues", []))
        audit_table_rows = audit_rows + blocked_rows
        issue_category_rows = "".join(
            self._render_issue_category_row(category, count)
            for category, count in sorted((audit.get("issue_categories", {}) or {}).items())
        )
        contracts_latest = context.get("contracts_latest", {})
        contracts_latest_line = ""
        if contracts_latest:
            contracts_latest_line = (
                f"<p>contracts_latest 对齐源日：<strong>{html.escape(str(contracts_latest.get('source_trade_date', '')))}</strong>，"
                f"一致性：<strong>{html.escape(str(contracts_latest.get('matches_source_snapshot', False)))}</strong></p>"
            )
        filter_line = (
            "<p>当前筛选："
            + "，".join(
                f"<code>{html.escape(key)}={html.escape(value)}</code>"
                for key, value in sorted(selected_filters.items())
            )
            + "</p>"
            if selected_filters
            else ""
        )
        audit_line = (
            f"<p>canonical 审计：<strong>needs_repair={html.escape(str(audit.get('needs_repair', False)))}</strong>，"
            f"需修复 {len(audit.get('issues', []))} 项，公开源阻塞 {len(audit.get('blocked_issues', []))} 项。</p>"
            if selected_date
            else ""
        )

        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif;
      margin: 0;
      background: linear-gradient(180deg, #f7f5ef 0%, #eef4f7 100%);
      color: #14202b;
    }}
    .page {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
    }}
    h1, h2, h3 {{ margin: 0 0 12px 0; }}
    .hero {{
      padding: 24px;
      border-radius: 20px;
      background: linear-gradient(135deg, #10324a 0%, #185f63 100%);
      color: #fff;
      box-shadow: 0 16px 40px rgba(16, 50, 74, 0.18);
    }}
    .muted {{ color: #d6e6ef; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
      margin-top: 20px;
    }}
    .card {{
      background: rgba(255, 255, 255, 0.92);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(20, 32, 43, 0.08);
    }}
    .pill {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 999px;
      background: #edf3f7;
      font-size: 12px;
      margin-right: 8px;
    }}
    .ok {{ background: #dff4e4; color: #0f6a2b; }}
    .warn {{ background: #fff2d8; color: #7a4a00; }}
    .bad {{ background: #ffe0dc; color: #8b1e12; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      background: rgba(255,255,255,0.95);
      border-radius: 12px;
      overflow: hidden;
    }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid #e7edf2;
      padding: 10px 12px;
      font-size: 13px;
      vertical-align: top;
    }}
    th {{ background: #f3f7fa; }}
    form {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: end;
      margin-top: 16px;
    }}
    label {{
      font-size: 13px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    input, select, button {{
      padding: 9px 12px;
      border-radius: 10px;
      border: 1px solid #c8d7e2;
      font: inherit;
    }}
    button {{
      background: #10324a;
      color: white;
      cursor: pointer;
    }}
    .section {{ margin-top: 24px; }}
    .small {{ font-size: 12px; color: #5b6b78; }}
    code {{ background: #eef4f7; padding: 2px 6px; border-radius: 6px; }}
    .download-link {{
      display: inline-block;
      margin-right: 10px;
      color: #10324a;
      text-decoration: none;
      font-weight: 600;
    }}
    .download-link:hover {{ text-decoration: underline; }}
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <h1>{title}</h1>
      <p class="muted">当前 GUI 直接读取本地 canonical / query 输出，优先服务已经落地的国内场内衍生品数据，并展示多资产平台注册层的扩展状态。</p>
      <div class="grid">
        <div>
          <div class="small">最新成功 canonical 日期</div>
          <h2>{html.escape(str(context.get("latest_successful_trade_date", ""))) or "未发现"}</h2>
        </div>
        <div>
          <div class="small">当前查看日期</div>
          <h2>{html.escape(selected_date) or "未选择"}</h2>
        </div>
        <div>
          <div class="small">checkpoint 状态</div>
          <h2>{html.escape(str(context.get("checkpoint_status", ""))) or "未知"}</h2>
        </div>
      </div>
      <p class="small">运行中资产族状态：<strong>{asset_coverage_summary or '暂无统计'}</strong></p>
      <p class="small">工程收口状态：<strong>{asset_coverage_engineering_summary or '暂无统计'}</strong></p>
      {contracts_latest_line}
      {filter_line}
      {audit_line}
      <p><a class="download-link" href="/">浏览总览</a><a class="download-link" href="/crawl">打开抓取工作台</a><a class="download-link" href="/agent">打开 Agent 中心</a><a class="download-link" href="/history">打开历史研究页</a><a class="download-link" href="/quality">打开质量趋势页</a><a class="download-link" href="/strategies">打开策略研究台</a><a class="download-link" href="/factor-lab">打开因子实验室</a><a class="download-link" href="/portfolio">打开组合研究</a><a class="download-link" href="/projects">打开研究项目</a><a class="download-link" href="/data-map">打开数据资产地图</a><a class="download-link" href="/lineage">打开数据血缘</a><a class="download-link" href="/knowledge">打开知识库</a><a class="download-link" href="/scheduler">打开本地调度</a><a class="download-link" href="/reports">打开报告中心</a></p>
      <form method="get" action="/">
        <label>交易日
          <input type="text" name="date" value="{html.escape(selected_date)}" placeholder="2026-04-16" />
        </label>
        <label>数据集
          <select name="dataset">{''.join(dataset_options)}</select>
        </label>
        <label>预览行数
          <input type="number" name="limit" value="{html.escape(str(selected_limit))}" min="1" max="100" />
        </label>
        {''.join(filter_inputs)}
        <button type="submit">刷新面板</button>
      </form>
    </div>

    <div class="section">
      <h2>抓取工作台</h2>
      <p class="small">点击进入独立抓取页，那里可以直接发起单日抓取、区间回补、逐交易所预抓，以及公开资产 / 债券 / 外汇 / crypto / 平台元数据同步。</p>
      <p><a class="download-link" href="/crawl">打开独立抓取工作台</a></p>
      <table>
        <thead><tr><th>最近预抓交易所</th><th>窗口</th><th>模式</th><th>运行状态</th><th>工程状态</th><th>清理状态</th><th>阻塞摘要</th></tr></thead>
        <tbody>
          {(
            f"<tr><td><strong>{html.escape(str(latest_pregrab.get('exchange', '')))}</strong></td>"
            f"<td>{html.escape(str(latest_pregrab.get('window_start', '')))}<br>{html.escape(str(latest_pregrab.get('window_end', '')))}</td>"
            f"<td>{html.escape(str(latest_pregrab.get('mode', '')))}</td>"
            f"<td>{html.escape(str(latest_pregrab.get('status', '')))}</td>"
            f"<td>{html.escape(str(latest_pregrab.get('engineering_status', '')))}</td>"
            f"<td>{html.escape(str(latest_pregrab.get('cleanup_status', '')))}</td>"
            f"<td><code>{html.escape(' | '.join(str(value) for value in (latest_pregrab.get('blocked_issues', []) or [])) or '-')}</code></td></tr>"
          ) if latest_pregrab else '<tr><td colspan="7">当前还没有逐交易所预抓摘要</td></tr>'}
        </tbody>
      </table>
    </div>

    <div class="section">
      <h2>数据集健康度</h2>
      <div class="grid">{cards_html}</div>
    </div>

    <div class="section">
      <h2>数据质量阻塞与修复</h2>
      <table>
        <thead><tr><th>分类</th><th>说明</th></tr></thead>
        <tbody>{audit_table_rows or '<tr><td colspan="2">当前日期没有需修复项或公开源阻塞项</td></tr>'}</tbody>
      </table>
      <table>
        <thead><tr><th>阻塞类别</th><th>数量</th></tr></thead>
        <tbody>{issue_category_rows or '<tr><td colspan="2">当前日期没有结构化阻塞分类</td></tr>'}</tbody>
      </table>
      <table>
        <thead><tr><th>问题类别</th><th>源数量</th><th>数据集数</th><th>blocked</th><th>最新交易日</th><th>状态统计</th><th>源类型统计</th></tr></thead>
        <tbody>{issue_category_overview_table_rows or '<tr><td colspan="7">暂无问题类别运行总览</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>最近 regression-smoke</h2>
      <p class="small">最近回归时间：<strong>{html.escape(str(regression_smoke.get("updated_at", ""))) or '未记录'}</strong>，运行状态：<strong>{html.escape(str(regression_smoke.get("status", ""))) or '未记录'}</strong>，工程收口状态：<strong>{html.escape(str(regression_smoke.get("engineering_status", ""))) or '未记录'}</strong>，平台元数据校验：<strong>{html.escape(str(regression_smoke.get("platform_validation_status", ""))) or '-'}</strong>，DuckDB 构建：<strong>{html.escape(str(regression_smoke.get("build_db_status", ""))) or '-'}</strong></p>
      <table>
        <thead><tr><th>代表日期</th><th>状态</th></tr></thead>
        <tbody>{regression_date_rows or '<tr><td colspan="2">暂无代表日期回归记录</td></tr>'}</tbody>
      </table>
      <table>
        <thead><tr><th>连续窗口</th><th>状态</th><th>样本数</th><th>状态统计</th><th>采样日期</th></tr></thead>
        <tbody>{regression_window_rows or '<tr><td colspan="5">暂无连续窗口回归记录</td></tr>'}</tbody>
      </table>
      <table>
        <thead><tr><th>阻塞类别</th><th>数量</th></tr></thead>
        <tbody>{regression_issue_rows or '<tr><td colspan="2">最近一次回归没有结构化阻塞类别</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>多资产平台注册表</h2>
      <table>
        <thead><tr><th>资产族</th><th>状态</th><th>阶段</th><th>市场</th><th>说明</th></tr></thead>
        <tbody>{family_rows}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>资产覆盖总览</h2>
      <p class="small">运行中资产族状态统计：{asset_coverage_summary or '暂无统计'}</p>
      <p class="small">工程收口状态统计：{asset_coverage_engineering_summary or '暂无统计'}</p>
      <table>
        <thead><tr><th>资产族</th><th>工程状态</th><th>运行状态</th><th>最新成功日</th><th>最新交易日</th><th>覆盖</th><th>成功/非成功</th><th>外部/内部问题</th><th>总行数</th><th>缺失数据集</th></tr></thead>
        <tbody>{asset_coverage_table_rows or '<tr><td colspan="10">暂无资产覆盖总览</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>源注册与 provenance</h2>
      <table>
        <thead><tr><th>source_type</th><th>数量</th></tr></thead>
        <tbody>{source_type_rows or '<tr><td colspan="2">暂无 source_type 统计</td></tr>'}</tbody>
      </table>
      <table>
        <thead><tr><th>source_type</th><th>源数量</th><th>数据集数</th><th>success/非success</th><th>blocked</th><th>最新交易日</th><th>状态统计</th></tr></thead>
        <tbody>{source_type_overview_table_rows or '<tr><td colspan="7">暂无源类型运行总览</td></tr>'}</tbody>
      </table>
      <table>
        <thead><tr><th>source_id</th><th>数据集</th><th>市场</th><th>交易所</th><th>source_type</th><th>优先级</th><th>URL</th></tr></thead>
        <tbody>{source_catalog_rows or '<tr><td colspan="7">暂无 source catalog</td></tr>'}</tbody>
      </table>
      <table>
        <thead><tr><th>source_id</th><th>数据集</th><th>最近状态</th><th>最近交易日</th><th>类别</th><th>根因</th><th>外部阻塞</th><th>阻塞原因</th><th>消息</th></tr></thead>
        <tbody>{source_health_detail_rows or '<tr><td colspan="9">暂无 source health 明细</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>公开资产与现货快照</h2>
      <table>
        <thead><tr><th>数据集</th><th>状态</th><th>行数</th><th>最近日期</th><th>输出路径</th></tr></thead>
        <tbody>{public_rows or '<tr><td colspan="5">暂无公开资产与现货快照</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>公开参考数据</h2>
      <table>
        <thead><tr><th>数据集</th><th>状态</th><th>行数</th><th>最近日期</th><th>输出路径</th></tr></thead>
        <tbody>{reference_rows or '<tr><td colspan="5">暂无公开参考数据</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>债券与收益率曲线</h2>
      <table>
        <thead><tr><th>数据集</th><th>状态</th><th>行数</th><th>最近日期</th><th>输出路径</th></tr></thead>
        <tbody>{bond_rows or '<tr><td colspan="5">暂无债券与收益率曲线数据</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>全球加密观察</h2>
      <table>
        <thead><tr><th>数据集</th><th>状态</th><th>行数</th><th>最近日期</th><th>输出路径</th></tr></thead>
        <tbody>{crypto_rows or '<tr><td colspan="5">暂无全球加密观察快照</td></tr>'}</tbody>
      </table>
      <p class="small">仅作全球公开市场数据研究与行情观察，不属于国内合法交易所 canonical 数据，也不提供任何交易入口。</p>
    </div>

    <div class="section">
      <h2>平台元数据与质量</h2>
      <table>
        <thead><tr><th>数据集</th><th>状态</th><th>行数</th><th>最近日期</th><th>输出路径</th></tr></thead>
        <tbody>{platform_rows or '<tr><td colspan="5">暂无平台元数据</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>DuckDB 索引概览</h2>
      <p class="small">数据库路径：<code>{html.escape(str(context.get("duckdb_database_path", "")))}</code>，已索引数据集：<strong>{html.escape(str(context.get("duckdb_dataset_count", 0)))}</strong></p>
      <table>
        <thead><tr><th>数据集</th><th>文件数</th><th>行数</th><th>最近构建时间</th></tr></thead>
        <tbody>{duckdb_rows or '<tr><td colspan="4">当前尚未构建 DuckDB manifest</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>数据预览</h2>
      <p class="small">当前数据集：<code>{html.escape(selected_dataset)}</code></p>
      <p class="small">导出当前数据集：{download_links or '暂无可导出数据集'}</p>
      {preview_html}
    </div>

    <div class="section">
      <h2>最近 canonical 运行</h2>
      <table>
        <thead><tr><th>日期</th><th>状态</th><th>输出数据集</th><th>行数摘要</th></tr></thead>
        <tbody>{recent_rows}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>最近 query 运行</h2>
      <table>
        <thead><tr><th>selection_id</th><th>最新修改</th><th>已记录日期数</th></tr></thead>
        <tbody>{query_rows or '<tr><td colspan="3">暂无 query 运行</td></tr>'}</tbody>
      </table>
    </div>
  </div>
</body>
</html>"""

    def render_crawl_html(self, context: Dict[str, object]) -> str:
        selected_date = str(context.get("selected_date", ""))
        latest_success = str(context.get("latest_successful_trade_date", "") or "")
        checkpoint_status = str(context.get("checkpoint_status", "") or "")
        asset_coverage_summary = ", ".join(
            f"{html.escape(str(status))}:{html.escape(str(count))}"
            for status, count in sorted((context.get("asset_coverage_status_counts", {}) or {}).items())
        )
        asset_coverage_engineering_summary = ", ".join(
            f"{html.escape(str(status))}:{html.escape(str(count))}"
            for status, count in sorted((context.get("asset_coverage_engineering_counts", {}) or {}).items())
        )
        crawl_console_html = self._render_crawl_console_section(context)
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>抓取工作台</title>
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif;
      margin: 0;
      background: linear-gradient(180deg, #f7f5ef 0%, #eef4f7 100%);
      color: #14202b;
    }}
    .page {{
      max-width: 1280px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero {{
      padding: 24px;
      border-radius: 20px;
      background: linear-gradient(135deg, #10324a 0%, #185f63 100%);
      color: #fff;
      box-shadow: 0 16px 40px rgba(16, 50, 74, 0.18);
    }}
    .muted {{ color: #d6e6ef; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
      margin-top: 20px;
    }}
    .card {{
      background: rgba(255, 255, 255, 0.92);
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 10px 30px rgba(20, 32, 43, 0.08);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 12px;
      background: rgba(255,255,255,0.95);
      border-radius: 12px;
      overflow: hidden;
    }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid #e7edf2;
      padding: 10px 12px;
      font-size: 13px;
      vertical-align: top;
    }}
    th {{ background: #f3f7fa; }}
    form {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: end;
      margin-top: 16px;
    }}
    label {{
      font-size: 13px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    input, select, button {{
      padding: 9px 12px;
      border-radius: 10px;
      border: 1px solid #c8d7e2;
      font: inherit;
    }}
    button {{
      background: #10324a;
      color: white;
      cursor: pointer;
    }}
    .section {{ margin-top: 24px; }}
    .small {{ font-size: 12px; color: #5b6b78; }}
    .hero .small {{ color: #d6e6ef; }}
    code {{ background: #eef4f7; padding: 2px 6px; border-radius: 6px; }}
    .download-link {{
      display: inline-block;
      margin-right: 10px;
      color: #10324a;
      text-decoration: none;
      font-weight: 600;
    }}
    .download-link:hover {{ text-decoration: underline; }}
    .nav-links a {{
      display: inline-block;
      margin-right: 12px;
      color: #fff;
      text-decoration: none;
      font-weight: 600;
    }}
    .nav-links a:hover {{ text-decoration: underline; }}
    fieldset {{
      border: 1px solid #c8d7e2;
      border-radius: 12px;
      padding: 10px 12px;
      min-width: 260px;
    }}
    legend {{
      padding: 0 6px;
      font-size: 12px;
    }}
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <div class="nav-links">
        <a href="/">返回总览页</a>
        <a href="/crawl">抓取工作台</a>
        <a href="/history">历史研究</a>
        <a href="/quality">质量趋势</a>
        <a href="/strategies">策略研究</a>
        <a href="/agent">Agent 中心</a>
        <a href="/factor-lab">因子实验室</a>
        <a href="/portfolio">组合研究</a>
        <a href="/projects">研究项目</a>
        <a href="/data-map">数据资产地图</a>
        <a href="/lineage">数据血缘</a>
        <a href="/knowledge">知识库</a>
        <a href="/scheduler">本地调度</a>
        <a href="/reports">报告中心</a>
      </div>
      <h1>抓取工作台</h1>
      <p class="muted">这个页面专门负责触发爬虫和查看预抓结果。浏览、筛选和数据预览仍留在总览页，避免和抓取操作混在一起。</p>
      <div class="grid">
        <div>
          <div class="small">最新成功 canonical 日期</div>
          <h2>{html.escape(latest_success) or "未发现"}</h2>
        </div>
        <div>
          <div class="small">当前默认交易日</div>
          <h2>{html.escape(selected_date) or "未选择"}</h2>
        </div>
        <div>
          <div class="small">checkpoint 状态</div>
          <h2>{html.escape(checkpoint_status) or "未知"}</h2>
        </div>
      </div>
      <p class="small">运行中资产族状态：<strong>{asset_coverage_summary or '暂无统计'}</strong></p>
      <p class="small">工程收口状态：<strong>{asset_coverage_engineering_summary or '暂无统计'}</strong></p>
    </div>
    {crawl_console_html}
  </div>
</body>
</html>"""

    def render_history_html(self, context: Dict[str, object]) -> str:
        selected_date = str(context.get("selected_date", ""))
        selected_dataset = str(context.get("selected_dataset", ""))
        selected_limit = int(context.get("selected_limit", 50) or 50)
        dataset_options = []
        for card in context.get("preview_options", []):
            dataset = str(card.get("dataset", ""))
            label = str(card.get("label", dataset))
            selected_attr = " selected" if dataset == selected_dataset else ""
            dataset_options.append(f'<option value="{html.escape(dataset)}"{selected_attr}>{html.escape(label)}</option>')
        filter_options = context.get("filter_options", {}) or {}
        selected_filters = {str(key): str(value) for key, value in (context.get("selected_filters", {}) or {}).items() if str(value).strip()}
        filter_inputs = []
        for field, label in GUI_FILTER_FIELDS:
            filter_inputs.append(self._render_filter_input(field, label, selected_filters.get(field, ""), filter_options.get(field, {})))
        download_links = ""
        if selected_dataset:
            query_base = {"dataset": selected_dataset, "date": str(context.get("selected_dataset_trade_date", selected_date))}
            query_base.update(selected_filters)
            download_links = " ".join(
                f'<a class="download-link" href="/download?{html.escape(urlencode({**query_base, "format": output_format}))}">导出 {output_format.upper()}</a>'
                for output_format in ("csv", "json", "parquet")
            )
        history_rows = "".join(self._render_run_history_row(item) for item in context.get("run_history_rows", [])[:20])
        coverage_rows = "".join(self._render_coverage_history_row(item) for item in context.get("coverage_history_rows", [])[:30])
        source_history_rows = "".join(self._render_source_health_history_row(item) for item in context.get("source_health_history_rows", [])[:30])
        preview_html = self._render_preview(context.get("preview", {}))
        chart_html = self._render_series_chart(context.get("preview", {}))
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>历史研究页</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif; margin: 0; background: linear-gradient(180deg, #f7f5ef 0%, #eef4f7 100%); color: #14202b; }}
    .page {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
    .hero {{ padding: 24px; border-radius: 20px; background: linear-gradient(135deg, #10324a 0%, #185f63 100%); color: #fff; box-shadow: 0 16px 40px rgba(16, 50, 74, 0.18); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-top: 20px; }}
    .card {{ background: rgba(255,255,255,0.94); border-radius: 16px; padding: 18px; box-shadow: 0 10px 30px rgba(20, 32, 43, 0.08); }}
    .section {{ margin-top: 24px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; background: rgba(255,255,255,0.95); border-radius: 12px; overflow: hidden; }}
    th, td {{ text-align: left; border-bottom: 1px solid #e7edf2; padding: 10px 12px; font-size: 13px; vertical-align: top; }}
    th {{ background: #f3f7fa; }}
    form {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: end; margin-top: 16px; }}
    label {{ font-size: 13px; display: flex; flex-direction: column; gap: 6px; }}
    input, select, textarea, button {{ padding: 9px 12px; border-radius: 10px; border: 1px solid #c8d7e2; font: inherit; }}
    textarea {{ min-width: 260px; min-height: 42px; }}
    button {{ background: #10324a; color: white; cursor: pointer; }}
    .small {{ font-size: 12px; color: #5b6b78; }}
    .hero .small {{ color: #d6e6ef; }}
    code {{ background: #eef4f7; padding: 2px 6px; border-radius: 6px; }}
    .download-link {{ display: inline-block; margin-right: 10px; color: #10324a; text-decoration: none; font-weight: 600; }}
    .download-link:hover {{ text-decoration: underline; }}
    .nav-links a {{ display: inline-block; margin-right: 12px; color: #fff; text-decoration: none; font-weight: 600; }}
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <div class="nav-links">
        <a href="/">总览</a>
        <a href="/crawl">抓取工作台</a>
        <a href="/history">历史研究</a>
        <a href="/quality">质量趋势</a>
        <a href="/strategies">策略研究</a>
        <a href="/factor-lab">因子实验室</a>
        <a href="/portfolio">组合研究</a>
        <a href="/projects">研究项目</a>
        <a href="/data-map">数据资产地图</a>
        <a href="/lineage">数据血缘</a>
        <a href="/knowledge">知识库</a>
        <a href="/scheduler">本地调度</a>
        <a href="/reports">报告中心</a>
      </div>
      <h1>历史研究页</h1>
      <p class="small">这里聚合二期的历史数据浏览入口。我们继续沿用当前统一数据表，不新起第二套 v2 表名；这个页面负责历史筛选、预览、导出和简单时间序列查看。</p>
      <form method="get" action="/history">
        <label>交易日
          <input type="text" name="date" value="{html.escape(selected_date)}" placeholder="2026-04-16" />
        </label>
        <label>历史数据集
          <select name="dataset">{''.join(dataset_options)}</select>
        </label>
        <label>预览行数
          <input type="number" name="limit" value="{html.escape(str(selected_limit))}" min="1" max="200" />
        </label>
        {''.join(filter_inputs)}
        <button type="submit">刷新历史视图</button>
      </form>
      <p class="small">当前数据集：<code>{html.escape(selected_dataset)}</code>，导出：{download_links or '暂无可导出数据集'}</p>
    </div>

    <div class="section">
      <h2>时间序列预览</h2>
      <div class="card">{chart_html}</div>
    </div>

    <div class="section">
      <h2>历史数据预览</h2>
      <div class="card">{preview_html}</div>
    </div>

    <div class="section">
      <h2>运行历史</h2>
      <table>
        <thead><tr><th>日期</th><th>类型</th><th>动作</th><th>目标</th><th>运行状态</th><th>工程状态</th><th>窗口</th><th>摘要</th></tr></thead>
        <tbody>{history_rows or '<tr><td colspan="8">暂无运行历史</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>资产覆盖历史</h2>
      <table>
        <thead><tr><th>日期</th><th>资产族</th><th>工程状态</th><th>运行状态</th><th>覆盖</th><th>成功/非成功</th><th>问题</th></tr></thead>
        <tbody>{coverage_rows or '<tr><td colspan="7">暂无资产覆盖历史</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>source health 历史</h2>
      <table>
        <thead><tr><th>日期</th><th>source_id</th><th>数据集</th><th>状态</th><th>类别</th><th>根因</th><th>消息</th></tr></thead>
        <tbody>{source_history_rows or '<tr><td colspan="7">暂无 source health 历史</td></tr>'}</tbody>
      </table>
    </div>
  </div>
</body>
</html>"""

    def render_quality_html(self, context: Dict[str, object]) -> str:
        regression_smoke = context.get("regression_smoke", {}) or {}
        selected_date = html.escape(str(context.get("page_selected_date") or context.get("selected_date", "") or ""))
        source_health_rows = "".join(self._render_source_health_row(item) for item in context.get("source_health_rows", []))
        run_history_rows = "".join(self._render_run_history_row(item) for item in context.get("run_history_rows", [])[:30])
        coverage_history_rows = "".join(self._render_coverage_history_row(item) for item in context.get("coverage_history_rows", [])[:30])
        window_run_rows = "".join(self._render_window_run_row(item) for item in context.get("window_runs", [])[:20])
        source_type_rows = "".join(
            self._render_source_type_overview_row(item) for item in context.get("source_type_overview_rows", [])
        )
        issue_rows = "".join(
            self._render_issue_category_overview_row(item) for item in context.get("issue_category_overview_rows", [])
        )
        quality_rows = "".join(self._render_quality_diagnostic_row(item) for item in context.get("quality_diagnostic_rows", [])[:30])
        dataset_quality_rows = "".join(
            self._render_dataset_quality_score_row(item) for item in context.get("dataset_quality_score_rows", [])[:40]
        )
        anomaly_rows = "".join(self._render_anomaly_event_row(item) for item in context.get("anomaly_event_rows", [])[:40])
        dataset_options = self._render_select_options(context.get("research_dataset_options", []), "daily_ohlcv")
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>质量趋势页</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif; margin: 0; background: linear-gradient(180deg, #f7f5ef 0%, #eef4f7 100%); color: #14202b; }}
    .page {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
    .hero {{ padding: 24px; border-radius: 20px; background: linear-gradient(135deg, #10324a 0%, #185f63 100%); color: #fff; box-shadow: 0 16px 40px rgba(16, 50, 74, 0.18); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; margin-top: 20px; }}
    .card {{ background: rgba(255,255,255,0.94); border-radius: 16px; padding: 18px; box-shadow: 0 10px 30px rgba(20, 32, 43, 0.08); }}
    .section {{ margin-top: 24px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; background: rgba(255,255,255,0.95); border-radius: 12px; overflow: hidden; }}
    th, td {{ text-align: left; border-bottom: 1px solid #e7edf2; padding: 10px 12px; font-size: 13px; vertical-align: top; }}
    th {{ background: #f3f7fa; }}
    .small {{ font-size: 12px; color: #d6e6ef; }}
    code {{ background: #eef4f7; padding: 2px 6px; border-radius: 6px; }}
    .nav-links a {{ display: inline-block; margin-right: 12px; color: #fff; text-decoration: none; font-weight: 600; }}
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <div class="nav-links">
        <a href="/">总览</a>
        <a href="/crawl">抓取工作台</a>
        <a href="/history">历史研究</a>
        <a href="/quality">质量趋势</a>
        <a href="/strategies">策略研究</a>
        <a href="/factor-lab">因子实验室</a>
        <a href="/portfolio">组合研究</a>
        <a href="/projects">研究项目</a>
        <a href="/data-map">数据资产地图</a>
        <a href="/lineage">数据血缘</a>
        <a href="/knowledge">知识库</a>
        <a href="/scheduler">本地调度</a>
        <a href="/reports">报告中心</a>
      </div>
      <h1>质量趋势页</h1>
      <p class="small">这里聚合二期的运行趋势、覆盖率趋势和 source health 历史。当前查看日期：<strong>{selected_date or '未记录'}</strong>。最近一次 regression-smoke：<strong>{html.escape(str(regression_smoke.get("status", ""))) or '未记录'}</strong> / 工程状态 <strong>{html.escape(str(regression_smoke.get("engineering_status", ""))) or '未记录'}</strong>。</p>
      <form method="post" action="/run">
        <input type="hidden" name="action_name" value="quality_score" />
        <input type="hidden" name="return_path" value="/quality" />
        <label>日期 <input name="date" value="{selected_date or 'latest'}" /></label>
        <button type="submit">生成数据质量评分</button>
      </form>
    </div>

    <div class="section">
      <h2>窗口任务历史</h2>
      <table>
        <thead><tr><th>动作</th><th>目标</th><th>窗口</th><th>运行状态</th><th>工程状态</th><th>摘要</th></tr></thead>
        <tbody>{window_run_rows or '<tr><td colspan="6">暂无窗口任务历史</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>运行趋势</h2>
      <table>
        <thead><tr><th>日期</th><th>类型</th><th>动作</th><th>目标</th><th>运行状态</th><th>工程状态</th><th>窗口</th><th>摘要</th></tr></thead>
        <tbody>{run_history_rows or '<tr><td colspan="8">暂无运行历史</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>覆盖率趋势</h2>
      <table>
        <thead><tr><th>日期</th><th>资产族</th><th>工程状态</th><th>运行状态</th><th>覆盖</th><th>成功/非成功</th><th>问题</th></tr></thead>
        <tbody>{coverage_history_rows or '<tr><td colspan="7">暂无覆盖率趋势</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>source health 明细</h2>
      <table>
        <thead><tr><th>source_id</th><th>数据集</th><th>最近状态</th><th>最近交易日</th><th>类别</th><th>根因</th><th>消息</th></tr></thead>
        <tbody>{source_health_rows or '<tr><td colspan="7">暂无 source health 明细</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>质量诊断摘要</h2>
      <table>
        <thead><tr><th>日期</th><th>类型</th><th>数据集</th><th>状态</th><th>级别</th><th>建议</th></tr></thead>
        <tbody>{quality_rows or '<tr><td colspan="6">暂无质量诊断摘要，可在抓取工作台或报告中心生成</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>数据质量评分</h2>
      <p class="small">评分由本地 normalized / platform 表计算，覆盖缺失、空表、source health 与回测输入质量；低分不代表工程失败，而是提示研究前需要注意。</p>
      <table>
        <thead><tr><th>日期</th><th>数据集</th><th>评分</th><th>等级</th><th>覆盖</th><th>异常</th><th>状态</th><th>建议</th></tr></thead>
        <tbody>{dataset_quality_rows or '<tr><td colspan="8">尚未生成数据质量评分，可点击顶部按钮生成。</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>异常事件</h2>
      <table>
        <thead><tr><th>日期</th><th>数据集</th><th>异常类型</th><th>级别</th><th>资产族</th><th>指标</th><th>阈值</th><th>说明</th></tr></thead>
        <tbody>{anomaly_rows or '<tr><td colspan="8">暂无异常事件；这通常表示尚未运行质量诊断，或当前样本未触发异常规则。</td></tr>'}</tbody>
      </table>
    </div>

    <div class="section">
      <h2>回测输入质量快速检查</h2>
      <div class="card">
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="backtest_run" />
          <input type="hidden" name="return_path" value="/quality" />
          <label>开始日期<input name="start_date" value="{selected_date or 'latest'}" /></label>
          <label>结束日期<input name="end_date" value="{selected_date or 'latest'}" /></label>
          <label>数据集<select name="dataset">{dataset_options}</select></label>
          <label>策略<input name="strategy" value="momentum" /></label>
          <button type="submit">检查并运行轻量回测</button>
        </form>
      </div>
    </div>

    <div class="section">
      <h2>源类型与问题类别趋势</h2>
      <table>
        <thead><tr><th>source_type</th><th>源数量</th><th>数据集数</th><th>success/非success</th><th>blocked</th><th>最新交易日</th><th>状态统计</th></tr></thead>
        <tbody>{source_type_rows or '<tr><td colspan="7">暂无源类型趋势</td></tr>'}</tbody>
      </table>
      <table>
        <thead><tr><th>问题类别</th><th>源数量</th><th>数据集数</th><th>blocked</th><th>最新交易日</th><th>状态统计</th><th>源类型统计</th></tr></thead>
        <tbody>{issue_rows or '<tr><td colspan="7">暂无问题类别趋势</td></tr>'}</tbody>
      </table>
    </div>
  </div>
</body>
</html>"""

    def render_strategies_html(self, context: Dict[str, object]) -> str:
        selected_date = html.escape(str(context.get("page_selected_date") or context.get("selected_date", "") or ""))
        start_date = html.escape(str(context.get("strategy_start_date") or selected_date))
        end_date = html.escape(str(context.get("strategy_end_date") or selected_date))
        dataset_options = self._render_select_options(context.get("research_dataset_options", []), "daily_ohlcv")
        factor_options = self._render_select_options(context.get("factor_template_options", []), "momentum")
        strategy_options = self._render_select_options(context.get("strategy_template_options", []), "momentum")
        algorithm_options = self._render_select_options(context.get("algorithm_template_options", []), "momentum")
        risk_options = self._render_select_options(context.get("risk_template_options", []), "var_cvar")
        portfolio_options = self._render_select_options(context.get("portfolio_template_options", []), "risk_parity")
        backtest_options = self._render_select_options(context.get("backtest_template_options", []), "momentum")
        ml_options = self._render_select_options(context.get("ml_template_options", []), "linear_regression")
        stress_options = self._render_select_options(context.get("stress_template_options", []), "equity_down")
        research_rows = "".join(self._render_research_metric_row(item) for item in context.get("research_metric_rows", [])[:30])
        factor_rows = "".join(self._render_factor_signal_row(item) for item in context.get("factor_signal_rows", [])[:30])
        strategy_rows = "".join(self._render_strategy_backtest_row(item) for item in context.get("strategy_backtest_rows", [])[:30])
        paper_rows = "".join(self._render_paper_portfolio_row(item) for item in context.get("paper_portfolio_rows", [])[:20])
        algorithm_rows = "".join(self._render_algorithm_output_row(item) for item in context.get("algorithm_output_rows", [])[:40])
        option_rows = "".join(self._render_option_analytics_row(item) for item in context.get("option_analytics_rows", [])[:20])
        bond_rows = "".join(self._render_bond_analytics_row(item) for item in context.get("bond_analytics_rows", [])[:20])
        curve_rows = "".join(self._render_curve_analytics_row(item) for item in context.get("curve_analytics_rows", [])[:20])
        finance_rows = option_rows + bond_rows + curve_rows
        risk_rows = "".join(self._render_risk_metric_row(item) for item in context.get("risk_metric_rows", [])[:40])
        allocation_rows = "".join(self._render_portfolio_allocation_row(item) for item in context.get("portfolio_allocation_rows", [])[:40])
        backtest_rows = "".join(self._render_backtest_equity_row(item) for item in context.get("backtest_equity_rows", [])[:40])
        comparison_rows = "".join(self._render_strategy_comparison_row(item) for item in context.get("strategy_comparison_rows", [])[:30])
        ml_model_rows = "".join(self._render_ml_model_run_row(item) for item in context.get("ml_model_rows", [])[:30])
        ml_feature_rows = "".join(self._render_ml_feature_row(item) for item in context.get("ml_feature_rows", [])[:40])
        ml_diagnostic_rows = "".join(self._render_model_diagnostic_row(item) for item in context.get("model_diagnostic_rows", [])[:60])
        ml_benchmark_rows = self._render_generic_table(context.get("ml_benchmark_rows", [])[:60], ["template_name", "dataset", "score_metric", "score_value", "r2", "mae", "rmse", "rank", "status", "reason"])
        ml_validation_rows = self._render_generic_table(context.get("ml_validation_fold_rows", [])[:60], ["template_name", "dataset", "fold_index", "method", "train_start", "test_start", "score_metric", "score_value", "status"])
        ml_classification_rows = self._render_generic_table(context.get("ml_classification_result_rows", [])[:40], ["template_name", "dataset", "task_name", "accuracy", "precision", "recall", "f1", "confusion_matrix", "status"])
        factor_perf_rows = "".join(self._render_factor_performance_row(item) for item in context.get("factor_performance_rows", [])[:40])
        stress_rows = "".join(self._render_stress_test_row(item) for item in context.get("stress_test_rows", [])[:40])
        input_quality_rows = "".join(
            self._render_backtest_input_quality_row(item) for item in context.get("backtest_input_quality_rows", [])[:40]
        )
        experiment_rows = "".join(self._render_experiment_run_row(item) for item in context.get("experiment_run_rows", [])[:40])
        return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>策略研究台</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif; margin: 0; background: linear-gradient(180deg, #f7f5ef 0%, #eef4f7 100%); color: #14202b; }}
    .page {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
    .hero {{ padding: 24px; border-radius: 20px; background: linear-gradient(135deg, #243b2f 0%, #53745d 100%); color: #fff; box-shadow: 0 16px 40px rgba(36, 59, 47, 0.18); }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; margin-top: 20px; }}
    .card {{ background: rgba(255,255,255,0.94); border-radius: 16px; padding: 18px; box-shadow: 0 10px 30px rgba(20, 32, 43, 0.08); }}
    .section {{ margin-top: 24px; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 12px; background: rgba(255,255,255,0.95); border-radius: 12px; overflow: hidden; }}
    th, td {{ text-align: left; border-bottom: 1px solid #e7edf2; padding: 10px 12px; font-size: 13px; vertical-align: top; }}
    th {{ background: #f3f7fa; }}
    form {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: end; margin-top: 12px; }}
    label {{ font-size: 13px; display: flex; flex-direction: column; gap: 6px; }}
    input, select, button {{ padding: 9px 12px; border-radius: 10px; border: 1px solid #c8d7e2; font: inherit; }}
    button {{ background: #243b2f; color: white; cursor: pointer; }}
    .small {{ font-size: 12px; color: #5b6b78; }}
    .hero .small {{ color: #e3efe5; }}
    code {{ background: #eef4f7; padding: 2px 6px; border-radius: 6px; }}
    .nav-links a {{ display: inline-block; margin-right: 12px; color: #fff; text-decoration: none; font-weight: 600; }}
  </style>
</head>
<body>
  <div class="page">
    <div class="hero">
      <div class="nav-links">
        <a href="/">总览</a><a href="/crawl">抓取工作台</a><a href="/history">历史研究</a><a href="/quality">质量趋势</a><a href="/strategies">策略研究</a><a href="/factor-lab">因子实验室</a><a href="/portfolio">组合研究</a><a href="/projects">研究项目</a><a href="/data-map">数据资产地图</a><a href="/lineage">数据血缘</a><a href="/knowledge">知识库</a><a href="/scheduler">本地调度</a><a href="/reports">报告中心</a>
      </div>
      <h1>策略研究台 / 算法工作台</h1>
      <p class="small">这里的算法只做本地研究、金融数学建模、因子计算、风险评估和模拟回测，不连接真实交易、不下单、不构成投资建议。当前默认数据口径是日频收盘价，字段不足会诚实标记 not_applicable。</p>
    </div>
    <div class="grid">
      <div class="card">
        <h3>研究指标计算</h3>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="research_run" /><input type="hidden" name="return_path" value="/strategies" />
          <label>开始日期<input name="start_date" value="{start_date}" /></label>
          <label>结束日期<input name="end_date" value="{end_date}" /></label>
          <label>数据集<select name="dataset">{dataset_options}</select></label>
          <label>资产族<input name="asset_family" placeholder="可留空" /></label>
          <button type="submit">计算研究指标</button>
        </form>
      </div>
      <div class="card">
        <h3>因子信号生成</h3>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="factor_run" /><input type="hidden" name="return_path" value="/strategies" />
          <label>开始日期<input name="start_date" value="{start_date}" /></label>
          <label>结束日期<input name="end_date" value="{end_date}" /></label>
          <label>因子模板<select name="factor">{factor_options}</select></label>
          <label>数据集<select name="dataset">{dataset_options}</select></label>
          <label>资产族<input name="asset_family" placeholder="可留空" /></label>
          <button type="submit">生成因子信号</button>
        </form>
      </div>
      <div class="card">
        <h3>算法模板运行</h3>
        <p class="small">统一入口：因子、期权定价、希腊值、隐含波动率、债券 YTM/久期、曲线斜率都走这里。</p>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="algorithm_run" /><input type="hidden" name="return_path" value="/strategies" />
          <label>开始日期<input name="start_date" value="{start_date}" /></label>
          <label>结束日期<input name="end_date" value="{end_date}" /></label>
          <label>算法模板<select name="template">{algorithm_options}</select></label>
          <label>数据集<select name="dataset">{dataset_options}</select></label>
          <label>资产族<input name="asset_family" placeholder="可留空" /></label>
          <label>参数 JSON<textarea name="params" placeholder='{{"underlying_price":100,"strike_price":100,"maturity_years":0.5,"risk_free_rate":0.02,"volatility":0.2,"option_type":"call"}}'></textarea></label>
          <button type="submit">运行算法模板</button>
        </form>
      </div>
      <div class="card">
        <h3>组合风险计算</h3>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="risk_run" /><input type="hidden" name="return_path" value="/strategies" />
          <label>开始日期<input name="start_date" value="{start_date}" /></label>
          <label>结束日期<input name="end_date" value="{end_date}" /></label>
          <label>风险模板<select name="template">{risk_options}</select></label>
          <label>数据集<select name="dataset">{dataset_options}</select></label>
          <label>参数 JSON<textarea name="params" placeholder='{{"confidence":0.95,"target_volatility":0.12}}'></textarea></label>
          <button type="submit">计算风险指标</button>
        </form>
      </div>
      <div class="card">
        <h3>组合配置优化</h3>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="portfolio_optimize" /><input type="hidden" name="return_path" value="/strategies" />
          <label>开始日期<input name="start_date" value="{start_date}" /></label>
          <label>结束日期<input name="end_date" value="{end_date}" /></label>
          <label>配置模板<select name="template">{portfolio_options}</select></label>
          <label>数据集<select name="dataset">{dataset_options}</select></label>
          <label>参数 JSON<textarea name="params" placeholder='{{"initial_cash":1000000}}'></textarea></label>
          <button type="submit">生成组合权重</button>
        </form>
      </div>
      <div class="card">
        <h3>正式回测引擎</h3>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="backtest_run" /><input type="hidden" name="return_path" value="/strategies" />
          <label>开始日期<input name="start_date" value="{start_date}" /></label>
          <label>结束日期<input name="end_date" value="{end_date}" /></label>
          <label>策略模板<select name="strategy">{backtest_options}</select></label>
          <label>数据集<select name="dataset">{dataset_options}</select></label>
          <label>初始资金<input name="initial_cash" value="1000000" /></label>
          <label>费用bps<input name="fee_bps" value="2" /></label>
          <label>滑点bps<input name="slippage_bps" value="1" /></label>
          <button type="submit">运行正式回测</button>
        </form>
      </div>
      <div class="card">
        <h3>日频模拟回测</h3>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="strategy_backtest" /><input type="hidden" name="return_path" value="/strategies" />
          <label>开始日期<input name="start_date" value="{start_date}" /></label>
          <label>结束日期<input name="end_date" value="{end_date}" /></label>
          <label>策略模板<select name="strategy">{strategy_options}</select></label>
          <label>数据集<select name="dataset">{dataset_options}</select></label>
          <label>初始资金<input name="initial_cash" value="1000000" /></label>
          <label>费用bps<input name="fee_bps" value="2" /></label>
          <button type="submit">运行日频模拟回测</button>
        </form>
      </div>
      <div class="card">
        <h3>一日模拟组合</h3>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="paper_sim" /><input type="hidden" name="return_path" value="/strategies" />
          <label>日期<input name="date" value="{selected_date}" /></label>
          <label>策略模板<select name="strategy">{strategy_options}</select></label>
          <label>数据集<select name="dataset">{dataset_options}</select></label>
          <label>初始资金<input name="initial_cash" value="1000000" /></label>
          <button type="submit">生成模拟组合</button>
        </form>
      </div>
	      <div class="card">
	        <h3>机器学习研究</h3>
        <p class="small">ML 只作为研究实验输出，结果会写入实验追踪；XGBoost 若本机不可用会稳定降级为 not_applicable。</p>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="ml_run" /><input type="hidden" name="return_path" value="/strategies" />
          <label>开始日期<input name="start_date" value="{start_date}" /></label>
          <label>结束日期<input name="end_date" value="{end_date}" /></label>
          <label>ML 模板<select name="template">{ml_options}</select></label>
          <label>数据集<select name="dataset">{dataset_options}</select></label>
          <label>目标字段<input name="target" placeholder="默认自动选择 close / yield / price" /></label>
          <label>特征字段<input name="features" placeholder="逗号分隔；留空自动选择" /></label>
          <label>调参<select name="tune"><option value="true">开启小网格</option><option value="false">关闭</option></select></label>
          <label>参数 JSON<textarea name="params" placeholder='{{"max_samples":500,"test_ratio":0.3}}'></textarea></label>
	          <button type="submit">运行 ML 研究</button>
	        </form>
	      </div>
	      <div class="card">
	        <h3>ML Benchmark / Walk-forward 验证</h3>
	        <p class="small">Benchmark 会跑 Linear/Ridge/Lasso/RandomForest/XGBoost/LightGBM/CatBoost/SVM/MLP 等模板；验证会输出时间序列 fold 和方向分类指标。</p>
	        <form method="post" action="/run">
	          <input type="hidden" name="action_name" value="ml_benchmark" /><input type="hidden" name="return_path" value="/strategies" />
	          <label>开始日期<input name="start_date" value="{start_date}" /></label>
	          <label>结束日期<input name="end_date" value="{end_date}" /></label>
	          <label>数据集<select name="dataset">{dataset_options}</select></label>
	          <label>模型列表<input name="models" placeholder="留空=全部模型" /></label>
	          <label>参数 JSON<textarea name="params" placeholder='{{"max_samples":800}}'></textarea></label>
	          <button type="submit">运行 ML Benchmark</button>
	        </form>
	        <form method="post" action="/run">
	          <input type="hidden" name="action_name" value="ml_validate" /><input type="hidden" name="return_path" value="/strategies" />
	          <label>开始日期<input name="start_date" value="{start_date}" /></label>
	          <label>结束日期<input name="end_date" value="{end_date}" /></label>
	          <label>ML 模板<select name="template">{ml_options}</select></label>
	          <label>数据集<select name="dataset">{dataset_options}</select></label>
	          <label>方法<select name="method"><option value="expanding">expanding</option><option value="rolling">rolling</option><option value="fixed_horizon">fixed horizon</option></select></label>
	          <button type="submit">运行时间序列验证</button>
	        </form>
	      </div>
      <div class="card">
        <h3>因子表现评估</h3>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="factor_performance" /><input type="hidden" name="return_path" value="/strategies" />
          <label>开始日期<input name="start_date" value="{start_date}" /></label>
          <label>结束日期<input name="end_date" value="{end_date}" /></label>
          <label>因子<select name="factor">{factor_options}</select></label>
          <label>数据集<select name="dataset">{dataset_options}</select></label>
          <label>资产族<input name="asset_family" placeholder="可留空" /></label>
          <button type="submit">评估因子表现</button>
        </form>
      </div>
      <div class="card">
        <h3>压力测试</h3>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="stress_test" /><input type="hidden" name="return_path" value="/strategies" />
          <label>开始日期<input name="start_date" value="{start_date}" /></label>
          <label>结束日期<input name="end_date" value="{end_date}" /></label>
          <label>压力模板<select name="template">{stress_options}</select></label>
          <label>数据集<select name="dataset">{dataset_options}</select></label>
          <label>参数 JSON<textarea name="params" placeholder='{{"shock_pct":-0.1,"vol_multiplier":1.5}}'></textarea></label>
          <button type="submit">运行压力测试</button>
        </form>
      </div>
    </div>
    <div class="section"><h2>研究指标</h2><table><thead><tr><th>日期</th><th>数据集</th><th>指标</th><th>数值</th><th>状态</th><th>原因</th></tr></thead><tbody>{research_rows or '<tr><td colspan="6">尚未生成研究指标，可在上方点击“计算研究指标”。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>因子信号</h2><table><thead><tr><th>日期</th><th>标的</th><th>因子</th><th>数值</th><th>方向</th><th>状态</th><th>原因</th></tr></thead><tbody>{factor_rows or '<tr><td colspan="7">尚未生成因子信号，可在上方点击“生成因子信号”。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>统一算法输出</h2><table><thead><tr><th>日期</th><th>模板</th><th>数据集/标的</th><th>指标</th><th>数值</th><th>状态</th><th>原因</th></tr></thead><tbody>{algorithm_rows or '<tr><td colspan="7">尚未运行算法模板，可在上方点击“运行算法模板”。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>金融数学模型</h2><table><thead><tr><th>日期</th><th>模型</th><th>标的</th><th>价格/YTM/斜率</th><th>希腊值/久期</th><th>状态</th><th>原因</th></tr></thead><tbody>{finance_rows or '<tr><td colspan="7">尚未生成期权、债券或曲线模型结果。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>组合风险指标</h2><table><thead><tr><th>日期</th><th>模板</th><th>组合</th><th>指标</th><th>数值</th><th>状态</th><th>原因</th></tr></thead><tbody>{risk_rows or '<tr><td colspan="7">尚未生成风险指标，可在上方点击“计算风险指标”。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>组合配置权重</h2><table><thead><tr><th>日期</th><th>模板</th><th>组合</th><th>标的</th><th>权重</th><th>名义金额</th><th>状态</th></tr></thead><tbody>{allocation_rows or '<tr><td colspan="7">尚未生成组合配置，可在上方点击“生成组合权重”。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>正式回测净值曲线</h2><table><thead><tr><th>日期</th><th>策略</th><th>组合权益</th><th>日收益</th><th>累计收益</th><th>回撤</th><th>状态</th><th>原因</th></tr></thead><tbody>{backtest_rows or '<tr><td colspan="8">尚未运行正式回测，可在上方点击“运行正式回测”。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>策略对比</h2><table><thead><tr><th>日期</th><th>策略</th><th>基准</th><th>指标</th><th>策略值</th><th>基准值</th><th>差异</th></tr></thead><tbody>{comparison_rows or '<tr><td colspan="7">尚未生成策略对比。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>回测输入质量</h2><table><thead><tr><th>日期</th><th>数据集</th><th>策略</th><th>状态</th><th>样本</th><th>字段</th><th>原因</th></tr></thead><tbody>{input_quality_rows or '<tr><td colspan="7">尚未生成回测输入质量，可先运行正式回测。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>策略回测</h2><table><thead><tr><th>日期</th><th>策略</th><th>组合权益</th><th>日收益</th><th>累计收益</th><th>回撤</th><th>状态</th><th>原因</th></tr></thead><tbody>{strategy_rows or '<tr><td colspan="8">尚未生成策略回测，可在上方点击“运行日频模拟回测”。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>模拟组合</h2><table><thead><tr><th>日期</th><th>策略</th><th>权益</th><th>现金</th><th>持仓数</th><th>状态</th><th>原因</th></tr></thead><tbody>{paper_rows or '<tr><td colspan="7">尚未生成模拟组合，可在上方点击“生成模拟组合”。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>机器学习模型运行</h2><table><thead><tr><th>日期</th><th>模板</th><th>数据集</th><th>目标/特征</th><th>评分</th><th>最佳参数</th><th>状态</th><th>原因</th></tr></thead><tbody>{ml_model_rows or '<tr><td colspan="8">尚未运行 ML 研究，可在上方点击“运行 ML 研究”。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>ML 特征重要性</h2><table><thead><tr><th>日期</th><th>模板</th><th>特征</th><th>重要性</th><th>排序</th><th>状态</th><th>原因</th></tr></thead><tbody>{ml_feature_rows or '<tr><td colspan="7">暂无 ML 特征重要性。</td></tr>'}</tbody></table></div>
	    <div class="section"><h2>ML 训练诊断</h2><table><thead><tr><th>日期</th><th>模板</th><th>数据集</th><th>诊断</th><th>指标</th><th>数值</th><th>状态</th><th>原因</th></tr></thead><tbody>{ml_diagnostic_rows or '<tr><td colspan="8">暂无 ML 训练诊断。</td></tr>'}</tbody></table></div>
	    <div class="section"><h2>ML Benchmark</h2>{ml_benchmark_rows}</div>
	    <div class="section"><h2>时间序列验证 Fold</h2>{ml_validation_rows}</div>
	    <div class="section"><h2>分类任务指标</h2>{ml_classification_rows}</div>
    <div class="section"><h2>因子表现</h2><table><thead><tr><th>日期</th><th>因子</th><th>数据集</th><th>IC</th><th>Rank IC</th><th>分组/胜率</th><th>状态</th><th>原因</th></tr></thead><tbody>{factor_perf_rows or '<tr><td colspan="8">尚未评估因子表现。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>压力测试结果</h2><table><thead><tr><th>日期</th><th>模板</th><th>数据集</th><th>情景</th><th>冲击</th><th>组合影响</th><th>状态</th><th>原因</th></tr></thead><tbody>{stress_rows or '<tr><td colspan="8">尚未运行压力测试。</td></tr>'}</tbody></table></div>
    <div class="section"><h2>实验历史</h2><table><thead><tr><th>日期</th><th>实验</th><th>类型</th><th>模板</th><th>数据集</th><th>状态</th><th>产物</th><th>参数</th></tr></thead><tbody>{experiment_rows or '<tr><td colspan="8">暂无实验历史。</td></tr>'}</tbody></table></div>
  </div>
</body>
</html>"""

    def render_scheduler_html(self, context: Dict[str, object]) -> str:
        schedule_rows = "".join(self._render_schedule_row(item) for item in context.get("scheduler_schedules", []))
        run_rows = "".join(self._render_scheduler_run_row(item) for item in context.get("scheduler_run_rows", [])[:30])
        due_schedules = list(context.get("scheduler_due_schedules", []) or [])
        due_text = "、".join(str(item.get("task_name") or item.get("schedule_id")) for item in due_schedules) or "当前没有到期任务"
        return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8" /><title>本地调度</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif; margin: 0; background: linear-gradient(180deg, #f7f5ef 0%, #eef4f7 100%); color: #14202b; }}
.page {{ max-width: 1280px; margin: 0 auto; padding: 24px; }} .hero {{ padding: 24px; border-radius: 20px; background: linear-gradient(135deg, #3b2b46 0%, #6e526e 100%); color: #fff; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 12px; background: rgba(255,255,255,0.95); border-radius: 12px; overflow: hidden; }} th, td {{ text-align: left; border-bottom: 1px solid #e7edf2; padding: 10px 12px; font-size: 13px; vertical-align: top; }} th {{ background: #f3f7fa; }}
button, input {{ padding: 8px 11px; border-radius: 10px; border: 1px solid #c8d7e2; }} button {{ background: #3b2b46; color: white; cursor: pointer; }} .section {{ margin-top: 24px; }} .nav-links a {{ color: #fff; margin-right: 12px; font-weight: 600; text-decoration: none; }} code {{ background: #eef4f7; padding: 2px 6px; border-radius: 6px; }} .small {{ font-size: 12px; opacity: .88; }}
</style></head>
<body><div class="page"><div class="hero"><div class="nav-links"><a href="/">总览</a><a href="/crawl">抓取工作台</a><a href="/history">历史研究</a><a href="/quality">质量趋势</a><a href="/strategies">策略研究</a><a href="/factor-lab">因子实验室</a><a href="/portfolio">组合研究</a><a href="/projects">研究项目</a><a href="/data-map">数据资产地图</a><a href="/lineage">数据血缘</a><a href="/knowledge">知识库</a><a href="/scheduler">本地调度</a><a href="/reports">报告中心</a></div><h1>本地调度</h1><p>本页使用本地 tick 模式：不会常驻后台，点击按钮或接入系统 cron 时才会执行到期任务。</p><p class="small">到期任务 {len(due_schedules)} 个：{html.escape(due_text)}</p><form method="post" action="/run"><input type="hidden" name="action_name" value="scheduler_tick" /><input type="hidden" name="return_path" value="/scheduler" /><button type="submit">运行所有到期任务</button></form></div>
<div class="section"><h2>调度计划</h2><table><thead><tr><th>任务</th><th>动作</th><th>频率</th><th>启用</th><th>下次运行</th><th>操作</th></tr></thead><tbody>{schedule_rows or '<tr><td colspan="6">暂无调度计划</td></tr>'}</tbody></table></div>
<div class="section"><h2>最近调度运行</h2><table><thead><tr><th>日期</th><th>任务</th><th>状态</th><th>工程状态</th><th>开始/结束</th><th>摘要</th></tr></thead><tbody>{run_rows or '<tr><td colspan="6">暂无调度运行</td></tr>'}</tbody></table></div>
</div></body></html>"""

    def render_reports_html(self, context: Dict[str, object]) -> str:
        report_rows = "".join(self._render_report_row(item) for item in context.get("report_rows", [])[:50])
        table_rows = "".join(self._render_research_report_dataset_row(item) for item in context.get("report_rows", [])[:50])
        artifact_rows = "".join(self._render_report_artifact_row(item) for item in context.get("report_artifact_rows", [])[:50])
        manifest_rows = "".join(self._render_artifact_manifest_row(item) for item in context.get("artifact_manifest_rows", [])[:50])
        insight_rows = self._render_generic_table(context.get("report_insight_rows", [])[:80], ["report_id", "insight_type", "title", "body", "severity", "status"])
        recommendation_rows = self._render_generic_table(context.get("recommendation_item_rows", [])[:80], ["category", "title", "body", "priority", "status"])
        selected_date = html.escape(str(context.get("page_selected_date") or context.get("selected_date", "") or "latest"))
        report_type_options = self._render_select_options(context.get("report_type_options", []), "comprehensive")
        return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8" /><title>报告中心</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif; margin: 0; background: linear-gradient(180deg, #f7f5ef 0%, #eef4f7 100%); color: #14202b; }}
.page {{ max-width: 1280px; margin: 0 auto; padding: 24px; }} .hero {{ padding: 24px; border-radius: 20px; background: linear-gradient(135deg, #49311f 0%, #8b6b42 100%); color: #fff; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 12px; background: rgba(255,255,255,0.95); border-radius: 12px; overflow: hidden; }} th, td {{ text-align: left; border-bottom: 1px solid #e7edf2; padding: 10px 12px; font-size: 13px; vertical-align: top; }} th {{ background: #f3f7fa; }}
button, input {{ padding: 8px 11px; border-radius: 10px; border: 1px solid #c8d7e2; }} button {{ background: #49311f; color: white; cursor: pointer; }} .section {{ margin-top: 24px; }} .nav-links a {{ color: #fff; margin-right: 12px; font-weight: 600; text-decoration: none; }} code {{ background: #eef4f7; padding: 2px 6px; border-radius: 6px; }}
</style></head>
<body><div class="page"><div class="hero"><div class="nav-links"><a href="/">总览</a><a href="/crawl">抓取工作台</a><a href="/history">历史研究</a><a href="/quality">质量趋势</a><a href="/strategies">策略研究</a><a href="/factor-lab">因子实验室</a><a href="/portfolio">组合研究</a><a href="/projects">研究项目</a><a href="/data-map">数据资产地图</a><a href="/lineage">数据血缘</a><a href="/knowledge">知识库</a><a href="/scheduler">本地调度</a><a href="/reports">报告中心</a></div><h1>报告中心</h1><p>这里浏览本地生成的 HTML / Markdown 研究运营报告；默认展示最新已生成报告日期。</p><form method="post" action="/run"><input type="hidden" name="action_name" value="report_generate" /><input type="hidden" name="return_path" value="/reports" /><label>日期 <input name="date" value="{selected_date}" /></label><label>报告类型 <select name="report_type">{report_type_options}</select></label><button type="submit">生成报告</button></form></div>
<div class="section"><h2>本地报告文件</h2><table><thead><tr><th>日期</th><th>文件</th><th>路径</th></tr></thead><tbody>{report_rows or '<tr><td colspan="3">暂无报告文件</td></tr>'}</tbody></table></div>
<div class="section"><h2>报告索引表</h2><table><thead><tr><th>日期</th><th>报告</th><th>状态</th><th>级别</th><th>摘要</th><th>路径</th></tr></thead><tbody>{table_rows or '<tr><td colspan="6">暂无报告索引</td></tr>'}</tbody></table></div>
<div class="section"><h2>自动解读</h2>{insight_rows}</div>
<div class="section"><h2>下一步建议</h2>{recommendation_rows}</div>
<div class="section"><h2>报告图表与附件</h2><table><thead><tr><th>日期</th><th>报告</th><th>附件</th><th>类型</th><th>状态</th><th>路径</th></tr></thead><tbody>{artifact_rows or '<tr><td colspan="6">暂无报告附件。</td></tr>'}</tbody></table></div>
	<div class="section"><h2>产物血缘 Manifest</h2><table><thead><tr><th>日期</th><th>run_id</th><th>产物</th><th>类型</th><th>源数据</th><th>checksum</th><th>路径</th></tr></thead><tbody>{manifest_rows or '<tr><td colspan="7">暂无产物血缘。</td></tr>'}</tbody></table></div>
	</div></body></html>"""

    def render_data_map_html(self, context: Dict[str, object]) -> str:
        inventory = self._render_generic_table(
            context.get("dataset_inventory_rows", [])[:100],
            ["dataset", "asset_family", "market", "exchange", "file_count", "row_count", "column_count", "first_trade_date", "last_trade_date", "duckdb_indexed", "status"],
        )
        fields = self._render_generic_table(
            context.get("dataset_field_profile_rows", [])[:100],
            ["dataset", "field_name", "inferred_type", "non_null_count", "missing_count", "missing_ratio", "unique_count", "status"],
        )
        sla = self._render_generic_table(
            context.get("dataset_sla_rule_rows", [])[:80],
            ["dataset", "expected_update_time", "min_rows", "max_stale_days", "enabled", "status"],
        )
        violations = self._render_generic_table(
            context.get("sla_violation_rows", [])[:80],
            ["dataset", "violation_type", "severity", "observed_value", "expected_value", "message", "status"],
        )
        return self._simple_page(
            "数据资产地图",
            "展示数据集、资产族、市场、交易所、日期范围、文件数、行数、字段画像、DuckDB 状态和 SLA 结果。",
            """
            <form method="post" action="/run">
              <input type="hidden" name="action_name" value="inventory_build" /><input type="hidden" name="return_path" value="/data-map" />
              <label>日期 <input name="date" value="latest" /></label><button type="submit">刷新数据资产地图</button>
            </form>
            <form method="post" action="/run">
              <input type="hidden" name="action_name" value="sla_check" /><input type="hidden" name="return_path" value="/data-map" />
              <label>日期 <input name="date" value="latest" /></label><button type="submit">执行 SLA 检查</button>
            </form>
            """,
            [
                ("数据集清单", inventory),
                ("字段画像", fields),
                ("SLA 规则", sla),
                ("SLA 违约", violations),
            ],
        )

    def render_lineage_html(self, context: Dict[str, object]) -> str:
        lineage = self._render_generic_table(context.get("data_lineage_rows", [])[:100], ["artifact_id", "artifact_type", "producer", "source_datasets", "parameters", "checksum", "path", "status", "reason"])
        artifacts = self._render_generic_table(context.get("artifact_manifest_rows", [])[:80], ["run_id", "artifact_id", "artifact_type", "source_datasets", "checksum", "path", "status"])
        experiments = self._render_generic_table(context.get("experiment_run_rows", [])[:80], ["run_id", "experiment_type", "template_name", "dataset", "status", "score_metric", "score_value"])
        return self._simple_page(
            "数据血缘",
            "追踪算法、因子、回测、ML、压力测试、报告和可复现包的来源、参数、checksum 与路径。",
            """
            <form method="post" action="/run">
              <input type="hidden" name="action_name" value="lineage_build" /><input type="hidden" name="return_path" value="/lineage" />
              <label>日期 <input name="date" value="latest" /></label><button type="submit">重建数据血缘</button>
            </form>
            """,
            [("血缘索引", lineage), ("产物 Manifest", artifacts), ("实验历史", experiments)],
        )

    def render_factor_lab_html(self, context: Dict[str, object]) -> str:
        selected_date = html.escape(str(context.get("page_selected_date") or context.get("selected_date", "") or "latest"))
        start_date = html.escape(str(context.get("strategy_start_date") or selected_date))
        end_date = html.escape(str(context.get("strategy_end_date") or selected_date))
        dataset_options = self._render_select_options(context.get("research_dataset_options", []), "daily_ohlcv")
        factor_options = self._render_select_options(context.get("factor_template_options", []), "momentum")
        experiments = self._render_generic_table(context.get("factor_experiment_rows", [])[:80], ["factor_name", "dataset", "parameter_set", "ic", "rank_ic", "long_short_return", "win_rate", "coverage", "status"])
        scans = self._render_generic_table(context.get("parameter_scan_rows", [])[:100], ["template_name", "dataset", "parameter_set", "metric_name", "metric_value", "rank", "status"])
        leaderboard = self._render_generic_table(context.get("strategy_leaderboard_rows", [])[:80], ["strategy_name", "dataset", "annual_return", "sharpe", "calmar", "max_drawdown", "quality_score", "rank", "status"])
        feature_rows = self._render_generic_table(context.get("ml_feature_store_rows", [])[:80], ["dataset", "symbol_or_contract", "feature_name", "feature_value", "window", "status"])
        controls = f"""
        <form method="post" action="/run"><input type="hidden" name="action_name" value="feature_run" /><input type="hidden" name="return_path" value="/factor-lab" />
          <label>开始 <input name="start_date" value="{start_date}" /></label><label>结束 <input name="end_date" value="{end_date}" /></label><label>数据集 <select name="dataset">{dataset_options}</select></label><label>特征 <input name="features" placeholder="留空=默认特征包" /></label><button type="submit">生成 Feature Store</button></form>
        <form method="post" action="/run"><input type="hidden" name="action_name" value="factor_experiment" /><input type="hidden" name="return_path" value="/factor-lab" />
          <label>开始 <input name="start_date" value="{start_date}" /></label><label>结束 <input name="end_date" value="{end_date}" /></label><label>因子 <select name="factor">{factor_options}</select></label><label>数据集 <select name="dataset">{dataset_options}</select></label><label>参数 JSON <input name="params" value="{{}}" /></label><button type="submit">运行因子实验</button></form>
        <form method="post" action="/run"><input type="hidden" name="action_name" value="parameter_scan" /><input type="hidden" name="return_path" value="/factor-lab" />
          <label>开始 <input name="start_date" value="{start_date}" /></label><label>结束 <input name="end_date" value="{end_date}" /></label><label>模板 <select name="template">{factor_options}</select></label><label>数据集 <select name="dataset">{dataset_options}</select></label><label>参数网格 JSON <input name="grid" value='{{"window":[5,20],"holding_period":[1,5]}}' /></label><button type="submit">运行参数扫描</button></form>
        <form method="post" action="/run"><input type="hidden" name="action_name" value="strategy_leaderboard" /><input type="hidden" name="return_path" value="/factor-lab" />
          <label>开始 <input name="start_date" value="{start_date}" /></label><label>结束 <input name="end_date" value="{end_date}" /></label><label>数据集 <select name="dataset">{dataset_options}</select></label><button type="submit">刷新策略排行榜</button></form>
        """
        return self._simple_page("因子实验室", "Feature Store、因子实验、参数扫描和策略排行榜集中在这里。", controls, [("Feature Store 样本", feature_rows), ("因子实验", experiments), ("参数扫描", scans), ("策略排行榜", leaderboard)])

    def render_portfolio_html(self, context: Dict[str, object]) -> str:
        selected_date = html.escape(str(context.get("page_selected_date") or context.get("selected_date", "") or "latest"))
        start_date = html.escape(str(context.get("strategy_start_date") or selected_date))
        end_date = html.escape(str(context.get("strategy_end_date") or selected_date))
        dataset_options = self._render_select_options(context.get("research_dataset_options", []), "daily_ohlcv")
        portfolio_options = self._render_select_options(context.get("portfolio_template_options", []), "risk_parity")
        stress_options = self._render_select_options(context.get("stress_template_options", []), "equity_down")
        controls = f"""
        <form method="post" action="/run"><input type="hidden" name="action_name" value="portfolio_run" /><input type="hidden" name="return_path" value="/portfolio" />
          <label>开始 <input name="start_date" value="{start_date}" /></label><label>结束 <input name="end_date" value="{end_date}" /></label><label>组合模板 <select name="template">{portfolio_options}</select></label><label>数据集 <select name="dataset">{dataset_options}</select></label><label>参数 JSON <input name="params" value="{{}}" /></label><button type="submit">运行组合研究</button></form>
        <form method="post" action="/run"><input type="hidden" name="action_name" value="scenario_sim" /><input type="hidden" name="return_path" value="/portfolio" />
          <label>开始 <input name="start_date" value="{start_date}" /></label><label>结束 <input name="end_date" value="{end_date}" /></label><label>情景 <select name="template">{stress_options}</select></label><label>数据集 <select name="dataset">{dataset_options}</select></label><label>参数 JSON <input name="params" value="{{}}" /></label><button type="submit">运行情景推演</button></form>
        """
        allocations = self._render_generic_table(context.get("portfolio_allocation_rows", [])[:80], ["template_name", "portfolio_id", "symbol_or_contract", "weight", "notional", "status"])
        experiments = self._render_generic_table(context.get("portfolio_experiment_rows", [])[:80], ["template_name", "dataset", "portfolio_id", "metric_name", "metric_value", "status"])
        scenarios = self._render_generic_table(context.get("scenario_simulation_rows", [])[:80], ["scenario_name", "dataset", "portfolio_id", "base_value", "stressed_value", "impact_value", "impact_pct", "status"])
        stress = self._render_generic_table(context.get("stress_test_rows", [])[:80], ["template_name", "scenario_name", "dataset", "metric_name", "base_value", "stressed_value", "impact_pct", "status"])
        return self._simple_page("组合研究与情景推演", "组合优化、风险平价、波动率目标、压力情景和情景推演的研究入口。", controls, [("组合权重", allocations), ("组合实验", experiments), ("情景推演", scenarios), ("压力测试", stress)])

    def render_projects_html(self, context: Dict[str, object]) -> str:
        selected_date = html.escape(str(context.get("page_selected_date") or context.get("selected_date", "") or "latest"))
        start_date = html.escape(str(context.get("strategy_start_date") or selected_date))
        end_date = html.escape(str(context.get("strategy_end_date") or selected_date))
        dataset_options = self._render_select_options(context.get("research_dataset_options", []), "daily_ohlcv")
        factor_options = self._render_select_options(context.get("factor_template_options", []), "momentum")
        controls = f"""
        <form method="post" action="/run"><input type="hidden" name="action_name" value="project_create" /><input type="hidden" name="return_path" value="/projects" />
          <label>项目名称 <input name="name" value="NewResearchProject" /></label><label>说明 <input name="description" /></label><label>日期 <input name="date" value="{selected_date}" /></label><button type="submit">创建研究项目</button></form>
        <form method="post" action="/run"><input type="hidden" name="action_name" value="project_run" /><input type="hidden" name="return_path" value="/projects" />
          <label>项目 ID <input name="project_id" placeholder="project-..." /></label><label>研究模板 <select name="template">{factor_options}</select></label><label>开始 <input name="start_date" value="{start_date}" /></label><label>结束 <input name="end_date" value="{end_date}" /></label><label>数据集 <select name="dataset">{dataset_options}</select></label><label>参数 JSON <input name="params" value='{{"report_type":"project"}}' /></label><button type="submit">运行项目闭环</button></form>
        <form method="post" action="/run"><input type="hidden" name="action_name" value="package_export" /><input type="hidden" name="return_path" value="/projects" />
          <label>run_id <input name="run_id" placeholder="可留空" /></label><label>日期 <input name="date" value="{selected_date}" /></label><button type="submit">导出可复现包</button></form>
        """
        projects = self._render_generic_table(context.get("research_project_rows", [])[:80], ["project_id", "name", "description", "status", "created_at", "updated_at"])
        runs = self._render_generic_table(context.get("project_run_rows", [])[:80], ["project_id", "run_id", "template_name", "dataset", "start_date", "end_date", "artifact_count", "status"])
        packages = self._render_generic_table(context.get("reproducible_package_rows", [])[:80], ["package_id", "run_id", "path", "source_datasets", "artifact_count", "checksum", "status"])
        experiments = self._render_generic_table(context.get("experiment_run_rows", [])[:80], ["run_id", "experiment_type", "template_name", "dataset", "window_start", "window_end", "status", "score_metric", "score_value", "artifact_count"])
        insights = self._render_generic_table(context.get("report_insight_rows", [])[:50], ["report_id", "insight_type", "title", "body", "severity", "status"])
        recommendations = self._render_generic_table(context.get("recommendation_item_rows", [])[:50], ["category", "title", "body", "priority", "status"])
        return self._simple_page(
            "研究项目与可复现包",
            "把数据窗口、模型、参数、回测、报告和 checksum 留痕；项目运行会自动串起因子实验、正式回测、排行榜、报告和复现包。",
            controls,
            [("研究项目", projects), ("项目运行", runs), ("实验对比", experiments), ("自动解读", insights), ("下一步建议", recommendations), ("可复现包", packages)],
        )

    def render_knowledge_html(self, context: Dict[str, object]) -> str:
        knowledge = self._render_generic_table(context.get("knowledge_index_rows", [])[:120], ["knowledge_id", "category", "title", "body", "tags", "source_path", "status"])
        return self._simple_page(
            "知识库",
            "索引数据源说明、字段说明、算法说明、GUI 操作、常见错误和外部阻塞解释。",
            """
            <form method="post" action="/run">
              <input type="hidden" name="action_name" value="knowledge_build" /><input type="hidden" name="return_path" value="/knowledge" />
              <label>日期 <input name="date" value="latest" /></label><button type="submit">重建知识库</button>
            </form>
            """,
            [("知识索引", knowledge)],
        )

    def render_agent_html(self, context: Dict[str, object]) -> str:
        selected_date = html.escape(str(context.get("page_selected_date") or context.get("selected_date", "") or "latest"))
        start_date = html.escape(str(context.get("strategy_start_date") or selected_date))
        end_date = html.escape(str(context.get("strategy_end_date") or selected_date))
        dataset_options = self._render_select_options(context.get("research_dataset_options", []), "daily_ohlcv")
        report_type_options = self._render_select_options(context.get("report_type_options", []), "comprehensive")
        latest_task_id = ""
        for row in context.get("agent_task_rows", []) or []:
            latest_task_id = str(row.get("task_id", "") or latest_task_id)
        latest_task_id_escaped = html.escape(latest_task_id)
        controls = f"""
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="agent_plan" /><input type="hidden" name="return_path" value="/agent" />
          <label>研究目标 <input name="goal" value="验证一个多资产动量研究链路，并生成报告" style="min-width:360px" /></label>
          <label>开始 <input name="start_date" value="{start_date}" /></label>
          <label>结束 <input name="end_date" value="{end_date}" /></label>
          <label>数据集 <select name="dataset">{dataset_options}</select></label>
          <label>资产族 <input name="asset_family" placeholder="可留空" /></label>
          <label>模式 <select name="mode"><option value="research">research</option><option value="trial">trial</option><option value="production">production</option></select></label>
          <label>报告类型 <select name="report_type">{report_type_options}</select></label>
          <button type="submit">生成计划（不执行长任务）</button>
        </form>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="agent_run" /><input type="hidden" name="return_path" value="/agent" />
          <label>任务 ID <input name="task_id" value="{latest_task_id_escaped}" placeholder="agent-..." /></label>
          <button type="submit">确认并运行任务</button>
        </form>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="quality_gate" /><input type="hidden" name="return_path" value="/agent" />
          <label>开始 <input name="start_date" value="{start_date}" /></label><label>结束 <input name="end_date" value="{end_date}" /></label>
          <label>数据集 <select name="dataset">{dataset_options}</select></label><label>资产族 <input name="asset_family" placeholder="可留空" /></label>
          <button type="submit">单独运行质量守门</button>
        </form>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="plugin_list" /><input type="hidden" name="return_path" value="/agent" />
          <label>日期 <input name="date" value="{selected_date}" /></label><button type="submit">刷新插件清单</button>
        </form>
        <p class="small">Agent 中心默认先生成执行计划、风险说明和质量守门；只有点击“确认并运行任务”后才会执行 Feature、因子、ML、回测、报告和血缘等长任务。</p>
        """
        tasks = self._render_generic_table(context.get("agent_task_rows", [])[:80], ["task_id", "goal", "dataset", "start_date", "end_date", "status", "engineering_status", "risk_summary", "updated_at"])
        steps = self._render_generic_table(context.get("agent_step_rows", [])[:120], ["task_id", "step_id", "step_order", "plugin_id", "step_name", "status", "engineering_status", "risk_level", "reason"])
        gates = self._render_generic_table(context.get("quality_gate_rows", [])[:80], ["task_id", "dataset", "start_date", "end_date", "gate_status", "severity", "sample_count", "missing_ratio", "message"])
        readiness = self._render_generic_table(context.get("research_readiness_rows", [])[:80], ["task_id", "dataset", "readiness_status", "score", "gate_status", "risk_flags", "message"])
        risks = self._render_generic_table(context.get("input_risk_flag_rows", [])[:80], ["task_id", "dataset", "risk_type", "severity", "message", "recommendation", "status"])
        queue = self._render_generic_table(context.get("task_queue_rows", [])[:80], ["task_id", "queue_status", "priority", "message", "updated_at"])
        logs = self._render_generic_table(context.get("task_log_rows", [])[:120], ["task_id", "step_id", "level", "message", "created_at"])
        plugins = self._render_generic_table(context.get("plugin_registry_rows", [])[:120], ["plugin_id", "category", "label", "risk_level", "supports_dry_run", "produces_artifacts", "status", "reason"])
        plugin_runs = self._render_generic_table(context.get("plugin_run_rows", [])[:80], ["run_id", "plugin_id", "task_id", "step_id", "status", "engineering_status", "elapsed_seconds", "reason"])
        memory = self._render_generic_table(context.get("research_memory_rows", [])[:80], ["task_id", "memory_type", "title", "body", "tags", "status"])
        insights = self._render_generic_table(context.get("report_insight_rows", [])[:80], ["task_id", "report_id", "insight_type", "title", "body", "severity", "status"])
        recommendations = self._render_generic_table(context.get("recommendation_item_rows", [])[:80], ["task_id", "category", "title", "body", "priority", "status"])
        models = self._render_generic_table(context.get("model_registry_rows", [])[:80], ["model_id", "template_name", "dataset", "score_metric", "score_value", "status", "reason"])
        drift = self._render_generic_table(context.get("model_drift_event_rows", [])[:80], ["model_id", "template_name", "dataset", "drift_metric", "drift_status", "severity", "message"])
        return self._simple_page(
            "Agent 中心",
            "把数据检查、质量守门、Feature、因子、ML、回测、报告和血缘统一编排成可确认、可重试、可追踪的本地工作流。",
            controls,
            [
                ("Agent 任务", tasks),
                ("步骤状态", steps),
                ("质量守门", gates),
                ("研究就绪度", readiness),
                ("输入风险", risks),
                ("任务队列", queue),
                ("任务日志", logs),
                ("插件清单", plugins),
                ("插件运行", plugin_runs),
                ("研究记忆", memory),
                ("报告解读", insights),
                ("下一步建议", recommendations),
                ("模型注册", models),
                ("模型漂移", drift),
            ],
        )

    def _simple_page(self, title: str, description: str, controls_html: str, sections) -> str:
        section_html = "\n".join(
            f'<div class="section"><h2>{html.escape(str(section_title))}</h2>{table_html}</div>'
            for section_title, table_html in sections
        )
        return f"""<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8" /><title>{html.escape(title)}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Helvetica Neue", sans-serif; margin: 0; background: linear-gradient(180deg, #f7f5ef 0%, #eef4f7 100%); color: #14202b; }}
.page {{ max-width: 1280px; margin: 0 auto; padding: 24px; }}
.hero {{ padding: 24px; border-radius: 20px; background: linear-gradient(135deg, #1e3848 0%, #52778a 100%); color: #fff; box-shadow: 0 16px 40px rgba(16, 50, 74, 0.18); }}
.section {{ margin-top: 24px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 12px; background: rgba(255,255,255,0.95); border-radius: 12px; overflow: hidden; }}
th, td {{ text-align: left; border-bottom: 1px solid #e7edf2; padding: 10px 12px; font-size: 13px; vertical-align: top; }}
th {{ background: #f3f7fa; }}
form {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: end; margin-top: 12px; }}
label {{ font-size: 13px; display: flex; flex-direction: column; gap: 6px; }}
input, select, button {{ padding: 8px 11px; border-radius: 10px; border: 1px solid #c8d7e2; font: inherit; }}
button {{ background: #1e3848; color: #fff; cursor: pointer; }}
.nav-links a {{ color: #fff; margin-right: 12px; font-weight: 600; text-decoration: none; }}
.small {{ font-size: 12px; color: #d6e6ef; }}
code {{ background: #eef4f7; padding: 2px 6px; border-radius: 6px; }}
</style></head>
<body><div class="page">
<div class="hero"><div class="nav-links"><a href="/">总览</a><a href="/crawl">抓取工作台</a><a href="/agent">Agent 中心</a><a href="/history">历史研究</a><a href="/quality">质量趋势</a><a href="/strategies">策略研究</a><a href="/factor-lab">因子实验室</a><a href="/portfolio">组合研究</a><a href="/projects">研究项目</a><a href="/data-map">数据资产地图</a><a href="/lineage">数据血缘</a><a href="/knowledge">知识库</a><a href="/scheduler">本地调度</a><a href="/reports">报告中心</a></div><h1>{html.escape(title)}</h1><p class="small">{html.escape(description)}</p>{controls_html}</div>
{section_html}
</div></body></html>"""

    @staticmethod
    def _render_generic_table(rows: List[Dict[str, object]], columns: List[str]) -> str:
        header = "".join(f"<th>{html.escape(column)}</th>" for column in columns)
        if not rows:
            return f"<table><thead><tr>{header}</tr></thead><tbody><tr><td colspan='{len(columns)}'>暂无数据，可先点击上方生成/刷新。</td></tr></tbody></table>"
        body = []
        for row in rows:
            cells = []
            for column in columns:
                value = str(row.get(column, "") or "")
                if len(value) > 180:
                    value = value[:177] + "..."
                cells.append(f"<td>{html.escape(value)}</td>")
            body.append("<tr>" + "".join(cells) + "</tr>")
        return f"<table><thead><tr>{header}</tr></thead><tbody>{''.join(body)}</tbody></table>"

    def _render_crawl_console_section(self, context: Dict[str, object]) -> str:
        selected_date = str(context.get("selected_date", ""))
        crawl_jobs_rows = "".join(self._render_crawl_job_row(item) for item in context.get("crawl_jobs", []))
        pregrab_rows = "".join(self._render_pregrab_row(item) for item in context.get("pregrab_runs", []))
        window_run_rows = "".join(self._render_window_run_row(item) for item in context.get("window_runs", []))
        return f"""
    <div class="section">
      <h2>抓取控制台</h2>
      <p class="small">这里可以直接从 GUI 触发爬虫。当前“区间抓取”主要覆盖场内衍生品主线；公开资产、参考、债券和 crypto 当前以 latest / 单日同步为主。</p>
      <p class="small">默认不选交易所时，衍生品抓取走 canonical all-scope：`all` = 全部已接入场内期货 + 期权市场；`futures` = 全部已接入期货交易所；`options` = 全部已接入期权市场。</p>
      <div class="card" style="margin-bottom: 18px;">
        <h3>一键抓取当前已接入的全部数据</h3>
        <p class="small">这是当前 GUI 里最接近“全量抓取”的入口，但它的含义是“抓当前仓库已经接入的 latest-view 全量链路”，不是逐券全历史全量库。</p>
        <p class="small">点击后会顺序执行：</p>
        <ul class="small">
          <li>场内衍生品 latest canonical：期货 + 期权 + 合约主数据 + 结果链</li>
          <li>公开资产：A 股 / 北交所 / ETF / LOF / 开放式基金 / 货币基金 / REITs / 可转债 / 上金所现货 / 碳市场</li>
          <li>公开参考：外汇参考价 / 人民币汇率中间价 / 即期 / 外币对 / 远掉 / C-Swap / Shibor / LPR / 回购利率 / 金银基准价 / 中美国债参考</li>
          <li>公开债券：银行间成交 / 报价 / 收益率曲线 / 上交所债券摘要</li>
          <li>crypto 观察：global snapshot / daily quotes / public derivatives / bitcoin holdings / CME public report</li>
          <li>平台元数据与 DuckDB：统一视图、质量状态、索引库重建</li>
        </ul>
        <p class="small">当前唯一明确外部阻塞仍是 `cffex.options_exercise_results / publication_lag`；如果官方月报还没发，这个动作也会诚实保留该阻塞，不会伪装全绿。</p>
        <form method="post" action="/run">
          <input type="hidden" name="action_name" value="full_latest" />
          <input type="hidden" name="return_path" value="/crawl" />
          <button type="submit">一键抓取当前已接入的全部数据</button>
        </form>
      </div>
      <div class="grid">
        <div class="card">
          <h3>单日抓取（衍生品）</h3>
          <p class="small">抓单个交易日的场内衍生品 canonical 输出。`all` 会覆盖当前已接入的 `SHFE / INE / CFFEX / CZCE / DCE / GFEX` 期货，以及 `SHFE / CFFEX / CZCE / GFEX / DCE / SSE / SZSE` 期权。</p>
          <form method="post" action="/run">
            <input type="hidden" name="action_name" value="fetch_date" />
            <input type="hidden" name="return_path" value="/crawl" />
            <label>交易日
              <input type="text" name="run_date" value="{html.escape(selected_date)}" placeholder="2026-04-16" />
            </label>
            <label>范围
              <select name="instrument_group">
                <option value="all">all</option>
                <option value="futures">futures</option>
                <option value="options">options</option>
              </select>
            </label>
            <button type="submit">开始单日抓取</button>
          </form>
        </div>
        <div class="card">
          <h3>区间回补（衍生品）</h3>
          <p class="small">按交易日历回补一段时间内的场内衍生品数据。默认也是全市场 canonical；若选 `futures` 就是全部已接入期货交易所，选 `options` 就是全部已接入期权市场。</p>
          <form method="post" action="/run">
            <input type="hidden" name="action_name" value="backfill" />
            <input type="hidden" name="return_path" value="/crawl" />
            <label>开始日期
              <input type="text" name="start_date" value="{html.escape(selected_date)}" placeholder="2026-04-01" />
            </label>
            <label>结束日期
              <input type="text" name="end_date" value="{html.escape(selected_date)}" placeholder="2026-04-20" />
            </label>
            <label>范围
              <select name="instrument_group">
                <option value="all">all</option>
                <option value="futures">futures</option>
                <option value="options">options</option>
              </select>
            </label>
            <button type="submit">开始区间回补</button>
          </form>
        </div>
        <div class="card">
          <h3>历史窗口同步（多资产）</h3>
          <p class="small">这是二期新增的多资产历史窗口入口。当前会按交易日日历逐日调用现有公开资产 / 参考 / 债券 / crypto collector，把 latest-view 扩成可持续积累的历史窗。</p>
          <form method="post" action="/run">
            <input type="hidden" name="action_name" value="window_sync" />
            <input type="hidden" name="return_path" value="/crawl" />
            <label>同步范围
              <select name="window_scope">
                <option value="public_assets">公开资产</option>
                <option value="public_references">公开参考</option>
                <option value="public_bonds">公开债券</option>
                <option value="crypto_observation">crypto 观察</option>
              </select>
            </label>
            <label>开始日期
              <input type="text" name="start_date" value="{html.escape(selected_date)}" placeholder="2026-01-21" />
            </label>
            <label>结束日期
              <input type="text" name="end_date" value="{html.escape(selected_date)}" placeholder="2026-04-21" />
            </label>
            <label>数据族过滤
              <input type="text" name="window_families" value="" placeholder="可留空，或逗号分隔 dataset/family" />
            </label>
            <button type="submit">开始历史窗口同步</button>
          </form>
        </div>
        <div class="card">
          <h3>逐交易所预抓</h3>
          <p class="small">这是“按交易所验收”的窗口试跑/正式抓取工具。固定范围为 `instrument_group=all`，会对所选交易所在窗口内逐日执行期货 + 期权 + 合约主数据 + 结果链抓取与校验。</p>
          <form method="post" action="/run">
            <input type="hidden" name="action_name" value="pregrab_window" />
            <input type="hidden" name="return_path" value="/crawl" />
            <label>窗口预设
              <select name="pregrab_preset">
                <option value="latest_7d">近 7 天</option>
                <option value="latest_1m">近 1 月</option>
                <option value="latest_3m" selected>近 3 月</option>
                <option value="custom">自定义</option>
              </select>
            </label>
            <label>开始日期
              <input type="text" name="start_date" value="{html.escape(selected_date)}" placeholder="2026-01-21" />
            </label>
            <label>结束日期
              <input type="text" name="end_date" value="{html.escape(selected_date)}" placeholder="2026-04-21" />
            </label>
            <label>模式
              <select name="pregrab_mode">
                <option value="production">生产抓取（保留）</option>
                <option value="trial">试跑验证（自动清理）</option>
              </select>
            </label>
            <fieldset>
              <legend>交易所</legend>
              <label><input type="checkbox" name="pregrab_exchange" value="CFFEX" checked /> CFFEX</label>
              <label><input type="checkbox" name="pregrab_exchange" value="CZCE" checked /> CZCE</label>
              <label><input type="checkbox" name="pregrab_exchange" value="DCE" checked /> DCE</label>
              <label><input type="checkbox" name="pregrab_exchange" value="GFEX" checked /> GFEX</label>
              <label><input type="checkbox" name="pregrab_exchange" value="SHFE" checked /> SHFE</label>
              <label><input type="checkbox" name="pregrab_exchange" value="SSE" checked /> SSE</label>
              <label><input type="checkbox" name="pregrab_exchange" value="SZSE" checked /> SZSE</label>
            </fieldset>
            <button type="submit">开始逐交易所预抓</button>
          </form>
        </div>
        <div class="card">
          <h3>latest / 单日同步</h3>
          <p class="small">这里不是场内衍生品全市场回补，而是多资产 latest-view 同步入口：公开资产会抓股票 / 北交所 / ETF / LOF / 开放式基金 / 货币基金 / REITs / 可转债 / 上金所现货 / 碳市场；公开参考会抓外汇、利率、金银基准价与中美国债参考；债券与 crypto 也各自走独立 collector。</p>
          <form method="post" action="/run">
            <input type="hidden" name="action_name" value="sync_public_assets" />
            <input type="hidden" name="return_path" value="/crawl" />
            <label>公开资产日期
              <input type="text" name="sync_date" value="latest" placeholder="latest 或 2026-04-21" />
            </label>
            <button type="submit">同步公开资产</button>
          </form>
          <form method="post" action="/run">
            <input type="hidden" name="action_name" value="sync_public_references" />
            <input type="hidden" name="return_path" value="/crawl" />
            <label>公开参考日期
              <input type="text" name="sync_date" value="latest" placeholder="latest 或 2026-04-17" />
            </label>
            <button type="submit">同步公开参考</button>
          </form>
          <form method="post" action="/run">
            <input type="hidden" name="action_name" value="sync_public_bonds" />
            <input type="hidden" name="return_path" value="/crawl" />
            <label>债券日期
              <input type="text" name="sync_date" value="latest" placeholder="latest 或 2026-04-17" />
            </label>
            <button type="submit">同步公开债券</button>
          </form>
          <form method="post" action="/run">
            <input type="hidden" name="action_name" value="sync_crypto_observation" />
            <input type="hidden" name="return_path" value="/crawl" />
            <label>crypto 日期
              <input type="text" name="sync_date" value="latest" placeholder="latest 或 2026-04-21" />
            </label>
            <button type="submit">同步 crypto 观察</button>
          </form>
        </div>
        <div class="card">
          <h3>平台与索引</h3>
          <p class="small">这里不直接抓交易所行情，而是同步平台派生表与本地索引。`同步平台元数据` 会重算统一视图；`重建 DuckDB` 会刷新本地查询库。完整 latest 全量入口已单独放到上面的“一键抓取当前已接入的全部数据”。</p>
          <form method="post" action="/run">
            <input type="hidden" name="action_name" value="sync_platform_metadata" />
            <input type="hidden" name="return_path" value="/crawl" />
            <label>平台元数据日期
              <input type="text" name="sync_date" value="latest" placeholder="latest 或 2026-04-21" />
            </label>
            <button type="submit">同步平台元数据</button>
          </form>
          <form method="post" action="/run">
            <input type="hidden" name="action_name" value="build_db" />
            <input type="hidden" name="return_path" value="/crawl" />
            <button type="submit">重建 DuckDB</button>
          </form>
          <form method="post" action="/run">
            <input type="hidden" name="action_name" value="environment_check" />
            <input type="hidden" name="return_path" value="/crawl" />
            <button type="submit">环境健康检查</button>
          </form>
        </div>
      </div>
      <table>
        <thead><tr><th>任务</th><th>状态</th><th>开始时间</th><th>结束时间</th><th>参数</th><th>结果摘要</th></tr></thead>
        <tbody>{crawl_jobs_rows or '<tr><td colspan="6">当前还没有抓取任务记录</td></tr>'}</tbody>
      </table>
      <table>
        <thead><tr><th>交易所</th><th>窗口</th><th>模式</th><th>运行状态</th><th>工程状态</th><th>通过</th><th>计数</th><th>耗时</th><th>清理</th><th>阻塞/失败</th></tr></thead>
        <tbody>{pregrab_rows or '<tr><td colspan="10">当前还没有逐交易所预抓摘要</td></tr>'}</tbody>
      </table>
      <table>
        <thead><tr><th>动作</th><th>范围</th><th>目标</th><th>窗口</th><th>运行状态</th><th>工程状态</th><th>计数</th><th>阻塞</th></tr></thead>
        <tbody>{window_run_rows or '<tr><td colspan="8">当前还没有历史窗口任务摘要</td></tr>'}</tbody>
      </table>
    </div>"""

    def _default_dataset(self, outputs: Dict[str, str]) -> str:
        for dataset in (
            "derivatives_daily_quotes",
            "options_daily_quotes",
            "futures_daily_quotes",
            "contracts_snapshot",
        ):
            if dataset in outputs:
                return dataset
        return next(iter(outputs), "")

    def _load_preview(self, relative_path: str, *, limit: int, filters: Dict[str, str]) -> Dict[str, object]:
        if not relative_path:
            return {"columns": [], "rows": [], "path": ""}
        csv_path = self.project_root / relative_path
        if not csv_path.exists():
            return {"columns": [], "rows": [], "path": relative_path}
        rows = []
        columns: List[str] = []
        for index, row in enumerate(iter_csv_rows(csv_path)):
            if index == 0:
                columns = list(row.keys())
            if not self._row_matches_filters(row, filters):
                continue
            rows.append(row)
            if len(rows) >= limit:
                break
        return {"columns": columns, "rows": rows, "path": relative_path}

    def _filter_option_map(self, relative_path: str, *, filters: Dict[str, str]) -> Dict[str, Dict[str, object]]:
        option_map: Dict[str, Dict[str, object]] = {
            field: {"kind": "text", "choices": [], "has_column": False}
            for field, _label in GUI_FILTER_FIELDS
        }
        if not relative_path:
            return option_map
        csv_path = self.project_root / relative_path
        if not csv_path.exists():
            return option_map

        unique_values: Dict[str, set[str]] = {field: set() for field, _label in GUI_FILTER_FIELDS}
        columns: List[str] = []
        for index, row in enumerate(iter_csv_rows(csv_path)):
            if index == 0:
                columns = list(row.keys())
            for field, _label in GUI_FILTER_FIELDS:
                if field not in row:
                    continue
                value = str(row.get(field, "")).strip()
                if not value or len(unique_values[field]) >= GUI_FILTER_OPTION_LIMIT:
                    continue
                unique_values[field].add(value)
            if index + 1 >= GUI_FILTER_SCAN_ROW_LIMIT:
                break

        for field, _label in GUI_FILTER_FIELDS:
            choices = sorted(unique_values[field])
            selected_value = str(filters.get(field, "")).strip()
            if not choices:
                choices = self._global_filter_choices(field)
            if selected_value and selected_value not in choices:
                choices = [selected_value, *choices]
            option_map[field] = {
                "kind": (
                    "select"
                    if field in GUI_SELECT_FILTER_FIELDS and choices
                    else "datalist"
                    if field in GUI_SUGGEST_FILTER_FIELDS and choices
                    else "text"
                ),
                "choices": choices[:GUI_FILTER_OPTION_LIMIT],
                "has_column": field in columns,
            }
        return option_map

    @staticmethod
    def _global_filter_choices(field: str) -> List[str]:
        if field == "asset_family":
            return sorted(
                {
                    str(item.to_summary().get("family_id", "")).strip()
                    for item in build_asset_family_registry()
                    if str(item.to_summary().get("family_id", "")).strip()
                }
            )
        if field in {"market", "exchange"}:
            return sorted(
                {
                    str(row.get(field, "")).strip()
                    for row in build_source_catalog()
                    if str(row.get(field, "")).strip()
                }
            )
        return []

    def _recent_days(self, *, limit: int) -> List[Dict[str, object]]:
        dates = self.checkpoints.data.get("dates", {})
        items = []
        for trade_date in sorted(dates, reverse=True)[:limit]:
            day = dates[trade_date]
            items.append(
                {
                    "trade_date": trade_date,
                    "status": day.get("status", ""),
                    "outputs": sorted(day.get("outputs", {}).keys()),
                    "row_counts": day.get("row_counts", {}),
                }
            )
        return items

    def _recent_query_runs(self, *, limit: int) -> List[Dict[str, object]]:
        if not self.query_state_dir.exists():
            return []
        items = []
        for path in sorted(self.query_state_dir.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)[:limit]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            items.append(
                {
                    "selection_id": path.stem,
                    "updated_at": payload.get("last_run_at", ""),
                    "date_count": len(payload.get("dates", {})),
                }
            )
        return items

    def _render_dataset_card(self, card: Dict[str, object]) -> str:
        status_cls = "ok" if card["schema_ok"] and card["completeness_ok"] else ("warn" if card["csv_exists"] else "bad")
        return (
            f'<div class="card">'
            f'<h3>{html.escape(str(card["label"]))}</h3>'
            f'<div class="small"><code>{html.escape(str(card["dataset"]))}</code></div>'
            f'<p><span class="pill {status_cls}">schema={card["schema_ok"]}</span>'
            f'<span class="pill {status_cls}">complete={card["completeness_ok"]}</span></p>'
            f'<p>行数：<strong>{html.escape(str(card["row_count"]))}</strong></p>'
            f'<p class="small">expected={html.escape(",".join(card["expected_exchanges"])) or "-"}</p>'
            f'<p class="small">observed={html.escape(",".join(card["observed_exchanges"])) or "-"}</p>'
            f'<p class="small">路径：<code>{html.escape(str(card["path"])) or "-"}</code></p>'
            f"</div>"
        )

    @staticmethod
    def _render_filter_input(field: str, label: str, selected_value: str, option_meta: Dict[str, object]) -> str:
        value = str(selected_value or "")
        kind = str(option_meta.get("kind", "text") or "text")
        choices = [str(item) for item in (option_meta.get("choices", []) or []) if str(item).strip()]
        if kind == "select":
            option_rows = ['<option value="">全部</option>']
            for choice in choices:
                selected_attr = " selected" if choice == value else ""
                option_rows.append(f'<option value="{html.escape(choice)}"{selected_attr}>{html.escape(choice)}</option>')
            control = f'<select name="{html.escape(field)}">{"".join(option_rows)}</select>'
        elif kind == "datalist":
            list_id = f"filter-options-{field}"
            option_rows = "".join(f'<option value="{html.escape(choice)}"></option>' for choice in choices)
            control = (
                f'<input type="text" name="{html.escape(field)}" value="{html.escape(value)}" '
                f'placeholder="{html.escape(field)}" list="{html.escape(list_id)}" />'
                f'<datalist id="{html.escape(list_id)}">{option_rows}</datalist>'
            )
        else:
            control = (
                f'<input type="text" name="{html.escape(field)}" value="{html.escape(value)}" '
                f'placeholder="{html.escape(field)}" />'
            )
        return f"<label>{html.escape(label)}{control}</label>"

    def _render_family_row(self, family: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td><strong>{html.escape(str(family['label']))}</strong><br><span class=\"small\">{html.escape(str(family['family_id']))}</span></td>"
            f"<td>{html.escape(str(family['status']))}</td>"
            f"<td>{html.escape(str(family['phase']))}</td>"
            f"<td>{html.escape(', '.join(family['markets']))}</td>"
            f"<td>{html.escape(str(family['notes']))}</td>"
            "</tr>"
        )

    def _render_recent_row(self, item: Dict[str, object]) -> str:
        row_counts = ", ".join(f"{key}:{value}" for key, value in sorted(item["row_counts"].items()))
        outputs = ", ".join(item["outputs"])
        return (
            "<tr>"
            f"<td>{html.escape(str(item['trade_date']))}</td>"
            f"<td>{html.escape(str(item['status']))}</td>"
            f"<td>{html.escape(outputs) or '-'}</td>"
            f"<td>{html.escape(row_counts) or '-'}</td>"
            "</tr>"
        )

    def _render_asset_coverage_row(self, item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td><strong>{html.escape(str(item['family_label']))}</strong><br><span class=\"small\">{html.escape(str(item['asset_family']))}</span></td>"
            f"<td>{html.escape(str(item['engineering_status'])) or '-'}</td>"
            f"<td>{html.escape(str(item['runtime_status'])) or '-'}</td>"
            f"<td>{html.escape(str(item['latest_success_trade_date'])) or '-'}</td>"
            f"<td>{html.escape(str(item['latest_trade_date'])) or '-'}</td>"
            f"<td>{html.escape(str(item['coverage_ratio'])) or '-'}</td>"
            f"<td>{html.escape(str(item['success_dataset_count']))}/{html.escape(str(item['non_success_dataset_count']))}</td>"
            f"<td>{html.escape(str(item['external_issue_count']))}/{html.escape(str(item['internal_issue_count']))}</td>"
            f"<td>{html.escape(str(item['total_row_count']))}</td>"
            f"<td>{html.escape(str(item['missing_datasets'])) or '-'}</td>"
            "</tr>"
        )

    def _render_source_type_overview_row(self, item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item['source_type']))}</td>"
            f"<td>{html.escape(str(item['source_count']))}</td>"
            f"<td>{html.escape(str(item['dataset_count']))}</td>"
            f"<td>{html.escape(str(item['success_count']))}/{html.escape(str(item['non_success_count']))}</td>"
            f"<td>{html.escape(str(item['blocked_issue_count']))}</td>"
            f"<td>{html.escape(str(item['latest_trade_date'])) or '-'}</td>"
            f"<td><code>{html.escape(str(item['status_counts']))}</code></td>"
            "</tr>"
        )

    def _render_issue_category_overview_row(self, item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item['issue_category']))}</td>"
            f"<td>{html.escape(str(item['source_count']))}</td>"
            f"<td>{html.escape(str(item['dataset_count']))}</td>"
            f"<td>{html.escape(str(item['blocked_issue_count']))}</td>"
            f"<td>{html.escape(str(item['latest_trade_date'])) or '-'}</td>"
            f"<td><code>{html.escape(str(item['status_counts']))}</code></td>"
            f"<td><code>{html.escape(str(item['source_type_counts']))}</code></td>"
            "</tr>"
        )

    def _render_regression_date_row(self, trade_date: str, status: str) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(trade_date))}</td>"
            f"<td>{html.escape(str(status)) or '-'}</td>"
            "</tr>"
        )

    def _render_query_row(self, item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td><code>{html.escape(str(item['selection_id']))}</code></td>"
            f"<td>{html.escape(str(item['updated_at'])) or '-'}</td>"
            f"<td>{html.escape(str(item['date_count']))}</td>"
            "</tr>"
        )

    def _render_public_row(self, item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item['label']))}<br><span class=\"small\"><code>{html.escape(str(item['dataset']))}</code></span></td>"
            f"<td>{html.escape(str(item['status']))}</td>"
            f"<td>{html.escape(str(item['row_count']))}</td>"
            f"<td>{html.escape(str(item['trade_date']))}</td>"
            f"<td><code>{html.escape(str(item['output_path']))}</code></td>"
            "</tr>"
        )

    def _render_duckdb_row(self, item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td><code>{html.escape(str(item['dataset']))}</code></td>"
            f"<td>{html.escape(str(item['file_count']))}</td>"
            f"<td>{html.escape(str(item['row_count']))}</td>"
            f"<td>{html.escape(str(item['built_at']))}</td>"
            "</tr>"
        )

    def _render_source_catalog_row(self, item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td><code>{html.escape(str(item['source_id']))}</code></td>"
            f"<td>{html.escape(str(item['dataset']))}</td>"
            f"<td>{html.escape(str(item['market']))}</td>"
            f"<td>{html.escape(str(item['exchange']))}</td>"
            f"<td>{html.escape(str(item['source_type']))}</td>"
            f"<td>{html.escape(str(item['priority']))}</td>"
            f"<td><code>{html.escape(str(item['url']))}</code></td>"
            "</tr>"
        )

    def _render_source_health_row(self, item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td><code>{html.escape(str(item['source_id']))}</code></td>"
            f"<td>{html.escape(str(item['dataset']))}</td>"
            f"<td>{html.escape(str(item['last_status']))}</td>"
            f"<td>{html.escape(str(item['last_trade_date']))}</td>"
            f"<td>{html.escape(str(item['issue_category']))}</td>"
            f"<td>{html.escape(str(item['issue_root_cause']))}</td>"
            f"<td>{html.escape(str(item.get('is_external_blocker', '')))}</td>"
            f"<td>{html.escape(str(item['blocked_reason']))}</td>"
            f"<td>{html.escape(str(item['message']))}</td>"
            "</tr>"
        )

    def _render_preview(self, preview: Dict[str, object]) -> str:
        columns = preview.get("columns", [])
        rows = preview.get("rows", [])
        path = preview.get("path", "")
        if not columns:
            return f"<p>当前没有可预览的 CSV。<span class=\"small\">{html.escape(str(path))}</span></p>"
        head = "".join(f"<th>{html.escape(str(column))}</th>" for column in columns)
        body_parts = []
        for row in rows:
            cells = "".join(f"<td>{html.escape(str(row.get(column, '')))}</td>" for column in columns)
            body_parts.append(f"<tr>{cells}</tr>")
        return (
            f"<p class=\"small\">文件：<code>{html.escape(str(path))}</code></p>"
            f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_parts)}</tbody></table>"
        )

    def _render_issue_row(self, category: str, issue: str) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(category)}</td>"
            f"<td><code>{html.escape(str(issue))}</code></td>"
            "</tr>"
        )

    def _render_issue_category_row(self, category: str, count: object) -> str:
        return (
            "<tr>"
            f"<td><code>{html.escape(str(category))}</code></td>"
            f"<td>{html.escape(str(count))}</td>"
            "</tr>"
        )

    def _render_crawl_job_row(self, item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td><strong>{html.escape(str(item.get('label', '')))}</strong><br><span class=\"small\"><code>{html.escape(str(item.get('action', '')))}</code></span></td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('started_at', '')))}</td>"
            f"<td>{html.escape(str(item.get('finished_at', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('params_text', '')))}</code></td>"
            f"<td><code>{html.escape(str(item.get('result_text', '')))}</code></td>"
            "</tr>"
        )

    def _pregrab_rows(self) -> List[Dict[str, object]]:
        try:
            payload = self.pregrab_state_reader(state_path=self.pregrab_state_path) or {}
        except TypeError:
            payload = self.pregrab_state_reader() or {}
        runs = list(payload.get("runs", []) or [])
        rows: List[Dict[str, object]] = []
        for run in reversed(runs):
            exchange_results = run.get("exchange_results", {}) or {}
            for exchange, summary in exchange_results.items():
                detail = dict(summary or {})
                rows.append(
                    {
                        "run_id": str(run.get("run_id", "") or ""),
                        "updated_at": str(run.get("updated_at", "") or payload.get("updated_at", "") or ""),
                        "exchange": str(detail.get("exchange", "") or exchange),
                        "window_start": str(run.get("window_start", "") or ""),
                        "window_end": str(run.get("window_end", "") or ""),
                        "mode": str(run.get("mode", "") or ""),
                        "status": str(detail.get("status", "") or run.get("status", "") or ""),
                        "engineering_status": str(detail.get("engineering_status", "") or run.get("engineering_status", "") or ""),
                        "elapsed_seconds": float(detail.get("elapsed_seconds", 0.0) or 0.0),
                        "day_count": int(detail.get("day_count", 0) or 0),
                        "success_count": int(detail.get("success_count", 0) or 0),
                        "no_data_count": int(detail.get("no_data_count", 0) or 0),
                        "not_applicable_count": int(detail.get("not_applicable_count", 0) or 0),
                        "blocked_external_count": int(detail.get("blocked_external_count", 0) or 0),
                        "failed_count": int(detail.get("failed_count", 0) or 0),
                        "passed": bool(detail.get("passed", False)),
                        "engineering_passed": bool(detail.get("engineering_passed", False)),
                        "cleanup_status": str(run.get("cleanup_status", "") or ""),
                        "blocked_issues": list(detail.get("blocked_issues", []) or []),
                        "failed_days": list(detail.get("failed_days", []) or []),
                        "blocked_days": list(detail.get("blocked_days", []) or []),
                    }
                )
        return rows[:40]

    def _render_pregrab_row(self, item: Dict[str, object]) -> str:
        counts = (
            f"success:{item.get('success_count', 0)} / no_data:{item.get('no_data_count', 0)} / "
            f"not_applicable:{item.get('not_applicable_count', 0)} / blocked:{item.get('blocked_external_count', 0)} / failed:{item.get('failed_count', 0)}"
        )
        issues = list(item.get("blocked_issues", []) or [])
        if item.get("failed_days"):
            issues.append("failed_days=" + ",".join(str(value) for value in item.get("failed_days", [])))
        if item.get("blocked_days"):
            issues.append("blocked_days=" + ",".join(str(value) for value in item.get("blocked_days", [])))
        verdict = "runtime=通过" if bool(item.get("passed", False)) else "runtime=未通过"
        verdict += " / engineering=通过" if bool(item.get("engineering_passed", False)) else " / engineering=未通过"
        return (
            "<tr>"
            f"<td><strong>{html.escape(str(item.get('exchange', '')))}</strong><br><span class='small'><code>{html.escape(str(item.get('run_id', '')))}</code></span></td>"
            f"<td>{html.escape(str(item.get('window_start', '')))}<br>{html.escape(str(item.get('window_end', '')))}</td>"
            f"<td>{html.escape(str(item.get('mode', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('engineering_status', '')))}</td>"
            f"<td>{html.escape(verdict)}</td>"
            f"<td><code>{html.escape(counts)}</code></td>"
            f"<td>{html.escape(str(item.get('elapsed_seconds', 0.0)))}s / {html.escape(str(item.get('day_count', 0)))} 天</td>"
            f"<td>{html.escape(str(item.get('cleanup_status', '')))}</td>"
            f"<td><code>{html.escape(' | '.join(str(value) for value in issues) or '-')}</code></td>"
            "</tr>"
        )

    def _window_run_rows(self) -> List[Dict[str, object]]:
        try:
            payload = self.window_state_reader(state_path=self.window_state_path) or {}
        except TypeError:
            payload = self.window_state_reader() or {}
        runs = list(payload.get("runs", []) or [])
        rows: List[Dict[str, object]] = []
        for run in reversed(runs):
            rows.append(
                {
                    "run_id": str(run.get("run_id", "") or ""),
                    "action_name": str(run.get("action_name", "") or ""),
                    "scope": str(run.get("scope", "") or ""),
                    "target": str(run.get("target", "") or ""),
                    "mode": str(run.get("mode", "") or ""),
                    "window_start": str(run.get("window_start", "") or ""),
                    "window_end": str(run.get("window_end", "") or ""),
                    "status": str(run.get("status", "") or ""),
                    "engineering_status": str(run.get("engineering_status", "") or ""),
                    "date_counts": dict(run.get("date_counts", {}) or {}),
                    "blocked_issues": list(run.get("blocked_issues", []) or []),
                    "updated_at": str(run.get("updated_at", "") or payload.get("updated_at", "") or ""),
                }
            )
        return rows[:40]

    def _render_window_run_row(self, item: Dict[str, object]) -> str:
        counts = ", ".join(
            f"{key}:{value}"
            for key, value in sorted((item.get("date_counts", {}) or {}).items())
        ) or "-"
        issues = " | ".join(str(value) for value in (item.get("blocked_issues", []) or [])) or "-"
        return (
            "<tr>"
            f"<td><strong>{html.escape(str(item.get('action_name', '')))}</strong><br><span class='small'><code>{html.escape(str(item.get('run_id', '')))}</code></span></td>"
            f"<td>{html.escape(str(item.get('scope', '')))}</td>"
            f"<td>{html.escape(str(item.get('target', '')))}</td>"
            f"<td>{html.escape(str(item.get('window_start', '')))}<br>{html.escape(str(item.get('window_end', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('engineering_status', '')))}</td>"
            f"<td><code>{html.escape(counts)}</code></td>"
            f"<td><code>{html.escape(issues)}</code></td>"
            "</tr>"
        )

    def _run_history_rows(self) -> List[Dict[str, object]]:
        return self._platform_history_rows("run_history", limit=40)

    def _coverage_history_rows(self) -> List[Dict[str, object]]:
        return self._platform_history_rows("coverage_history", limit=60)

    def _source_health_history_rows(self) -> List[Dict[str, object]]:
        return self._platform_history_rows("source_health_history", limit=60)

    def _platform_history_rows(self, dataset_name: str, *, limit: int) -> List[Dict[str, object]]:
        summaries = self.platform_metadata_runner.latest_summaries()
        summary = summaries.get(dataset_name, {})
        output_path = str(summary.get("output_path", "")).strip()
        if not output_path:
            return []
        csv_path = self.project_root / output_path
        if not csv_path.exists():
            return []
        rows = [dict(row) for row in iter_csv_rows(csv_path)]
        rows.sort(
            key=lambda item: (
                str(item.get("trade_date", "")),
                str(item.get("updated_at", "")),
                str(item.get("run_id", "")),
                str(item.get("source_id", "")),
            ),
            reverse=True,
        )
        return rows[:limit]

    def _render_run_history_row(self, item: Dict[str, object]) -> str:
        summary = (
            f"items={item.get('item_count', '')} / success={item.get('success_count', '')} / "
            f"non_success={item.get('non_success_count', '')} / blocked={item.get('blocked_issue_count', '')}"
        )
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('history_kind', '')))}</td>"
            f"<td>{html.escape(str(item.get('action_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('target', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('engineering_status', '')))}</td>"
            f"<td>{html.escape(str(item.get('window_start', '')))}<br>{html.escape(str(item.get('window_end', '')))}</td>"
            f"<td><code>{html.escape(summary)}</code></td>"
            "</tr>"
        )

    def _render_coverage_history_row(self, item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td><strong>{html.escape(str(item.get('family_label', '')))}</strong><br><span class='small'>{html.escape(str(item.get('asset_family', '')))}</span></td>"
            f"<td>{html.escape(str(item.get('engineering_status', '')))}</td>"
            f"<td>{html.escape(str(item.get('runtime_status', '')))}</td>"
            f"<td>{html.escape(str(item.get('coverage_ratio', '')))}</td>"
            f"<td>{html.escape(str(item.get('success_dataset_count', '')))} / {html.escape(str(item.get('non_success_dataset_count', '')))}</td>"
            f"<td>{html.escape(str(item.get('issue_root_cause_counts', '')))}</td>"
            "</tr>"
        )

    def _render_source_health_history_row(self, item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('source_id', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('dataset', '')))}</td>"
            f"<td>{html.escape(str(item.get('last_status', '')))}</td>"
            f"<td>{html.escape(str(item.get('issue_category', '')))}</td>"
            f"<td>{html.escape(str(item.get('issue_root_cause', '')))}</td>"
            f"<td>{html.escape(str(item.get('message', '')))}</td>"
            "</tr>"
        )

    def _render_series_chart(self, preview: Dict[str, object]) -> str:
        rows = list(preview.get("rows", []) or [])
        columns = list(preview.get("columns", []) or [])
        if not rows or not columns:
            return "<p class='small'>当前数据不足，暂时无法绘制时间序列。</p>"
        x_field = "trade_date" if "trade_date" in columns else columns[0]
        numeric_field = next(
            (
                field
                for field in ("close", "price", "value", "yield", "nav", "last_price", "price_usd")
                if field in columns
            ),
            "",
        )
        if not numeric_field:
            return "<p class='small'>当前数据集没有可识别的数值列，暂时不绘图。</p>"
        points = []
        for row in rows:
            try:
                value = float(str(row.get(numeric_field, "")).replace(",", ""))
            except (TypeError, ValueError):
                continue
            points.append((str(row.get(x_field, "")), value))
        if len(points) < 2:
            return "<p class='small'>可用数值样本不足，暂时不绘图。</p>"
        values = [value for _, value in points]
        low = min(values)
        high = max(values)
        span = high - low or 1.0
        svg_points = []
        for index, (_label, value) in enumerate(points):
            x = 20 + (index * 560 / max(len(points) - 1, 1))
            y = 160 - ((value - low) / span) * 120
            svg_points.append(f"{x:.1f},{y:.1f}")
        labels = "".join(
            f"<text x='{20 + (index * 560 / max(len(points) - 1, 1)):.1f}' y='190' font-size='10' text-anchor='middle'>{html.escape(label)}</text>"
            for index, (label, _value) in enumerate(points[:8])
        )
        return (
            f"<p class='small'>字段：<code>{html.escape(numeric_field)}</code>，样本：{len(points)} 条</p>"
            "<svg viewBox='0 0 600 200' width='100%' height='220' role='img' aria-label='history-series-chart'>"
            "<rect x='0' y='0' width='600' height='200' fill='#f7fbfd' rx='12' />"
            f"<polyline fill='none' stroke='#185f63' stroke-width='3' points='{' '.join(svg_points)}' />"
            f"{labels}"
            f"<text x='20' y='25' font-size='11'>max {html.escape(str(round(high, 6)))}</text>"
            f"<text x='20' y='175' font-size='11'>min {html.escape(str(round(low, 6)))}</text>"
            "</svg>"
        )

    def _scheduler_schedules(self) -> List[Dict[str, object]]:
        try:
            payload = self.scheduler_runner.read_schedules()
        except Exception:
            return []
        return list(payload.get("schedules", []) or [])

    def _due_schedules(self, schedules: List[Dict[str, object]]) -> List[Dict[str, object]]:
        now_text = now_shanghai().isoformat()
        rows = []
        for schedule in schedules:
            if not bool(schedule.get("enabled", False)):
                continue
            due_at = str(schedule.get("next_run_at", "") or "")
            if not due_at or due_at <= now_text:
                rows.append(schedule)
        return rows

    def _scheduler_run_rows(self) -> List[Dict[str, object]]:
        try:
            payload = self.scheduler_runner.read_runs()
        except Exception:
            return self._platform_history_rows("scheduler_runs", limit=40)
        rows = list(payload.get("runs", []) or [])
        rows.sort(key=lambda item: str(item.get("started_at", "")), reverse=True)
        return rows[:40]

    def _default_page_date(self, page: str) -> str:
        if page == "reports":
            return self._latest_report_date() or self._latest_platform_dataset_date(["research_reports"], require_rows=True) or self._fallback_selected_date()
        if page == "quality":
            return (
                self._latest_platform_dataset_date(["quality_diagnostics"], require_rows=True)
                or self._latest_platform_dataset_date(["source_health", "run_health"], require_rows=False)
                or self._fallback_selected_date()
            )
        if page == "strategies":
            return (
                self._latest_platform_dataset_date(
                    [
                        "backtest_equity_curves",
                        "portfolio_allocations",
                        "risk_metrics",
                        "algorithm_outputs",
                        "strategy_backtests",
                        "paper_portfolios",
                        "factor_signals",
                        "research_metrics",
                    ],
                    require_rows=True,
                )
                or self._latest_platform_dataset_date(["daily_ohlcv"], require_rows=False)
                or self._fallback_selected_date()
            )
        return self._fallback_selected_date()

    def _fallback_selected_date(self) -> str:
        latest_success = ""
        if hasattr(self.checkpoints, "get_last_fully_successful_trade_date"):
            latest_success = self.checkpoints.get_last_fully_successful_trade_date() or ""
        return latest_success or self.checkpoints.get_last_successful_trade_date() or now_shanghai().date().isoformat()

    def _latest_report_date(self) -> str:
        if not self.reports_dir.exists():
            return ""
        dates = []
        for child in self.reports_dir.iterdir():
            if not child.is_dir():
                continue
            if not any((child / file_name).exists() for file_name in ALLOWED_REPORT_FILES):
                continue
            try:
                dates.append(parse_trade_date(child.name).isoformat())
            except Exception:
                continue
        return max(dates) if dates else ""

    def _latest_platform_dataset_date(self, dataset_names: List[str], *, require_rows: bool) -> str:
        dates = []
        for dataset_name in dataset_names:
            dataset_dir = self.project_root / "data" / "normalized" / "platform" / dataset_name
            if not dataset_dir.exists():
                continue
            for csv_path in dataset_dir.glob("*.csv"):
                try:
                    trade_date = parse_trade_date(csv_path.stem).isoformat()
                except Exception:
                    continue
                if require_rows and not any(True for _row in iter_csv_rows(csv_path)):
                    continue
                dates.append(trade_date)
        return max(dates) if dates else ""

    def _report_rows(self) -> List[Dict[str, object]]:
        rows = self._platform_history_rows("research_reports", limit=80)
        file_rows = []
        reports_root = self.reports_dir
        if reports_root.exists():
            for path in sorted(reports_root.glob("*/*"), reverse=True):
                if path.suffix.lower() not in {".md", ".html"}:
                    continue
                file_rows.append(
                    {
                        "trade_date": path.parent.name,
                        "file_name": path.name,
                        "file_path": self._relative_display_path(path),
                        "report_id": "",
                        "status": "",
                        "severity": "",
                        "summary": "",
                    }
                )
        return rows + file_rows[:40]

    @staticmethod
    def _render_research_metric_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('dataset', '')))}</code><br>{html.escape(str(item.get('asset_family', '')))}</td>"
            f"<td>{html.escape(str(item.get('metric_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('metric_value', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_factor_signal_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('symbol_or_contract', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('factor_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('factor_value', '')))}</td>"
            f"<td>{html.escape(str(item.get('signal_direction', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_strategy_backtest_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('strategy_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('portfolio_value', '')))}</td>"
            f"<td>{html.escape(str(item.get('daily_return', '')))}</td>"
            f"<td>{html.escape(str(item.get('cumulative_return', '')))}</td>"
            f"<td>{html.escape(str(item.get('drawdown', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_paper_portfolio_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('strategy_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('equity', '')))}</td>"
            f"<td>{html.escape(str(item.get('cash', '')))}</td>"
            f"<td>{html.escape(str(item.get('position_count', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_algorithm_output_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('template_name', '')))}<br><code>{html.escape(str(item.get('category', '')))}</code></td>"
            f"<td><code>{html.escape(str(item.get('dataset', '')))}</code><br>{html.escape(str(item.get('symbol_or_contract', '')))}</td>"
            f"<td>{html.escape(str(item.get('metric_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('metric_value', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_option_analytics_row(item: Dict[str, object]) -> str:
        greeks = f"Δ={item.get('delta', '')} Γ={item.get('gamma', '')} V={item.get('vega', '')} Θ={item.get('theta', '')}"
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('model_name', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('symbol_or_contract', '')))}</code></td>"
            f"<td>price={html.escape(str(item.get('model_price', '')))}<br>iv={html.escape(str(item.get('implied_volatility', '')))}</td>"
            f"<td>{html.escape(greeks)}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_bond_analytics_row(item: Dict[str, object]) -> str:
        risk_text = f"duration={item.get('duration', '')} convexity={item.get('convexity', '')}"
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('model_name', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('symbol_or_contract', '')))}</code></td>"
            f"<td>ytm={html.escape(str(item.get('ytm', '')))}</td>"
            f"<td>{html.escape(risk_text)}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_curve_analytics_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('model_name', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('curve_name', '')))}</code></td>"
            f"<td>slope={html.escape(str(item.get('slope', '')))}</td>"
            f"<td>{html.escape(str(item.get('tenor_short', '')))} / {html.escape(str(item.get('tenor_long', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_risk_metric_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('template_name', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('portfolio_id', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('metric_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('metric_value', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_portfolio_allocation_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('template_name', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('portfolio_id', '')))}</code></td>"
            f"<td><code>{html.escape(str(item.get('symbol_or_contract', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('weight', '')))}</td>"
            f"<td>{html.escape(str(item.get('notional', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_backtest_equity_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('strategy_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('portfolio_value', '')))}</td>"
            f"<td>{html.escape(str(item.get('daily_return', '')))}</td>"
            f"<td>{html.escape(str(item.get('cumulative_return', '')))}</td>"
            f"<td>{html.escape(str(item.get('drawdown', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_strategy_comparison_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('strategy_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('benchmark_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('metric_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('strategy_value', '')))}</td>"
            f"<td>{html.escape(str(item.get('benchmark_value', '')))}</td>"
            f"<td>{html.escape(str(item.get('difference', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_quality_diagnostic_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('diagnostic_type', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('dataset', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('severity', '')))}</td>"
            f"<td>{html.escape(str(item.get('recommendation', '') or item.get('message', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _quality_grade(value: object) -> str:
        try:
            score = float(value)
        except (TypeError, ValueError):
            return "unknown"
        if score >= 90:
            return "A"
        if score >= 75:
            return "B"
        if score >= 60:
            return "C"
        return "D"

    @staticmethod
    def _render_dataset_quality_score_row(item: Dict[str, object]) -> str:
        score = item.get("quality_score", "")
        details = (
            f"complete={item.get('completeness_score', '')} "
            f"fresh={item.get('freshness_score', '')} "
            f"source={item.get('source_health_score', '')}"
        )
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('dataset', '')))}</code><br>{html.escape(str(item.get('asset_family', '')))}</td>"
            f"<td>{html.escape(str(score))}</td>"
            f"<td>{html.escape(DashboardApp._quality_grade(score))}</td>"
            f"<td>{html.escape(details)}</td>"
            f"<td>{html.escape(str(item.get('anomaly_score', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_anomaly_event_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('dataset', '')))}</code><br>{html.escape(str(item.get('source_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('event_type', '')))}</td>"
            f"<td>{html.escape(str(item.get('severity', '')))}</td>"
            f"<td>{html.escape(str(item.get('asset_family', '')))}</td>"
            f"<td>{html.escape(str(item.get('metric_name', '')))}={html.escape(str(item.get('metric_value', '')))}</td>"
            f"<td>{html.escape(str(item.get('threshold', '')))}</td>"
            f"<td>{html.escape(str(item.get('message', '') or item.get('recommendation', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_backtest_input_quality_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('dataset', '')))}</code><br>{html.escape(str(item.get('asset_family', '')))}</td>"
            f"<td>{html.escape(str(item.get('strategy_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('severity', '')))} / {html.escape(str(item.get('issue_type', '')))}</td>"
            f"<td>{html.escape(str(item.get('metric_name', '')))}={html.escape(str(item.get('metric_value', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('symbol_or_contract', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('message', '') or item.get('recommendation', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_ml_model_run_row(item: Dict[str, object]) -> str:
        features = str(item.get("feature_fields", ""))
        if len(features) > 90:
            features = features[:87] + "..."
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('template_name', '')))}<br><code>{html.escape(str(item.get('run_id', '')))}</code></td>"
            f"<td><code>{html.escape(str(item.get('dataset', '')))}</code><br>{html.escape(str(item.get('asset_family', '')))}</td>"
            f"<td>target={html.escape(str(item.get('target_field', '')))}<br>{html.escape(features)}</td>"
            f"<td>{html.escape(str(item.get('score_metric', '')))}={html.escape(str(item.get('score_value', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('best_params', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_ml_feature_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('template_name', '')))}<br><code>{html.escape(str(item.get('run_id', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('feature_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('importance_value', '')))}</td>"
            f"<td>{html.escape(str(item.get('rank', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_model_diagnostic_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('template_name', '')))}<br><code>{html.escape(str(item.get('run_id', '')))}</code></td>"
            f"<td><code>{html.escape(str(item.get('dataset', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('diagnostic_type', '')))}</td>"
            f"<td>{html.escape(str(item.get('metric_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('metric_value', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_factor_performance_row(item: Dict[str, object]) -> str:
        metric_name = str(item.get("metric_name", ""))
        metric_value = str(item.get("metric_value", ""))
        grouped = f"{metric_name}={metric_value}"
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('factor_name', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('dataset', '')))}</code><br>{html.escape(str(item.get('asset_family', '')))}</td>"
            f"<td>{html.escape(metric_value if metric_name == 'ic' else '')}</td>"
            f"<td>{html.escape(metric_value if metric_name == 'rank_ic' else '')}</td>"
            f"<td>{html.escape(grouped)}<br>n={html.escape(str(item.get('sample_count', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_stress_test_row(item: Dict[str, object]) -> str:
        shock = f"base={item.get('base_value', '')} stressed={item.get('stressed_value', '')}"
        impact = f"{item.get('impact_value', '')} / {item.get('impact_pct', '')}"
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td>{html.escape(str(item.get('template_name', '')))}<br><code>{html.escape(str(item.get('run_id', '')))}</code></td>"
            f"<td><code>{html.escape(str(item.get('dataset', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('scenario_name', '')))}<br>{html.escape(str(item.get('metric_name', '')))}</td>"
            f"<td>{html.escape(shock)}</td>"
            f"<td>{html.escape(impact)}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('reason', '')))}</td>"
            "</tr>"
        )

    @staticmethod
    def _render_experiment_run_row(item: Dict[str, object]) -> str:
        params = str(item.get("parameters", ""))
        if len(params) > 100:
            params = params[:97] + "..."
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('run_id', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('experiment_type', '')))}</td>"
            f"<td>{html.escape(str(item.get('template_name', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('dataset', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('artifact_count', '')))}</td>"
            f"<td><code>{html.escape(params)}</code></td>"
            "</tr>"
        )

    @staticmethod
    def _render_report_artifact_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('report_id', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('title', '')))}<br><code>{html.escape(str(item.get('artifact_id', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('artifact_type', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('path', '')))}</code></td>"
            "</tr>"
        )

    @staticmethod
    def _render_artifact_manifest_row(item: Dict[str, object]) -> str:
        sources = str(item.get("source_datasets", ""))
        if len(sources) > 80:
            sources = sources[:77] + "..."
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('run_id', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('title', '')))}<br><code>{html.escape(str(item.get('artifact_id', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('artifact_type', '')))}</td>"
            f"<td>{html.escape(sources)}</td>"
            f"<td><code>{html.escape(str(item.get('checksum', '')))}</code></td>"
            f"<td><code>{html.escape(str(item.get('path', '')))}</code></td>"
            "</tr>"
        )

    def _render_schedule_row(self, item: Dict[str, object]) -> str:
        schedule_id = str(item.get("schedule_id", ""))
        enabled = bool(item.get("enabled", False))
        toggle_label = "停用" if enabled else "启用"
        toggle_value = "false" if enabled else "true"
        return (
            "<tr>"
            f"<td><strong>{html.escape(str(item.get('task_name', '')))}</strong><br><code>{html.escape(schedule_id)}</code></td>"
            f"<td>{html.escape(str(item.get('action_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('cadence', '')))}</td>"
            f"<td>{html.escape(str(enabled).lower())}</td>"
            f"<td>{html.escape(str(item.get('next_run_at', '')))}</td>"
            "<td>"
            "<form method='post' action='/run' style='display:inline'>"
            "<input type='hidden' name='action_name' value='scheduler_toggle' />"
            "<input type='hidden' name='return_path' value='/scheduler' />"
            f"<input type='hidden' name='schedule_id' value='{html.escape(schedule_id)}' />"
            f"<input type='hidden' name='enabled' value='{toggle_value}' />"
            f"<button type='submit'>{toggle_label}</button>"
            "</form> "
            "<form method='post' action='/run' style='display:inline'>"
            "<input type='hidden' name='action_name' value='scheduler_run_one' />"
            "<input type='hidden' name='return_path' value='/scheduler' />"
            f"<input type='hidden' name='schedule_id' value='{html.escape(schedule_id)}' />"
            "<button type='submit'>手动运行</button>"
            "</form>"
            "</td>"
            "</tr>"
        )

    @staticmethod
    def _render_scheduler_run_row(item: Dict[str, object]) -> str:
        return (
            "<tr>"
            f"<td>{html.escape(str(item.get('trade_date', '')))}</td>"
            f"<td><strong>{html.escape(str(item.get('task_name', '')))}</strong><br><code>{html.escape(str(item.get('schedule_id', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('engineering_status', '')))}</td>"
            f"<td>{html.escape(str(item.get('started_at', '')))}<br>{html.escape(str(item.get('finished_at', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('result_summary', '') or item.get('message', '')))}</code></td>"
            "</tr>"
        )

    def _render_report_row(self, item: Dict[str, object]) -> str:
        if item.get("file_name"):
            trade_date = str(item.get("trade_date", ""))
            file_name = str(item.get("file_name", ""))
            href = "/reports/file?" + urlencode({"date": trade_date, "file": file_name})
            return (
                "<tr>"
                f"<td>{html.escape(trade_date)}</td>"
                f"<td><a href='{html.escape(href)}' target='_blank'>{html.escape(file_name)}</a></td>"
                f"<td><code>{html.escape(str(item.get('file_path', '')))}</code></td>"
                "</tr>"
            )
        return ""

    def _render_research_report_dataset_row(self, item: Dict[str, object]) -> str:
        if item.get("file_name"):
            return ""
        trade_date = str(item.get("trade_date", ""))
        markdown_name = Path(str(item.get("markdown_path", ""))).name
        html_name = Path(str(item.get("html_path", ""))).name
        markdown_link = ""
        html_link = ""
        if markdown_name in ALLOWED_REPORT_FILES:
            markdown_link = "/reports/file?" + urlencode({"date": trade_date, "file": markdown_name})
        if html_name in ALLOWED_REPORT_FILES:
            html_link = "/reports/file?" + urlencode({"date": trade_date, "file": html_name})
        link_html = " ".join(
            piece
            for piece in [
                f"<a href='{html.escape(markdown_link)}' target='_blank'>Markdown</a>" if markdown_link else "",
                f"<a href='{html.escape(html_link)}' target='_blank'>HTML</a>" if html_link else "",
            ]
            if piece
        )
        return (
            "<tr>"
            f"<td>{html.escape(trade_date)}</td>"
            f"<td><code>{html.escape(str(item.get('report_id', '')))}</code></td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('severity', '')))}</td>"
            f"<td>{html.escape(str(item.get('summary', '')))}</td>"
            f"<td>{link_html or '-'}<br><code>{html.escape(str(item.get('markdown_path', '')))}<br>{html.escape(str(item.get('html_path', '')))}</code></td>"
            "</tr>"
        )

    def _resolve_pregrab_window(self, params: Dict[str, str]) -> tuple[str, str]:
        preset = str(params.get("pregrab_preset", "latest_3m") or "latest_3m").strip()
        end_text = str(params.get("end_date", "") or "").strip()
        reference_date = parse_trade_date(end_text) if end_text else self.runner.calendar.previous_trading_day("all", now_shanghai().date())
        if preset == "custom":
            start_text = str(params.get("start_date", "") or "").strip()
            if not start_text or not end_text:
                raise ValueError("custom pregrab requires both start_date and end_date")
            return start_text, end_text
        day_count = {
            "latest_7d": 7,
            "latest_1m": 31,
            "latest_3m": 92,
        }.get(preset, 92)
        start_date = reference_date - timedelta(days=day_count - 1)
        return start_date.isoformat(), reference_date.isoformat()

    def _run_pregrab_subprocess(self, *, exchanges: List[str], start_date: str, end_date: str, mode: str) -> Dict[str, object]:
        env = os.environ.copy()
        src_path = str(self.project_root / "src")
        existing_pythonpath = str(env.get("PYTHONPATH", "") or "").strip()
        env["PYTHONPATH"] = src_path if not existing_pythonpath else src_path + os.pathsep + existing_pythonpath
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
            mode,
            "--no-persist",
        ]
        for exchange in exchanges:
            command.extend(["--exchange", exchange])
        temp_base = self.project_root / ".tmp" / "pregrab"
        temp_base.mkdir(parents=True, exist_ok=True)
        tempdir_context = tempfile.TemporaryDirectory(prefix="fw-pregrab-", dir=str(temp_base)) if mode == "trial" else None
        try:
            if tempdir_context is not None:
                temp_root = Path(tempdir_context.name)
                env["FUTURES_WORKFLOW_DATA_DIR"] = str(temp_root / "data")
                env["FUTURES_WORKFLOW_STATE_DIR"] = str(temp_root / "state")
                env["FUTURES_WORKFLOW_DB_DIR"] = str(temp_root / "data" / "db")
                env["FUTURES_WORKFLOW_DUCKDB_PATH"] = str(temp_root / "data" / "db" / "market_data.duckdb")
                env["FUTURES_WORKFLOW_EXPORTS_DIR"] = str(temp_root / "data" / "exports")
            completed = self.subprocess_runner(
                command,
                cwd=str(self.project_root),
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
        finally:
            if tempdir_context is not None:
                tempdir_context.cleanup()
        result["cleanup_status"] = "cleaned" if mode == "trial" else "retained"
        try:
            self.pregrab_state_writer(result, state_path=self.pregrab_state_path)
        except TypeError:
            self.pregrab_state_writer(result)
        return result

    def _run_window_sync_subprocess(
        self,
        *,
        scope: str,
        start_date: str,
        end_date: str,
        families: List[str],
    ) -> Dict[str, object]:
        command_name = {
            "public_assets": "sync-public-assets",
            "public_references": "sync-public-references",
            "public_bonds": "sync-public-bonds",
            "crypto_observation": "sync-crypto-observation",
        }.get(scope)
        if not command_name:
            raise ValueError(f"unsupported window sync scope: {scope}")
        env = os.environ.copy()
        src_path = str(self.project_root / "src")
        existing_pythonpath = str(env.get("PYTHONPATH", "") or "").strip()
        env["PYTHONPATH"] = src_path if not existing_pythonpath else src_path + os.pathsep + existing_pythonpath
        command = [
            sys.executable,
            "-m",
            "futures_workflow",
            command_name,
            "--start",
            start_date,
            "--end",
            end_date,
        ]
        if scope != "crypto_observation":
            for family in families:
                command.extend(["--family", family])
        completed = self.subprocess_runner(
            command,
            cwd=str(self.project_root),
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        stdout = str(getattr(completed, "stdout", "") or "").strip()
        stderr = str(getattr(completed, "stderr", "") or "").strip()
        returncode = int(getattr(completed, "returncode", 0) or 0)
        if returncode != 0:
            raise RuntimeError(stderr or stdout or f"window sync subprocess failed with code {returncode}")
        if not stdout:
            raise RuntimeError("window sync subprocess returned empty stdout")
        return json.loads(stdout)

    def _job_rows(self) -> List[Dict[str, object]]:
        with self.job_lock:
            rows = [dict(item) for item in self.jobs]
        return sorted(rows, key=lambda item: str(item.get("started_at", "")), reverse=True)

    def _start_job(self, *, action: str, params: Dict[str, List[str]]) -> str:
        job_id = f"job-{next(self.job_counter)}"
        flat_params = {}
        for key, values in params.items():
            normalized = [str(value).strip() for value in values if str(value).strip()]
            if not normalized:
                continue
            flat_params[str(key)] = ",".join(normalized)
        job = {
            "job_id": job_id,
            "action": action,
            "label": self._action_label(action),
            "status": "queued",
            "started_at": iso_timestamp(),
            "finished_at": "",
            "params": flat_params,
            "params_text": self._compact_json(flat_params),
            "result_text": "",
        }
        with self.job_lock:
            self.jobs.append(job)
            self.jobs[:] = self.jobs[-30:]
        if self.run_jobs_async:
            thread = threading.Thread(target=self._execute_job, args=(job_id, action, flat_params), daemon=True)
            thread.start()
        else:
            self._execute_job(job_id, action, flat_params)
        return job_id

    def _return_location(self, return_path: str, params: Dict[str, List[str]]) -> str:
        action = self._single_param(params, "action_name")
        query: Dict[str, str] = {}
        if return_path in {"/reports", "/quality", "/data-map", "/lineage", "/knowledge"}:
            date_value = self._single_param(params, "date")
            if date_value:
                query["date"] = date_value
        elif return_path in {"/strategies", "/factor-lab", "/portfolio", "/projects", "/agent"}:
            start_date = self._single_param(params, "start_date")
            end_date = self._single_param(params, "end_date")
            date_value = self._single_param(params, "date") or end_date or start_date
            if date_value:
                query["date"] = date_value
            if start_date:
                query["start_date"] = start_date
            if end_date:
                query["end_date"] = end_date
            dataset = self._single_param(params, "dataset")
            if dataset:
                query["dataset"] = dataset
        if action == "scheduler_run_one":
            schedule_id = self._single_param(params, "schedule_id")
            if schedule_id:
                query["schedule_id"] = schedule_id
        return return_path + (("?" + urlencode(query)) if query else "")

    def _execute_job(self, job_id: str, action: str, params: Dict[str, str]) -> None:
        self._update_job(job_id, status="running")
        try:
            result = self._run_control_action(action, params)
            self._update_job(
                job_id,
                status=str((result or {}).get("status", "") or "success"),
                finished_at=iso_timestamp(),
                result_text=self._summarize_job_result(result),
            )
        except Exception as exc:
            self._update_job(
                job_id,
                status="failed",
                finished_at=iso_timestamp(),
                result_text=str(exc),
            )

    def _update_job(self, job_id: str, **updates) -> None:
        with self.job_lock:
            for item in self.jobs:
                if str(item.get("job_id")) == job_id:
                    item.update(updates)
                    break

    def _run_control_action(self, action: str, params: Dict[str, str]) -> Dict[str, object]:
        if action == "fetch_date":
            selection = CrawlSelection(instrument_group=params.get("instrument_group") or "all")
            return self.runner.fetch_date(params.get("run_date") or params.get("date") or "", selection=selection)
        if action == "backfill":
            selection = CrawlSelection(instrument_group=params.get("instrument_group") or "all")
            return self.runner.backfill(params.get("start_date") or "", params.get("end_date") or "", selection=selection)
        if action == "sync_public_assets":
            return self.public_asset_runner.sync(params.get("sync_date") or "latest")
        if action == "sync_public_references":
            return self.public_reference_runner.sync(params.get("sync_date") or "latest")
        if action == "sync_public_bonds":
            return self.public_bond_runner.sync(params.get("sync_date") or "latest")
        if action == "sync_crypto_observation":
            return self.crypto_runner.sync(params.get("sync_date") or "latest")
        if action == "sync_platform_metadata":
            return self.platform_metadata_runner.sync(params.get("sync_date") or "latest")
        if action == "window_sync":
            scope = str(params.get("window_scope", "") or "public_assets")
            families = [piece.strip() for piece in str(params.get("window_families", "") or "").split(",") if piece.strip()]
            return self._run_window_sync_subprocess(
                scope=scope,
                start_date=str(params.get("start_date", "") or ""),
                end_date=str(params.get("end_date", "") or ""),
                families=families,
            )
        if action == "pregrab_window":
            raw_exchanges = [piece.strip().upper() for piece in str(params.get("pregrab_exchange", "") or "").split(",") if piece.strip()]
            exchanges = []
            for exchange in raw_exchanges:
                if exchange not in exchanges:
                    exchanges.append(exchange)
            if not exchanges:
                raise ValueError("pregrab_window requires at least one exchange")
            start_date, end_date = self._resolve_pregrab_window(params)
            return self._run_pregrab_subprocess(
                exchanges=exchanges,
                start_date=start_date,
                end_date=end_date,
                mode=str(params.get("pregrab_mode", "production") or "production"),
            )
        if action == "build_db":
            result = build_duckdb_database()
            result["manifest"] = read_dataset_manifest()
            return result
        if action == "environment_check":
            return self.environment_check_runner(project_root=self.project_root, duckdb_path=self.duckdb_path)
        if action == "full_latest":
            sync_daily = self.runner.sync_daily("latest", selection=CrawlSelection(instrument_group="all"))
            public_assets = self.public_asset_runner.sync("latest")
            public_references = self.public_reference_runner.sync("latest")
            public_bonds = self.public_bond_runner.sync("latest")
            crypto = self.crypto_runner.sync("latest")
            platform = self.platform_metadata_runner.sync("latest")
            build_db = build_duckdb_database()
            build_db["manifest"] = read_dataset_manifest()
            statuses = [
                str(sync_daily.get("status", "")),
                str(public_assets.get("status", "")),
                str(public_references.get("status", "")),
                str(public_bonds.get("status", "")),
                str(crypto.get("status", "")),
                str(platform.get("status", "")),
                str(build_db.get("status", "")),
            ]
            return {
                "status": self._merge_job_statuses(statuses),
                "steps": {
                    "sync_daily": sync_daily.get("status", ""),
                    "sync_public_assets": public_assets.get("status", ""),
                    "sync_public_references": public_references.get("status", ""),
                    "sync_public_bonds": public_bonds.get("status", ""),
                    "sync_crypto_observation": crypto.get("status", ""),
                    "sync_platform_metadata": platform.get("status", ""),
                    "build_db": build_db.get("status", ""),
                },
            }
        if action == "research_run":
            return self.research_runner.run_research(
                date_value=params.get("date") or "latest",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                asset_family=params.get("asset_family") or "",
                dataset=params.get("dataset") or "",
            )
        if action == "factor_run":
            return self.research_runner.run_factors(
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                factor=params.get("factor") or "momentum",
                asset_family=params.get("asset_family") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
            )
        if action == "algorithm_run":
            return self.research_runner.run_algorithm(
                template=params.get("template") or "momentum",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                asset_family=params.get("asset_family") or "",
                params_json=params.get("params") or "{}",
            )
        if action == "risk_run":
            return self.research_runner.run_risk(
                template=params.get("template") or "var_cvar",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                asset_family=params.get("asset_family") or "",
                params_json=params.get("params") or "{}",
            )
        if action == "portfolio_optimize":
            return self.research_runner.optimize_portfolio(
                template=params.get("template") or "risk_parity",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                asset_family=params.get("asset_family") or "",
                params_json=params.get("params") or "{}",
            )
        if action == "backtest_run":
            return self.research_runner.run_backtest(
                strategy=params.get("strategy") or "momentum",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                initial_cash=float(params.get("initial_cash") or 1_000_000.0),
                fee_bps=float(params.get("fee_bps") or 2.0),
                slippage_bps=float(params.get("slippage_bps") or 1.0),
                asset_family=params.get("asset_family") or "",
                params_json=params.get("params") or "{}",
            )
        if action == "ml_run":
            features = [piece.strip() for piece in str(params.get("features", "") or "").split(",") if piece.strip()]
            return self.research_runner.run_ml(
                template=params.get("template") or "linear_regression",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                target=params.get("target") or "",
                features=features,
                asset_family=params.get("asset_family") or "",
                params_json=params.get("params") or "{}",
                tune=str(params.get("tune", "false")).lower() == "true",
            )
        if action == "feature_run":
            return self.research_runner.feature_run(
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                asset_family=params.get("asset_family") or "",
                features=params.get("features") or "",
                mode=params.get("mode") or "incremental",
            )
        if action == "ml_benchmark":
            return self.research_runner.ml_benchmark(
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                target=params.get("target") or "",
                features=params.get("features") or "",
                models=params.get("models") or "",
                params_json=params.get("params") or "{}",
                asset_family=params.get("asset_family") or "",
            )
        if action == "ml_validate":
            return self.research_runner.ml_validate(
                template=params.get("template") or "ridge",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                target=params.get("target") or "",
                features=params.get("features") or "",
                method=params.get("method") or "expanding",
                params_json=params.get("params") or "{}",
                asset_family=params.get("asset_family") or "",
            )
        if action == "factor_experiment":
            return self.research_runner.factor_experiment(
                factor=params.get("factor") or "momentum",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                params_json=params.get("params") or "{}",
                asset_family=params.get("asset_family") or "",
            )
        if action == "parameter_scan":
            return self.research_runner.parameter_scan(
                template=params.get("template") or "momentum",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                grid_json=params.get("grid") or "{}",
                asset_family=params.get("asset_family") or "",
            )
        if action == "strategy_leaderboard":
            return self.research_runner.strategy_leaderboard(
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
            )
        if action == "factor_performance":
            return self.research_runner.factor_performance(
                factor=params.get("factor") or "momentum",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                asset_family=params.get("asset_family") or "",
            )
        if action == "stress_test":
            return self.research_runner.stress_test(
                template=params.get("template") or "equity_down",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                asset_family=params.get("asset_family") or "",
                params_json=params.get("params") or "{}",
            )
        if action == "portfolio_run":
            return self.research_runner.portfolio_run(
                template=params.get("template") or "risk_parity",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                params_json=params.get("params") or "{}",
                asset_family=params.get("asset_family") or "",
            )
        if action == "scenario_sim":
            return self.research_runner.scenario_sim(
                template=params.get("template") or "equity_down",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                params_json=params.get("params") or "{}",
                asset_family=params.get("asset_family") or "",
            )
        if action == "project_create":
            return self.research_runner.project_create(
                name=params.get("name") or "ResearchProject",
                description=params.get("description") or "",
                date_value=params.get("date") or "latest",
            )
        if action == "project_run":
            return self.research_runner.project_run(
                project_id=params.get("project_id") or "",
                template=params.get("template") or "momentum",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                params_json=params.get("params") or "{}",
            )
        if action == "package_export":
            return self.research_runner.package_export(
                run_id=params.get("run_id") or "",
                date_value=params.get("date") or "latest",
            )
        if action == "strategy_backtest":
            return self.research_runner.run_strategy_backtest(
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                strategy=params.get("strategy") or "momentum",
                initial_cash=float(params.get("initial_cash") or 1_000_000.0),
                fee_bps=float(params.get("fee_bps") or 2.0),
                asset_family=params.get("asset_family") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
            )
        if action == "paper_sim":
            return self.research_runner.run_paper_sim(
                date_value=params.get("date") or "latest",
                strategy=params.get("strategy") or "momentum",
                initial_cash=float(params.get("initial_cash") or 1_000_000.0),
                asset_family=params.get("asset_family") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
            )
        if action == "quality_diagnose":
            return self.research_runner.quality_diagnose(date_value=params.get("date") or "latest")
        if action == "quality_score":
            return self.research_runner.quality_score(date_value=params.get("date") or "latest")
        if action == "inventory_build":
            return self.research_runner.inventory_build(date_value=params.get("date") or "latest")
        if action == "lineage_build":
            return self.research_runner.lineage_build(date_value=params.get("date") or "latest")
        if action == "sla_check":
            return self.research_runner.sla_check(date_value=params.get("date") or "latest")
        if action == "knowledge_build":
            return self.research_runner.knowledge_build(date_value=params.get("date") or "latest")
        if action == "agent_plan":
            return self.agent_runner.agent_plan(
                goal=params.get("goal") or "",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                dataset=params.get("dataset") or "daily_ohlcv",
                asset_family=params.get("asset_family") or "",
                mode=params.get("mode") or "research",
                report_type=params.get("report_type") or "comprehensive",
            )
        if action == "agent_run":
            return self.agent_runner.agent_run(task_id=params.get("task_id") or "")
        if action == "quality_gate":
            return self.agent_runner.quality_gate(
                dataset=params.get("dataset") or "daily_ohlcv",
                start_date=params.get("start_date") or "",
                end_date=params.get("end_date") or "",
                asset_family=params.get("asset_family") or "",
            )
        if action == "plugin_list":
            return self.agent_runner.plugin_list(date_value=params.get("date") or "latest")
        if action == "scheduler_tick":
            return self.scheduler_runner.tick()
        if action == "scheduler_toggle":
            return self.scheduler_runner.set_enabled(
                schedule_id=params.get("schedule_id") or "",
                enabled=str(params.get("enabled", "")).lower() == "true",
            )
        if action == "scheduler_run_one":
            return self.scheduler_runner.tick(schedule_id=params.get("schedule_id") or "")
        if action == "report_generate":
            return self.research_runner.report_generate(
                date_value=params.get("date") or "latest",
                report_type=params.get("report_type") or "comprehensive",
            )
        raise ValueError(f"unsupported action: {action}")

    @staticmethod
    def _merge_job_statuses(statuses: List[str]) -> str:
        normalized = [str(status or "").strip() for status in statuses if str(status or "").strip()]
        if not normalized:
            return ""
        if all(status == "success" for status in normalized):
            return "success"
        if any(status == "failed" for status in normalized):
            return "failed"
        if any(status == "pending_retry" for status in normalized):
            return "pending_retry"
        if any(status == "partial_success" for status in normalized):
            return "partial_success"
        if any(status == "no_data" for status in normalized):
            return "no_data"
        return normalized[0]

    @staticmethod
    def _compact_json(payload: object) -> str:
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return text if len(text) <= 240 else text[:237] + "..."

    def _summarize_job_result(self, result: Dict[str, object]) -> str:
        if not isinstance(result, dict):
            return str(result)
        summary = {}
        for key in ("trade_date", "status", "run_id", "output_path", "message"):
            value = result.get(key)
            if value is not None and value != "" and value != [] and value != {}:
                summary[key] = value
        if "outputs" in result:
            summary["outputs"] = sorted((result.get("outputs") or {}).keys())
        if "row_counts" in result:
            summary["row_counts"] = result.get("row_counts", {})
        if "steps" in result:
            summary["steps"] = result.get("steps", {})
        if "datasets" in result:
            summary["datasets"] = sorted((result.get("datasets", {}) or {}).keys())
        if "manifest" in result:
            summary["dataset_count"] = len(result.get("manifest", []) or [])
        if "markdown_path" in result:
            summary["markdown_path"] = result.get("markdown_path", "")
        if "html_path" in result:
            summary["html_path"] = result.get("html_path", "")
        if "window_start" in result or "window_end" in result:
            summary["window_start"] = result.get("window_start", "")
            summary["window_end"] = result.get("window_end", "")
        if "mode" in result:
            summary["mode"] = result.get("mode", "")
        if "engineering_status" in result:
            summary["engineering_status"] = result.get("engineering_status", "")
        if "date_counts" in result:
            summary["date_counts"] = result.get("date_counts", {})
        if "cleanup_status" in result:
            summary["cleanup_status"] = result.get("cleanup_status", "")
        if "blocked_issues" in result:
            summary["blocked_issue_count"] = len(result.get("blocked_issues", []) or [])
        if "checks" in result:
            summary["checks"] = result.get("checks", {})
        return self._compact_json(summary or result)

    @staticmethod
    def _action_label(action: str) -> str:
        for action_name, label in GUI_ACTION_DEFINITIONS:
            if action_name == action:
                return label
        return action

    def _respond_html(self, start_response, content: str):
        body = content.encode("utf-8")
        start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))])
        return [body]

    def _respond_json(self, start_response, payload: Dict[str, object]):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        start_response("200 OK", [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body)))])
        return [body]

    def _respond_text(self, start_response, status: str, text: str):
        body = text.encode("utf-8")
        start_response(status, [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))])
        return [body]

    def _respond_bytes(self, start_response, *, status: str, body: bytes, content_type: str):
        start_response(status, [("Content-Type", content_type), ("Content-Length", str(len(body)))])
        return [body]

    def _respond_file(self, start_response, *, file_path: Path, content_type: str, download_name: str):
        body = file_path.read_bytes()
        start_response(
            "200 OK",
            [
                ("Content-Type", content_type),
                ("Content-Length", str(len(body))),
                ("Content-Disposition", f'attachment; filename="{download_name}"'),
            ],
        )
        return [body]

    def _handle_download(self, params: Dict[str, List[str]], start_response):
        dataset_name = self._single_param(params, "dataset")
        output_format = self._single_param(params, "format") or "csv"
        trade_date = self._single_param(params, "date") or None
        filters = self._collect_filter_params(params)
        if not dataset_name:
            return self._respond_text(start_response, "400 Bad Request", "missing dataset")
        if output_format not in {"csv", "json", "parquet"}:
            return self._respond_text(start_response, "400 Bad Request", "unsupported format")
        try:
            result = export_dataset(
                dataset_name=dataset_name,
                output_format=output_format,
                trade_date=trade_date,
                filters=filters,
            )
        except Exception as exc:
            return self._respond_text(start_response, "500 Internal Server Error", str(exc))
        output_path = self.project_root / str(result.get("output_path", ""))
        content_type = {
            "csv": "text/csv; charset=utf-8",
            "json": "application/json; charset=utf-8",
            "parquet": "application/octet-stream",
        }[output_format]
        return self._respond_file(
            start_response,
            file_path=output_path,
            content_type=content_type,
            download_name=output_path.name,
        )

    def _handle_report_file(self, params: Dict[str, List[str]], start_response):
        date_text = self._single_param(params, "date")
        file_name = self._single_param(params, "file")
        if file_name not in ALLOWED_REPORT_FILES:
            return self._respond_text(start_response, "400 Bad Request", "unsupported report file")
        try:
            trade_date = parse_trade_date(date_text).isoformat()
        except Exception:
            return self._respond_text(start_response, "400 Bad Request", "invalid report date")
        file_path = self.reports_dir / trade_date / file_name
        if not file_path.exists() or not file_path.is_file():
            return self._respond_text(start_response, "404 Not Found", "report file not found")
        content_type = "text/html; charset=utf-8" if file_name.endswith(".html") else "text/markdown; charset=utf-8"
        return self._respond_bytes(
            start_response,
            status="200 OK",
            body=file_path.read_bytes(),
            content_type=content_type,
        )

    def _public_asset_cards(self) -> List[Dict[str, object]]:
        summaries = self.public_asset_runner.latest_summaries()
        labels = {
            "equities_spot_snapshot": "A 股快照",
            "bse_equities_spot_snapshot": "北交所股票快照",
            "etf_spot_snapshot": "ETF 快照",
            "lof_spot_snapshot": "LOF 基金快照",
            "open_fund_nav_snapshot": "开放式基金净值快照",
            "money_market_fund_snapshot": "货币基金收益快照",
            "reits_spot_snapshot": "REITs 快照",
            "convertible_bond_spot_snapshot": "可转债快照",
            "sge_spot_daily_quotes": "上金所现货日行情",
            "carbon_market_snapshot": "国内碳市场快照",
        }
        cards = []
        for dataset_name, summary in summaries.items():
            cards.append(
                {
                    "dataset": dataset_name,
                    "label": labels.get(dataset_name, dataset_name),
                    "status": summary.get("status", ""),
                    "row_count": summary.get("row_count", 0),
                    "trade_date": summary.get("trade_date", ""),
                    "output_path": summary.get("output_path", ""),
                }
            )
        return sorted(cards, key=lambda item: item["dataset"])

    def _public_reference_cards(self) -> List[Dict[str, object]]:
        summaries = self.public_reference_runner.latest_summaries()
        labels = {
            "fx_reference_rates": "人民币外汇参考价",
            "rmb_middle_rates": "人民币汇率中间价",
            "fx_spot_quotes": "人民币外汇即期报价",
            "fx_pair_quotes": "外币对即期报价",
            "fx_swap_quotes": "人民币外汇远掉报价",
            "fx_c_swap_curve": "USD/CNY C-Swap 曲线",
            "money_market_rates": "Shibor 参考表",
            "reserve_reference_series": "外汇与黄金储备参考序列",
            "loan_prime_rates": "LPR 参考表",
            "repo_reference_rates": "回购利率参考表",
            "cn_us_treasury_yields": "中美国债收益率",
            "precious_metal_reference_quotes": "上海金银基准价",
        }
        cards = []
        for dataset_name, summary in summaries.items():
            cards.append(
                {
                    "dataset": dataset_name,
                    "label": labels.get(dataset_name, dataset_name),
                    "status": summary.get("status", ""),
                    "row_count": summary.get("row_count", 0),
                    "trade_date": summary.get("trade_date", ""),
                    "output_path": summary.get("output_path", ""),
                }
            )
        return sorted(cards, key=lambda item: item["dataset"])

    def _public_bond_cards(self) -> List[Dict[str, object]]:
        summaries = self.public_bond_runner.latest_summaries()
        labels = {
            "interbank_bond_deal_snapshot": "银行间现券成交",
            "interbank_bond_quote_snapshot": "银行间做市报价",
            "yield_curve_points": "中债收益率曲线",
            "sse_bond_deal_summary": "上交所债券成交概览",
            "sse_bond_cash_summary": "上交所债券现券概览",
        }
        cards = []
        for dataset_name, summary in summaries.items():
            cards.append(
                {
                    "dataset": dataset_name,
                    "label": labels.get(dataset_name, dataset_name),
                    "status": summary.get("status", ""),
                    "row_count": summary.get("row_count", 0),
                    "trade_date": summary.get("trade_date", ""),
                    "output_path": summary.get("output_path", ""),
                }
            )
        return sorted(cards, key=lambda item: item["dataset"])

    def _crypto_observation_cards(self) -> List[Dict[str, object]]:
        if hasattr(self.crypto_runner, "latest_summaries"):
            summaries = self.crypto_runner.latest_summaries()
        else:
            summary = self.crypto_runner.latest_summary() if hasattr(self.crypto_runner, "latest_summary") else {}
            summaries = {str(summary.get("dataset", "crypto_global_snapshot")): summary} if summary else {}
        labels = {
            "crypto_global_snapshot": "全球加密资产观察",
            "crypto_assets": "全球加密资产清单",
            "crypto_bitcoin_holdings_public": "全球公开比特币持仓参考",
            "crypto_cme_bitcoin_report": "CME 比特币公开报告",
            "crypto_daily_quotes": "全球加密日线快照",
            "crypto_derivatives_public": "全球加密衍生品公开参考",
        }
        cards = []
        for dataset_name, summary in summaries.items():
            cards.append(
                {
                    "dataset": dataset_name,
                    "label": labels.get(dataset_name, dataset_name),
                    "status": summary.get("status", ""),
                    "row_count": summary.get("row_count", 0),
                    "trade_date": summary.get("trade_date", ""),
                    "output_path": summary.get("output_path", ""),
                }
            )
        return sorted(cards, key=lambda item: item["dataset"])

    def _platform_metadata_cards(self) -> List[Dict[str, object]]:
        summaries = self.platform_metadata_runner.latest_summaries()
        labels = {
            "instrument_master": "统一 instrument master",
            "bond_master": "统一债券主数据",
            "bond_quotes": "统一债券报价表",
            "fx_quotes": "统一外汇报价表",
            "commodity_spot_quotes": "统一现货与基准价表",
            "crypto_global_quotes": "统一全球加密报价表",
            "daily_ohlcv": "统一日线行情表",
            "fund_nav": "统一基金净值表",
            "reits_quotes": "统一 REITs 行情表",
            "trading_calendar": "统一交易日日历快照",
            "yield_curves": "统一收益率曲线表",
            "asset_coverage": "资产覆盖总览",
            "coverage_history": "资产覆盖历史表",
            "run_health": "统一回归健康表",
            "run_history": "运行历史表",
            "validation_results": "统一 validation 结果",
            "source_health": "统一 source health",
            "source_health_history": "source health 历史表",
            "source_type_overview": "源类型运行总览",
            "issue_category_overview": "问题类别运行总览",
            "research_metrics": "研究指标表",
            "factor_signals": "因子信号表",
            "strategy_backtests": "策略回测表",
            "paper_portfolios": "模拟交易组合表",
            "quality_diagnostics": "质量诊断表",
            "scheduler_runs": "本地调度运行表",
            "research_reports": "研究报告索引表",
            "algorithm_outputs": "统一算法输出表",
            "option_analytics": "期权金融数学分析表",
            "bond_analytics": "债券金融数学分析表",
            "curve_analytics": "收益率曲线分析表",
            "risk_metrics": "组合风险指标表",
            "portfolio_allocations": "组合配置权重表",
            "backtest_equity_curves": "正式回测净值曲线表",
            "backtest_positions": "正式回测持仓明细表",
            "backtest_trades": "正式回测交易明细表",
            "strategy_comparisons": "策略对比指标表",
            "anomaly_events": "异常事件表",
        }
        cards = []
        for dataset_name, summary in summaries.items():
            cards.append(
                {
                    "dataset": dataset_name,
                    "label": labels.get(dataset_name, dataset_name),
                    "status": summary.get("status", ""),
                    "row_count": summary.get("row_count", 0),
                    "trade_date": summary.get("trade_date", ""),
                    "output_path": summary.get("output_path", ""),
                }
            )
        return sorted(cards, key=lambda item: item["dataset"])

    def _duckdb_manifest_cards(self) -> List[Dict[str, object]]:
        try:
            rows = list(self.manifest_reader(self.duckdb_path) or [])
        except Exception:
            return []
        cards = []
        for row in rows:
            dataset = str(row.get("dataset", "")).strip()
            if not dataset:
                continue
            cards.append(
                {
                    "dataset": dataset,
                    "file_count": int(row.get("file_count", 0) or 0),
                    "row_count": int(row.get("row_count", 0) or 0),
                    "built_at": str(row.get("built_at", "")),
                }
            )
        return sorted(cards, key=lambda item: item["dataset"])

    def _regression_smoke_summary(self) -> Dict[str, object]:
        payload = self.regression_state_reader() or {}
        result = payload.get("result", {}) or {}
        audit = result.get("audit", {}) or {}
        return {
            "updated_at": payload.get("updated_at", ""),
            "status": result.get("status", ""),
            "engineering_status": result.get("engineering_status", ""),
            "dates": list(result.get("dates", []) or []),
            "date_statuses": dict(result.get("date_statuses", {}) or {}),
            "window_results": dict(result.get("window_results", {}) or {}),
            "audit": {
                "needs_repair_dates": list(audit.get("needs_repair_dates", []) or []),
                "issue_category_counts": dict(audit.get("issue_category_counts", {}) or {}),
                "blocked_issues": list(audit.get("blocked_issues", []) or []),
            },
            "platform_sync_status": result.get("platform_sync_status", ""),
            "platform_validation_status": result.get("platform_validation_status", ""),
            "build_db_status": result.get("build_db_status", ""),
            "gui_smoke": dict(result.get("gui_smoke", {}) or {}),
            "hydrated_dates": list(result.get("hydrated_dates", []) or []),
        }

    def _source_catalog_cards(self) -> List[Dict[str, object]]:
        cards = []
        for row in build_source_catalog():
            cards.append(
                {
                    "source_id": str(row.get("source_id", "")),
                    "dataset": str(row.get("dataset", "")),
                    "market": str(row.get("market", "")),
                    "exchange": str(row.get("exchange", "")),
                    "source_type": str(row.get("source_type", "")),
                    "priority": int(row.get("priority", 0) or 0),
                    "url": str(row.get("url", "")),
                }
            )
        return sorted(cards, key=lambda item: (item["source_type"], item["dataset"], item["source_id"]))

    @staticmethod
    def _source_type_counts(source_catalog: List[Dict[str, object]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in source_catalog:
            source_type = str(row.get("source_type", "")).strip() or "unknown"
            counts[source_type] = counts.get(source_type, 0) + 1
        return counts

    def _source_health_rows(self) -> List[Dict[str, object]]:
        summaries = self.platform_metadata_runner.latest_summaries()
        summary = summaries.get("source_health", {})
        output_path = str(summary.get("output_path", "")).strip()
        if not output_path:
            return []
        csv_path = self.project_root / output_path
        if not csv_path.exists():
            return []
        rows: List[Dict[str, object]] = []
        for row in iter_csv_rows(csv_path):
            last_status = str(row.get("last_status", "")).strip()
            issue_category = str(row.get("issue_category", "")).strip()
            blocked_reason = str(row.get("blocked_reason", "")).strip()
            if last_status == "success" and issue_category in {"", "healthy"} and not blocked_reason:
                continue
            rows.append(
                {
                    "source_id": str(row.get("source_id", "")),
                    "dataset": str(row.get("dataset", "")),
                    "last_status": last_status,
                    "last_trade_date": str(row.get("last_trade_date", "")),
                    "issue_category": issue_category,
                    "issue_root_cause": str(row.get("issue_root_cause", "")),
                    "is_external_blocker": str(row.get("is_external_blocker", "")),
                    "blocked_reason": blocked_reason,
                    "message": str(row.get("message", "")),
                }
            )
        return rows[:25]

    def _source_type_overview_rows(self) -> List[Dict[str, object]]:
        summaries = self.platform_metadata_runner.latest_summaries()
        summary = summaries.get("source_type_overview", {})
        output_path = str(summary.get("output_path", "")).strip()
        if not output_path:
            return []
        csv_path = self.project_root / output_path
        if not csv_path.exists():
            return []
        rows: List[Dict[str, object]] = []
        for row in iter_csv_rows(csv_path):
            rows.append(
                {
                    "source_type": str(row.get("source_type", "")),
                    "source_count": str(row.get("source_count", "")),
                    "dataset_count": str(row.get("dataset_count", "")),
                    "success_count": str(row.get("success_count", "")),
                    "non_success_count": str(row.get("non_success_count", "")),
                    "blocked_issue_count": str(row.get("blocked_issue_count", "")),
                    "latest_trade_date": str(row.get("latest_trade_date", "")),
                    "status_counts": str(row.get("status_counts", "")),
                }
            )
        return rows

    def _issue_category_overview_rows(self) -> List[Dict[str, object]]:
        summaries = self.platform_metadata_runner.latest_summaries()
        summary = summaries.get("issue_category_overview", {})
        output_path = str(summary.get("output_path", "")).strip()
        if not output_path:
            return []
        csv_path = self.project_root / output_path
        if not csv_path.exists():
            return []
        rows: List[Dict[str, object]] = []
        for row in iter_csv_rows(csv_path):
            rows.append(
                {
                    "issue_category": str(row.get("issue_category", "")),
                    "source_count": str(row.get("source_count", "")),
                    "dataset_count": str(row.get("dataset_count", "")),
                    "blocked_issue_count": str(row.get("blocked_issue_count", "")),
                    "latest_trade_date": str(row.get("latest_trade_date", "")),
                    "status_counts": str(row.get("status_counts", "")),
                    "source_type_counts": str(row.get("source_type_counts", "")),
                }
            )
        return rows

    def _asset_coverage_rows(self) -> List[Dict[str, object]]:
        summaries = self.platform_metadata_runner.latest_summaries()
        summary = summaries.get("asset_coverage", {})
        output_path = str(summary.get("output_path", "")).strip()
        if not output_path:
            return []
        csv_path = self.project_root / output_path
        if not csv_path.exists():
            return []
        rows: List[Dict[str, object]] = []
        for row in iter_csv_rows(csv_path):
            rows.append(
                {
                    "asset_family": str(row.get("asset_family", "")),
                    "family_label": str(row.get("family_label", "")),
                    "engineering_status": str(row.get("engineering_status", "")),
                    "runtime_status": str(row.get("runtime_status", "")),
                    "latest_success_trade_date": str(row.get("latest_success_trade_date", "")),
                    "latest_trade_date": str(row.get("latest_trade_date", "")),
                    "coverage_ratio": str(row.get("coverage_ratio", "")),
                    "success_dataset_count": str(row.get("success_dataset_count", "")),
                    "non_success_dataset_count": str(row.get("non_success_dataset_count", "")),
                    "external_issue_count": str(row.get("external_issue_count", "")),
                    "internal_issue_count": str(row.get("internal_issue_count", "")),
                    "total_row_count": str(row.get("total_row_count", "")),
                    "missing_datasets": str(row.get("missing_datasets", "")),
                }
            )
        return rows

    @staticmethod
    def _asset_coverage_status_counts(rows: List[Dict[str, object]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in rows:
            status = str(row.get("runtime_status", "")).strip() or "unknown"
            counts[status] = counts.get(status, 0) + 1
        return counts

    @staticmethod
    def _asset_coverage_engineering_counts(rows: List[Dict[str, object]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in rows:
            status = str(row.get("engineering_status", "")).strip() or "unknown"
            counts[status] = counts.get(status, 0) + 1
        return counts

    def _preview_options(
        self,
        *,
        dataset_cards: List[Dict[str, object]],
        public_assets: List[Dict[str, object]],
        public_bonds: List[Dict[str, object]],
        public_references: List[Dict[str, object]],
        crypto_observation: List[Dict[str, object]],
        platform_metadata: List[Dict[str, object]],
    ) -> List[Dict[str, object]]:
        options: List[Dict[str, object]] = []
        for card in dataset_cards:
            if card.get("path"):
                options.append(
                    {
                        "dataset": card["dataset"],
                        "label": card["label"],
                        "path": card["path"],
                        "trade_date": str(card.get("trade_date", "")),
                    }
                )
        for group_label, cards in (
            ("公开资产", public_assets),
            ("公开债券", public_bonds),
            ("公开参考", public_references),
        ):
            for card in cards:
                output_path = str(card.get("output_path", "")).strip()
                if not output_path:
                    continue
                options.append(
                    {
                        "dataset": str(card["dataset"]),
                        "label": f"{group_label} / {card['label']}",
                        "path": output_path,
                        "trade_date": str(card.get("trade_date", "")),
                    }
                )
        for card in crypto_observation:
            output_path = str(card.get("output_path", "")).strip()
            if output_path:
                options.append(
                    {
                        "dataset": str(card["dataset"]),
                        "label": f"全球观察 / {card['label']}",
                        "path": output_path,
                        "trade_date": str(card.get("trade_date", "")),
                    }
                )
        for card in platform_metadata:
            output_path = str(card.get("output_path", "")).strip()
            if output_path:
                options.append(
                    {
                        "dataset": str(card["dataset"]),
                        "label": f"平台元数据 / {card['label']}",
                        "path": output_path,
                        "trade_date": str(card.get("trade_date", "")),
                    }
                )
        return options

    @staticmethod
    def _default_preview_dataset(preview_options: List[Dict[str, object]]) -> str:
        if not preview_options:
            return ""
        return str(preview_options[0]["dataset"])

    @staticmethod
    def _render_select_options(options: List[object], selected_value: str) -> str:
        rendered = []
        for item in options:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                value = str(item[0])
                label = str(item[1])
            else:
                value = str(item)
                label = value
            selected = " selected" if value == selected_value else ""
            rendered.append(f'<option value="{html.escape(value)}"{selected}>{html.escape(label)}</option>')
        return "".join(rendered)

    @staticmethod
    def _single_param(params: Dict[str, List[str]], name: str) -> str:
        values = params.get(name, [])
        return values[0] if values else ""

    @staticmethod
    def _parse_post_params(environ) -> Dict[str, List[str]]:
        try:
            content_length = int(environ.get("CONTENT_LENGTH", "0") or "0")
        except ValueError:
            content_length = 0
        body = environ.get("wsgi.input").read(content_length) if content_length > 0 else b""
        return parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=False)

    @staticmethod
    def _collect_filter_params(params: Dict[str, List[str]]) -> Dict[str, str]:
        filters: Dict[str, str] = {}
        for field, _label in GUI_FILTER_FIELDS:
            value = DashboardApp._single_param(params, field).strip()
            if value:
                filters[field] = value
        return filters

    @staticmethod
    def _row_matches_filters(row: Dict[str, str], filters: Dict[str, str]) -> bool:
        for field, expected in filters.items():
            if field not in row:
                continue
            if str(row.get(field, "")).strip() != expected:
                return False
        return True

    def _relative_display_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.project_root))
        except ValueError:
            return str(path)

    @staticmethod
    def _int_param(params: Dict[str, List[str]], name: str, default: int) -> int:
        try:
            return max(1, int(DashboardApp._single_param(params, name) or default))
        except ValueError:
            return default


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="启动本地多资产数据平台 GUI")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=8765, help="监听端口，默认 8765")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    app = DashboardApp()
    with make_server(args.host, args.port, app) as server:
        print(f"GUI 已启动: http://{args.host}:{args.port}")
        server.serve_forever()
    return 0
