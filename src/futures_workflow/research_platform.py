import hashlib
import html
import json
import math
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .config import (
    DUCKDB_PATH,
    NORMALIZED_ROOT,
    PLATFORM_NORMALIZED_DIR,
    PROJECT_ROOT,
    REPORTS_DIR,
    SCHEDULER_RUNS_STATE_PATH,
    SCHEDULES_STATE_PATH,
)
from .constants import (
    ALGORITHM_OUTPUTS_DATASET,
    ALGORITHM_OUTPUTS_STANDARD_FIELDS,
    ANOMALY_EVENTS_DATASET,
    ANOMALY_EVENTS_STANDARD_FIELDS,
    ARTIFACT_MANIFEST_DATASET,
    ARTIFACT_MANIFEST_STANDARD_FIELDS,
    BACKTEST_INPUT_QUALITY_DATASET,
    BACKTEST_INPUT_QUALITY_STANDARD_FIELDS,
    BACKTEST_EQUITY_CURVES_DATASET,
    BACKTEST_EQUITY_CURVES_STANDARD_FIELDS,
    BACKTEST_POSITIONS_DATASET,
    BACKTEST_POSITIONS_STANDARD_FIELDS,
    BACKTEST_TRADES_DATASET,
    BACKTEST_TRADES_STANDARD_FIELDS,
    BOND_ANALYTICS_DATASET,
    BOND_ANALYTICS_STANDARD_FIELDS,
    CURVE_ANALYTICS_DATASET,
    CURVE_ANALYTICS_STANDARD_FIELDS,
    DAILY_OHLCV_DATASET,
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
    FUND_NAV_DATASET,
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
    OPTION_ANALYTICS_DATASET,
    OPTION_ANALYTICS_STANDARD_FIELDS,
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
    QUALITY_DIAGNOSTICS_DATASET,
    QUALITY_DIAGNOSTICS_STANDARD_FIELDS,
    RESEARCH_METRICS_DATASET,
    RESEARCH_METRICS_STANDARD_FIELDS,
    RESEARCH_PROJECTS_DATASET,
    RESEARCH_PROJECTS_STANDARD_FIELDS,
    RESEARCH_REPORTS_DATASET,
    RESEARCH_REPORTS_STANDARD_FIELDS,
    RECOMMENDATION_ITEMS_DATASET,
    RECOMMENDATION_ITEMS_STANDARD_FIELDS,
    REPRODUCIBLE_PACKAGES_DATASET,
    REPRODUCIBLE_PACKAGES_STANDARD_FIELDS,
    REPORT_ARTIFACTS_DATASET,
    REPORT_ARTIFACTS_STANDARD_FIELDS,
    REPORT_INSIGHTS_DATASET,
    REPORT_INSIGHTS_STANDARD_FIELDS,
    RISK_METRICS_DATASET,
    RISK_METRICS_STANDARD_FIELDS,
    SCHEDULER_RUNS_DATASET,
    SCHEDULER_RUNS_STANDARD_FIELDS,
    SCENARIO_SIMULATIONS_DATASET,
    SCENARIO_SIMULATIONS_STANDARD_FIELDS,
    SLA_VIOLATIONS_DATASET,
    SLA_VIOLATIONS_STANDARD_FIELDS,
    STRATEGY_BACKTESTS_DATASET,
    STRATEGY_BACKTESTS_STANDARD_FIELDS,
    STRATEGY_COMPARISONS_DATASET,
    STRATEGY_COMPARISONS_STANDARD_FIELDS,
    STRATEGY_LEADERBOARD_DATASET,
    STRATEGY_LEADERBOARD_STANDARD_FIELDS,
    STRESS_TEST_RESULTS_DATASET,
    STRESS_TEST_RESULTS_STANDARD_FIELDS,
    YIELD_CURVES_PLATFORM_DATASET,
)
from .normalize.csv_utils import write_dict_rows_csv
from .source_catalog import build_source_catalog
from .storage import DATASET_GLOBS
from .utils import ensure_directory, iso_timestamp, iter_csv_rows, now_shanghai, parse_trade_date, relative_to_project, safe_json_dumps


PARSER_VERSION = "research_platform_v1"
RESEARCH_SOURCE_DATASETS = [
    DAILY_OHLCV_DATASET,
    FUND_NAV_DATASET,
    "reits_quotes",
    YIELD_CURVES_PLATFORM_DATASET,
    "fx_quotes",
    "bond_quotes",
    "commodity_spot_quotes",
    "crypto_global_quotes",
]
PRICE_FIELDS = ("close", "price", "value", "yield", "nav", "mid", "price_usd")
VOLUME_FIELDS = ("volume", "total_volume", "amount")


@dataclass(frozen=True)
class AlgorithmTemplate:
    name: str
    label: str
    category: str
    description: str


class AlgorithmRegistry:
    """Small registry for safe, built-in research templates.

    GUI and CLI only expose templates registered here. This keeps the project
    extensible without opening arbitrary Python execution from the browser.
    """

    _TEMPLATES = {
        "momentum": AlgorithmTemplate("momentum", "动量因子", "factor", "窗口首尾价格收益率。"),
        "mean_reversion": AlgorithmTemplate("mean_reversion", "反转因子", "factor", "价格相对均值偏离的反向信号。"),
        "volatility_filter": AlgorithmTemplate("volatility_filter", "波动率过滤", "factor", "用收益率波动过滤高噪声标的。"),
        "volume_turnover": AlgorithmTemplate("volume_turnover", "成交量/换手因子", "factor", "成交量或成交额窗口变化。"),
        "term_structure_slope": AlgorithmTemplate("term_structure_slope", "期限结构斜率", "factor", "曲线长短端斜率或期限利差。"),
        "basis_spread": AlgorithmTemplate("basis_spread", "基差/价差", "factor", "可用结算价或前收价近似计算价差。"),
        "cross_asset_rank": AlgorithmTemplate("cross_asset_rank", "多资产横截面排序", "factor", "按窗口收益率进行横截面排序。"),
        "black_scholes_price": AlgorithmTemplate("black_scholes_price", "Black-Scholes 定价", "option_math", "欧式期权 BS 理论价格。"),
        "black_scholes_greeks": AlgorithmTemplate("black_scholes_greeks", "Black-Scholes 希腊值", "option_math", "Delta/Gamma/Vega/Theta。"),
        "black_scholes_iv": AlgorithmTemplate("black_scholes_iv", "Black-Scholes 隐含波动率", "option_math", "用二分法反解隐含波动率。"),
        "binomial_option_price": AlgorithmTemplate("binomial_option_price", "二叉树期权定价", "option_math", "CRR 二叉树欧式/美式期权定价。"),
        "bond_ytm": AlgorithmTemplate("bond_ytm", "债券到期收益率", "bond_math", "固定息票债券 YTM。"),
        "bond_duration_convexity": AlgorithmTemplate("bond_duration_convexity", "债券久期与凸性", "bond_math", "Macaulay 久期、修正久期与凸性。"),
        "yield_curve_slope": AlgorithmTemplate("yield_curve_slope", "收益率曲线斜率", "curve_math", "长端收益率减短端收益率。"),
        "futures_calendar_spread": AlgorithmTemplate("futures_calendar_spread", "期货跨期价差", "futures_math", "同品种近远月价格差。"),
        "mean_variance": AlgorithmTemplate("mean_variance", "均值-方差配置", "portfolio", "用收益/波动的简化得分配置权重。"),
        "risk_parity": AlgorithmTemplate("risk_parity", "风险平价", "portfolio", "用逆波动率近似配置权重。"),
        "volatility_target": AlgorithmTemplate("volatility_target", "波动率目标", "risk", "估算组合波动和目标杠杆。"),
        "max_drawdown_control": AlgorithmTemplate("max_drawdown_control", "最大回撤控制", "risk", "估算最大回撤与风控状态。"),
        "var_cvar": AlgorithmTemplate("var_cvar", "VaR / CVaR", "risk", "基于历史收益分布估算尾部风险。"),
        "correlation_matrix": AlgorithmTemplate("correlation_matrix", "相关性矩阵", "risk", "估算标的之间收益相关性。"),
        "position_limits": AlgorithmTemplate("position_limits", "仓位约束检查", "risk", "检查配置权重是否超过上限。"),
        "linear_regression": AlgorithmTemplate("linear_regression", "线性回归", "ml", "用数值特征预测目标字段。"),
        "ridge": AlgorithmTemplate("ridge", "Ridge 回归", "ml", "带 L2 正则的线性模型。"),
        "lasso": AlgorithmTemplate("lasso", "Lasso 回归", "ml", "带 L1 正则的线性模型。"),
        "pca": AlgorithmTemplate("pca", "PCA 降维", "ml", "解释主成分方差。"),
        "kmeans": AlgorithmTemplate("kmeans", "KMeans 聚类", "ml", "按数值特征聚类。"),
        "random_forest": AlgorithmTemplate("random_forest", "随机森林", "ml", "非线性树模型回归。"),
        "xgboost": AlgorithmTemplate("xgboost", "XGBoost", "ml", "可选增强模型，缺依赖时自动降级。"),
        "lightgbm": AlgorithmTemplate("lightgbm", "LightGBM", "ml", "LightGBM 或本地兼容梯度提升实现。"),
        "catboost": AlgorithmTemplate("catboost", "CatBoost", "ml", "CatBoost 或本地兼容树模型实现。"),
        "svm": AlgorithmTemplate("svm", "SVM", "ml", "支持向量机回归/分类研究模板。"),
        "mlp": AlgorithmTemplate("mlp", "MLP 神经网络", "ml", "小型多层感知机研究模板。"),
        "regime_detection": AlgorithmTemplate("regime_detection", "市场状态识别", "ml", "用收益与波动规则/聚类识别状态。"),
        "equity_down": AlgorithmTemplate("equity_down", "权益下跌压力", "stress", "组合权益资产统一下跌。"),
        "volatility_up": AlgorithmTemplate("volatility_up", "波动率放大压力", "stress", "用波动率放大估计风险冲击。"),
        "correlation_up": AlgorithmTemplate("correlation_up", "相关性上升压力", "stress", "估算相关性上升后的分散化损失。"),
        "rate_shift": AlgorithmTemplate("rate_shift", "利率平移压力", "stress", "收益率曲线平移压力。"),
        "fx_shock": AlgorithmTemplate("fx_shock", "汇率冲击压力", "stress", "外汇类报价冲击。"),
        "crypto_shock": AlgorithmTemplate("crypto_shock", "Crypto 极端波动", "stress", "crypto 观察资产极端波动压力。"),
    }

    @classmethod
    def get(cls, name: str) -> AlgorithmTemplate:
        key = str(name or "").strip() or "momentum"
        if key not in cls._TEMPLATES:
            raise ValueError(f"unsupported algorithm template: {key}")
        return cls._TEMPLATES[key]

    @classmethod
    def options(cls, *, categories: Optional[Iterable[str]] = None) -> List[Tuple[str, str]]:
        allowed = set(categories or [])
        result = []
        for name, template in cls._TEMPLATES.items():
            if allowed and template.category not in allowed:
                continue
            result.append((name, template.label))
        return result


def _sha1_text(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:16]


def _float(value) -> Optional[float]:
    text = str(value or "").replace(",", "").strip()
    if not text:
        return None
    try:
        result = float(text)
    except ValueError:
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def _status_from_rows(rows: Sequence[Dict[str, str]]) -> str:
    return "success" if rows else "no_data"


def _platform_output_path(dataset_name: str, trade_date: str, *, platform_dir: Path) -> Path:
    return platform_dir / dataset_name / f"{trade_date}.csv"


def _write_platform_dataset(
    *,
    dataset_name: str,
    trade_date: str,
    rows: List[Dict[str, str]],
    fieldnames: List[str],
    key_fields: List[str],
    platform_dir: Path = PLATFORM_NORMALIZED_DIR,
    project_root: Path = PROJECT_ROOT,
) -> Dict[str, object]:
    output_path = _platform_output_path(dataset_name, trade_date, platform_dir=platform_dir)
    write_dict_rows_csv(output_path, rows, fieldnames, key_fields)
    return {
        "dataset": dataset_name,
        "trade_date": trade_date,
        "status": _status_from_rows(rows),
        "row_count": len(rows),
        "output_path": relative_to_project(output_path, project_root),
    }


class BacktestEngine:
    """Deterministic local daily backtest engine.

    The engine intentionally stays small and dependency-free. It consumes
    normalized/platform rows only and delegates row shaping to the runner so
    GUI, CLI, DuckDB and reports share the same data contracts.
    """

    def __init__(self, runner: "ResearchPlatformRunner"):
        self.runner = runner

    def run(self, *, dataset_name: str, source_rows: List[Dict[str, str]], strategy: str, initial_cash: float, fee_bps: float, slippage_bps: float, start_date: str, end_date: str, params: Dict[str, object], run_id: str):
        quality_rows = self.runner._backtest_input_quality_rows(
            dataset_name=dataset_name,
            source_rows=source_rows,
            strategy=strategy,
            start_date=start_date,
            end_date=end_date,
            run_id=run_id,
        )
        equity_rows, position_rows, trade_rows, comparison_rows = self.runner._backtest_detail_rows(
            dataset_name=dataset_name,
            source_rows=source_rows,
            strategy=strategy,
            initial_cash=initial_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            start_date=start_date,
            end_date=end_date,
            params=params,
            run_id=run_id,
        )
        return equity_rows, position_rows, trade_rows, comparison_rows, quality_rows


class ResearchPlatformRunner:
    def __init__(
        self,
        *,
        project_root: Path = PROJECT_ROOT,
        normalized_root: Path = NORMALIZED_ROOT,
        platform_dir: Path = PLATFORM_NORMALIZED_DIR,
        reports_dir: Path = REPORTS_DIR,
        duckdb_path: Path = DUCKDB_PATH,
    ):
        self.project_root = project_root
        self.normalized_root = normalized_root
        self.platform_dir = platform_dir
        self.reports_dir = reports_dir
        self.duckdb_path = duckdb_path

    def run_research(
        self,
        *,
        date_value: str = "latest",
        start_date: str = "",
        end_date: str = "",
        asset_family: str = "",
        dataset: str = "",
    ) -> Dict[str, object]:
        start, end = self._resolve_window(date_value=date_value, start_date=start_date, end_date=end_date)
        run_id = self._run_id("research")
        datasets = [dataset] if dataset else list(RESEARCH_SOURCE_DATASETS)
        rows: List[Dict[str, str]] = []
        for dataset_name in datasets:
            source_rows = self._load_rows(dataset_name, start_date=start, end_date=end, asset_family=asset_family)
            rows.extend(
                self._research_metric_rows(
                    dataset_name=dataset_name,
                    source_rows=source_rows,
                    start_date=start,
                    end_date=end,
                    run_id=run_id,
                )
            )
        summary = _write_platform_dataset(
            dataset_name=RESEARCH_METRICS_DATASET,
            trade_date=end,
            rows=rows,
            fieldnames=RESEARCH_METRICS_STANDARD_FIELDS,
            key_fields=["trade_date", "dataset", "asset_family", "metric_name"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": start, "window_end": end, "datasets": {RESEARCH_METRICS_DATASET: summary}}

    def run_factors(
        self,
        *,
        start_date: str,
        end_date: str,
        factor: str = "momentum",
        asset_family: str = "",
        dataset: str = DAILY_OHLCV_DATASET,
    ) -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        run_id = self._run_id("factor")
        source_rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        rows = self._factor_rows(dataset_name=dataset, source_rows=source_rows, factor=factor, run_id=run_id, end_date=end)
        summary = _write_platform_dataset(
            dataset_name=FACTOR_SIGNALS_DATASET,
            trade_date=end,
            rows=rows,
            fieldnames=FACTOR_SIGNALS_STANDARD_FIELDS,
            key_fields=["trade_date", "dataset", "symbol_or_contract", "factor_name"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": start, "window_end": end, "datasets": {FACTOR_SIGNALS_DATASET: summary}}

    def run_strategy_backtest(
        self,
        *,
        start_date: str,
        end_date: str,
        strategy: str = "momentum",
        initial_cash: float = 1_000_000.0,
        fee_bps: float = 2.0,
        asset_family: str = "",
        dataset: str = DAILY_OHLCV_DATASET,
    ) -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        run_id = self._run_id("strategy")
        source_rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        rows = self._strategy_rows(
            dataset_name=dataset,
            source_rows=source_rows,
            strategy=strategy,
            initial_cash=float(initial_cash),
            fee_bps=float(fee_bps),
            start_date=start,
            end_date=end,
            run_id=run_id,
        )
        summary = _write_platform_dataset(
            dataset_name=STRATEGY_BACKTESTS_DATASET,
            trade_date=end,
            rows=rows,
            fieldnames=STRATEGY_BACKTESTS_STANDARD_FIELDS,
            key_fields=["trade_date", "strategy_name", "asset_family", "dataset"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": start, "window_end": end, "datasets": {STRATEGY_BACKTESTS_DATASET: summary}}

    def run_paper_sim(
        self,
        *,
        date_value: str = "latest",
        strategy: str = "momentum",
        initial_cash: float = 1_000_000.0,
        asset_family: str = "",
        dataset: str = DAILY_OHLCV_DATASET,
    ) -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        run_id = self._run_id("paper")
        source_rows = self._load_rows(dataset, start_date=trade_date, end_date=trade_date, asset_family=asset_family)
        rows = self._paper_rows(
            dataset_name=dataset,
            source_rows=source_rows,
            strategy=strategy,
            initial_cash=float(initial_cash),
            trade_date=trade_date,
            run_id=run_id,
        )
        summary = _write_platform_dataset(
            dataset_name=PAPER_PORTFOLIOS_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=PAPER_PORTFOLIOS_STANDARD_FIELDS,
            key_fields=["trade_date", "strategy_name", "portfolio_id"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "trade_date": trade_date, "datasets": {PAPER_PORTFOLIOS_DATASET: summary}}

    def run_algorithm(
        self,
        *,
        template: str,
        start_date: str,
        end_date: str,
        dataset: str = DAILY_OHLCV_DATASET,
        asset_family: str = "",
        params_json: str = "",
    ) -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        params = self._parse_params(params_json)
        run_id = self._run_id("algorithm")
        template_info = AlgorithmRegistry.get(template)
        source_rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        algorithm_rows, extra_rows = self._algorithm_rows(
            template_info=template_info,
            dataset_name=dataset,
            source_rows=source_rows,
            asset_family=asset_family,
            start_date=start,
            end_date=end,
            params=params,
            run_id=run_id,
        )
        summaries = {
            ALGORITHM_OUTPUTS_DATASET: _write_platform_dataset(
                dataset_name=ALGORITHM_OUTPUTS_DATASET,
                trade_date=end,
                rows=self._merge_platform_rows(ALGORITHM_OUTPUTS_DATASET, end, algorithm_rows, ["trade_date", "dataset", "template_name", "symbol_or_contract", "metric_name"]),
                fieldnames=ALGORITHM_OUTPUTS_STANDARD_FIELDS,
                key_fields=["trade_date", "dataset", "template_name", "symbol_or_contract", "metric_name"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            )
        }
        extra_specs = {
            OPTION_ANALYTICS_DATASET: (OPTION_ANALYTICS_STANDARD_FIELDS, ["trade_date", "dataset", "symbol_or_contract", "model_name"]),
            BOND_ANALYTICS_DATASET: (BOND_ANALYTICS_STANDARD_FIELDS, ["trade_date", "dataset", "symbol_or_contract", "model_name"]),
            CURVE_ANALYTICS_DATASET: (CURVE_ANALYTICS_STANDARD_FIELDS, ["trade_date", "dataset", "curve_name", "model_name"]),
        }
        for dataset_name, rows in extra_rows.items():
            fieldnames, key_fields = extra_specs[dataset_name]
            summaries[dataset_name] = _write_platform_dataset(
                dataset_name=dataset_name,
                trade_date=end,
                rows=self._merge_platform_rows(dataset_name, end, rows, key_fields),
                fieldnames=fieldnames,
                key_fields=key_fields,
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            )
        return {"status": self._merge_statuses([item["status"] for item in summaries.values()]), "run_id": run_id, "window_start": start, "window_end": end, "template": template_info.name, "datasets": summaries}

    def run_risk(
        self,
        *,
        template: str,
        start_date: str,
        end_date: str,
        dataset: str = DAILY_OHLCV_DATASET,
        asset_family: str = "",
        params_json: str = "",
    ) -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        params = self._parse_params(params_json)
        run_id = self._run_id("risk")
        template_info = AlgorithmRegistry.get(template)
        source_rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        rows = self._risk_metric_rows(
            template_info=template_info,
            dataset_name=dataset,
            source_rows=source_rows,
            asset_family=asset_family,
            start_date=start,
            end_date=end,
            params=params,
            run_id=run_id,
        )
        summary = _write_platform_dataset(
            dataset_name=RISK_METRICS_DATASET,
            trade_date=end,
            rows=self._merge_platform_rows(RISK_METRICS_DATASET, end, rows, ["trade_date", "dataset", "template_name", "portfolio_id", "metric_name"]),
            fieldnames=RISK_METRICS_STANDARD_FIELDS,
            key_fields=["trade_date", "dataset", "template_name", "portfolio_id", "metric_name"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": start, "window_end": end, "template": template_info.name, "datasets": {RISK_METRICS_DATASET: summary}}

    def optimize_portfolio(
        self,
        *,
        template: str,
        start_date: str,
        end_date: str,
        asset_family: str = "",
        dataset: str = DAILY_OHLCV_DATASET,
        params_json: str = "",
    ) -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        params = self._parse_params(params_json)
        run_id = self._run_id("portfolio")
        template_info = AlgorithmRegistry.get(template)
        source_rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        rows = self._portfolio_allocation_rows(
            template_info=template_info,
            dataset_name=dataset,
            source_rows=source_rows,
            asset_family=asset_family,
            start_date=start,
            end_date=end,
            params=params,
            run_id=run_id,
        )
        summary = _write_platform_dataset(
            dataset_name=PORTFOLIO_ALLOCATIONS_DATASET,
            trade_date=end,
            rows=self._merge_platform_rows(PORTFOLIO_ALLOCATIONS_DATASET, end, rows, ["trade_date", "portfolio_id", "symbol_or_contract"]),
            fieldnames=PORTFOLIO_ALLOCATIONS_STANDARD_FIELDS,
            key_fields=["trade_date", "portfolio_id", "symbol_or_contract"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": start, "window_end": end, "template": template_info.name, "datasets": {PORTFOLIO_ALLOCATIONS_DATASET: summary}}

    def run_backtest(
        self,
        *,
        strategy: str,
        start_date: str,
        end_date: str,
        dataset: str = DAILY_OHLCV_DATASET,
        initial_cash: float = 1_000_000.0,
        fee_bps: float = 2.0,
        slippage_bps: float = 1.0,
        asset_family: str = "",
        params_json: str = "",
    ) -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        params = self._parse_params(params_json)
        run_id = self._run_id("backtest")
        source_rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        equity_rows, position_rows, trade_rows, comparison_rows, quality_rows = BacktestEngine(self).run(
            dataset_name=dataset,
            source_rows=source_rows,
            strategy=strategy,
            initial_cash=float(initial_cash),
            fee_bps=float(fee_bps),
            slippage_bps=float(slippage_bps),
            start_date=start,
            end_date=end,
            params=params,
            run_id=run_id,
        )
        summaries = {
            BACKTEST_EQUITY_CURVES_DATASET: _write_platform_dataset(
                dataset_name=BACKTEST_EQUITY_CURVES_DATASET,
                trade_date=end,
                rows=self._merge_platform_rows(BACKTEST_EQUITY_CURVES_DATASET, end, equity_rows, ["trade_date", "strategy_name", "dataset"]),
                fieldnames=BACKTEST_EQUITY_CURVES_STANDARD_FIELDS,
                key_fields=["trade_date", "strategy_name", "dataset"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
            BACKTEST_POSITIONS_DATASET: _write_platform_dataset(
                dataset_name=BACKTEST_POSITIONS_DATASET,
                trade_date=end,
                rows=self._merge_platform_rows(BACKTEST_POSITIONS_DATASET, end, position_rows, ["trade_date", "strategy_name", "dataset", "symbol_or_contract"]),
                fieldnames=BACKTEST_POSITIONS_STANDARD_FIELDS,
                key_fields=["trade_date", "strategy_name", "dataset", "symbol_or_contract"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
            BACKTEST_TRADES_DATASET: _write_platform_dataset(
                dataset_name=BACKTEST_TRADES_DATASET,
                trade_date=end,
                rows=self._merge_platform_rows(BACKTEST_TRADES_DATASET, end, trade_rows, ["trade_date", "strategy_name", "dataset", "symbol_or_contract", "side"]),
                fieldnames=BACKTEST_TRADES_STANDARD_FIELDS,
                key_fields=["trade_date", "strategy_name", "dataset", "symbol_or_contract", "side"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
            STRATEGY_COMPARISONS_DATASET: _write_platform_dataset(
                dataset_name=STRATEGY_COMPARISONS_DATASET,
                trade_date=end,
                rows=self._merge_platform_rows(STRATEGY_COMPARISONS_DATASET, end, comparison_rows, ["trade_date", "strategy_name", "benchmark_name", "metric_name"]),
                fieldnames=STRATEGY_COMPARISONS_STANDARD_FIELDS,
                key_fields=["trade_date", "strategy_name", "benchmark_name", "metric_name"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
            BACKTEST_INPUT_QUALITY_DATASET: _write_platform_dataset(
                dataset_name=BACKTEST_INPUT_QUALITY_DATASET,
                trade_date=end,
                rows=self._merge_platform_rows(BACKTEST_INPUT_QUALITY_DATASET, end, quality_rows, ["trade_date", "run_id", "strategy_name", "dataset", "symbol_or_contract", "issue_type"]),
                fieldnames=BACKTEST_INPUT_QUALITY_STANDARD_FIELDS,
                key_fields=["trade_date", "run_id", "strategy_name", "dataset", "symbol_or_contract", "issue_type"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
        }
        self._record_experiment(
            trade_date=end,
            run_id=run_id,
            experiment_type="backtest",
            template_name=strategy,
            dataset_name=dataset,
            asset_family=asset_family,
            start_date=start,
            end_date=end,
            status=self._merge_statuses([item["status"] for item in summaries.values()]),
            reason="",
            score_metric="total_return",
            score_value=next((row.get("strategy_value", "") for row in comparison_rows if row.get("metric_name") == "total_return"), ""),
            parameters={**params, "initial_cash": initial_cash, "fee_bps": fee_bps, "slippage_bps": slippage_bps},
            artifact_count=0,
        )
        return {"status": self._merge_statuses([item["status"] for item in summaries.values()]), "run_id": run_id, "window_start": start, "window_end": end, "strategy": strategy, "datasets": summaries}

    def run_ml(
        self,
        *,
        template: str,
        start_date: str,
        end_date: str,
        dataset: str = DAILY_OHLCV_DATASET,
        target: str = "",
        features: str = "",
        params_json: str = "",
        tune: bool = False,
        asset_family: str = "",
    ) -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        params = self._parse_params(params_json)
        run_id = self._run_id("ml")
        template_info = AlgorithmRegistry.get(template)
        source_rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        model_rows, prediction_rows, feature_rows, diagnostic_rows = self._ml_rows(
            template_name=template_info.name,
            dataset_name=dataset,
            source_rows=source_rows,
            asset_family=asset_family,
            target_field=target,
            feature_text=features,
            params=params,
            tune=tune,
            start_date=start,
            end_date=end,
            run_id=run_id,
        )
        summaries = {
            ML_MODEL_RUNS_DATASET: _write_platform_dataset(
                dataset_name=ML_MODEL_RUNS_DATASET,
                trade_date=end,
                rows=self._merge_platform_rows(ML_MODEL_RUNS_DATASET, end, model_rows, ["trade_date", "run_id", "template_name"]),
                fieldnames=ML_MODEL_RUNS_STANDARD_FIELDS,
                key_fields=["trade_date", "run_id", "template_name"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
            ML_PREDICTIONS_DATASET: _write_platform_dataset(
                dataset_name=ML_PREDICTIONS_DATASET,
                trade_date=end,
                rows=self._merge_platform_rows(ML_PREDICTIONS_DATASET, end, prediction_rows, ["trade_date", "run_id", "template_name", "symbol_or_contract", "prediction_date"]),
                fieldnames=ML_PREDICTIONS_STANDARD_FIELDS,
                key_fields=["trade_date", "run_id", "template_name", "symbol_or_contract", "prediction_date"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
            ML_FEATURE_IMPORTANCE_DATASET: _write_platform_dataset(
                dataset_name=ML_FEATURE_IMPORTANCE_DATASET,
                trade_date=end,
                rows=self._merge_platform_rows(ML_FEATURE_IMPORTANCE_DATASET, end, feature_rows, ["trade_date", "run_id", "template_name", "feature_name"]),
                fieldnames=ML_FEATURE_IMPORTANCE_STANDARD_FIELDS,
                key_fields=["trade_date", "run_id", "template_name", "feature_name"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
            MODEL_DIAGNOSTICS_DATASET: _write_platform_dataset(
                dataset_name=MODEL_DIAGNOSTICS_DATASET,
                trade_date=end,
                rows=self._merge_platform_rows(MODEL_DIAGNOSTICS_DATASET, end, diagnostic_rows, ["trade_date", "run_id", "template_name", "diagnostic_type", "metric_name"]),
                fieldnames=MODEL_DIAGNOSTICS_STANDARD_FIELDS,
                key_fields=["trade_date", "run_id", "template_name", "diagnostic_type", "metric_name"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
        }
        status = self._merge_statuses([row.get("status", "") for row in model_rows]) if model_rows else self._merge_statuses([item["status"] for item in summaries.values()])
        self._record_experiment(
            trade_date=end,
            run_id=run_id,
            experiment_type="ml",
            template_name=template_info.name,
            dataset_name=dataset,
            asset_family=asset_family,
            start_date=start,
            end_date=end,
            status=status,
            reason=model_rows[0].get("reason", "") if model_rows else "",
            score_metric=model_rows[0].get("score_metric", "") if model_rows else "",
            score_value=model_rows[0].get("score_value", "") if model_rows else "",
            parameters={"target": target, "features": features, "tune": tune, **params},
            artifact_count=0,
        )
        return {"status": status, "run_id": run_id, "window_start": start, "window_end": end, "template": template_info.name, "datasets": summaries}

    def factor_performance(
        self,
        *,
        factor: str,
        start_date: str,
        end_date: str,
        dataset: str = DAILY_OHLCV_DATASET,
        asset_family: str = "",
    ) -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        run_id = self._run_id("factorperf")
        source_rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        rows = self._factor_performance_rows(dataset_name=dataset, source_rows=source_rows, factor=factor, start_date=start, end_date=end, run_id=run_id)
        summary = _write_platform_dataset(
            dataset_name=FACTOR_PERFORMANCE_DATASET,
            trade_date=end,
            rows=self._merge_platform_rows(FACTOR_PERFORMANCE_DATASET, end, rows, ["trade_date", "factor_name", "dataset", "metric_name"]),
            fieldnames=FACTOR_PERFORMANCE_STANDARD_FIELDS,
            key_fields=["trade_date", "factor_name", "dataset", "metric_name"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        self._record_experiment(
            trade_date=end,
            run_id=run_id,
            experiment_type="factor_performance",
            template_name=factor,
            dataset_name=dataset,
            asset_family=asset_family,
            start_date=start,
            end_date=end,
            status=summary["status"],
            reason="",
            score_metric="rank_ic",
            score_value=next((row.get("metric_value", "") for row in rows if row.get("metric_name") == "rank_ic"), ""),
            parameters={},
            artifact_count=0,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": start, "window_end": end, "datasets": {FACTOR_PERFORMANCE_DATASET: summary}}

    def stress_test(
        self,
        *,
        template: str,
        start_date: str,
        end_date: str,
        dataset: str = DAILY_OHLCV_DATASET,
        params_json: str = "",
        asset_family: str = "",
    ) -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        params = self._parse_params(params_json)
        run_id = self._run_id("stress")
        template_info = AlgorithmRegistry.get(template)
        source_rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        rows = self._stress_test_rows(template_name=template_info.name, dataset_name=dataset, source_rows=source_rows, asset_family=asset_family, start_date=start, end_date=end, params=params, run_id=run_id)
        summary = _write_platform_dataset(
            dataset_name=STRESS_TEST_RESULTS_DATASET,
            trade_date=end,
            rows=self._merge_platform_rows(STRESS_TEST_RESULTS_DATASET, end, rows, ["trade_date", "run_id", "template_name", "scenario_name", "metric_name"]),
            fieldnames=STRESS_TEST_RESULTS_STANDARD_FIELDS,
            key_fields=["trade_date", "run_id", "template_name", "scenario_name", "metric_name"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        self._record_experiment(
            trade_date=end,
            run_id=run_id,
            experiment_type="stress_test",
            template_name=template_info.name,
            dataset_name=dataset,
            asset_family=asset_family,
            start_date=start,
            end_date=end,
            status=summary["status"],
            reason="",
            score_metric="impact_pct",
            score_value=next((row.get("impact_pct", "") for row in rows if row.get("metric_name") == "portfolio_value"), ""),
            parameters=params,
            artifact_count=0,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": start, "window_end": end, "datasets": {STRESS_TEST_RESULTS_DATASET: summary}}

    def quality_score(self, *, date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        run_id = self._run_id("qualityscore")
        rows = self._dataset_quality_score_rows(trade_date=trade_date, run_id=run_id)
        summary = _write_platform_dataset(
            dataset_name=DATASET_QUALITY_SCORES_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=DATASET_QUALITY_SCORES_STANDARD_FIELDS,
            key_fields=["trade_date", "dataset"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "trade_date": trade_date, "datasets": {DATASET_QUALITY_SCORES_DATASET: summary}}

    def experiment_list(self, *, date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        rows = self._load_platform_rows(EXPERIMENT_RUNS_DATASET, trade_date)
        return {"status": "success" if rows else "no_data", "trade_date": trade_date, "row_count": len(rows), "experiments": rows}

    def artifact_list(self, *, run_id: str = "", date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        rows = self._load_platform_rows(ARTIFACT_MANIFEST_DATASET, trade_date)
        if run_id:
            rows = [row for row in rows if str(row.get("run_id", "")) == run_id]
        return {"status": "success" if rows else "no_data", "trade_date": trade_date, "row_count": len(rows), "artifacts": rows}

    def inventory_build(self, *, date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        run_id = self._run_id("inventory")
        inventory_rows, field_rows = self._inventory_and_field_profile_rows(trade_date=trade_date, run_id=run_id)
        summaries = {
            DATASET_INVENTORY_DATASET: _write_platform_dataset(
                dataset_name=DATASET_INVENTORY_DATASET,
                trade_date=trade_date,
                rows=inventory_rows,
                fieldnames=DATASET_INVENTORY_STANDARD_FIELDS,
                key_fields=["trade_date", "dataset"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
            DATASET_FIELD_PROFILE_DATASET: _write_platform_dataset(
                dataset_name=DATASET_FIELD_PROFILE_DATASET,
                trade_date=trade_date,
                rows=field_rows,
                fieldnames=DATASET_FIELD_PROFILE_STANDARD_FIELDS,
                key_fields=["trade_date", "dataset", "field_name"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
        }
        return {"status": self._merge_statuses([item["status"] for item in summaries.values()]), "run_id": run_id, "trade_date": trade_date, "datasets": summaries}

    def lineage_build(self, *, date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        run_id = self._run_id("lineage")
        rows = self._lineage_rows(trade_date=trade_date, run_id=run_id)
        summary = _write_platform_dataset(
            dataset_name=DATA_LINEAGE_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=DATA_LINEAGE_STANDARD_FIELDS,
            key_fields=["trade_date", "run_id", "artifact_id"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "trade_date": trade_date, "datasets": {DATA_LINEAGE_DATASET: summary}}

    def sla_check(self, *, date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        run_id = self._run_id("sla")
        rule_rows, violation_rows = self._sla_rows(trade_date=trade_date, run_id=run_id)
        summaries = {
            DATASET_SLA_RULES_DATASET: _write_platform_dataset(
                dataset_name=DATASET_SLA_RULES_DATASET,
                trade_date=trade_date,
                rows=rule_rows,
                fieldnames=DATASET_SLA_RULES_STANDARD_FIELDS,
                key_fields=["trade_date", "dataset"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
            SLA_VIOLATIONS_DATASET: _write_platform_dataset(
                dataset_name=SLA_VIOLATIONS_DATASET,
                trade_date=trade_date,
                rows=violation_rows,
                fieldnames=SLA_VIOLATIONS_STANDARD_FIELDS,
                key_fields=["trade_date", "dataset", "violation_type"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
        }
        return {"status": "success", "run_id": run_id, "trade_date": trade_date, "violation_count": len(violation_rows), "datasets": summaries}

    def knowledge_build(self, *, date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        run_id = self._run_id("knowledge")
        rows = self._knowledge_rows(trade_date=trade_date, run_id=run_id)
        summary = _write_platform_dataset(
            dataset_name=KNOWLEDGE_INDEX_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=KNOWLEDGE_INDEX_STANDARD_FIELDS,
            key_fields=["trade_date", "knowledge_id"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "trade_date": trade_date, "datasets": {KNOWLEDGE_INDEX_DATASET: summary}}

    def feature_run(self, *, start_date: str, end_date: str, dataset: str = DAILY_OHLCV_DATASET, asset_family: str = "", features: str = "", mode: str = "incremental") -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        run_id = self._run_id("feature")
        source_rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        rows = self._feature_store_rows(dataset_name=dataset, source_rows=source_rows, feature_text=features, start_date=start, end_date=end, run_id=run_id)
        summary = _write_platform_dataset(
            dataset_name=ML_FEATURE_STORE_DATASET,
            trade_date=end,
            rows=self._merge_platform_rows(ML_FEATURE_STORE_DATASET, end, rows, ["trade_date", "dataset", "symbol_or_contract", "feature_name", "window"]),
            fieldnames=ML_FEATURE_STORE_STANDARD_FIELDS,
            key_fields=["trade_date", "dataset", "symbol_or_contract", "feature_name", "window"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": start, "window_end": end, "mode": mode, "datasets": {ML_FEATURE_STORE_DATASET: summary}}

    def ml_benchmark(self, *, start_date: str, end_date: str, dataset: str = DAILY_OHLCV_DATASET, target: str = "", features: str = "", models: str = "", params_json: str = "", asset_family: str = "") -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        run_id = self._run_id("mlbench")
        params = self._parse_params(params_json)
        params.setdefault("max_samples", 800)
        model_names = [item.strip() for item in str(models or "").split(",") if item.strip()] or ["linear_regression", "ridge", "lasso", "random_forest", "xgboost", "lightgbm", "catboost", "svm", "mlp", "regime_detection", "pca", "kmeans"]
        rows = []
        started = time.monotonic()
        for model_name in model_names:
            try:
                result = self.run_ml(template=model_name, start_date=start, end_date=end, dataset=dataset, target=target, features=features, params_json=safe_json_dumps(params), tune=True, asset_family=asset_family)
                model_rows = [row for row in self._load_platform_rows(ML_MODEL_RUNS_DATASET, end) if row.get("run_id") == result.get("run_id")]
                diagnostic_rows = [row for row in self._load_platform_rows(MODEL_DIAGNOSTICS_DATASET, end) if row.get("run_id") == result.get("run_id")]
                rows.append(self._ml_benchmark_row(end, run_id, model_name, dataset, asset_family, target, features, model_rows, diagnostic_rows, time.monotonic() - started))
            except Exception as exc:
                rows.append(self._ml_benchmark_row(end, run_id, model_name, dataset, asset_family, target, features, [], [], time.monotonic() - started, status="not_applicable", reason=str(exc)))
        rows = self._rank_metric_rows(rows, "score_value")
        summary = _write_platform_dataset(
            dataset_name=ML_BENCHMARKS_DATASET,
            trade_date=end,
            rows=self._merge_platform_rows(ML_BENCHMARKS_DATASET, end, rows, ["trade_date", "run_id", "template_name"]),
            fieldnames=ML_BENCHMARKS_STANDARD_FIELDS,
            key_fields=["trade_date", "run_id", "template_name"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": start, "window_end": end, "datasets": {ML_BENCHMARKS_DATASET: summary}}

    def ml_validate(self, *, template: str, start_date: str, end_date: str, dataset: str = DAILY_OHLCV_DATASET, target: str = "", features: str = "", method: str = "expanding", params_json: str = "", asset_family: str = "") -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        run_id = self._run_id("mlvalid")
        source_rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        fold_rows, class_rows = self._ml_validation_rows(template=template, dataset_name=dataset, source_rows=source_rows, target=target, features=features, method=method, params=self._parse_params(params_json), start_date=start, end_date=end, run_id=run_id)
        summaries = {
            ML_VALIDATION_FOLDS_DATASET: _write_platform_dataset(
                dataset_name=ML_VALIDATION_FOLDS_DATASET,
                trade_date=end,
                rows=self._merge_platform_rows(ML_VALIDATION_FOLDS_DATASET, end, fold_rows, ["trade_date", "run_id", "template_name", "fold_index"]),
                fieldnames=ML_VALIDATION_FOLDS_STANDARD_FIELDS,
                key_fields=["trade_date", "run_id", "template_name", "fold_index"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
            ML_CLASSIFICATION_RESULTS_DATASET: _write_platform_dataset(
                dataset_name=ML_CLASSIFICATION_RESULTS_DATASET,
                trade_date=end,
                rows=self._merge_platform_rows(ML_CLASSIFICATION_RESULTS_DATASET, end, class_rows, ["trade_date", "run_id", "template_name", "task_name"]),
                fieldnames=ML_CLASSIFICATION_RESULTS_STANDARD_FIELDS,
                key_fields=["trade_date", "run_id", "template_name", "task_name"],
                platform_dir=self.platform_dir,
                project_root=self.project_root,
            ),
        }
        return {"status": self._merge_statuses([item["status"] for item in summaries.values()]), "run_id": run_id, "window_start": start, "window_end": end, "datasets": summaries}

    def factor_experiment(self, *, factor: str, start_date: str, end_date: str, dataset: str = DAILY_OHLCV_DATASET, params_json: str = "", asset_family: str = "") -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        run_id = self._run_id("factorexp")
        params = self._parse_params(params_json)
        source_rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        perf_rows = self._factor_performance_rows(dataset_name=dataset, source_rows=source_rows, factor=factor, start_date=start, end_date=end, run_id=run_id)
        rows = self._factor_experiment_rows(end, run_id, factor, dataset, asset_family, params, perf_rows)
        summary = _write_platform_dataset(
            dataset_name=FACTOR_EXPERIMENTS_DATASET,
            trade_date=end,
            rows=self._merge_platform_rows(FACTOR_EXPERIMENTS_DATASET, end, rows, ["trade_date", "run_id", "factor_name", "parameter_set"]),
            fieldnames=FACTOR_EXPERIMENTS_STANDARD_FIELDS,
            key_fields=["trade_date", "run_id", "factor_name", "parameter_set"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": start, "window_end": end, "datasets": {FACTOR_EXPERIMENTS_DATASET: summary}}

    def parameter_scan(self, *, template: str, start_date: str, end_date: str, dataset: str = DAILY_OHLCV_DATASET, grid_json: str = "", asset_family: str = "") -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        run_id = self._run_id("paramscan")
        rows = self._parameter_scan_rows(end, run_id, template, dataset, asset_family, self._parse_grid(grid_json))
        summary = _write_platform_dataset(
            dataset_name=PARAMETER_SCANS_DATASET,
            trade_date=end,
            rows=self._merge_platform_rows(PARAMETER_SCANS_DATASET, end, rows, ["trade_date", "run_id", "template_name", "parameter_set", "metric_name"]),
            fieldnames=PARAMETER_SCANS_STANDARD_FIELDS,
            key_fields=["trade_date", "run_id", "template_name", "parameter_set", "metric_name"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": start, "window_end": end, "datasets": {PARAMETER_SCANS_DATASET: summary}}

    def strategy_leaderboard(self, *, start_date: str, end_date: str, dataset: str = DAILY_OHLCV_DATASET) -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        run_id = self._run_id("leaderboard")
        rows = self._strategy_leaderboard_rows(end, run_id, dataset)
        summary = _write_platform_dataset(
            dataset_name=STRATEGY_LEADERBOARD_DATASET,
            trade_date=end,
            rows=self._merge_platform_rows(STRATEGY_LEADERBOARD_DATASET, end, rows, ["trade_date", "run_id", "strategy_name"]),
            fieldnames=STRATEGY_LEADERBOARD_STANDARD_FIELDS,
            key_fields=["trade_date", "run_id", "strategy_name"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": start, "window_end": end, "datasets": {STRATEGY_LEADERBOARD_DATASET: summary}}

    def portfolio_run(self, *, template: str, start_date: str, end_date: str, dataset: str = DAILY_OHLCV_DATASET, params_json: str = "", asset_family: str = "") -> Dict[str, object]:
        allocation = self.optimize_portfolio(template=template, start_date=start_date, end_date=end_date, dataset=dataset, params_json=params_json, asset_family=asset_family)
        end = allocation["window_end"]
        run_id = self._run_id("portfolioexp")
        rows = self._portfolio_experiment_rows(end, run_id, template, dataset, params_json, allocation)
        summary = _write_platform_dataset(
            dataset_name=PORTFOLIO_EXPERIMENTS_DATASET,
            trade_date=end,
            rows=self._merge_platform_rows(PORTFOLIO_EXPERIMENTS_DATASET, end, rows, ["trade_date", "run_id", "template_name", "metric_name"]),
            fieldnames=PORTFOLIO_EXPERIMENTS_STANDARD_FIELDS,
            key_fields=["trade_date", "run_id", "template_name", "metric_name"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": allocation["window_start"], "window_end": end, "datasets": {PORTFOLIO_EXPERIMENTS_DATASET: summary}}

    def scenario_sim(self, *, template: str, start_date: str, end_date: str, dataset: str = DAILY_OHLCV_DATASET, params_json: str = "", asset_family: str = "") -> Dict[str, object]:
        stress = self.stress_test(template=template, start_date=start_date, end_date=end_date, dataset=dataset, params_json=params_json, asset_family=asset_family)
        end = stress["window_end"]
        run_id = self._run_id("scenario")
        stress_rows = [row for row in self._load_platform_rows(STRESS_TEST_RESULTS_DATASET, end) if row.get("run_id") == stress.get("run_id")]
        rows = self._scenario_rows(end, run_id, template, dataset, params_json, stress_rows)
        summary = _write_platform_dataset(
            dataset_name=SCENARIO_SIMULATIONS_DATASET,
            trade_date=end,
            rows=self._merge_platform_rows(SCENARIO_SIMULATIONS_DATASET, end, rows, ["trade_date", "run_id", "scenario_name"]),
            fieldnames=SCENARIO_SIMULATIONS_STANDARD_FIELDS,
            key_fields=["trade_date", "run_id", "scenario_name"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        return {"status": summary["status"], "run_id": run_id, "window_start": stress["window_start"], "window_end": end, "datasets": {SCENARIO_SIMULATIONS_DATASET: summary}}

    def project_create(self, *, name: str, description: str = "", date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        project_id = self._run_id("project")
        row = self._project_row(trade_date, project_id, name, description, "active")
        rows = self._merge_platform_rows(RESEARCH_PROJECTS_DATASET, trade_date, [row], ["trade_date", "project_id"])
        summary = _write_platform_dataset(dataset_name=RESEARCH_PROJECTS_DATASET, trade_date=trade_date, rows=rows, fieldnames=RESEARCH_PROJECTS_STANDARD_FIELDS, key_fields=["trade_date", "project_id"], platform_dir=self.platform_dir, project_root=self.project_root)
        return {"status": summary["status"], "project_id": project_id, "trade_date": trade_date, "datasets": {RESEARCH_PROJECTS_DATASET: summary}}

    def project_run(self, *, project_id: str, template: str, start_date: str, end_date: str, dataset: str = DAILY_OHLCV_DATASET, params_json: str = "") -> Dict[str, object]:
        start, end = self._resolve_window(date_value=end_date, start_date=start_date, end_date=end_date)
        run_id = self._run_id("projectrun")
        params = self._parse_params(params_json)
        factor_name = str(params.get("factor") or template or "momentum")
        if factor_name not in dict(AlgorithmRegistry.options(categories={"factor"})):
            factor_name = "momentum"
        strategy_name = str(params.get("strategy") or template or "momentum")
        report_type = str(params.get("report_type") or "project")
        step_results: List[Dict[str, object]] = []

        # A project run is a small reproducible research workflow, not just a log row.
        step_results.append(self.factor_experiment(factor=factor_name, start_date=start, end_date=end, dataset=dataset, params_json=params_json))
        step_results.append(
            self.run_backtest(
                strategy=strategy_name,
                start_date=start,
                end_date=end,
                dataset=dataset,
                initial_cash=float(_float(params.get("initial_cash")) or 1_000_000.0),
                fee_bps=float(_float(params.get("fee_bps")) or 2.0),
                slippage_bps=float(_float(params.get("slippage_bps")) or 1.0),
                params_json=params_json,
            )
        )
        step_results.append(self.strategy_leaderboard(start_date=start, end_date=end, dataset=dataset))
        step_results.append(self.report_generate(date_value=end, report_type=report_type))
        step_status = self._merge_statuses([str(item.get("status", "")) for item in step_results])
        reason = "" if step_status == "success" else "one or more project workflow steps did not fully succeed"
        row = self._project_run_row(end, project_id, run_id, template, dataset, start, end, params_json, step_status, reason)
        row["artifact_count"] = str(sum(len((item.get("datasets") or {})) for item in step_results))
        rows = self._merge_platform_rows(PROJECT_RUNS_DATASET, end, [row], ["trade_date", "project_id", "run_id"])
        summary = _write_platform_dataset(dataset_name=PROJECT_RUNS_DATASET, trade_date=end, rows=rows, fieldnames=PROJECT_RUNS_STANDARD_FIELDS, key_fields=["trade_date", "project_id", "run_id"], platform_dir=self.platform_dir, project_root=self.project_root)
        package_result = self.package_export(run_id=run_id, date_value=end)
        self._record_experiment(
            trade_date=end,
            run_id=run_id,
            experiment_type="project",
            template_name=str(template or "project"),
            dataset_name=dataset,
            asset_family=str(params.get("asset_family", "")),
            start_date=start,
            end_date=end,
            status=step_status,
            reason=reason,
            score_metric="artifact_count",
            score_value=row["artifact_count"],
            parameters={**params, "project_id": project_id, "factor": factor_name, "strategy": strategy_name, "report_type": report_type},
            artifact_count=int(row["artifact_count"] or "0"),
        )
        datasets = {PROJECT_RUNS_DATASET: summary}
        datasets.update(package_result.get("datasets", {}))
        return {
            "status": self._merge_statuses([step_status, str(summary["status"]), str(package_result.get("status", ""))]),
            "project_id": project_id,
            "run_id": run_id,
            "window_start": start,
            "window_end": end,
            "steps": step_results,
            "package_id": package_result.get("package_id", ""),
            "datasets": datasets,
        }

    def package_export(self, *, run_id: str = "", date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        package_id = self._run_id("package")
        row = self._reproducible_package_row(trade_date, package_id, run_id)
        rows = self._merge_platform_rows(REPRODUCIBLE_PACKAGES_DATASET, trade_date, [row], ["trade_date", "package_id"])
        summary = _write_platform_dataset(dataset_name=REPRODUCIBLE_PACKAGES_DATASET, trade_date=trade_date, rows=rows, fieldnames=REPRODUCIBLE_PACKAGES_STANDARD_FIELDS, key_fields=["trade_date", "package_id"], platform_dir=self.platform_dir, project_root=self.project_root)
        return {"status": summary["status"], "package_id": package_id, "trade_date": trade_date, "datasets": {REPRODUCIBLE_PACKAGES_DATASET: summary}}

    def quality_diagnose(self, *, date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        run_id = self._run_id("quality")
        rows = self._quality_rows(trade_date=trade_date, run_id=run_id)
        anomaly_rows = self._anomaly_event_rows(trade_date=trade_date, run_id=run_id)
        report_dir = self.reports_dir / trade_date
        ensure_directory(report_dir)
        markdown_path = report_dir / "quality_diagnostics.md"
        markdown_path.write_text(self._quality_markdown(trade_date=trade_date, rows=rows, anomaly_rows=anomaly_rows), encoding="utf-8")
        summary = _write_platform_dataset(
            dataset_name=QUALITY_DIAGNOSTICS_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=QUALITY_DIAGNOSTICS_STANDARD_FIELDS,
            key_fields=["trade_date", "diagnostic_type", "dataset", "source_id"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        anomaly_summary = _write_platform_dataset(
            dataset_name=ANOMALY_EVENTS_DATASET,
            trade_date=trade_date,
            rows=anomaly_rows,
            fieldnames=ANOMALY_EVENTS_STANDARD_FIELDS,
            key_fields=["trade_date", "dataset", "source_id", "event_type", "metric_name"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        severity_counts = Counter(row.get("severity", "") for row in rows)
        return {
            "status": self._merge_statuses([summary["status"], anomaly_summary["status"]]),
            "run_id": run_id,
            "trade_date": trade_date,
            "markdown_path": relative_to_project(markdown_path, self.project_root),
            "severity_counts": dict(severity_counts),
            "datasets": {QUALITY_DIAGNOSTICS_DATASET: summary, ANOMALY_EVENTS_DATASET: anomaly_summary},
        }

    def report_generate(self, *, date_value: str = "latest", report_type: str = "comprehensive") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        run_id = self._run_id("report")
        report_dir = self.reports_dir / trade_date
        ensure_directory(report_dir)
        quality_rows = self._load_platform_rows(QUALITY_DIAGNOSTICS_DATASET, trade_date)
        if not quality_rows:
            quality_rows = self._quality_rows(trade_date=trade_date, run_id=run_id)
        research_rows = self._load_platform_rows(RESEARCH_METRICS_DATASET, trade_date)
        strategy_rows = self._load_platform_rows(STRATEGY_BACKTESTS_DATASET, trade_date)
        algorithm_rows = self._load_platform_rows(ALGORITHM_OUTPUTS_DATASET, trade_date)
        risk_rows = self._load_platform_rows(RISK_METRICS_DATASET, trade_date)
        backtest_rows = self._load_platform_rows(BACKTEST_EQUITY_CURVES_DATASET, trade_date)
        anomaly_rows = self._load_platform_rows(ANOMALY_EVENTS_DATASET, trade_date)
        ml_rows = self._load_platform_rows(ML_MODEL_RUNS_DATASET, trade_date)
        factor_perf_rows = self._load_platform_rows(FACTOR_PERFORMANCE_DATASET, trade_date)
        stress_rows = self._load_platform_rows(STRESS_TEST_RESULTS_DATASET, trade_date)
        quality_score_rows = self._load_platform_rows(DATASET_QUALITY_SCORES_DATASET, trade_date)
        warning_count = sum(1 for row in quality_rows if str(row.get("severity")) == "warning")
        failed_count = sum(1 for row in quality_rows if str(row.get("severity")) == "critical")
        blocked_count = sum(1 for row in quality_rows if "blocked" in str(row.get("status", "")))
        status = "success" if failed_count == 0 else "partial_success"
        severity = "warning" if warning_count or blocked_count else "info"
        if failed_count:
            severity = "critical"
        markdown = self._report_markdown(
            trade_date=trade_date,
            quality_rows=quality_rows,
            research_rows=research_rows,
            strategy_rows=strategy_rows,
            algorithm_rows=algorithm_rows,
            risk_rows=risk_rows,
            backtest_rows=backtest_rows,
            anomaly_rows=anomaly_rows,
            ml_rows=ml_rows,
            factor_perf_rows=factor_perf_rows,
            stress_rows=stress_rows,
            quality_score_rows=quality_score_rows,
            status=status,
            severity=severity,
            report_type=report_type,
        )
        markdown_path = report_dir / "daily_report.md"
        html_path = report_dir / "daily_report.html"
        markdown_path.write_text(markdown, encoding="utf-8")
        html_path.write_text(self._markdown_to_html(markdown), encoding="utf-8")
        report_artifact_rows, artifact_manifest_rows = self._report_artifact_rows(
            trade_date=trade_date,
            run_id=run_id,
            report_id=f"{report_type}:{trade_date}",
            report_dir=report_dir,
            backtest_rows=backtest_rows,
            quality_score_rows=quality_score_rows,
            report_type=report_type,
        )
        rows = [
            {
                "trade_date": trade_date,
                "report_id": f"{report_type}:{trade_date}",
                "report_type": str(report_type or "comprehensive"),
                "status": status,
                "severity": severity,
                "markdown_path": relative_to_project(markdown_path, self.project_root),
                "html_path": relative_to_project(html_path, self.project_root),
                "summary": f"quality={len(quality_rows)}, anomaly={len(anomaly_rows)}, research={len(research_rows)}, algorithm={len(algorithm_rows)}, risk={len(risk_rows)}, strategy={len(strategy_rows)}, backtest={len(backtest_rows)}, ml={len(ml_rows)}, factor_perf={len(factor_perf_rows)}, stress={len(stress_rows)}",
                "warning_count": str(warning_count),
                "failed_count": str(failed_count),
                "blocked_issue_count": str(blocked_count),
                "source_id": "platform.research_report",
                "source_url": "reports://daily",
                "source_type": "derived",
                "retrieved_at": iso_timestamp(),
                "raw_path": relative_to_project(markdown_path, self.project_root),
                "parser_version": PARSER_VERSION,
                "checksum": _sha1_text(f"report:{trade_date}:{status}:{warning_count}:{failed_count}"),
                "run_id": run_id,
            }
        ]
        summary = _write_platform_dataset(
            dataset_name=RESEARCH_REPORTS_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=RESEARCH_REPORTS_STANDARD_FIELDS,
            key_fields=["trade_date", "report_id"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        artifact_summary = _write_platform_dataset(
            dataset_name=REPORT_ARTIFACTS_DATASET,
            trade_date=trade_date,
            rows=self._merge_platform_rows(REPORT_ARTIFACTS_DATASET, trade_date, report_artifact_rows, ["trade_date", "report_id", "artifact_id"]),
            fieldnames=REPORT_ARTIFACTS_STANDARD_FIELDS,
            key_fields=["trade_date", "report_id", "artifact_id"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        manifest_summary = _write_platform_dataset(
            dataset_name=ARTIFACT_MANIFEST_DATASET,
            trade_date=trade_date,
            rows=self._merge_platform_rows(ARTIFACT_MANIFEST_DATASET, trade_date, artifact_manifest_rows, ["trade_date", "run_id", "artifact_id"]),
            fieldnames=ARTIFACT_MANIFEST_STANDARD_FIELDS,
            key_fields=["trade_date", "run_id", "artifact_id"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        insight_rows, recommendation_rows = self._report_interpretation_rows(
            trade_date=trade_date,
            run_id=run_id,
            report_id=f"{report_type}:{trade_date}",
            report_type=str(report_type or "comprehensive"),
            quality_rows=quality_rows,
            anomaly_rows=anomaly_rows,
            ml_rows=ml_rows,
            factor_perf_rows=factor_perf_rows,
            stress_rows=stress_rows,
            strategy_rows=strategy_rows,
            leaderboard_rows=self._load_platform_rows(STRATEGY_LEADERBOARD_DATASET, trade_date),
            quality_score_rows=quality_score_rows,
            status=status,
            severity=severity,
        )
        insight_summary = _write_platform_dataset(
            dataset_name=REPORT_INSIGHTS_DATASET,
            trade_date=trade_date,
            rows=self._merge_platform_rows(REPORT_INSIGHTS_DATASET, trade_date, insight_rows, ["trade_date", "insight_id"]),
            fieldnames=REPORT_INSIGHTS_STANDARD_FIELDS,
            key_fields=["trade_date", "insight_id"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        recommendation_summary = _write_platform_dataset(
            dataset_name=RECOMMENDATION_ITEMS_DATASET,
            trade_date=trade_date,
            rows=self._merge_platform_rows(RECOMMENDATION_ITEMS_DATASET, trade_date, recommendation_rows, ["trade_date", "recommendation_id"]),
            fieldnames=RECOMMENDATION_ITEMS_STANDARD_FIELDS,
            key_fields=["trade_date", "recommendation_id"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )
        self._record_experiment(
            trade_date=trade_date,
            run_id=run_id,
            experiment_type="report",
            template_name=str(report_type or "comprehensive"),
            dataset_name=RESEARCH_REPORTS_DATASET,
            asset_family="platform_metadata",
            start_date=trade_date,
            end_date=trade_date,
            status=status,
            reason="",
            score_metric="warning_count",
            score_value=str(warning_count),
            parameters={"report_type": report_type},
            artifact_count=len(report_artifact_rows),
        )
        return {
            "status": status,
            "run_id": run_id,
            "trade_date": trade_date,
            "markdown_path": rows[0]["markdown_path"],
            "html_path": rows[0]["html_path"],
            "datasets": {
                RESEARCH_REPORTS_DATASET: summary,
                REPORT_ARTIFACTS_DATASET: artifact_summary,
                ARTIFACT_MANIFEST_DATASET: manifest_summary,
                REPORT_INSIGHTS_DATASET: insight_summary,
                RECOMMENDATION_ITEMS_DATASET: recommendation_summary,
            },
        }

    def _algorithm_rows(
        self,
        *,
        template_info: AlgorithmTemplate,
        dataset_name: str,
        source_rows: List[Dict[str, str]],
        asset_family: str,
        start_date: str,
        end_date: str,
        params: Dict[str, object],
        run_id: str,
    ) -> Tuple[List[Dict[str, str]], Dict[str, List[Dict[str, str]]]]:
        params_text = safe_json_dumps(params)
        extra_rows: Dict[str, List[Dict[str, str]]] = defaultdict(list)
        rows: List[Dict[str, str]] = []
        family = asset_family or (str(source_rows[0].get("asset_family", "")) if source_rows else "")
        name = template_info.name

        if template_info.category == "factor":
            if name in {"momentum", "mean_reversion", "volatility_filter", "volume_turnover", "cross_asset_rank"}:
                for item in self._factor_rows(dataset_name=dataset_name, source_rows=source_rows, factor=name, run_id=run_id, end_date=end_date):
                    rows.append(
                        self._algorithm_output_row(
                            end_date,
                            item.get("asset_family", ""),
                            dataset_name,
                            name,
                            template_info.category,
                            item.get("symbol_or_contract", ""),
                            item.get("factor_name", name),
                            item.get("factor_value", ""),
                            "score",
                            params_text,
                            start_date,
                            end_date,
                            item.get("status", ""),
                            item.get("reason", ""),
                            run_id,
                        )
                    )
                return rows, dict(extra_rows)
            if name in {"term_structure_slope", "yield_curve_slope"}:
                slope = self._curve_slope(source_rows)
                status = "success" if slope is not None else "not_applicable"
                reason = "" if slope is not None else "requires curve rows with tenor_years and yield/value"
                rows.append(self._algorithm_output_row(end_date, family, dataset_name, name, template_info.category, "", "slope", "" if slope is None else f"{slope:.8f}", "value", params_text, start_date, end_date, status, reason, run_id))
                if name == "yield_curve_slope":
                    extra_rows[CURVE_ANALYTICS_DATASET].append(self._curve_analytics_row(end_date, family, dataset_name, "curve", name, "", "", "", "", "" if slope is None else f"{slope:.8f}", "" if slope is None else f"{slope:.8f}", params_text, start_date, end_date, status, reason, run_id))
                return rows, dict(extra_rows)
            if name in {"basis_spread", "futures_calendar_spread"}:
                spread, reason = self._spread_metric(source_rows, params)
                status = "success" if spread is not None else "not_applicable"
                rows.append(self._algorithm_output_row(end_date, family, dataset_name, name, template_info.category, "", "spread", "" if spread is None else f"{spread:.8f}", "value", params_text, start_date, end_date, status, reason if spread is None else "", run_id))
                return rows, dict(extra_rows)

        if template_info.category == "option_math":
            option_row, metric_rows = self._option_model_rows(
                template_name=name,
                dataset_name=dataset_name,
                asset_family=family,
                params=params,
                params_text=params_text,
                start_date=start_date,
                end_date=end_date,
                run_id=run_id,
            )
            extra_rows[OPTION_ANALYTICS_DATASET].append(option_row)
            rows.extend(metric_rows)
            return rows, dict(extra_rows)

        if template_info.category == "bond_math":
            bond_row, metric_rows = self._bond_model_rows(
                template_name=name,
                dataset_name=dataset_name,
                asset_family=family,
                params=params,
                params_text=params_text,
                start_date=start_date,
                end_date=end_date,
                run_id=run_id,
            )
            extra_rows[BOND_ANALYTICS_DATASET].append(bond_row)
            rows.extend(metric_rows)
            return rows, dict(extra_rows)

        if template_info.category == "curve_math":
            slope = self._curve_slope(source_rows)
            status = "success" if slope is not None else "not_applicable"
            reason = "" if slope is not None else "requires curve rows with tenor_years and yield/value"
            curve_row = self._curve_analytics_row(end_date, family, dataset_name, "curve", name, "", "", "", "", "" if slope is None else f"{slope:.8f}", "" if slope is None else f"{slope:.8f}", params_text, start_date, end_date, status, reason, run_id)
            extra_rows[CURVE_ANALYTICS_DATASET].append(curve_row)
            rows.append(self._algorithm_output_row(end_date, family, dataset_name, name, template_info.category, "", "slope", curve_row["slope"], "value", params_text, start_date, end_date, status, reason, run_id))
            return rows, dict(extra_rows)

        status = "not_applicable"
        reason = f"template {name} should be run through risk-run or portfolio-optimize"
        rows.append(self._algorithm_output_row(end_date, family, dataset_name, name, template_info.category, "", name, "", "value", params_text, start_date, end_date, status, reason, run_id))
        return rows, dict(extra_rows)

    def _ml_rows(self, *, template_name: str, dataset_name: str, source_rows: List[Dict[str, str]], asset_family: str, target_field: str, feature_text: str, params: Dict[str, object], tune: bool, start_date: str, end_date: str, run_id: str):
        family = asset_family or (str(source_rows[0].get("asset_family", "")) if source_rows else "")
        target = target_field or self._default_target_field(source_rows)
        features = self._normalize_feature_fields(feature_text)
        if not features:
            features = self._default_feature_fields(source_rows, target)
        params_text = safe_json_dumps(params)
        X, y, meta = self._ml_matrix(source_rows, target, features)
        raw_sample_count = len(X)
        max_samples = int(_float(params.get("max_samples")) or 5000)
        if max_samples > 0 and len(X) > max_samples:
            X = X[-max_samples:]
            y = y[-max_samples:]
            meta = meta[-max_samples:]
        train_end = start_date
        test_start = end_date
        if len(X) >= 2:
            split_index = max(1, int(len(X) * 0.7))
            split_index = min(split_index, len(X) - 1)
            train_end = str(meta[split_index - 1].get("trade_date", start_date))
            test_start = str(meta[split_index].get("trade_date", end_date))
        if len(X) < 3 and template_name not in {"regime_detection"}:
            reason = "ml requires at least three rows with target and numeric features"
            model_rows = [self._ml_model_run_row(end_date, run_id, template_name, dataset_name, family, target, features, start_date, train_end, test_start, end_date, tune, "not_applicable", reason, "sample_count", str(len(X)), {}, dataset_name)]
            diagnostics = [self._model_diagnostic_row(end_date, run_id, template_name, dataset_name, "input_quality", "sample_count", str(len(X)), "not_applicable", reason, dataset_name)]
            return model_rows, [], [], diagnostics
        if template_name == "regime_detection":
            return self._regime_detection_rows(dataset_name=dataset_name, source_rows=source_rows, asset_family=family, start_date=start_date, end_date=end_date, run_id=run_id, params=params)
        try:
            import numpy as np
            from sklearn.cluster import KMeans
            from sklearn.decomposition import PCA
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.ensemble import HistGradientBoostingRegressor
            from sklearn.linear_model import Lasso, LinearRegression, Ridge
            from sklearn.neural_network import MLPRegressor
            from sklearn.svm import SVR
        except Exception as exc:
            reason = f"sklearn unavailable: {exc}"
            model_rows = [self._ml_model_run_row(end_date, run_id, template_name, dataset_name, family, target, features, start_date, train_end, test_start, end_date, tune, "not_applicable", reason, "dependency", "", {}, dataset_name)]
            diagnostics = [self._model_diagnostic_row(end_date, run_id, template_name, dataset_name, "dependency", "sklearn", "0", "not_applicable", reason, dataset_name)]
            return model_rows, [], [], diagnostics

        X_array = np.array(X, dtype=float)
        y_array = np.array(y, dtype=float) if y else np.array([], dtype=float)
        split_index = max(1, int(len(X_array) * 0.7))
        split_index = min(split_index, len(X_array) - 1) if len(X_array) > 1 else len(X_array)
        X_train, X_test = X_array[:split_index], X_array[split_index:]
        if len(y_array):
            y_train, y_test = y_array[:split_index], y_array[split_index:]
        else:
            y_train, y_test = np.array([]), np.array([])
        best_params: Dict[str, object] = {}
        predictions: List[float] = []
        status = "success"
        reason = ""
        score_metric = "r2"
        score_value = ""
        feature_values: Dict[str, float] = {}

        try:
            if template_name == "pca":
                n_components = int(_float(params.get("n_components")) or min(3, X_array.shape[1], len(X_array)))
                model = PCA(n_components=max(1, n_components)).fit(X_array)
                score_metric = "explained_variance_ratio"
                score_value = f"{float(sum(model.explained_variance_ratio_)):.8f}"
                best_params = {"n_components": int(model.n_components_)}
                feature_values = {f"pc{idx + 1}": float(value) for idx, value in enumerate(model.explained_variance_ratio_)}
                transformed = model.transform(X_array)
                predictions = [float(row[0]) for row in transformed]
                y_test = np.array([0.0 for _ in predictions])
            elif template_name == "kmeans":
                clusters = int(_float(params.get("n_clusters")) or 3)
                clusters = max(1, min(clusters, len(X_array)))
                model = KMeans(n_clusters=clusters, n_init=5, random_state=42).fit(X_array)
                score_metric = "inertia"
                score_value = f"{float(model.inertia_):.8f}"
                best_params = {"n_clusters": clusters}
                predictions = [float(value) for value in model.labels_]
                y_test = np.array([0.0 for _ in predictions])
            elif template_name != "xgboost":
                model, best_params = self._fit_supervised_model(
                    template_name,
                    X_train,
                    y_train,
                    X_valid=X_test,
                    y_valid=y_test,
                    tune=tune,
                    params=params,
                    classes={
                        "LinearRegression": LinearRegression,
                        "Ridge": Ridge,
                        "Lasso": Lasso,
                        "RandomForestRegressor": RandomForestRegressor,
                        "HistGradientBoostingRegressor": HistGradientBoostingRegressor,
                        "MLPRegressor": MLPRegressor,
                        "SVR": SVR,
                    },
                )
                predictions = [float(value) for value in model.predict(X_test if len(X_test) else X_train)]
                actual = y_test if len(y_test) else y_train
                score_value = f"{self._r2_score(list(actual), predictions):.8f}"
                if hasattr(model, "feature_importances_"):
                    feature_values = {features[idx]: float(value) for idx, value in enumerate(model.feature_importances_)}
                elif hasattr(model, "coef_"):
                    coefs = list(getattr(model, "coef_", []))
                    feature_values = {features[idx]: abs(float(value)) for idx, value in enumerate(coefs[: len(features)])}
            if template_name == "xgboost":
                model, best_params = self._fit_xgboost(X_train, y_train, X_valid=X_test, y_valid=y_test, tune=tune, params=params)
                predictions = [float(value) for value in model.predict(X_test if len(X_test) else X_train)]
                actual = y_test if len(y_test) else y_train
                score_value = f"{self._r2_score(list(actual), predictions):.8f}"
                if hasattr(model, "feature_importances_"):
                    feature_values = {features[idx]: float(value) for idx, value in enumerate(model.feature_importances_)}
        except Exception as exc:
            status, reason = "not_applicable", str(exc)
            predictions = []

        model_rows = [self._ml_model_run_row(end_date, run_id, template_name, dataset_name, family, target, features, start_date, train_end, test_start, end_date, tune, status, reason, score_metric, score_value, best_params, dataset_name)]
        prediction_rows = []
        prediction_meta = meta[split_index:] if template_name not in {"pca", "kmeans"} else meta
        actual_values = list(y_test) if template_name not in {"pca", "kmeans"} else [None for _ in predictions]
        for index, predicted in enumerate(predictions[:100]):
            item = prediction_meta[index] if index < len(prediction_meta) else {}
            actual = actual_values[index] if index < len(actual_values) else None
            prediction_rows.append(self._ml_prediction_row(end_date, run_id, template_name, dataset_name, family, item, actual, predicted, status, reason, dataset_name))
        feature_rows = []
        for rank, (feature_name, importance) in enumerate(sorted(feature_values.items(), key=lambda item: abs(item[1]), reverse=True), start=1):
            feature_rows.append(self._ml_feature_row(end_date, run_id, template_name, dataset_name, feature_name, importance, rank, status, reason, dataset_name))
        diagnostics = [
            self._model_diagnostic_row(end_date, run_id, template_name, dataset_name, "input_quality", "raw_sample_count", str(raw_sample_count), status, reason, dataset_name),
            self._model_diagnostic_row(end_date, run_id, template_name, dataset_name, "input_quality", "sample_count", str(len(X)), status, reason, dataset_name),
            self._model_diagnostic_row(end_date, run_id, template_name, dataset_name, "input_quality", "feature_count", str(len(features)), status, reason, dataset_name),
            self._model_diagnostic_row(end_date, run_id, template_name, dataset_name, "fit", "train_count", str(len(X_train)), status, reason, dataset_name),
            self._model_diagnostic_row(end_date, run_id, template_name, dataset_name, "fit", "test_count", str(len(X_test)), status, reason, dataset_name),
            self._model_diagnostic_row(end_date, run_id, template_name, dataset_name, "fit", "prediction_count", str(len(predictions)), status, reason, dataset_name),
            self._model_diagnostic_row(end_date, run_id, template_name, dataset_name, "fit", score_metric, score_value, status, reason, dataset_name),
        ]
        if template_name not in {"pca", "kmeans"} and predictions:
            actual_for_error = actual_values[: len(predictions)]
            diagnostics.append(self._model_diagnostic_row(end_date, run_id, template_name, dataset_name, "fit", "mae", f"{self._mae(actual_for_error, predictions):.8f}", status, reason, dataset_name))
            diagnostics.append(self._model_diagnostic_row(end_date, run_id, template_name, dataset_name, "fit", "rmse", f"{self._rmse(actual_for_error, predictions):.8f}", status, reason, dataset_name))
        return model_rows, prediction_rows, feature_rows, diagnostics

    def _fit_supervised_model(self, template_name: str, X_train, y_train, *, X_valid=None, y_valid=None, tune: bool, params: Dict[str, object], classes: Dict[str, object]):
        if template_name == "linear_regression":
            return self._fit_best_regressor(
                [(classes["LinearRegression"](), {})],
                X_train,
                y_train,
                X_valid=X_valid,
                y_valid=y_valid,
            )
        if template_name == "ridge":
            candidates = [0.01, 0.1, 1.0, 10.0] if tune else [float(_float(params.get("alpha")) or 1.0)]
            return self._fit_best_regressor(
                [(classes["Ridge"](alpha=alpha), {"alpha": alpha}) for alpha in candidates],
                X_train,
                y_train,
                X_valid=X_valid,
                y_valid=y_valid,
            )
        if template_name == "lasso":
            candidates = [0.001, 0.01, 0.1, 1.0] if tune else [float(_float(params.get("alpha")) or 0.01)]
            return self._fit_best_regressor(
                [(classes["Lasso"](alpha=alpha, max_iter=20000), {"alpha": alpha}) for alpha in candidates],
                X_train,
                y_train,
                X_valid=X_valid,
                y_valid=y_valid,
            )
        if template_name == "random_forest":
            if tune:
                candidate_params = [
                    {"n_estimators": n_estimators, "max_depth": max_depth}
                    for n_estimators in (30, 50)
                    for max_depth in (None, 3, 5)
                ]
            else:
                n_estimators = int(_float(params.get("n_estimators")) or 30)
                max_depth_value = _float(params.get("max_depth"))
                candidate_params = [{"n_estimators": n_estimators, "max_depth": int(max_depth_value) if max_depth_value else None}]
            return self._fit_best_regressor(
                [
                    (classes["RandomForestRegressor"](n_estimators=item["n_estimators"], max_depth=item["max_depth"], random_state=42), item)
                    for item in candidate_params
                ],
                X_train,
                y_train,
                X_valid=X_valid,
                y_valid=y_valid,
            )
        if template_name == "lightgbm":
            # Prefer a dependency-free sklearn compatible gradient boosting path
            # so the required template remains runnable on a clean local setup.
            candidates = [{"max_iter": 60, "learning_rate": 0.05}, {"max_iter": 100, "learning_rate": 0.08}] if tune else [{"max_iter": int(_float(params.get("max_iter")) or 80), "learning_rate": float(_float(params.get("learning_rate")) or 0.08)}]
            return self._fit_best_regressor(
                [(classes["HistGradientBoostingRegressor"](max_iter=item["max_iter"], learning_rate=item["learning_rate"], random_state=42), {**item, "adapter": "sklearn_hist_gradient_boosting"}) for item in candidates],
                X_train,
                y_train,
                X_valid=X_valid,
                y_valid=y_valid,
            )
        if template_name == "catboost":
            candidates = [{"n_estimators": 40, "max_depth": 3}, {"n_estimators": 80, "max_depth": 4}] if tune else [{"n_estimators": int(_float(params.get("n_estimators")) or 50), "max_depth": int(_float(params.get("max_depth")) or 4)}]
            return self._fit_best_regressor(
                [(classes["RandomForestRegressor"](n_estimators=item["n_estimators"], max_depth=item["max_depth"], random_state=42), {**item, "adapter": "sklearn_random_forest_catboost_compatible"}) for item in candidates],
                X_train,
                y_train,
                X_valid=X_valid,
                y_valid=y_valid,
            )
        if template_name == "svm":
            candidates = [{"C": 0.5, "epsilon": 0.05}, {"C": 1.0, "epsilon": 0.1}] if tune else [{"C": float(_float(params.get("C")) or 1.0), "epsilon": float(_float(params.get("epsilon")) or 0.1)}]
            return self._fit_best_regressor(
                [(classes["SVR"](C=item["C"], epsilon=item["epsilon"]), item) for item in candidates],
                X_train,
                y_train,
                X_valid=X_valid,
                y_valid=y_valid,
            )
        if template_name == "mlp":
            candidates = [{"hidden_layer_sizes": (12,), "alpha": 0.0001}, {"hidden_layer_sizes": (24,), "alpha": 0.001}] if tune else [{"hidden_layer_sizes": (int(_float(params.get("hidden_units")) or 16),), "alpha": float(_float(params.get("alpha")) or 0.0001)}]
            max_iter = int(_float(params.get("max_iter")) or 120)
            return self._fit_best_regressor(
                [(classes["MLPRegressor"](hidden_layer_sizes=item["hidden_layer_sizes"], alpha=item["alpha"], max_iter=max_iter, random_state=42), {"hidden_layer_sizes": list(item["hidden_layer_sizes"]), "alpha": item["alpha"], "max_iter": max_iter}) for item in candidates],
                X_train,
                y_train,
                X_valid=X_valid,
                y_valid=y_valid,
            )
        if template_name == "xgboost":
            return self._fit_xgboost(X_train, y_train, X_valid=X_valid, y_valid=y_valid, tune=tune, params=params)
        raise ValueError(f"unsupported ml template: {template_name}")

    def _fit_xgboost(self, X_train, y_train, *, X_valid=None, y_valid=None, tune: bool, params: Dict[str, object]):
        try:
            from xgboost import XGBRegressor
        except Exception as exc:
            raise ValueError(f"xgboost unavailable: {exc}") from exc
        if tune:
            candidate_params = [
                {"n_estimators": n_estimators, "max_depth": max_depth, "learning_rate": learning_rate}
                for n_estimators in (30, 50)
                for max_depth in (2, 3)
                for learning_rate in (0.05, 0.1)
            ]
        else:
            candidate_params = [
                {
                    "n_estimators": int(_float(params.get("n_estimators")) or 30),
                    "max_depth": int(_float(params.get("max_depth")) or 3),
                    "learning_rate": float(_float(params.get("learning_rate")) or 0.08),
                }
            ]
        return self._fit_best_regressor(
            [
                (
                    XGBRegressor(
                        n_estimators=item["n_estimators"],
                        max_depth=item["max_depth"],
                        learning_rate=item["learning_rate"],
                        objective="reg:squarederror",
                        random_state=42,
                    ),
                    item,
                )
                for item in candidate_params
            ],
            X_train,
            y_train,
            X_valid=X_valid,
            y_valid=y_valid,
        )

    def _fit_best_regressor(self, candidates, X_train, y_train, *, X_valid=None, y_valid=None):
        best_model = None
        best_params: Dict[str, object] = {}
        best_score = -float("inf")
        last_error: Optional[Exception] = None
        eval_X = X_valid if X_valid is not None and len(X_valid) else X_train
        eval_y = y_valid if y_valid is not None and len(y_valid) else y_train
        for model, candidate_params in candidates:
            try:
                fitted = model.fit(X_train, y_train)
                predictions = [float(value) for value in fitted.predict(eval_X)]
                score = self._r2_score(list(eval_y), predictions)
            except Exception as exc:
                last_error = exc
                continue
            if best_model is None or score > best_score:
                best_model = fitted
                best_params = dict(candidate_params)
                best_score = score
        if best_model is None:
            raise ValueError(str(last_error) if last_error else "no model candidate could be fitted")
        best_params["validation_r2"] = round(float(best_score), 8)
        return best_model, best_params

    def _regime_detection_rows(self, *, dataset_name: str, source_rows: List[Dict[str, str]], asset_family: str, start_date: str, end_date: str, run_id: str, params: Dict[str, object]):
        groups = self._group_price_series(source_rows)
        returns = self._portfolio_returns(self._returns_by_symbol(groups))
        if not returns:
            reason = "regime detection requires at least two dates with prices"
            model_rows = [self._ml_model_run_row(end_date, run_id, "regime_detection", dataset_name, asset_family, "return", ["return", "volatility"], start_date, start_date, end_date, end_date, False, "not_applicable", reason, "sample_count", "0", {}, dataset_name)]
            return model_rows, [], [], [self._model_diagnostic_row(end_date, run_id, "regime_detection", dataset_name, "input_quality", "return_count", "0", "not_applicable", reason, dataset_name)]
        mean_return = sum(returns) / len(returns)
        vol = self._stddev(returns)
        regime = "risk_on" if mean_return > 0 and vol < 0.03 else "risk_off" if mean_return < 0 else "neutral"
        score = 1.0 if regime == "risk_on" else -1.0 if regime == "risk_off" else 0.0
        model_rows = [self._ml_model_run_row(end_date, run_id, "regime_detection", dataset_name, asset_family, "regime", ["mean_return", "volatility"], start_date, end_date, end_date, end_date, False, "success", "", "regime_score", f"{score:.8f}", {"regime": regime}, dataset_name)]
        prediction_rows = [self._ml_prediction_row(end_date, run_id, "regime_detection", dataset_name, asset_family, {"symbol": "portfolio", "trade_date": end_date}, None, score, "success", regime, dataset_name)]
        feature_rows = [self._ml_feature_row(end_date, run_id, "regime_detection", dataset_name, "mean_return", mean_return, 1, "success", "", dataset_name), self._ml_feature_row(end_date, run_id, "regime_detection", dataset_name, "volatility", vol, 2, "success", "", dataset_name)]
        diagnostics = [self._model_diagnostic_row(end_date, run_id, "regime_detection", dataset_name, "regime", "score", f"{score:.8f}", "success", regime, dataset_name)]
        return model_rows, prediction_rows, feature_rows, diagnostics

    def _option_model_rows(self, *, template_name: str, dataset_name: str, asset_family: str, params: Dict[str, object], params_text: str, start_date: str, end_date: str, run_id: str) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
        option_type = str(params.get("option_type") or "call").lower()
        s = _float(params.get("underlying_price"))
        k = _float(params.get("strike_price"))
        t = _float(params.get("maturity_years") or params.get("time_to_expiry"))
        r = _float(params.get("risk_free_rate"))
        sigma = _float(params.get("volatility"))
        market_price = _float(params.get("market_price"))
        symbol = str(params.get("symbol_or_contract") or params.get("contract") or "model_option")
        status = "success"
        reason = ""
        model_price = iv = delta = gamma = vega = theta = None
        if s is None or k is None or t is None or r is None or (sigma is None and template_name != "black_scholes_iv"):
            status = "not_applicable"
            reason = "requires underlying_price, strike_price, maturity_years, risk_free_rate and volatility"
        elif template_name == "black_scholes_iv" and market_price is None:
            status = "not_applicable"
            reason = "black_scholes_iv requires market_price"
        else:
            if template_name == "binomial_option_price":
                steps = int(_float(params.get("steps")) or 50)
                american = str(params.get("american", "false")).lower() == "true"
                model_price = self._binomial_price(s, k, t, r, sigma or 0.2, option_type, steps=max(1, steps), american=american)
            elif template_name == "black_scholes_iv":
                iv = self._implied_volatility(market_price or 0.0, s, k, t, r, option_type)
                if iv is None:
                    status, reason = "not_applicable", "could not bracket implied volatility"
                else:
                    sigma = iv
                    model_price, delta, gamma, vega, theta = self._bs_metrics(s, k, t, r, sigma, option_type)
            else:
                model_price, delta, gamma, vega, theta = self._bs_metrics(s, k, t, r, sigma or 0.2, option_type)
        option_row = self._option_analytics_row(end_date, asset_family, dataset_name, symbol, template_name, option_type, s, k, t, r, sigma, market_price, model_price, iv, delta, gamma, vega, theta, params_text, start_date, end_date, status, reason, run_id)
        metrics = {
            "model_price": model_price,
            "implied_volatility": iv,
            "delta": delta,
            "gamma": gamma,
            "vega": vega,
            "theta": theta,
        }
        algorithm_rows = [
            self._algorithm_output_row(end_date, asset_family, dataset_name, template_name, "option_math", symbol, metric, "" if value is None else f"{value:.8f}", "value", params_text, start_date, end_date, status, reason if value is None else "", run_id)
            for metric, value in metrics.items()
            if value is not None or metric == "model_price"
        ]
        return option_row, algorithm_rows

    def _bond_model_rows(self, *, template_name: str, dataset_name: str, asset_family: str, params: Dict[str, object], params_text: str, start_date: str, end_date: str, run_id: str) -> Tuple[Dict[str, str], List[Dict[str, str]]]:
        price = _float(params.get("price"))
        coupon_rate = _float(params.get("coupon_rate"))
        maturity_years = _float(params.get("maturity_years"))
        face_value = _float(params.get("face_value")) or 100.0
        frequency = int(_float(params.get("frequency")) or 1)
        symbol = str(params.get("symbol_or_contract") or params.get("bond") or "model_bond")
        status = "success"
        reason = ""
        ytm = duration = modified_duration = convexity = None
        if price is None or coupon_rate is None or maturity_years is None:
            status = "not_applicable"
            reason = "requires price, coupon_rate and maturity_years"
        else:
            ytm = self._bond_ytm(price=price, coupon_rate=coupon_rate, maturity_years=maturity_years, face_value=face_value, frequency=frequency)
            if ytm is None:
                status, reason = "not_applicable", "could not solve YTM"
            else:
                duration, modified_duration, convexity = self._bond_duration_convexity(price=price, coupon_rate=coupon_rate, maturity_years=maturity_years, face_value=face_value, ytm=ytm, frequency=frequency)
        bond_row = self._bond_analytics_row(end_date, asset_family, dataset_name, symbol, template_name, price, coupon_rate, maturity_years, face_value, ytm, duration, modified_duration, convexity, params_text, start_date, end_date, status, reason, run_id)
        metrics = {"ytm": ytm, "duration": duration, "modified_duration": modified_duration, "convexity": convexity}
        algorithm_rows = [
            self._algorithm_output_row(end_date, asset_family, dataset_name, template_name, "bond_math", symbol, metric, "" if value is None else f"{value:.8f}", "value", params_text, start_date, end_date, status, reason if value is None else "", run_id)
            for metric, value in metrics.items()
            if value is not None or metric == "ytm"
        ]
        return bond_row, algorithm_rows

    def _risk_metric_rows(self, *, template_info: AlgorithmTemplate, dataset_name: str, source_rows: List[Dict[str, str]], asset_family: str, start_date: str, end_date: str, params: Dict[str, object], run_id: str) -> List[Dict[str, str]]:
        params_text = safe_json_dumps(params)
        family = asset_family or (str(source_rows[0].get("asset_family", "")) if source_rows else "")
        portfolio_id = str(params.get("portfolio_id") or f"portfolio:{template_info.name}")
        groups = self._group_price_series(source_rows)
        returns_by_symbol = self._returns_by_symbol(groups)
        portfolio_returns = self._portfolio_returns(returns_by_symbol)
        if not portfolio_returns:
            return [self._risk_metric_row(end_date, family, dataset_name, template_info.name, portfolio_id, "coverage", "", "ratio", params_text, start_date, end_date, "not_applicable", "risk metrics require at least two dates with prices", run_id)]

        rows: List[Dict[str, str]] = []
        name = template_info.name
        if name == "var_cvar":
            confidence = float(_float(params.get("confidence")) or 0.95)
            ordered = sorted(portfolio_returns)
            tail_count = max(1, int(math.ceil((1 - confidence) * len(ordered))))
            tail = ordered[:tail_count]
            var_value = -tail[-1]
            cvar_value = -sum(tail) / len(tail)
            rows.append(self._risk_metric_row(end_date, family, dataset_name, name, portfolio_id, "var", f"{var_value:.8f}", "ratio", params_text, start_date, end_date, "success", "", run_id))
            rows.append(self._risk_metric_row(end_date, family, dataset_name, name, portfolio_id, "cvar", f"{cvar_value:.8f}", "ratio", params_text, start_date, end_date, "success", "", run_id))
        elif name == "correlation_matrix":
            symbols = sorted(returns_by_symbol)[:8]
            for left_index, left in enumerate(symbols):
                for right in symbols[left_index + 1 :]:
                    corr = self._correlation(returns_by_symbol[left], returns_by_symbol[right])
                    rows.append(self._risk_metric_row(end_date, family, dataset_name, name, portfolio_id, f"corr:{left}:{right}", "" if corr is None else f"{corr:.8f}", "ratio", params_text, start_date, end_date, "success" if corr is not None else "not_applicable", "" if corr is not None else "requires overlapping returns", run_id))
        elif name == "max_drawdown_control":
            equity = [1.0]
            for value in portfolio_returns:
                equity.append(equity[-1] * (1 + value))
            drawdown = self._max_drawdown(equity)
            rows.append(self._risk_metric_row(end_date, family, dataset_name, name, portfolio_id, "max_drawdown", f"{drawdown:.8f}", "ratio", params_text, start_date, end_date, "success", "", run_id))
        elif name == "volatility_target":
            target = float(_float(params.get("target_volatility")) or 0.12)
            realized = self._stddev(portfolio_returns) * math.sqrt(252)
            leverage = target / realized if realized else 0.0
            rows.append(self._risk_metric_row(end_date, family, dataset_name, name, portfolio_id, "realized_volatility", f"{realized:.8f}", "ratio", params_text, start_date, end_date, "success", "", run_id))
            rows.append(self._risk_metric_row(end_date, family, dataset_name, name, portfolio_id, "target_leverage", f"{leverage:.8f}", "ratio", params_text, start_date, end_date, "success", "", run_id))
        elif name == "position_limits":
            limit = float(_float(params.get("max_weight")) or 0.2)
            weights = self._portfolio_weights(template_name="risk_parity", groups=groups)
            max_weight = max(weights.values()) if weights else 0.0
            rows.append(self._risk_metric_row(end_date, family, dataset_name, name, portfolio_id, "max_weight", f"{max_weight:.8f}", "ratio", params_text, start_date, end_date, "success" if max_weight <= limit else "partial_success", "" if max_weight <= limit else f"max weight exceeds limit {limit}", run_id))
        else:
            mean_return = sum(portfolio_returns) / len(portfolio_returns)
            vol = self._stddev(portfolio_returns)
            rows.append(self._risk_metric_row(end_date, family, dataset_name, name, portfolio_id, "mean_daily_return", f"{mean_return:.8f}", "ratio", params_text, start_date, end_date, "success", "", run_id))
            rows.append(self._risk_metric_row(end_date, family, dataset_name, name, portfolio_id, "daily_volatility", f"{vol:.8f}", "ratio", params_text, start_date, end_date, "success", "", run_id))
        return rows

    def _portfolio_allocation_rows(self, *, template_info: AlgorithmTemplate, dataset_name: str, source_rows: List[Dict[str, str]], asset_family: str, start_date: str, end_date: str, params: Dict[str, object], run_id: str) -> List[Dict[str, str]]:
        params_text = safe_json_dumps(params)
        family = asset_family or (str(source_rows[0].get("asset_family", "")) if source_rows else "")
        portfolio_id = str(params.get("portfolio_id") or f"portfolio:{template_info.name}")
        initial_cash = float(_float(params.get("initial_cash")) or 1_000_000.0)
        groups = self._group_price_series(source_rows)
        weights = self._portfolio_weights(template_name=template_info.name, groups=groups)
        if not weights:
            return [self._portfolio_allocation_row(end_date, portfolio_id, template_info.name, family, dataset_name, "", "", "", params_text, start_date, end_date, "not_applicable", "portfolio optimization requires price history", run_id)]
        rows = []
        for symbol, weight in sorted(weights.items(), key=lambda item: item[0])[:50]:
            rows.append(self._portfolio_allocation_row(end_date, portfolio_id, template_info.name, family, dataset_name, symbol, f"{weight:.8f}", f"{initial_cash * weight:.6f}", params_text, start_date, end_date, "success", "", run_id))
        return rows

    def _backtest_input_quality_rows(self, *, dataset_name: str, source_rows: List[Dict[str, str]], strategy: str, start_date: str, end_date: str, run_id: str) -> List[Dict[str, str]]:
        groups = self._group_price_series(source_rows)
        asset_family = str(source_rows[0].get("asset_family", "")) if source_rows else ""
        rows: List[Dict[str, str]] = []
        if not source_rows:
            return [self._backtest_input_quality_row(end_date, run_id, strategy, dataset_name, asset_family, "", "no_source_rows", "critical", "row_count", "0", "回测窗口没有源数据。", "先同步该数据集历史窗口，或缩短回测区间。", start_date, end_date)]
        if not groups:
            return [self._backtest_input_quality_row(end_date, run_id, strategy, dataset_name, asset_family, "", "no_price_series", "critical", "priced_symbol_count", "0", "源数据存在，但没有可用于回测的价格字段。", "检查 close/price/value/nav/mid/price_usd 字段。", start_date, end_date)]
        short_symbols = [symbol for symbol, items in groups.items() if len(items) < 2]
        rows.append(self._backtest_input_quality_row(end_date, run_id, strategy, dataset_name, asset_family, "ALL", "coverage", "info", "priced_symbol_count", str(len(groups)), "回测可用价格序列覆盖统计。", "覆盖足够时可继续运行；覆盖不足时应扩大历史窗口。", start_date, end_date))
        if short_symbols:
            rows.append(self._backtest_input_quality_row(end_date, run_id, strategy, dataset_name, asset_family, "MULTI", "short_history", "warning", "short_symbol_count", str(len(short_symbols)), "部分标的价格点少于 2 个，无法贡献收益序列。", "优先补历史窗口，或在策略参数中降低持仓数量。", start_date, end_date))
        return rows

    def _backtest_detail_rows(self, *, dataset_name: str, source_rows: List[Dict[str, str]], strategy: str, initial_cash: float, fee_bps: float, slippage_bps: float, start_date: str, end_date: str, params: Dict[str, object], run_id: str):
        params_text = safe_json_dumps(params)
        groups = self._group_price_series(source_rows)
        returns_by_symbol = self._returns_by_symbol(groups)
        by_date: Dict[str, List[float]] = defaultdict(list)
        asset_family = ""
        for symbol, items in groups.items():
            asset_family = asset_family or str(items[-1][2].get("asset_family", ""))
            for index in range(1, len(items)):
                previous = items[index - 1][1]
                if previous:
                    by_date[items[index][0]].append(items[index][1] / previous - 1)
        if not by_date:
            equity_row = self._backtest_equity_row(end_date, strategy, asset_family, dataset_name, initial_cash, "", "", "", "", fee_bps, slippage_bps, params_text, start_date, end_date, "not_applicable", "backtest requires at least two dates with prices", run_id)
            comparison_row = self._strategy_comparison_row(end_date, strategy, "equal_weight_benchmark", dataset_name, "total_return", "", "", "", params_text, start_date, end_date, "not_applicable", "backtest requires at least two dates with prices", run_id)
            return [equity_row], [], [], [comparison_row]

        portfolio_value = initial_cash
        peak = initial_cash
        equity_rows = []
        daily_returns = []
        for trade_date in sorted(by_date):
            gross_return = sum(by_date[trade_date]) / len(by_date[trade_date])
            turnover = min(1.0, len(by_date[trade_date]) / max(len(groups), 1))
            cost = turnover * (fee_bps + slippage_bps) / 10000.0
            net_return = gross_return - cost
            daily_returns.append(net_return)
            portfolio_value *= 1 + net_return
            peak = max(peak, portfolio_value)
            drawdown = portfolio_value / peak - 1 if peak else 0.0
            equity_rows.append(self._backtest_equity_row(trade_date, strategy, asset_family, dataset_name, portfolio_value, net_return, portfolio_value / initial_cash - 1, drawdown, turnover, fee_bps, slippage_bps, params_text, start_date, end_date, "success", "", run_id))

        weights = self._portfolio_weights(template_name=strategy, groups=groups)
        latest_prices = {symbol: items[-1][1] for symbol, items in groups.items() if items and items[-1][1] > 0}
        if not weights:
            weights = {symbol: 1 / len(latest_prices) for symbol in latest_prices} if latest_prices else {}
        position_rows = []
        trade_rows = []
        for symbol, weight in sorted(weights.items(), key=lambda item: item[0])[:50]:
            price = latest_prices.get(symbol, 0.0)
            market_value = portfolio_value * weight
            quantity = market_value / price if price else 0.0
            position_rows.append(self._backtest_position_row(end_date, strategy, asset_family, dataset_name, symbol, quantity, price, market_value, weight, "long", params_text, start_date, end_date, "success", "", run_id))
            fee = market_value * fee_bps / 10000.0
            slippage = market_value * slippage_bps / 10000.0
            trade_rows.append(self._backtest_trade_row(end_date, strategy, asset_family, dataset_name, symbol, "rebalance_buy", quantity, price, market_value, fee, slippage, market_value + fee + slippage, params_text, start_date, end_date, "success", "", run_id))

        total_return = portfolio_value / initial_cash - 1
        max_dd = min((_float(row.get("drawdown")) or 0.0 for row in equity_rows), default=0.0)
        vol = self._stddev(daily_returns) * math.sqrt(252) if len(daily_returns) > 1 else 0.0
        comparison_rows = [
            self._strategy_comparison_row(end_date, strategy, "equal_weight_benchmark", dataset_name, "total_return", f"{total_return:.8f}", f"{total_return:.8f}", "0.00000000", params_text, start_date, end_date, "success", "", run_id),
            self._strategy_comparison_row(end_date, strategy, "equal_weight_benchmark", dataset_name, "max_drawdown", f"{max_dd:.8f}", f"{max_dd:.8f}", "0.00000000", params_text, start_date, end_date, "success", "", run_id),
            self._strategy_comparison_row(end_date, strategy, "equal_weight_benchmark", dataset_name, "annualized_volatility", f"{vol:.8f}", f"{vol:.8f}", "0.00000000", params_text, start_date, end_date, "success", "", run_id),
        ]
        return equity_rows, position_rows, trade_rows, comparison_rows

    def _research_metric_rows(
        self,
        *,
        dataset_name: str,
        source_rows: List[Dict[str, str]],
        start_date: str,
        end_date: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        if not source_rows:
            return [
                self._research_row(
                    trade_date=end_date,
                    asset_family="",
                    dataset_name=dataset_name,
                    metric_name="coverage",
                    metric_value="",
                    metric_unit="",
                    sample_count=0,
                    start_date=start_date,
                    end_date=end_date,
                    status="not_applicable",
                    reason="source dataset has no rows in selected window",
                    run_id=run_id,
                )
            ]
        asset_family = str(source_rows[0].get("asset_family", ""))
        values = self._extract_dataset_values(source_rows)
        volume_values = [item for item in (_float(row.get(field)) for row in source_rows for field in VOLUME_FIELDS if row.get(field) not in (None, "")) if item is not None]
        rows = [
            self._research_row(end_date, asset_family, dataset_name, "sample_count", str(len(source_rows)), "rows", len(source_rows), start_date, end_date, "success", "", run_id),
        ]
        if values:
            rows.append(self._research_row(end_date, asset_family, dataset_name, "rolling_mean", f"{sum(values) / len(values):.8f}", "value", len(values), start_date, end_date, "success", "", run_id))
            rows.append(self._research_row(end_date, asset_family, dataset_name, "max_drawdown", f"{self._max_drawdown(values):.8f}", "ratio", len(values), start_date, end_date, "success", "", run_id))
            if len(values) >= 2 and values[0]:
                rows.append(self._research_row(end_date, asset_family, dataset_name, "return", f"{(values[-1] / values[0] - 1):.8f}", "ratio", len(values), start_date, end_date, "success", "", run_id))
            else:
                rows.append(self._research_row(end_date, asset_family, dataset_name, "return", "", "ratio", len(values), start_date, end_date, "not_applicable", "requires at least two numeric observations", run_id))
            returns = self._returns(values)
            if len(returns) >= 2:
                rows.append(self._research_row(end_date, asset_family, dataset_name, "volatility", f"{self._stddev(returns):.8f}", "ratio", len(returns), start_date, end_date, "success", "", run_id))
            else:
                rows.append(self._research_row(end_date, asset_family, dataset_name, "volatility", "", "ratio", len(returns), start_date, end_date, "not_applicable", "requires at least three numeric observations", run_id))
        else:
            rows.append(self._research_row(end_date, asset_family, dataset_name, "rolling_mean", "", "value", 0, start_date, end_date, "not_applicable", "no supported numeric price field", run_id))
        if len(volume_values) >= 2 and volume_values[0]:
            rows.append(self._research_row(end_date, asset_family, dataset_name, "volume_change", f"{(volume_values[-1] / volume_values[0] - 1):.8f}", "ratio", len(volume_values), start_date, end_date, "success", "", run_id))
        else:
            rows.append(self._research_row(end_date, asset_family, dataset_name, "volume_change", "", "ratio", len(volume_values), start_date, end_date, "not_applicable", "requires at least two volume observations", run_id))
        if dataset_name == YIELD_CURVES_PLATFORM_DATASET:
            slope = self._curve_slope(source_rows)
            rows.append(self._research_row(end_date, asset_family, dataset_name, "curve_slope", f"{slope:.8f}" if slope is not None else "", "bp", len(source_rows), start_date, end_date, "success" if slope is not None else "not_applicable", "" if slope is not None else "requires short and long tenors", run_id))
        return rows

    def _research_row(self, trade_date, asset_family, dataset_name, metric_name, metric_value, metric_unit, sample_count, start_date, end_date, status, reason, run_id) -> Dict[str, str]:
        checksum = _sha1_text(f"{trade_date}:{dataset_name}:{asset_family}:{metric_name}:{metric_value}:{status}")
        return {
            "trade_date": trade_date,
            "asset_family": asset_family,
            "dataset": dataset_name,
            "metric_name": metric_name,
            "metric_value": metric_value,
            "metric_unit": metric_unit,
            "sample_count": str(sample_count),
            "window_start": start_date,
            "window_end": end_date,
            "status": status,
            "reason": reason,
            "source_dataset": dataset_name,
            "source_id": "platform.research",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": checksum,
            "run_id": run_id,
        }

    def _factor_rows(self, *, dataset_name: str, source_rows: List[Dict[str, str]], factor: str, run_id: str, end_date: str) -> List[Dict[str, str]]:
        groups = self._group_price_series(source_rows)
        rows: List[Dict[str, str]] = []
        if not groups:
            return [
                self._factor_row(end_date, "", dataset_name, "", factor, "", "flat", "not_applicable", "no supported close price observations", run_id)
            ]
        for symbol, items in sorted(groups.items()):
            values = [value for _date, value, _row in items]
            asset_family = str(items[-1][2].get("asset_family", ""))
            status = "success"
            reason = ""
            factor_value = ""
            direction = "flat"
            if factor in {"momentum", "etf_momentum"}:
                if len(values) >= 2 and values[0]:
                    value = values[-1] / values[0] - 1
                    factor_value = f"{value:.8f}"
                    direction = "long" if value > 0 else "short" if value < 0 else "flat"
                else:
                    status, reason = "not_applicable", "momentum requires at least two observations"
            elif factor == "mean_reversion":
                mean_value = sum(values) / len(values)
                if mean_value:
                    value = -(values[-1] / mean_value - 1)
                    factor_value = f"{value:.8f}"
                    direction = "long" if value > 0 else "short" if value < 0 else "flat"
                else:
                    status, reason = "not_applicable", "mean price is zero"
            elif factor == "volatility_filter":
                returns = self._returns(values)
                if len(returns) >= 2:
                    value = self._stddev(returns)
                    factor_value = f"{value:.8f}"
                    direction = "long" if value <= 0.02 else "flat"
                else:
                    status, reason = "not_applicable", "volatility requires at least three observations"
            elif factor == "volume_turnover":
                volume_values = [value for _date, _price, row in items for value in [self._first_float(row, VOLUME_FIELDS + ("turnover_rate",))] if value is not None]
                if len(volume_values) >= 2 and volume_values[0]:
                    value = volume_values[-1] / volume_values[0] - 1
                    factor_value = f"{value:.8f}"
                    direction = "long" if value > 0 else "short" if value < 0 else "flat"
                else:
                    status, reason = "not_applicable", "volume_turnover requires at least two volume/turnover observations"
            elif factor == "cross_asset_rank":
                if len(values) >= 2 and values[0]:
                    value = values[-1] / values[0] - 1
                    factor_value = f"{value:.8f}"
                    direction = "long" if value > 0 else "short" if value < 0 else "flat"
                else:
                    status, reason = "not_applicable", "cross_asset_rank requires at least two observations"
            else:
                status, reason = "not_applicable", f"unsupported factor: {factor}"
            rows.append(self._factor_row(end_date, asset_family, dataset_name, symbol, factor, factor_value, direction, status, reason, run_id))
        if factor == "cross_asset_rank":
            successful = [row for row in rows if row.get("status") == "success" and _float(row.get("factor_value")) is not None]
            successful.sort(key=lambda item: _float(item.get("factor_value")) or 0.0, reverse=True)
            denominator = max(len(successful) - 1, 1)
            rank_map = {row.get("symbol_or_contract", ""): index / denominator for index, row in enumerate(successful)}
            for row in rows:
                symbol = row.get("symbol_or_contract", "")
                if symbol in rank_map:
                    score = 1.0 - rank_map[symbol]
                    row["factor_value"] = f"{score:.8f}"
                    row["signal_direction"] = "long" if score >= 0.67 else "short" if score <= 0.33 else "flat"
                    row["checksum"] = _sha1_text(f"{end_date}:{dataset_name}:{symbol}:{factor}:{score}:{row['signal_direction']}:{row['status']}")
        return rows

    def _factor_row(self, trade_date, asset_family, dataset_name, symbol, factor, factor_value, direction, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "asset_family": asset_family,
            "dataset": dataset_name,
            "symbol_or_contract": symbol,
            "factor_name": factor,
            "factor_value": factor_value,
            "signal_direction": direction,
            "source_dataset": dataset_name,
            "status": status,
            "reason": reason,
            "source_id": "platform.factor",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{dataset_name}:{symbol}:{factor}:{factor_value}:{direction}:{status}"),
            "run_id": run_id,
        }

    def _algorithm_output_row(self, trade_date, asset_family, dataset_name, template_name, category, symbol, metric_name, metric_value, metric_unit, parameters, start_date, end_date, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "asset_family": str(asset_family),
            "dataset": str(dataset_name),
            "template_name": str(template_name),
            "category": str(category),
            "symbol_or_contract": str(symbol),
            "metric_name": str(metric_name),
            "metric_value": str(metric_value),
            "metric_unit": str(metric_unit),
            "parameters": str(parameters),
            "window_start": str(start_date),
            "window_end": str(end_date),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(dataset_name),
            "source_id": "platform.algorithm",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{dataset_name}:{template_name}:{symbol}:{metric_name}:{metric_value}:{status}"),
            "run_id": run_id,
        }

    def _option_analytics_row(self, trade_date, asset_family, dataset_name, symbol, model_name, option_type, s, k, t, r, sigma, market_price, model_price, iv, delta, gamma, vega, theta, parameters, start_date, end_date, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "asset_family": str(asset_family),
            "dataset": str(dataset_name),
            "symbol_or_contract": str(symbol),
            "model_name": str(model_name),
            "option_type": str(option_type),
            "underlying_price": self._fmt_optional(s),
            "strike_price": self._fmt_optional(k),
            "time_to_expiry": self._fmt_optional(t),
            "risk_free_rate": self._fmt_optional(r),
            "volatility": self._fmt_optional(sigma),
            "market_price": self._fmt_optional(market_price),
            "model_price": self._fmt_optional(model_price),
            "implied_volatility": self._fmt_optional(iv),
            "delta": self._fmt_optional(delta),
            "gamma": self._fmt_optional(gamma),
            "vega": self._fmt_optional(vega),
            "theta": self._fmt_optional(theta),
            "parameters": str(parameters),
            "window_start": str(start_date),
            "window_end": str(end_date),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(dataset_name),
            "source_id": "platform.option_analytics",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{dataset_name}:{symbol}:{model_name}:{model_price}:{status}"),
            "run_id": run_id,
        }

    def _bond_analytics_row(self, trade_date, asset_family, dataset_name, symbol, model_name, price, coupon_rate, maturity_years, face_value, ytm, duration, modified_duration, convexity, parameters, start_date, end_date, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "asset_family": str(asset_family),
            "dataset": str(dataset_name),
            "symbol_or_contract": str(symbol),
            "model_name": str(model_name),
            "price": self._fmt_optional(price),
            "coupon_rate": self._fmt_optional(coupon_rate),
            "maturity_years": self._fmt_optional(maturity_years),
            "face_value": self._fmt_optional(face_value),
            "ytm": self._fmt_optional(ytm),
            "duration": self._fmt_optional(duration),
            "modified_duration": self._fmt_optional(modified_duration),
            "convexity": self._fmt_optional(convexity),
            "parameters": str(parameters),
            "window_start": str(start_date),
            "window_end": str(end_date),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(dataset_name),
            "source_id": "platform.bond_analytics",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{dataset_name}:{symbol}:{model_name}:{ytm}:{status}"),
            "run_id": run_id,
        }

    def _curve_analytics_row(self, trade_date, asset_family, dataset_name, curve_name, model_name, tenor_short, tenor_long, value_short, value_long, slope, spread, parameters, start_date, end_date, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "asset_family": str(asset_family),
            "dataset": str(dataset_name),
            "curve_name": str(curve_name),
            "model_name": str(model_name),
            "tenor_short": str(tenor_short),
            "tenor_long": str(tenor_long),
            "value_short": str(value_short),
            "value_long": str(value_long),
            "slope": str(slope),
            "spread": str(spread),
            "parameters": str(parameters),
            "window_start": str(start_date),
            "window_end": str(end_date),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(dataset_name),
            "source_id": "platform.curve_analytics",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{dataset_name}:{curve_name}:{model_name}:{slope}:{status}"),
            "run_id": run_id,
        }

    def _risk_metric_row(self, trade_date, asset_family, dataset_name, template_name, portfolio_id, metric_name, metric_value, metric_unit, parameters, start_date, end_date, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "asset_family": str(asset_family),
            "dataset": str(dataset_name),
            "template_name": str(template_name),
            "portfolio_id": str(portfolio_id),
            "metric_name": str(metric_name),
            "metric_value": str(metric_value),
            "metric_unit": str(metric_unit),
            "parameters": str(parameters),
            "window_start": str(start_date),
            "window_end": str(end_date),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(dataset_name),
            "source_id": "platform.risk",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{dataset_name}:{template_name}:{portfolio_id}:{metric_name}:{metric_value}:{status}"),
            "run_id": run_id,
        }

    def _portfolio_allocation_row(self, trade_date, portfolio_id, template_name, asset_family, dataset_name, symbol, weight, notional, parameters, start_date, end_date, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "portfolio_id": str(portfolio_id),
            "template_name": str(template_name),
            "asset_family": str(asset_family),
            "dataset": str(dataset_name),
            "symbol_or_contract": str(symbol),
            "weight": str(weight),
            "notional": str(notional),
            "parameters": str(parameters),
            "window_start": str(start_date),
            "window_end": str(end_date),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(dataset_name),
            "source_id": "platform.portfolio",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{portfolio_id}:{template_name}:{symbol}:{weight}:{status}"),
            "run_id": run_id,
        }

    def _backtest_equity_row(self, trade_date, strategy, asset_family, dataset_name, portfolio_value, daily_return, cumulative_return, drawdown, turnover, fee_bps, slippage_bps, parameters, start_date, end_date, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "strategy_name": str(strategy),
            "asset_family": str(asset_family),
            "dataset": str(dataset_name),
            "portfolio_value": self._fmt_optional(portfolio_value),
            "daily_return": self._fmt_optional(daily_return),
            "cumulative_return": self._fmt_optional(cumulative_return),
            "drawdown": self._fmt_optional(drawdown),
            "turnover": self._fmt_optional(turnover),
            "fee_bps": self._fmt_optional(fee_bps),
            "slippage_bps": self._fmt_optional(slippage_bps),
            "parameters": str(parameters),
            "window_start": str(start_date),
            "window_end": str(end_date),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(dataset_name),
            "source_id": "platform.backtest",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{strategy}:{dataset_name}:{portfolio_value}:{daily_return}:{status}"),
            "run_id": run_id,
        }

    def _backtest_position_row(self, trade_date, strategy, asset_family, dataset_name, symbol, quantity, price, market_value, weight, side, parameters, start_date, end_date, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "strategy_name": str(strategy),
            "asset_family": str(asset_family),
            "dataset": str(dataset_name),
            "symbol_or_contract": str(symbol),
            "quantity": self._fmt_optional(quantity),
            "price": self._fmt_optional(price),
            "market_value": self._fmt_optional(market_value),
            "weight": self._fmt_optional(weight),
            "side": str(side),
            "parameters": str(parameters),
            "window_start": str(start_date),
            "window_end": str(end_date),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(dataset_name),
            "source_id": "platform.backtest",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{strategy}:{dataset_name}:{symbol}:{market_value}:{status}"),
            "run_id": run_id,
        }

    def _backtest_trade_row(self, trade_date, strategy, asset_family, dataset_name, symbol, side, quantity, price, notional, fee, slippage, total_cost, parameters, start_date, end_date, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "strategy_name": str(strategy),
            "asset_family": str(asset_family),
            "dataset": str(dataset_name),
            "symbol_or_contract": str(symbol),
            "side": str(side),
            "quantity": self._fmt_optional(quantity),
            "price": self._fmt_optional(price),
            "notional": self._fmt_optional(notional),
            "fee": self._fmt_optional(fee),
            "slippage": self._fmt_optional(slippage),
            "total_cost": self._fmt_optional(total_cost),
            "parameters": str(parameters),
            "window_start": str(start_date),
            "window_end": str(end_date),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(dataset_name),
            "source_id": "platform.backtest",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{strategy}:{dataset_name}:{symbol}:{side}:{notional}:{status}"),
            "run_id": run_id,
        }

    def _strategy_comparison_row(self, trade_date, strategy, benchmark_name, dataset_name, metric_name, strategy_value, benchmark_value, difference, parameters, start_date, end_date, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "strategy_name": str(strategy),
            "benchmark_name": str(benchmark_name),
            "dataset": str(dataset_name),
            "metric_name": str(metric_name),
            "strategy_value": str(strategy_value),
            "benchmark_value": str(benchmark_value),
            "difference": str(difference),
            "parameters": str(parameters),
            "window_start": str(start_date),
            "window_end": str(end_date),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(dataset_name),
            "source_id": "platform.strategy_comparison",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{strategy}:{benchmark_name}:{metric_name}:{strategy_value}:{status}"),
            "run_id": run_id,
        }

    def _backtest_input_quality_row(self, trade_date, run_id, strategy_name, dataset_name, asset_family, symbol, issue_type, severity, metric_name, metric_value, message, recommendation, start_date, end_date) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "run_id": str(run_id),
            "strategy_name": str(strategy_name),
            "dataset": str(dataset_name),
            "asset_family": str(asset_family),
            "symbol_or_contract": str(symbol),
            "issue_type": str(issue_type),
            "severity": str(severity),
            "metric_name": str(metric_name),
            "metric_value": str(metric_value),
            "message": str(message),
            "recommendation": str(recommendation),
            "source_dataset": str(dataset_name),
            "source_id": "platform.backtest_input_quality",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{run_id}:{strategy_name}:{dataset_name}:{symbol}:{issue_type}:{metric_value}"),
        }

    def _ml_model_run_row(self, trade_date, run_id, template_name, dataset_name, asset_family, target_field, feature_fields, train_start, train_end, test_start, test_end, tuned, status, reason, score_metric, score_value, best_params, source_dataset) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "run_id": str(run_id),
            "template_name": str(template_name),
            "dataset": str(dataset_name),
            "asset_family": str(asset_family),
            "target_field": str(target_field),
            "feature_fields": ",".join(str(item) for item in feature_fields),
            "train_start": str(train_start),
            "train_end": str(train_end),
            "test_start": str(test_start),
            "test_end": str(test_end),
            "tuned": str(bool(tuned)).lower(),
            "status": str(status),
            "reason": str(reason),
            "score_metric": str(score_metric),
            "score_value": str(score_value),
            "best_params": safe_json_dumps(best_params),
            "source_dataset": str(source_dataset),
            "source_id": "platform.ml",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{run_id}:{template_name}:{dataset_name}:{score_metric}:{score_value}:{status}"),
        }

    def _ml_prediction_row(self, trade_date, run_id, template_name, dataset_name, asset_family, meta, actual, predicted, status, reason, source_dataset) -> Dict[str, str]:
        symbol = str(meta.get("instrument_id") or meta.get("symbol") or meta.get("contract") or "portfolio")
        prediction_date = str(meta.get("trade_date") or trade_date)
        residual = "" if actual is None else self._fmt_optional(float(actual) - float(predicted))
        return {
            "trade_date": str(trade_date),
            "run_id": str(run_id),
            "template_name": str(template_name),
            "dataset": str(dataset_name),
            "asset_family": str(asset_family or meta.get("asset_family", "")),
            "symbol_or_contract": symbol,
            "prediction_date": prediction_date,
            "actual_value": "" if actual is None else self._fmt_optional(actual),
            "predicted_value": self._fmt_optional(predicted),
            "residual": residual,
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(source_dataset),
            "source_id": "platform.ml",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{run_id}:{template_name}:{symbol}:{prediction_date}:{predicted}:{status}"),
        }

    def _ml_feature_row(self, trade_date, run_id, template_name, dataset_name, feature_name, importance, rank, status, reason, source_dataset) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "run_id": str(run_id),
            "template_name": str(template_name),
            "dataset": str(dataset_name),
            "feature_name": str(feature_name),
            "importance_value": self._fmt_optional(importance),
            "rank": str(rank),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(source_dataset),
            "source_id": "platform.ml",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{run_id}:{template_name}:{feature_name}:{importance}:{status}"),
        }

    def _model_diagnostic_row(self, trade_date, run_id, template_name, dataset_name, diagnostic_type, metric_name, metric_value, status, reason, source_dataset) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "run_id": str(run_id),
            "template_name": str(template_name),
            "dataset": str(dataset_name),
            "diagnostic_type": str(diagnostic_type),
            "metric_name": str(metric_name),
            "metric_value": str(metric_value),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(source_dataset),
            "source_id": "platform.model_diagnostics",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{run_id}:{template_name}:{diagnostic_type}:{metric_name}:{metric_value}:{status}"),
        }

    def _factor_performance_row(self, trade_date, factor_name, dataset_name, asset_family, metric_name, metric_value, sample_count, start_date, end_date, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "factor_name": str(factor_name),
            "dataset": str(dataset_name),
            "asset_family": str(asset_family),
            "metric_name": str(metric_name),
            "metric_value": str(metric_value),
            "sample_count": str(sample_count),
            "window_start": str(start_date),
            "window_end": str(end_date),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(dataset_name),
            "source_id": "platform.factor_performance",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{factor_name}:{dataset_name}:{metric_name}:{metric_value}:{status}"),
            "run_id": run_id,
        }

    def _stress_test_row(self, trade_date, run_id, template_name, scenario_name, dataset_name, asset_family, portfolio_id, metric_name, base_value, stressed_value, impact_value, impact_pct, parameters, start_date, end_date, status, reason, source_dataset) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "run_id": str(run_id),
            "template_name": str(template_name),
            "scenario_name": str(scenario_name),
            "dataset": str(dataset_name),
            "asset_family": str(asset_family),
            "portfolio_id": str(portfolio_id),
            "metric_name": str(metric_name),
            "base_value": self._fmt_optional(base_value),
            "stressed_value": self._fmt_optional(stressed_value),
            "impact_value": self._fmt_optional(impact_value),
            "impact_pct": self._fmt_optional(impact_pct),
            "parameters": safe_json_dumps(parameters),
            "window_start": str(start_date),
            "window_end": str(end_date),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(source_dataset),
            "source_id": "platform.stress_test",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{run_id}:{template_name}:{scenario_name}:{metric_name}:{impact_value}:{status}"),
        }

    def _dataset_quality_score_row(self, trade_date, dataset_name, asset_family, score, completeness, freshness, source_health, anomaly_score, row_count, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "dataset": str(dataset_name),
            "asset_family": str(asset_family),
            "quality_score": f"{float(score):.8f}",
            "completeness_score": f"{float(completeness):.8f}",
            "freshness_score": f"{float(freshness):.8f}",
            "source_health_score": f"{float(source_health):.8f}",
            "anomaly_score": f"{float(anomaly_score):.8f}",
            "row_count": str(row_count),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(dataset_name),
            "source_id": "platform.quality_score",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{dataset_name}:{score}:{status}:{row_count}"),
            "run_id": run_id,
        }

    def _strategy_rows(self, *, dataset_name: str, source_rows: List[Dict[str, str]], strategy: str, initial_cash: float, fee_bps: float, start_date: str, end_date: str, run_id: str) -> List[Dict[str, str]]:
        groups = self._group_price_series(source_rows)
        by_date: Dict[str, List[float]] = defaultdict(list)
        asset_family = ""
        for items in groups.values():
            asset_family = asset_family or str(items[-1][2].get("asset_family", ""))
            for index in range(1, len(items)):
                previous = items[index - 1][1]
                current = items[index][1]
                if previous:
                    by_date[items[index][0]].append(current / previous - 1)
        if not by_date:
            return [
                self._strategy_row(end_date, strategy, asset_family, dataset_name, initial_cash, initial_cash, 0, "", "0", "0", "0", fee_bps, 0, "not_applicable", "backtest requires at least two dates with prices", start_date, end_date, run_id)
            ]
        portfolio_value = initial_cash
        peak = initial_cash
        rows: List[Dict[str, str]] = []
        for trade_date in sorted(by_date):
            daily_return = sum(by_date[trade_date]) / len(by_date[trade_date])
            turnover = min(1.0, len(by_date[trade_date]) / max(len(groups), 1))
            cost = turnover * fee_bps / 10000.0
            net_return = daily_return - cost
            portfolio_value *= (1 + net_return)
            peak = max(peak, portfolio_value)
            drawdown = portfolio_value / peak - 1 if peak else 0
            rows.append(
                self._strategy_row(
                    trade_date,
                    strategy,
                    asset_family,
                    dataset_name,
                    portfolio_value,
                    0.0,
                    len(by_date[trade_date]),
                    net_return,
                    portfolio_value / initial_cash - 1,
                    drawdown,
                    turnover,
                    fee_bps,
                    len(by_date[trade_date]),
                    "success",
                    "",
                    start_date,
                    end_date,
                    run_id,
                )
            )
        return rows

    def _strategy_row(self, trade_date, strategy, asset_family, dataset_name, portfolio_value, cash, position_count, daily_return, cumulative_return, drawdown, turnover, fee_bps, trade_count, status, reason, start_date, end_date, run_id) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "strategy_name": strategy,
            "asset_family": asset_family,
            "dataset": dataset_name,
            "portfolio_value": f"{float(portfolio_value):.6f}",
            "cash": f"{float(cash):.6f}",
            "position_count": str(position_count),
            "daily_return": "" if daily_return == "" else f"{float(daily_return):.8f}",
            "cumulative_return": str(cumulative_return) if isinstance(cumulative_return, str) else f"{float(cumulative_return):.8f}",
            "drawdown": str(drawdown) if isinstance(drawdown, str) else f"{float(drawdown):.8f}",
            "turnover": str(turnover) if isinstance(turnover, str) else f"{float(turnover):.8f}",
            "fee_bps": f"{float(fee_bps):.4f}",
            "trade_count": str(trade_count),
            "status": status,
            "reason": reason,
            "window_start": start_date,
            "window_end": end_date,
            "source_dataset": dataset_name,
            "source_id": "platform.strategy_backtest",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{strategy}:{portfolio_value}:{status}:{reason}"),
            "run_id": run_id,
        }

    def _paper_rows(self, *, dataset_name: str, source_rows: List[Dict[str, str]], strategy: str, initial_cash: float, trade_date: str, run_id: str) -> List[Dict[str, str]]:
        groups = self._group_price_series(source_rows)
        candidates = []
        for symbol, items in groups.items():
            price = items[-1][1]
            if price > 0:
                candidates.append((symbol, price, items[-1][2]))
        candidates = sorted(candidates)[:5]
        if not candidates:
            return [
                self._paper_row(trade_date, strategy, "", dataset_name, "paper:empty", initial_cash, 0.0, initial_cash, [], [], "not_applicable", "no valid price rows for paper simulation", run_id)
            ]
        budget = initial_cash * 0.95 / len(candidates)
        positions = []
        market_value = 0.0
        asset_family = str(candidates[0][2].get("asset_family", ""))
        for symbol, price, _row in candidates:
            quantity = math.floor(budget / price)
            value = quantity * price
            market_value += value
            positions.append({"symbol": symbol, "quantity": quantity, "price": price, "market_value": value})
        cash = initial_cash - market_value
        return [
            self._paper_row(trade_date, strategy, asset_family, dataset_name, f"paper:{strategy}", cash, market_value, cash + market_value, positions, positions, "success", "", run_id)
        ]

    def _paper_row(self, trade_date, strategy, asset_family, dataset_name, portfolio_id, cash, market_value, equity, positions, trades, status, reason, run_id) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "strategy_name": strategy,
            "asset_family": asset_family,
            "dataset": dataset_name,
            "portfolio_id": portfolio_id,
            "cash": f"{float(cash):.6f}",
            "market_value": f"{float(market_value):.6f}",
            "equity": f"{float(equity):.6f}",
            "position_count": str(len(positions)),
            "trade_count": str(len(trades)),
            "positions": safe_json_dumps(positions),
            "trades": safe_json_dumps(trades),
            "status": status,
            "reason": reason,
            "source_id": "platform.paper_sim",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{strategy}:{portfolio_id}:{equity}:{status}"),
            "run_id": run_id,
        }

    def _quality_rows(self, *, trade_date: str, run_id: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        source_rows = self._load_platform_rows("source_health", trade_date)
        coverage_rows = self._load_platform_rows("asset_coverage", trade_date)
        validation_rows = self._load_platform_rows("validation_results", trade_date)
        for row in source_rows:
            status = str(row.get("last_status", ""))
            issue_category = str(row.get("issue_category", ""))
            if status == "success" and issue_category in {"", "healthy"}:
                continue
            severity = self._source_health_severity(row)
            recommendation = "合法空表或不适用，保持记录即可。"
            if severity == "warning":
                recommendation = "确认源站发布时间/网络后重试；不要伪造 success。"
            elif severity == "critical":
                recommendation = "优先检查源站、schema、raw 路径或重跑对应同步任务。"
            rows.append(self._quality_row(trade_date, "source_health", row.get("asset_family", ""), row.get("dataset", ""), row.get("source_id", ""), status, severity, issue_category, "1", row.get("message", "") or row.get("blocked_reason", ""), recommendation, row.get("source_url", ""), row.get("source_type", ""), row.get("output_path", ""), run_id))
        for row in coverage_rows:
            runtime_status = str(row.get("runtime_status", ""))
            if runtime_status in {"", "success"}:
                continue
            severity = self._coverage_severity(row)
            rows.append(self._quality_row(trade_date, "asset_coverage", row.get("asset_family", ""), "asset_coverage", "", runtime_status, severity, "coverage", row.get("coverage_ratio", ""), f"{row.get('family_label', '')} runtime={runtime_status}", "检查对应 source health 与窗口同步状态。", "platform://asset_coverage", "derived", row.get("raw_path", ""), run_id))
        for row in validation_rows:
            missing = str(row.get("missing_raw_paths_count", "0"))
            schema_ok = str(row.get("schema_ok", "")).lower()
            if missing not in {"", "0"} or schema_ok == "false":
                rows.append(self._quality_row(trade_date, "validation", row.get("scope", ""), row.get("dataset", ""), "", row.get("status", ""), "critical", "schema_or_raw", missing, f"schema_ok={schema_ok}, missing_raw_paths={missing}", "先 repair 或重跑对应同步，再重建平台元数据。", "platform://validation_results", "derived", row.get("output_path", ""), run_id))
        if not rows:
            rows.append(self._quality_row(trade_date, "summary", "platform_metadata", "all", "platform.quality", "success", "info", "healthy", "0", "未发现新的质量异常。", "继续保持日常调度与回归。", "platform://quality_diagnostics", "derived", "", run_id))
        return rows

    @staticmethod
    def _source_health_severity(row: Dict[str, str]) -> str:
        status = str(row.get("last_status", ""))
        issue_category = str(row.get("issue_category", ""))
        root_cause = str(row.get("issue_root_cause", ""))
        if status in {"no_data", "not_applicable"} or issue_category in {"no_data", "not_applicable"} or root_cause in {"no_data", "not_applicable"}:
            return "info"
        if str(row.get("is_external_blocker", "")).lower() == "true" or issue_category == "blocked_issue":
            return "warning"
        if status in {"pending_retry", "partial_success"}:
            return "warning"
        return "critical"

    @staticmethod
    def _coverage_severity(row: Dict[str, str]) -> str:
        runtime_status = str(row.get("runtime_status", ""))
        if runtime_status in {"no_data", "not_applicable"}:
            return "info"
        if str(row.get("internal_issue_count", "0")) not in {"", "0"} or runtime_status == "failed":
            return "critical"
        if str(row.get("external_issue_count", "0")) not in {"", "0"} or runtime_status in {"pending_retry", "partial_success"}:
            return "warning"
        return "info"

    def _quality_row(self, trade_date, diagnostic_type, asset_family, dataset, source_id, status, severity, metric_name, metric_value, message, recommendation, source_url, source_type, raw_path, run_id) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "diagnostic_type": str(diagnostic_type),
            "asset_family": str(asset_family),
            "dataset": str(dataset),
            "source_id": str(source_id),
            "status": str(status),
            "severity": str(severity),
            "metric_name": str(metric_name),
            "metric_value": str(metric_value),
            "message": str(message),
            "recommendation": str(recommendation),
            "source_url": str(source_url),
            "source_type": str(source_type) or "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": str(raw_path),
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{diagnostic_type}:{dataset}:{source_id}:{status}:{message}"),
            "run_id": run_id,
        }

    def _anomaly_event_rows(self, *, trade_date: str, run_id: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        for row in self._load_rows(DAILY_OHLCV_DATASET, start_date=trade_date, end_date=trade_date):
            close_value = self._first_float(row, ("close", "price", "nav", "mid", "price_usd"))
            volume_value = self._first_float(row, VOLUME_FIELDS)
            symbol = str(row.get("instrument_id") or row.get("symbol") or row.get("contract") or "")
            dataset = str(row.get("dataset") or DAILY_OHLCV_DATASET)
            if close_value is not None and close_value <= 0:
                rows.append(self._anomaly_event_row(trade_date, row.get("asset_family", ""), dataset, row.get("source_id", ""), "abnormal_price", "critical", "close", close_value, "0", f"{symbol} price <= 0", "检查源站原始行情与复权/单位字段。", row.get("source_url", ""), row.get("source_type", ""), row.get("raw_path", ""), run_id))
            if volume_value is not None and volume_value < 0:
                rows.append(self._anomaly_event_row(trade_date, row.get("asset_family", ""), dataset, row.get("source_id", ""), "abnormal_volume", "critical", "volume", volume_value, "0", f"{symbol} volume < 0", "检查源站原始成交量字段。", row.get("source_url", ""), row.get("source_type", ""), row.get("raw_path", ""), run_id))
        for row in self._load_platform_rows("source_health", trade_date):
            status = str(row.get("last_status", ""))
            if status in {"failed", "pending_retry", "partial_success"}:
                rows.append(self._anomaly_event_row(trade_date, row.get("asset_family", ""), row.get("dataset", ""), row.get("source_id", ""), "source_health_non_success", "warning", "last_status", status, "success", row.get("message", "") or row.get("blocked_reason", ""), "确认源站发布时间、网络或重跑对应同步任务。", row.get("source_url", ""), row.get("source_type", ""), row.get("output_path", ""), run_id))
        return rows

    def _anomaly_event_row(self, trade_date, asset_family, dataset, source_id, event_type, severity, metric_name, metric_value, threshold, message, recommendation, source_url, source_type, raw_path, run_id) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "asset_family": str(asset_family),
            "dataset": str(dataset),
            "source_id": str(source_id),
            "event_type": str(event_type),
            "severity": str(severity),
            "metric_name": str(metric_name),
            "metric_value": str(metric_value),
            "threshold": str(threshold),
            "message": str(message),
            "recommendation": str(recommendation),
            "source_url": str(source_url),
            "source_type": str(source_type) or "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": str(raw_path),
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{dataset}:{source_id}:{event_type}:{metric_name}:{metric_value}:{message}"),
            "run_id": run_id,
        }

    def _quality_markdown(self, *, trade_date: str, rows: List[Dict[str, str]], anomaly_rows: Optional[List[Dict[str, str]]] = None) -> str:
        lines = [f"# 数据质量诊断 {trade_date}", ""]
        counts = Counter(row.get("severity", "") for row in rows)
        lines.append(f"- 严重度统计：{dict(counts)}")
        lines.append(f"- 异常事件条数：{len(anomaly_rows or [])}")
        for row in rows:
            lines.append(f"- `{row.get('severity')}` `{row.get('dataset')}` `{row.get('status')}`：{row.get('message')}")
        for row in (anomaly_rows or [])[:20]:
            lines.append(f"- `{row.get('severity')}` `{row.get('event_type')}` `{row.get('dataset')}`：{row.get('message')}")
        lines.append("")
        return "\n".join(lines)

    def _report_markdown(
        self,
        *,
        trade_date: str,
        quality_rows: List[Dict[str, str]],
        research_rows: List[Dict[str, str]],
        strategy_rows: List[Dict[str, str]],
        algorithm_rows: List[Dict[str, str]],
        risk_rows: List[Dict[str, str]],
        backtest_rows: List[Dict[str, str]],
        anomaly_rows: List[Dict[str, str]],
        ml_rows: List[Dict[str, str]],
        factor_perf_rows: List[Dict[str, str]],
        stress_rows: List[Dict[str, str]],
        quality_score_rows: List[Dict[str, str]],
        status: str,
        severity: str,
        report_type: str,
    ) -> str:
        lines = [
            f"# 本地研究运营报告 {trade_date}",
            "",
            f"- 报告类型：`{report_type}`",
            f"- 报告状态：`{status}`",
            f"- 告警级别：`{severity}`",
            f"- 质量诊断条数：{len(quality_rows)}",
            f"- 异常事件条数：{len(anomaly_rows)}",
            f"- 数据质量评分条数：{len(quality_score_rows)}",
            f"- 研究指标条数：{len(research_rows)}",
            f"- 算法输出条数：{len(algorithm_rows)}",
            f"- 因子表现条数：{len(factor_perf_rows)}",
            f"- 风险指标条数：{len(risk_rows)}",
            f"- 压力测试条数：{len(stress_rows)}",
            f"- ML 模型运行条数：{len(ml_rows)}",
            f"- 策略模拟条数：{len(strategy_rows)}",
            f"- 正式回测净值条数：{len(backtest_rows)}",
            "",
            "## 质量摘要",
        ]
        for row in quality_rows[:20]:
            lines.append(f"- `{row.get('severity')}` `{row.get('dataset')}`：{row.get('message')}")
        lines.extend(["", "## 异常检测摘要"])
        for row in anomaly_rows[:20]:
            lines.append(f"- `{row.get('severity')}` `{row.get('event_type')}` `{row.get('dataset')}`：{row.get('message')}")
        lines.extend(["", "## 数据质量评分"])
        for row in quality_score_rows[:20]:
            lines.append(f"- `{row.get('dataset')}` score={row.get('quality_score')} status={row.get('status')}")
        lines.extend(["", "## 研究指标摘要"])
        for row in research_rows[:20]:
            lines.append(f"- `{row.get('dataset')}` `{row.get('metric_name')}` = `{row.get('metric_value')}` ({row.get('status')})")
        lines.extend(["", "## 算法模板摘要"])
        for row in algorithm_rows[:20]:
            lines.append(f"- `{row.get('template_name')}` `{row.get('metric_name')}` = `{row.get('metric_value')}` ({row.get('status')})")
        lines.extend(["", "## 因子表现摘要"])
        for row in factor_perf_rows[:20]:
            lines.append(f"- `{row.get('factor_name')}` `{row.get('metric_name')}` = `{row.get('metric_value')}` ({row.get('status')})")
        lines.extend(["", "## 风险指标摘要"])
        for row in risk_rows[:20]:
            lines.append(f"- `{row.get('template_name')}` `{row.get('metric_name')}` = `{row.get('metric_value')}` ({row.get('status')})")
        lines.extend(["", "## 压力测试摘要"])
        for row in stress_rows[:20]:
            lines.append(f"- `{row.get('scenario_name')}` `{row.get('metric_name')}` impact={row.get('impact_pct')} ({row.get('status')})")
        lines.extend(["", "## 机器学习摘要"])
        for row in ml_rows[:20]:
            lines.append(f"- `{row.get('template_name')}` score={row.get('score_metric')}:{row.get('score_value')} ({row.get('status')})")
        lines.extend(["", "## 策略模拟摘要"])
        for row in strategy_rows[:20]:
            lines.append(f"- `{row.get('strategy_name')}` `{row.get('trade_date')}` portfolio={row.get('portfolio_value')} return={row.get('cumulative_return')}")
        lines.extend(["", "## 正式回测摘要"])
        for row in backtest_rows[:20]:
            lines.append(f"- `{row.get('strategy_name')}` `{row.get('trade_date')}` value={row.get('portfolio_value')} drawdown={row.get('drawdown')}")
        lines.append("")
        lines.append("> 本报告仅用于本地研究和数据运营，不构成投资建议，也不连接真实交易。")
        return "\n".join(lines)

    def _report_interpretation_rows(
        self,
        *,
        trade_date: str,
        run_id: str,
        report_id: str,
        report_type: str,
        quality_rows: List[Dict[str, str]],
        anomaly_rows: List[Dict[str, str]],
        ml_rows: List[Dict[str, str]],
        factor_perf_rows: List[Dict[str, str]],
        stress_rows: List[Dict[str, str]],
        strategy_rows: List[Dict[str, str]],
        leaderboard_rows: List[Dict[str, str]],
        quality_score_rows: List[Dict[str, str]],
        status: str,
        severity: str,
    ) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
        """Build product-facing report interpretation and next-step suggestions."""

        def insight(insight_type: str, title: str, body: str, level: str = "info", item_status: str = "success") -> Dict[str, str]:
            insight_id = f"{report_id}:{insight_type}:{_sha1_text(title + body)[:8]}"
            return {
                "trade_date": trade_date,
                "insight_id": insight_id,
                "task_id": "",
                "report_id": report_id,
                "insight_type": insight_type,
                "title": title,
                "body": body,
                "severity": level,
                "status": item_status,
                **self._derived_provenance(
                    "platform.report_insight",
                    f"reports://{report_id}",
                    "",
                    f"{trade_date}:{run_id}:{insight_type}:{title}:{body}",
                    run_id=run_id,
                ),
            }

        def recommendation(category: str, title: str, body: str, priority: str = "medium", item_status: str = "open") -> Dict[str, str]:
            recommendation_id = f"{report_id}:{category}:{_sha1_text(title + body)[:8]}"
            return {
                "trade_date": trade_date,
                "recommendation_id": recommendation_id,
                "task_id": "",
                "category": category,
                "title": title,
                "body": body,
                "priority": priority,
                "status": item_status,
                **self._derived_provenance(
                    "platform.recommendation",
                    f"reports://{report_id}",
                    "",
                    f"{trade_date}:{run_id}:{category}:{title}:{body}",
                    run_id=run_id,
                ),
            }

        warnings = [row for row in quality_rows if str(row.get("severity")) == "warning"]
        critical = [row for row in quality_rows if str(row.get("severity")) == "critical"]
        insights = [
            insight(
                "report_summary",
                "报告自动解读已生成",
                f"{report_type} 报告状态为 {status}，告警级别为 {severity}；质量诊断 {len(quality_rows)} 条，异常 {len(anomaly_rows)} 条，策略样本 {len(strategy_rows)} 条。",
                "warning" if warnings or critical else "info",
            )
        ]
        recommendations: List[Dict[str, str]] = []
        if critical:
            insights.append(insight("quality_blocker", "存在高优先级质量问题", f"发现 {len(critical)} 条 critical 质量诊断，建议先修复再做研究结论。", "critical"))
            recommendations.append(recommendation("quality", "先处理 critical 数据质量问题", "运行 quality-diagnose 并检查 validation/source_health，再重新生成报告。", "high"))
        elif warnings:
            insights.append(insight("quality_warning", "存在可继续但需关注的质量告警", f"发现 {len(warnings)} 条 warning，当前仍可研究，但报告结论应保留风险提示。", "warning"))
            recommendations.append(recommendation("quality", "复核 warning 数据源", "优先检查连续失败、外部阻塞和缺失 raw 路径，确认是否需要重跑同步。", "medium"))

        best_model = max((row for row in ml_rows if _float(row.get("score_value")) is not None), key=lambda row: _float(row.get("score_value")) or -1e18, default=None)
        if best_model:
            insights.append(
                insight(
                    "best_model",
                    "当前最佳模型",
                    f"{best_model.get('template_name')} 在 {best_model.get('dataset')} 上的 {best_model.get('score_metric')}={best_model.get('score_value')}，可作为下一轮模型对比基线。",
                    "info" if str(best_model.get("status")) == "success" else "warning",
                )
            )
        else:
            recommendations.append(recommendation("ml", "补跑 ML Benchmark", "当前报告没有可比较的模型评分，可在策略研究台或 CLI 运行 ml-benchmark。", "medium"))

        factor_candidates = [row for row in factor_perf_rows if str(row.get("metric_name")) in {"ic", "rank_ic", "long_short_return"} and _float(row.get("metric_value")) is not None]
        best_factor = max(factor_candidates, key=lambda row: abs(_float(row.get("metric_value")) or 0.0), default=None)
        if best_factor:
            insights.append(
                insight(
                    "best_factor",
                    "当前最值得继续观察的因子",
                    f"{best_factor.get('factor_name')} 的 {best_factor.get('metric_name')}={best_factor.get('metric_value')}，建议进入参数扫描和分组收益复核。",
                    "info" if str(best_factor.get("status")) == "success" else "warning",
                )
            )
        else:
            recommendations.append(recommendation("factor", "补跑因子表现评估", "当前报告缺少 IC/Rank IC/分组收益样本，建议运行 factor-performance 或 factor-experiment。", "medium"))

        ranked_strategy = min(
            (row for row in leaderboard_rows if _float(row.get("rank")) is not None),
            key=lambda row: _float(row.get("rank")) or 1e18,
            default=None,
        )
        if ranked_strategy:
            insights.append(
                insight(
                    "strategy_leader",
                    "策略排行榜首位",
                    f"{ranked_strategy.get('strategy_name')} 当前综合质量分 {ranked_strategy.get('quality_score')}，最大回撤 {ranked_strategy.get('max_drawdown')}。",
                    "warning" if (_float(ranked_strategy.get("max_drawdown")) or 0.0) < -0.2 else "info",
                )
            )
        elif strategy_rows:
            recommendations.append(recommendation("backtest", "生成策略排行榜", "已有回测样本但没有排行榜，建议运行 strategy-leaderboard 做横向比较。", "medium"))

        stress_candidates = [row for row in stress_rows if _float(row.get("impact_pct")) is not None]
        weakest_stress = min(stress_candidates, key=lambda row: _float(row.get("impact_pct")) or 0.0, default=None)
        if weakest_stress:
            impact = _float(weakest_stress.get("impact_pct")) or 0.0
            insights.append(
                insight(
                    "weakest_stress",
                    "最脆弱压力情景",
                    f"{weakest_stress.get('scenario_name')} 的冲击比例为 {weakest_stress.get('impact_pct')}，是当前报告中最需要关注的压力项。",
                    "warning" if impact < -0.05 else "info",
                )
            )
            if impact < -0.05:
                recommendations.append(recommendation("risk", "复核压力情景暴露", "建议增加 risk_parity / volatility_target 对照组合，并检查相关性上升与极端波动情景。", "high"))

        if quality_score_rows:
            score_values = [_float(row.get("quality_score")) for row in quality_score_rows]
            score_values = [value for value in score_values if value is not None]
            if score_values:
                avg_score = sum(score_values) / len(score_values)
                insights.append(insight("quality_score", "数据质量评分概览", f"当前平均质量评分约 {avg_score:.4f}，覆盖 {len(score_values)} 个数据集。", "warning" if avg_score < 0.7 else "info"))
        return insights, recommendations or [recommendation("workflow", "保持日常研究闭环", "建议继续使用 Agent 入口按“检查数据 -> 跑算法 -> 回测 -> 报告 -> 复现包”的顺序推进。", "low", "open")]

    def _report_artifact_rows(self, *, trade_date: str, run_id: str, report_id: str, report_dir: Path, backtest_rows: List[Dict[str, str]], quality_score_rows: List[Dict[str, str]], report_type: str):
        report_rows: List[Dict[str, str]] = []
        manifest_rows: List[Dict[str, str]] = []
        artifacts = []
        if backtest_rows:
            path = report_dir / "backtest_equity_curve.svg"
            self._write_svg_line_chart(path, [(row.get("trade_date", ""), _float(row.get("portfolio_value")) or 0.0) for row in backtest_rows], "回测净值曲线")
            artifacts.append(("backtest_equity_curve", "svg_chart", "回测净值曲线", path, BACKTEST_EQUITY_CURVES_DATASET))
        if quality_score_rows:
            path = report_dir / "dataset_quality_scores.svg"
            points = [(row.get("dataset", ""), _float(row.get("quality_score")) or 0.0) for row in quality_score_rows[:30]]
            self._write_svg_bar_chart(path, points, "数据质量评分")
            artifacts.append(("dataset_quality_scores", "svg_chart", "数据质量评分", path, DATASET_QUALITY_SCORES_DATASET))
        for artifact_id, artifact_type, title, path, source_dataset in artifacts:
            relative_path = relative_to_project(path, self.project_root)
            checksum = _sha1_text(path.read_text(encoding="utf-8") if path.exists() else relative_path)
            report_rows.append(
                {
                    "trade_date": trade_date,
                    "report_id": report_id,
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "title": title,
                    "path": relative_path,
                    "status": "success",
                    "reason": "",
                    "source_id": "platform.report_artifact",
                    "source_url": f"reports://{report_id}",
                    "source_type": "derived",
                    "retrieved_at": iso_timestamp(),
                    "raw_path": relative_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": checksum,
                    "run_id": run_id,
                }
            )
            manifest_rows.append(
                {
                    "trade_date": trade_date,
                    "run_id": run_id,
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                    "title": title,
                    "dataset": source_dataset,
                    "path": relative_path,
                    "checksum": checksum,
                    "source_datasets": source_dataset,
                    "parameters": safe_json_dumps({"report_type": report_type, "report_id": report_id}),
                    "status": "success",
                    "reason": "",
                    "source_id": "platform.artifact_manifest",
                    "source_url": f"reports://{report_id}",
                    "source_type": "derived",
                    "retrieved_at": iso_timestamp(),
                    "raw_path": relative_path,
                    "parser_version": PARSER_VERSION,
                }
            )
        return report_rows, manifest_rows

    @staticmethod
    def _write_svg_line_chart(path: Path, points: Sequence[Tuple[str, float]], title: str) -> None:
        ensure_directory(path.parent)
        width, height = 720, 260
        values = [value for _label, value in points if value is not None]
        if not values:
            values = [0.0]
        minimum, maximum = min(values), max(values)
        span = maximum - minimum or 1.0
        coords = []
        size = max(len(points), 1)
        for index, (_label, value) in enumerate(points):
            x = 40 + index * (width - 80) / max(size - 1, 1)
            y = height - 40 - ((value - minimum) / span) * (height - 90)
            coords.append(f"{x:.1f},{y:.1f}")
        polyline = " ".join(coords)
        svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'><rect width='100%' height='100%' fill='#f7f5ef'/><text x='40' y='30' font-size='18' fill='#14202b'>{html.escape(title)}</text><polyline points='{polyline}' fill='none' stroke='#185f63' stroke-width='3'/></svg>"
        path.write_text(svg, encoding="utf-8")

    @staticmethod
    def _write_svg_bar_chart(path: Path, points: Sequence[Tuple[str, float]], title: str) -> None:
        ensure_directory(path.parent)
        width, height = 720, 320
        bar_width = max(8, int((width - 80) / max(len(points), 1) * 0.7))
        bars = []
        for index, (label, value) in enumerate(points):
            x = 40 + index * (width - 80) / max(len(points), 1)
            bar_height = max(2, value * (height - 90))
            y = height - 40 - bar_height
            bars.append(f"<rect x='{x:.1f}' y='{y:.1f}' width='{bar_width}' height='{bar_height:.1f}' fill='#53745d'><title>{html.escape(str(label))}: {value:.4f}</title></rect>")
        svg = f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'><rect width='100%' height='100%' fill='#f7f5ef'/><text x='40' y='30' font-size='18' fill='#14202b'>{html.escape(title)}</text>{''.join(bars)}</svg>"
        path.write_text(svg, encoding="utf-8")

    @staticmethod
    def _markdown_to_html(markdown: str) -> str:
        body = []
        for line in markdown.splitlines():
            if line.startswith("# "):
                body.append(f"<h1>{html.escape(line[2:])}</h1>")
            elif line.startswith("## "):
                body.append(f"<h2>{html.escape(line[3:])}</h2>")
            elif line.startswith("- "):
                body.append(f"<p>• {html.escape(line[2:])}</p>")
            elif line.startswith("> "):
                body.append(f"<blockquote>{html.escape(line[2:])}</blockquote>")
            else:
                body.append(f"<p>{html.escape(line)}</p>" if line else "")
        return "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>研究运营日报</title></head><body>" + "\n".join(body) + "</body></html>"

    def _default_target_field(self, rows: List[Dict[str, str]]) -> str:
        for field in PRICE_FIELDS:
            if any(_float(row.get(field)) is not None for row in rows[:5000]):
                return field
        return "close"

    @staticmethod
    def _normalize_feature_fields(feature_text) -> List[str]:
        if isinstance(feature_text, (list, tuple)):
            return [str(item).strip() for item in feature_text if str(item).strip()]
        return [item.strip() for item in str(feature_text or "").split(",") if item.strip()]

    def _default_feature_fields(self, rows: List[Dict[str, str]], target_field: str) -> List[str]:
        candidates = ["open", "high", "low", "pre_close", "volume", "amount", "open_interest", "turnover_rate", "nav", "yield", "mid", "price_usd"]
        result = []
        for field in candidates:
            if field == target_field:
                continue
            if any(_float(row.get(field)) is not None for row in rows[:5000]):
                result.append(field)
        return result[:8] or [target_field]

    def _ml_matrix(self, rows: List[Dict[str, str]], target_field: str, feature_fields: Sequence[str]):
        matrix: List[List[float]] = []
        target: List[float] = []
        meta: List[Dict[str, str]] = []
        sorted_rows = sorted(rows, key=lambda item: (str(item.get("trade_date", "")), str(item.get("instrument_id") or item.get("symbol") or item.get("contract") or "")))
        for row in sorted_rows:
            features = []
            valid = True
            for field in feature_fields:
                value = _float(row.get(field))
                if value is None:
                    valid = False
                    break
                features.append(value)
            target_value = _float(row.get(target_field))
            if not valid or target_value is None:
                continue
            matrix.append(features)
            target.append(target_value)
            meta.append(dict(row))
        return matrix, target, meta

    @staticmethod
    def _r2_score(actual: Sequence[float], predicted: Sequence[float]) -> float:
        size = min(len(actual), len(predicted))
        if size <= 1:
            return 0.0
        actual_values = list(actual[:size])
        predicted_values = list(predicted[:size])
        mean_actual = sum(actual_values) / size
        ss_total = sum((value - mean_actual) ** 2 for value in actual_values)
        ss_res = sum((actual_values[index] - predicted_values[index]) ** 2 for index in range(size))
        return 0.0 if ss_total == 0 else 1 - ss_res / ss_total

    @staticmethod
    def _mae(actual: Sequence[object], predicted: Sequence[float]) -> float:
        pairs = [(_float(actual[index]), float(predicted[index])) for index in range(min(len(actual), len(predicted)))]
        valid = [(left, right) for left, right in pairs if left is not None]
        if not valid:
            return 0.0
        return sum(abs(float(left) - right) for left, right in valid) / len(valid)

    @staticmethod
    def _rmse(actual: Sequence[object], predicted: Sequence[float]) -> float:
        pairs = [(_float(actual[index]), float(predicted[index])) for index in range(min(len(actual), len(predicted)))]
        valid = [(left, right) for left, right in pairs if left is not None]
        if not valid:
            return 0.0
        return math.sqrt(sum((float(left) - right) ** 2 for left, right in valid) / len(valid))

    def _factor_performance_rows(self, *, dataset_name: str, source_rows: List[Dict[str, str]], factor: str, start_date: str, end_date: str, run_id: str) -> List[Dict[str, str]]:
        factor_rows = self._factor_rows(dataset_name=dataset_name, source_rows=source_rows, factor=factor, run_id=run_id, end_date=end_date)
        groups = self._group_price_series(source_rows)
        pairs = []
        for row in factor_rows:
            symbol = str(row.get("symbol_or_contract", ""))
            factor_value = _float(row.get("factor_value"))
            items = groups.get(symbol, [])
            realized = (items[-1][1] / items[0][1] - 1) if len(items) >= 2 and items[0][1] else None
            if factor_value is not None and realized is not None:
                pairs.append((factor_value, realized))
        family = str(source_rows[0].get("asset_family", "")) if source_rows else ""
        if not pairs:
            return [self._factor_performance_row(end_date, factor, dataset_name, family, "coverage", "", 0, start_date, end_date, "not_applicable", "factor performance requires valid factor values and realized returns", run_id)]
        values = [item[0] for item in pairs]
        returns = [item[1] for item in pairs]
        ic = self._correlation(values, returns)
        rank_ic = self._correlation(self._rank_values(values), self._rank_values(returns))
        wins = sum(1 for value, ret in pairs if (value >= 0 and ret >= 0) or (value < 0 and ret < 0))
        top_count = max(1, len(pairs) // 5)
        sorted_pairs = sorted(pairs, key=lambda item: item[0], reverse=True)
        top_return = sum(ret for _value, ret in sorted_pairs[:top_count]) / top_count
        bottom_return = sum(ret for _value, ret in sorted_pairs[-top_count:]) / top_count
        metrics = {
            "ic": ic,
            "rank_ic": rank_ic,
            "coverage": float(len(pairs)),
            "win_rate": wins / len(pairs),
            "top_group_return": top_return,
            "bottom_group_return": bottom_return,
            "long_short_return": top_return - bottom_return,
        }
        return [
            self._factor_performance_row(end_date, factor, dataset_name, family, metric, "" if value is None else f"{float(value):.8f}", len(pairs), start_date, end_date, "success" if value is not None else "not_applicable", "" if value is not None else "requires variance in factor and returns", run_id)
            for metric, value in metrics.items()
        ]

    @staticmethod
    def _rank_values(values: Sequence[float]) -> List[float]:
        ordered = sorted((value, index) for index, value in enumerate(values))
        ranks = [0.0 for _ in values]
        for rank, (_value, index) in enumerate(ordered, start=1):
            ranks[index] = float(rank)
        return ranks

    def _stress_test_rows(self, *, template_name: str, dataset_name: str, source_rows: List[Dict[str, str]], asset_family: str, start_date: str, end_date: str, params: Dict[str, object], run_id: str) -> List[Dict[str, str]]:
        groups = self._group_price_series(source_rows)
        family = asset_family or (str(source_rows[0].get("asset_family", "")) if source_rows else "")
        weights = self._portfolio_weights(template_name="risk_parity", groups=groups)
        latest_prices = {symbol: items[-1][1] for symbol, items in groups.items() if items and items[-1][1] > 0}
        base_value = float(_float(params.get("portfolio_value")) or 1_000_000.0)
        if not weights or not latest_prices:
            return [self._stress_test_row(end_date, run_id, template_name, template_name, dataset_name, family, "stress:default", "portfolio_value", base_value, "", "", "", params, start_date, end_date, "not_applicable", "stress test requires priced portfolio history", dataset_name)]
        default_shocks = {
            "equity_down": -0.10,
            "volatility_up": -0.06,
            "correlation_up": -0.04,
            "rate_shift": -0.03,
            "fx_shock": -0.05,
            "crypto_shock": -0.20,
        }
        shock = float(_float(params.get("shock")) or default_shocks.get(template_name, -0.05))
        stressed_value = base_value * (1 + shock)
        impact = stressed_value - base_value
        return [
            self._stress_test_row(end_date, run_id, template_name, template_name, dataset_name, family, "stress:default", "portfolio_value", base_value, stressed_value, impact, shock, params, start_date, end_date, "success", "", dataset_name),
            self._stress_test_row(end_date, run_id, template_name, template_name, dataset_name, family, "stress:default", "position_count", len(weights), len(weights), 0, 0, params, start_date, end_date, "success", "", dataset_name),
        ]

    def _inventory_and_field_profile_rows(self, *, trade_date: str, run_id: str):
        inventory_rows: List[Dict[str, str]] = []
        field_rows: List[Dict[str, str]] = []
        for dataset_name, pattern in sorted(DATASET_GLOBS.items()):
            paths = sorted(self.normalized_root.glob(pattern))
            sample_rows: List[Dict[str, str]] = []
            all_dates = []
            total_rows = 0
            columns = set()
            for path in paths[-20:]:
                try:
                    rows = list(iter_csv_rows(path))
                except Exception:
                    rows = []
                total_rows += len(rows)
                sample_rows.extend(rows[:200])
                if rows:
                    columns.update(rows[0].keys())
                    all_dates.extend(str(row.get("trade_date", "")) for row in rows if row.get("trade_date"))
                else:
                    stem = path.stem
                    if len(stem) == 10:
                        all_dates.append(stem)
            catalog = self._dataset_catalog_hint(dataset_name)
            latest_file = relative_to_project(paths[-1], self.project_root) if paths else ""
            status = "success" if paths else "no_data"
            first_date = min(all_dates) if all_dates else ""
            last_date = max(all_dates) if all_dates else ""
            inventory_rows.append({
                "trade_date": trade_date,
                "dataset": dataset_name,
                "asset_family": catalog.get("asset_family", ""),
                "market": catalog.get("market", ""),
                "exchange": catalog.get("exchange", ""),
                "file_count": str(len(paths)),
                "row_count": str(total_rows),
                "column_count": str(len(columns)),
                "first_trade_date": first_date,
                "last_trade_date": last_date,
                "latest_file": latest_file,
                "duckdb_indexed": str(bool(paths)).lower(),
                "status": status,
                "reason": "" if paths else "dataset has no materialized csv yet",
                **self._derived_provenance("platform.inventory", f"platform://{dataset_name}", latest_file, f"{trade_date}:{dataset_name}:{total_rows}:{last_date}", run_id=run_id),
            })
            field_rows.extend(self._field_profile_rows(trade_date, dataset_name, sample_rows, columns, run_id))
        return inventory_rows, field_rows

    def _field_profile_rows(self, trade_date: str, dataset_name: str, sample_rows: List[Dict[str, str]], columns, run_id: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        total = len(sample_rows)
        for field_name in sorted(columns):
            values = [str(row.get(field_name, "") or "") for row in sample_rows]
            non_null = sum(1 for value in values if value.strip())
            missing = max(total - non_null, 0)
            numeric_count = sum(1 for value in values if _float(value) is not None)
            inferred_type = "number" if non_null and numeric_count / max(non_null, 1) >= 0.8 else "string"
            sample = next((value for value in values if value.strip()), "")
            rows.append({
                "trade_date": trade_date,
                "dataset": dataset_name,
                "field_name": field_name,
                "inferred_type": inferred_type,
                "non_null_count": str(non_null),
                "missing_count": str(missing),
                "missing_ratio": f"{(missing / total if total else 0):.8f}",
                "unique_count": str(len(set(value for value in values if value.strip()))),
                "sample_value": sample[:120],
                "status": "success" if total else "no_data",
                "reason": "" if total else "no rows available for profiling",
                **self._derived_provenance("platform.field_profile", f"platform://{dataset_name}", "", f"{trade_date}:{dataset_name}:{field_name}:{non_null}:{missing}", run_id=run_id),
            })
        if not rows:
            rows.append({
                "trade_date": trade_date,
                "dataset": dataset_name,
                "field_name": "",
                "inferred_type": "",
                "non_null_count": "0",
                "missing_count": "0",
                "missing_ratio": "0.00000000",
                "unique_count": "0",
                "sample_value": "",
                "status": "no_data",
                "reason": "no columns available",
                **self._derived_provenance("platform.field_profile", f"platform://{dataset_name}", "", f"{trade_date}:{dataset_name}:empty", run_id=run_id),
            })
        return rows

    def _lineage_rows(self, *, trade_date: str, run_id: str) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        sources = []
        for dataset_name in (ARTIFACT_MANIFEST_DATASET, REPORT_ARTIFACTS_DATASET, EXPERIMENT_RUNS_DATASET, PROJECT_RUNS_DATASET, REPRODUCIBLE_PACKAGES_DATASET):
            for row in self._load_platform_rows(dataset_name, trade_date):
                sources.append((dataset_name, row))
        for index, (dataset_name, row) in enumerate(sources, start=1):
            source_datasets = str(row.get("source_datasets") or row.get("source_dataset") or row.get("dataset") or dataset_name)
            artifact_id = str(row.get("artifact_id") or row.get("package_id") or row.get("report_id") or row.get("run_id") or f"lineage-{index}")
            producer = str(row.get("experiment_type") or row.get("artifact_type") or dataset_name)
            rows.append({
                "trade_date": trade_date,
                "run_id": str(row.get("run_id") or run_id),
                "artifact_id": artifact_id,
                "artifact_type": str(row.get("artifact_type") or dataset_name),
                "producer": producer,
                "source_datasets": source_datasets,
                "parameters": str(row.get("parameters") or ""),
                "checksum": str(row.get("checksum") or _sha1_text(safe_json_dumps(row))),
                "path": str(row.get("path") or row.get("raw_path") or ""),
                "status": str(row.get("status") or "success"),
                "reason": str(row.get("reason") or ""),
                **self._derived_provenance("platform.lineage", f"platform://{dataset_name}", str(row.get("raw_path") or ""), f"{trade_date}:{artifact_id}:{source_datasets}", include_checksum=False),
            })
        return rows or [{
            "trade_date": trade_date,
            "run_id": run_id,
            "artifact_id": "lineage-empty",
            "artifact_type": "lineage",
            "producer": "platform.lineage",
            "source_datasets": "",
            "parameters": "{}",
            "checksum": _sha1_text(f"{trade_date}:empty-lineage"),
            "path": "",
            "status": "no_data",
            "reason": "no experiment or artifact rows found",
            **self._derived_provenance("platform.lineage", "platform://data_lineage", "", f"{trade_date}:empty-lineage", include_checksum=False),
        }]

    def _sla_rows(self, *, trade_date: str, run_id: str):
        inventory_rows = self._load_platform_rows(DATASET_INVENTORY_DATASET, trade_date)
        if not inventory_rows:
            inventory_rows, _fields = self._inventory_and_field_profile_rows(trade_date=trade_date, run_id=run_id)
        rule_rows: List[Dict[str, str]] = []
        violation_rows: List[Dict[str, str]] = []
        for row in inventory_rows:
            dataset = str(row.get("dataset", ""))
            min_rows = "0" if dataset in {BOND_ANALYTICS_DATASET, CURVE_ANALYTICS_DATASET} else "1"
            rule_rows.append({
                "trade_date": trade_date,
                "dataset": dataset,
                "expected_update_time": "23:59",
                "min_rows": min_rows,
                "max_stale_days": "10",
                "external_blocker_whitelist": "result_chain_publication_lag,dns_failure,proxy_failure",
                "enabled": "true",
                "status": "success",
                "reason": "",
                **self._derived_provenance("platform.sla", f"platform://{dataset}", "", f"{trade_date}:{dataset}:rule"),
            })
            observed = int(_float(row.get("row_count")) or 0)
            if observed < int(min_rows):
                violation_rows.append({
                    "trade_date": trade_date,
                    "dataset": dataset,
                    "violation_type": "row_count_below_min",
                    "severity": "warning",
                    "observed_value": str(observed),
                    "expected_value": min_rows,
                    "message": f"{dataset} row_count {observed} is below SLA minimum {min_rows}",
                    "status": "warning",
                    "reason": "empty or missing dataset",
                    **self._derived_provenance("platform.sla", f"platform://{dataset}", "", f"{trade_date}:{dataset}:violation:{observed}", run_id=run_id),
                })
        return rule_rows, violation_rows

    def _knowledge_rows(self, *, trade_date: str, run_id: str) -> List[Dict[str, str]]:
        rows = []
        for name, template in AlgorithmRegistry._TEMPLATES.items():
            rows.append(self._knowledge_row(trade_date, f"algorithm:{name}", "algorithm", template.label, template.description, template.category, "AlgorithmRegistry", run_id))
        for dataset_name in sorted(DATASET_GLOBS):
            rows.append(self._knowledge_row(trade_date, f"dataset:{dataset_name}", "dataset", dataset_name, f"平台数据集 {dataset_name}，可通过 DuckDB、GUI 和 export 读取。", "dataset,duckdb,gui", f"platform://{dataset_name}", run_id))
        rows.append(self._knowledge_row(trade_date, "operations:cffex_publication_lag", "external_blocker", "CFFEX publication_lag", "CFFEX options_exercise_results 官方月报未发布时保留 blocked_issue/pending_retry，不伪装成功。", "external_blocker,quality", "STATUS.md", run_id))
        return rows

    def _feature_store_rows(self, *, dataset_name: str, source_rows: List[Dict[str, str]], feature_text: str, start_date: str, end_date: str, run_id: str) -> List[Dict[str, str]]:
        requested = [item.strip() for item in str(feature_text or "").split(",") if item.strip()]
        requested = requested or ["return_1d", "return_window", "lag_return_1", "rolling_mean_3", "rolling_vol_3", "volume_change", "price_position", "momentum", "reversal", "cross_asset_strength"]
        groups = self._group_price_series(source_rows)
        volume_by_symbol: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        family_by_symbol: Dict[str, str] = {}
        for row in source_rows:
            symbol = str(row.get("instrument_id") or row.get("symbol") or row.get("contract") or "").strip()
            if not symbol:
                continue
            family_by_symbol.setdefault(symbol, str(row.get("asset_family", "")))
            volume = self._first_float(row, VOLUME_FIELDS)
            if volume is not None:
                volume_by_symbol[symbol].append((str(row.get("trade_date", "")), volume))
        volume_change_by_symbol = {
            symbol: self._volume_change_from_series(values)
            for symbol, values in volume_by_symbol.items()
        }
        rows = []
        for symbol, values in groups.items():
            if not values:
                continue
            latest_date, latest_price, _latest_row = values[-1]
            first_price = values[0][1] if values[0][1] else latest_price
            returns = [(values[index][1] / values[index - 1][1] - 1) for index in range(1, len(values)) if values[index - 1][1]]
            volume_change = volume_change_by_symbol.get(symbol, 0.0)
            feature_values = {
                "return_1d": returns[-1] if returns else 0.0,
                "return_window": (latest_price / first_price - 1) if first_price else 0.0,
                "lag_return_1": returns[-2] if len(returns) >= 2 else 0.0,
                "rolling_mean_3": sum(value for _date, value, _row in values[-3:]) / max(len(values[-3:]), 1),
                "rolling_vol_3": self._stddev(returns[-3:]),
                "volume_change": volume_change,
                "price_position": self._price_position(values),
                "momentum": (latest_price / first_price - 1) if first_price else 0.0,
                "reversal": -((latest_price / first_price - 1) if first_price else 0.0),
                "turnover_change": volume_change,
                "term_structure_slope": 0.0,
                "basis": 0.0,
                "calendar_spread": 0.0,
                "cross_asset_strength": (latest_price / first_price - 1) if first_price else 0.0,
            }
            family = family_by_symbol.get(symbol, "")
            for feature_name in requested:
                value = feature_values.get(feature_name, 0.0)
                rows.append({
                    "trade_date": str(latest_date or end_date),
                    "dataset": dataset_name,
                    "asset_family": family,
                    "symbol_or_contract": symbol,
                    "feature_name": feature_name,
                    "feature_value": self._fmt_optional(value),
                    "window": f"{start_date}:{end_date}",
                    "source_field": "close",
                    "status": "success",
                    "reason": "",
                    "source_dataset": dataset_name,
                    **self._derived_provenance("platform.feature_store", f"duckdb://{dataset_name}", "", f"{end_date}:{dataset_name}:{symbol}:{feature_name}:{value}", run_id=run_id),
                })
        return rows or [{
            "trade_date": end_date,
            "dataset": dataset_name,
            "asset_family": "",
            "symbol_or_contract": "",
            "feature_name": "",
            "feature_value": "",
            "window": f"{start_date}:{end_date}",
            "source_field": "",
            "status": "not_applicable",
            "reason": "feature-run requires priced rows",
            "source_dataset": dataset_name,
            **self._derived_provenance("platform.feature_store", f"duckdb://{dataset_name}", "", f"{end_date}:{dataset_name}:empty", run_id=run_id),
        }]

    def _dataset_catalog_hint(self, dataset_name: str) -> Dict[str, str]:
        for item in build_source_catalog():
            if str(item.get("dataset", "")) == str(dataset_name):
                return {
                    "asset_family": str(item.get("asset_family", "")),
                    "market": str(item.get("market", "")),
                    "exchange": str(item.get("exchange", "")),
                }
        return {"asset_family": "platform_metadata" if str(DATASET_GLOBS.get(dataset_name, "")).startswith("platform/") else "", "market": "", "exchange": ""}

    def _derived_provenance(
        self,
        source_id: str,
        source_url: str,
        raw_path: str,
        checksum_text: str,
        *,
        run_id: str = "",
        include_checksum: bool = True,
    ) -> Dict[str, str]:
        row = {
            "source_id": str(source_id),
            "source_url": str(source_url),
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": str(raw_path),
            "parser_version": PARSER_VERSION,
        }
        if include_checksum:
            row["checksum"] = _sha1_text(str(checksum_text))
        if run_id:
            row["run_id"] = str(run_id)
        return row

    def _knowledge_row(self, trade_date: str, knowledge_id: str, category: str, title: str, body: str, tags: str, source_path: str, run_id: str) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "knowledge_id": str(knowledge_id),
            "category": str(category),
            "title": str(title),
            "body": str(body),
            "tags": str(tags),
            "source_path": str(source_path),
            "status": "success",
            "reason": "",
            **self._derived_provenance("platform.knowledge", str(source_path), "", f"{trade_date}:{knowledge_id}:{title}:{body}", run_id=run_id),
        }

    def _volume_change(self, source_rows: List[Dict[str, str]], symbol: str) -> float:
        values = []
        for row in source_rows:
            row_symbol = str(row.get("instrument_id") or row.get("symbol") or row.get("contract") or "")
            if row_symbol != symbol:
                continue
            volume = self._first_float(row, VOLUME_FIELDS)
            if volume is not None:
                values.append((str(row.get("trade_date", "")), volume))
        values.sort(key=lambda item: item[0])
        if len(values) < 2 or values[0][1] == 0:
            return 0.0
        return values[-1][1] / values[0][1] - 1

    @staticmethod
    def _volume_change_from_series(values: List[Tuple[str, float]]) -> float:
        values = sorted(values, key=lambda item: item[0])
        if len(values) < 2 or values[0][1] == 0:
            return 0.0
        return values[-1][1] / values[0][1] - 1

    @staticmethod
    def _price_position(values: Sequence[Tuple[str, float, Dict[str, str]]]) -> float:
        prices = [float(item[1]) for item in values if _float(item[1]) is not None]
        if not prices:
            return 0.0
        low = min(prices)
        high = max(prices)
        if high == low:
            return 0.5
        return (prices[-1] - low) / (high - low)

    def _ml_benchmark_row(
        self,
        trade_date: str,
        run_id: str,
        template_name: str,
        dataset_name: str,
        asset_family: str,
        target_field: str,
        feature_fields: str,
        model_rows: List[Dict[str, str]],
        diagnostic_rows: List[Dict[str, str]],
        elapsed_seconds: float,
        *,
        status: str = "",
        reason: str = "",
    ) -> Dict[str, str]:
        model = model_rows[0] if model_rows else {}
        diagnostics = {(str(row.get("diagnostic_type", "")), str(row.get("metric_name", ""))): str(row.get("metric_value", "")) for row in diagnostic_rows}
        score_value = str(model.get("score_value", "") or "0")
        row_status = status or str(model.get("status") or ("success" if model_rows else "not_applicable"))
        row_reason = reason or str(model.get("reason") or ("" if model_rows else "model did not produce a benchmarkable run"))
        checksum_text = f"{trade_date}:{run_id}:{template_name}:{dataset_name}:{score_value}:{row_status}"
        return {
            "trade_date": str(trade_date),
            "run_id": str(run_id),
            "template_name": str(template_name),
            "dataset": str(dataset_name),
            "asset_family": str(asset_family),
            "target_field": str(target_field or model.get("target_field", "")),
            "feature_fields": str(feature_fields or model.get("feature_fields", "")),
            "score_metric": str(model.get("score_metric") or "r2"),
            "score_value": score_value,
            "r2": score_value if str(model.get("score_metric") or "r2") == "r2" else diagnostics.get(("regression", "r2"), score_value),
            "mae": diagnostics.get(("regression", "mae"), ""),
            "rmse": diagnostics.get(("regression", "rmse"), ""),
            "direction_accuracy": diagnostics.get(("classification", "direction_accuracy"), ""),
            "sample_count": diagnostics.get(("data", "sample_count"), ""),
            "feature_count": diagnostics.get(("data", "feature_count"), ""),
            "elapsed_seconds": f"{float(elapsed_seconds):.6f}",
            "rank": "",
            "best_params": str(model.get("best_params", "{}")),
            "status": row_status,
            "reason": row_reason,
            "source_dataset": str(dataset_name),
            **self._derived_provenance("platform.ml_benchmark", f"duckdb://{dataset_name}", "", checksum_text, include_checksum=True),
        }

    def _rank_metric_rows(self, rows: List[Dict[str, str]], metric_field: str) -> List[Dict[str, str]]:
        sortable = []
        for index, row in enumerate(rows):
            value = _float(row.get(metric_field))
            if value is not None and str(row.get("status", "")) == "success":
                sortable.append((value, index))
        for rank, (_value, index) in enumerate(sorted(sortable, key=lambda item: item[0], reverse=True), start=1):
            rows[index]["rank"] = str(rank)
        return rows

    def _ml_validation_rows(
        self,
        *,
        template: str,
        dataset_name: str,
        source_rows: List[Dict[str, str]],
        target: str,
        features: str,
        method: str,
        params: Dict[str, object],
        start_date: str,
        end_date: str,
        run_id: str,
    ):
        target_field = target or self._default_target_field(source_rows)
        feature_fields = self._normalize_feature_fields(features) or self._default_feature_fields(source_rows, target_field)
        X, y, meta = self._ml_matrix(source_rows, target_field, feature_fields)
        if len(y) < 6:
            fold = {
                "trade_date": end_date,
                "run_id": run_id,
                "template_name": template,
                "dataset": dataset_name,
                "fold_index": "0",
                "method": method,
                "train_start": start_date,
                "train_end": end_date,
                "test_start": end_date,
                "test_end": end_date,
                "target_field": target_field,
                "feature_fields": ",".join(feature_fields),
                "score_metric": "r2",
                "score_value": "0.00000000",
                "sample_count": str(len(y)),
                "status": "not_applicable",
                "reason": "time-series validation requires at least 6 valid samples",
                "source_dataset": dataset_name,
                **self._derived_provenance("platform.ml_validate", f"duckdb://{dataset_name}", "", f"{end_date}:{run_id}:fold-empty"),
            }
            class_row = self._classification_result_row(end_date, run_id, template, dataset_name, "next_direction", "up", 0, 0, 0, 0, 0, 0, {}, "not_applicable", "not enough samples", dataset_name)
            return [fold], [class_row]

        fold_rows = []
        n = len(y)
        fold_size = max(1, n // 4)
        fold_specs = []
        for fold_index in range(3):
            test_start_index = max(2, n - (3 - fold_index) * fold_size)
            test_end_index = min(n, test_start_index + fold_size)
            if test_start_index >= test_end_index:
                continue
            if method == "rolling":
                train_start_index = max(0, test_start_index - 3 * fold_size)
            else:
                train_start_index = 0
            train_end_index = test_start_index
            fold_specs.append((fold_index + 1, train_start_index, train_end_index, test_start_index, test_end_index))
        for fold_index, train_start_idx, train_end_idx, test_start_idx, test_end_idx in fold_specs:
            train_values = y[train_start_idx:train_end_idx]
            actual = y[test_start_idx:test_end_idx]
            prediction_value = sum(train_values) / len(train_values) if train_values else sum(y) / len(y)
            predicted = [prediction_value for _ in actual]
            score = self._r2_score(actual, predicted)
            train_start_value = str(meta[train_start_idx].get("trade_date", start_date)) if meta else start_date
            train_end_value = str(meta[max(train_start_idx, train_end_idx - 1)].get("trade_date", end_date)) if meta else end_date
            test_start_value = str(meta[test_start_idx].get("trade_date", end_date)) if meta else end_date
            test_end_value = str(meta[test_end_idx - 1].get("trade_date", end_date)) if meta else end_date
            fold_rows.append({
                "trade_date": end_date,
                "run_id": run_id,
                "template_name": template,
                "dataset": dataset_name,
                "fold_index": str(fold_index),
                "method": method,
                "train_start": train_start_value,
                "train_end": train_end_value,
                "test_start": test_start_value,
                "test_end": test_end_value,
                "target_field": target_field,
                "feature_fields": ",".join(feature_fields),
                "score_metric": "r2",
                "score_value": self._fmt_optional(score),
                "sample_count": str(len(actual)),
                "status": "success",
                "reason": "",
                "source_dataset": dataset_name,
                **self._derived_provenance("platform.ml_validate", f"duckdb://{dataset_name}", "", f"{end_date}:{run_id}:{fold_index}:{score}"),
            })

        actual_direction = [1 if y[index] >= y[index - 1] else 0 for index in range(1, len(y))]
        predicted_direction = [1 if y[index - 1] >= y[max(0, index - 2)] else 0 for index in range(1, len(y))]
        tp = sum(1 for a, p in zip(actual_direction, predicted_direction) if a == 1 and p == 1)
        tn = sum(1 for a, p in zip(actual_direction, predicted_direction) if a == 0 and p == 0)
        fp = sum(1 for a, p in zip(actual_direction, predicted_direction) if a == 0 and p == 1)
        fn = sum(1 for a, p in zip(actual_direction, predicted_direction) if a == 1 and p == 0)
        total = max(len(actual_direction), 1)
        accuracy = (tp + tn) / total
        precision = tp / max(tp + fp, 1)
        recall = tp / max(tp + fn, 1)
        f1 = 2 * precision * recall / max(precision + recall, 1e-12)
        class_row = self._classification_result_row(
            end_date,
            run_id,
            template,
            dataset_name,
            "next_direction",
            "up",
            len(actual_direction),
            accuracy,
            precision,
            recall,
            f1,
            accuracy,
            {"tp": tp, "tn": tn, "fp": fp, "fn": fn},
            "success",
            "",
            dataset_name,
        )
        return fold_rows, [class_row]

    def _classification_result_row(self, trade_date, run_id, template_name, dataset_name, task_name, class_label, prediction_count, accuracy, precision, recall, f1, roc_auc, confusion_matrix, status, reason, source_dataset) -> Dict[str, str]:
        return {
            "trade_date": str(trade_date),
            "run_id": str(run_id),
            "template_name": str(template_name),
            "dataset": str(dataset_name),
            "task_name": str(task_name),
            "class_label": str(class_label),
            "prediction_count": str(prediction_count),
            "accuracy": self._fmt_optional(accuracy),
            "precision": self._fmt_optional(precision),
            "recall": self._fmt_optional(recall),
            "f1": self._fmt_optional(f1),
            "roc_auc": self._fmt_optional(roc_auc),
            "confusion_matrix": safe_json_dumps(confusion_matrix),
            "status": str(status),
            "reason": str(reason),
            "source_dataset": str(source_dataset),
            **self._derived_provenance("platform.ml_classification", f"duckdb://{dataset_name}", "", f"{trade_date}:{run_id}:{template_name}:{task_name}:{accuracy}:{status}"),
        }

    def _factor_experiment_rows(self, trade_date: str, run_id: str, factor: str, dataset_name: str, asset_family: str, params: Dict[str, object], perf_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
        metrics = {str(row.get("metric_name", "")): str(row.get("metric_value", "")) for row in perf_rows}
        status = "success" if any(str(row.get("status")) == "success" for row in perf_rows) else "not_applicable"
        reason = "" if status == "success" else "factor experiment requires valid factor performance rows"
        parameter_set = safe_json_dumps(params or {"window": "default"})
        return [{
            "trade_date": trade_date,
            "run_id": run_id,
            "factor_name": factor,
            "dataset": dataset_name,
            "asset_family": asset_family,
            "parameter_set": parameter_set,
            "ic": metrics.get("ic", ""),
            "rank_ic": metrics.get("rank_ic", ""),
            "long_short_return": metrics.get("long_short_return", ""),
            "win_rate": metrics.get("win_rate", ""),
            "turnover": metrics.get("turnover", "0.00000000"),
            "coverage": metrics.get("coverage", ""),
            "status": status,
            "reason": reason,
            "source_dataset": dataset_name,
            **self._derived_provenance("platform.factor_experiment", f"duckdb://{dataset_name}", "", f"{trade_date}:{run_id}:{factor}:{parameter_set}:{metrics}", include_checksum=True),
        }]

    @staticmethod
    def _parse_grid(grid_json: str) -> List[Dict[str, object]]:
        text = str(grid_json or "").strip()
        if not text:
            parsed = {"window": [5, 20], "holding_period": [1, 5], "fee_bps": [1.0], "slippage_bps": [0.5]}
        else:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("--grid must be a JSON object")
        keys = list(parsed)
        grids: List[Dict[str, object]] = [{}]
        for key in keys:
            values = parsed[key] if isinstance(parsed[key], list) else [parsed[key]]
            grids = [dict(existing, **{key: value}) for existing in grids for value in values]
        return grids[:100]

    def _parameter_scan_rows(self, trade_date: str, run_id: str, template: str, dataset_name: str, asset_family: str, grid: List[Dict[str, object]]) -> List[Dict[str, str]]:
        rows = []
        for index, params in enumerate(grid, start=1):
            window = float(_float(params.get("window")) or index)
            holding = float(_float(params.get("holding_period")) or 1)
            fee = float(_float(params.get("fee_bps")) or 0)
            slippage = float(_float(params.get("slippage_bps")) or 0)
            score = 1.0 / (1.0 + abs(window - 20) / 20.0 + abs(holding - 5) / 10.0 + (fee + slippage) / 100.0)
            rows.append({
                "trade_date": trade_date,
                "run_id": run_id,
                "template_name": template,
                "dataset": dataset_name,
                "parameter_set": safe_json_dumps(params),
                "metric_name": "score",
                "metric_value": self._fmt_optional(score),
                "rank": "",
                "status": "success",
                "reason": "",
                "source_dataset": dataset_name,
                **self._derived_provenance("platform.parameter_scan", f"duckdb://{dataset_name}", "", f"{trade_date}:{run_id}:{template}:{index}:{score}"),
            })
        return self._rank_metric_rows(rows, "metric_value")

    def _strategy_leaderboard_rows(self, trade_date: str, run_id: str, dataset_name: str) -> List[Dict[str, str]]:
        comparison_rows = [row for row in self._load_platform_rows(STRATEGY_COMPARISONS_DATASET, trade_date) if not dataset_name or row.get("dataset") == dataset_name]
        by_strategy: Dict[str, Dict[str, str]] = defaultdict(dict)
        for row in comparison_rows:
            by_strategy[str(row.get("strategy_name", "strategy"))][str(row.get("metric_name", ""))] = str(row.get("strategy_value", ""))
        if not by_strategy:
            by_strategy["strategy:default"] = {}
        rows = []
        for strategy, metrics in by_strategy.items():
            annual_return = _float(metrics.get("annual_return")) or _float(metrics.get("total_return")) or 0.0
            annual_vol = _float(metrics.get("annual_volatility")) or 0.0
            sharpe = _float(metrics.get("sharpe")) or (annual_return / annual_vol if annual_vol else 0.0)
            max_drawdown = _float(metrics.get("max_drawdown")) or 0.0
            calmar = annual_return / abs(max_drawdown) if max_drawdown else 0.0
            win_rate = _float(metrics.get("win_rate")) or 0.0
            turnover = _float(metrics.get("turnover")) or 0.0
            quality = max(0.0, min(1.0, 0.35 + max(sharpe, 0.0) * 0.2 + max(calmar, 0.0) * 0.1 - abs(max_drawdown) * 0.2))
            status = "success" if comparison_rows else "not_applicable"
            rows.append({
                "trade_date": trade_date,
                "run_id": run_id,
                "strategy_name": strategy,
                "dataset": dataset_name,
                "annual_return": self._fmt_optional(annual_return),
                "annual_volatility": self._fmt_optional(annual_vol),
                "sharpe": self._fmt_optional(sharpe),
                "calmar": self._fmt_optional(calmar),
                "max_drawdown": self._fmt_optional(max_drawdown),
                "win_rate": self._fmt_optional(win_rate),
                "turnover": self._fmt_optional(turnover),
                "quality_score": self._fmt_optional(quality),
                "rank": "",
                "status": status,
                "reason": "" if comparison_rows else "run backtest-run first to build strategy comparison rows",
                "source_dataset": dataset_name,
                **self._derived_provenance("platform.strategy_leaderboard", f"duckdb://{dataset_name}", "", f"{trade_date}:{run_id}:{strategy}:{quality}"),
            })
        return self._rank_metric_rows(rows, "quality_score")

    def _portfolio_experiment_rows(self, trade_date: str, run_id: str, template: str, dataset_name: str, params_json: str, allocation: Dict[str, object]) -> List[Dict[str, str]]:
        allocation_summary = ((allocation.get("datasets") or {}).get(PORTFOLIO_ALLOCATIONS_DATASET) or {}) if isinstance(allocation, dict) else {}
        row_count = int(allocation_summary.get("row_count", 0) or 0)
        params = self._parse_params(params_json)
        metrics = {"allocation_count": row_count, "target_notional": _float(params.get("notional")) or 1_000_000.0}
        status = str(allocation.get("status") or ("success" if row_count else "not_applicable"))
        return [
            {
                "trade_date": trade_date,
                "run_id": run_id,
                "template_name": template,
                "dataset": dataset_name,
                "portfolio_id": f"portfolio:{template}",
                "metric_name": metric_name,
                "metric_value": self._fmt_optional(metric_value),
                "parameters": safe_json_dumps(params),
                "status": status,
                "reason": "" if row_count else "portfolio optimization produced no allocation rows",
                "source_dataset": dataset_name,
                **self._derived_provenance("platform.portfolio_experiment", f"duckdb://{dataset_name}", "", f"{trade_date}:{run_id}:{template}:{metric_name}:{metric_value}"),
            }
            for metric_name, metric_value in metrics.items()
        ]

    def _scenario_rows(self, trade_date: str, run_id: str, template: str, dataset_name: str, params_json: str, stress_rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
        params = self._parse_params(params_json)
        rows = []
        for row in stress_rows:
            if str(row.get("metric_name")) != "portfolio_value":
                continue
            rows.append({
                "trade_date": trade_date,
                "run_id": run_id,
                "scenario_name": str(row.get("scenario_name") or template),
                "dataset": dataset_name,
                "portfolio_id": str(row.get("portfolio_id") or f"portfolio:{template}"),
                "base_value": str(row.get("base_value", "")),
                "stressed_value": str(row.get("stressed_value", "")),
                "impact_value": str(row.get("impact_value", "")),
                "impact_pct": str(row.get("impact_pct", "")),
                "parameters": safe_json_dumps(params),
                "status": str(row.get("status") or "success"),
                "reason": str(row.get("reason") or ""),
                "source_dataset": dataset_name,
                **self._derived_provenance("platform.scenario_simulation", f"duckdb://{dataset_name}", "", f"{trade_date}:{run_id}:{template}:{row.get('impact_pct','')}"),
            })
        return rows or [{
            "trade_date": trade_date,
            "run_id": run_id,
            "scenario_name": template,
            "dataset": dataset_name,
            "portfolio_id": f"portfolio:{template}",
            "base_value": "",
            "stressed_value": "",
            "impact_value": "",
            "impact_pct": "",
            "parameters": safe_json_dumps(params),
            "status": "not_applicable",
            "reason": "scenario simulation requires stress test rows",
            "source_dataset": dataset_name,
            **self._derived_provenance("platform.scenario_simulation", f"duckdb://{dataset_name}", "", f"{trade_date}:{run_id}:{template}:empty"),
        }]

    def _project_row(self, trade_date: str, project_id: str, name: str, description: str, status: str) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "project_id": project_id,
            "name": str(name or project_id),
            "description": str(description),
            "status": status,
            "created_at": iso_timestamp(),
            "updated_at": iso_timestamp(),
            **self._derived_provenance("platform.project", f"platform://projects/{project_id}", "", f"{trade_date}:{project_id}:{name}:{description}:{status}", include_checksum=True),
        }

    def _project_run_row(self, trade_date: str, project_id: str, run_id: str, template: str, dataset_name: str, start_date: str, end_date: str, params_json: str, status: str, reason: str) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "project_id": project_id,
            "run_id": run_id,
            "template_name": template,
            "dataset": dataset_name,
            "start_date": start_date,
            "end_date": end_date,
            "parameters": params_json or "{}",
            "artifact_count": "0",
            "status": status,
            "reason": reason,
            **self._derived_provenance("platform.project_run", f"platform://projects/{project_id}/runs/{run_id}", "", f"{trade_date}:{project_id}:{run_id}:{template}:{dataset_name}:{params_json}", include_checksum=True),
        }

    def _reproducible_package_row(self, trade_date: str, package_id: str, run_id: str) -> Dict[str, str]:
        package_dir = self.project_root / "exports" / "packages" / package_id
        ensure_directory(package_dir)
        manifest = {
            "package_id": package_id,
            "run_id": run_id,
            "trade_date": trade_date,
            "generated_at": iso_timestamp(),
            "source_datasets": [EXPERIMENT_RUNS_DATASET, ARTIFACT_MANIFEST_DATASET, RESEARCH_REPORTS_DATASET],
        }
        manifest_path = package_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        zip_path = package_dir.with_suffix(".zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(manifest_path, arcname="manifest.json")
        checksum = _sha1_text(zip_path.read_bytes().hex())
        return {
            "trade_date": trade_date,
            "package_id": package_id,
            "run_id": run_id,
            "path": relative_to_project(zip_path, self.project_root),
            "source_datasets": ",".join(manifest["source_datasets"]),
            "parameters": safe_json_dumps({"run_id": run_id}),
            "artifact_count": "1",
            "checksum": checksum,
            "status": "success",
            "reason": "",
            "source_id": "platform.package",
            "source_url": f"platform://packages/{package_id}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": relative_to_project(manifest_path, self.project_root),
            "parser_version": PARSER_VERSION,
        }

    def _dataset_quality_score_rows(self, *, trade_date: str, run_id: str) -> List[Dict[str, str]]:
        rows = []
        source_health = self._load_platform_rows("source_health", trade_date)
        anomaly_events = self._load_platform_rows(ANOMALY_EVENTS_DATASET, trade_date)
        source_status = {str(row.get("dataset", "")): str(row.get("last_status", "")) for row in source_health}
        anomaly_count = Counter(str(row.get("dataset", "")) for row in anomaly_events)
        for dataset_name in sorted(DATASET_GLOBS):
            dataset_rows = self._load_platform_rows(dataset_name, trade_date) if str(DATASET_GLOBS.get(dataset_name, "")).startswith("platform/") else []
            row_count = len(dataset_rows)
            completeness = 1.0 if row_count else 0.6 if dataset_name in {BOND_ANALYTICS_DATASET, CURVE_ANALYTICS_DATASET} else 0.0
            freshness = 1.0 if row_count else 0.7
            health = 1.0 if source_status.get(dataset_name, "success") in {"", "success"} else 0.5
            anomaly_score = max(0.0, 1.0 - min(anomaly_count.get(dataset_name, 0), 10) / 10.0)
            score = max(0.0, min(1.0, 0.35 * completeness + 0.25 * freshness + 0.25 * health + 0.15 * anomaly_score))
            status = "success" if score >= 0.7 else "partial_success" if score >= 0.4 else "not_applicable"
            rows.append(self._dataset_quality_score_row(trade_date, dataset_name, "", score, completeness, freshness, health, anomaly_score, row_count, status, "" if row_count else "no rows on selected date or schema-only dataset", run_id))
        return rows

    def _record_experiment(self, *, trade_date: str, run_id: str, experiment_type: str, template_name: str, dataset_name: str, asset_family: str, start_date: str, end_date: str, status: str, reason: str, score_metric: str, score_value: str, parameters: Dict[str, object], artifact_count: int) -> None:
        row = {
            "trade_date": trade_date,
            "run_id": run_id,
            "experiment_type": experiment_type,
            "template_name": template_name,
            "dataset": dataset_name,
            "asset_family": asset_family,
            "window_start": start_date,
            "window_end": end_date,
            "status": status,
            "reason": reason,
            "score_metric": score_metric,
            "score_value": str(score_value),
            "parameters": safe_json_dumps(parameters),
            "artifact_count": str(artifact_count),
            "source_dataset": dataset_name,
            "source_id": "platform.experiment",
            "source_url": f"duckdb://{self.duckdb_path.name}",
            "source_type": "derived",
            "retrieved_at": iso_timestamp(),
            "raw_path": "",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{trade_date}:{run_id}:{experiment_type}:{template_name}:{dataset_name}:{status}:{score_value}"),
        }
        rows = self._merge_platform_rows(EXPERIMENT_RUNS_DATASET, trade_date, [row], ["trade_date", "run_id", "experiment_type", "template_name"])
        _write_platform_dataset(
            dataset_name=EXPERIMENT_RUNS_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=EXPERIMENT_RUNS_STANDARD_FIELDS,
            key_fields=["trade_date", "run_id", "experiment_type", "template_name"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )

    def _load_rows(self, dataset_name: str, *, start_date: str, end_date: str, asset_family: str = "") -> List[Dict[str, str]]:
        pattern = DATASET_GLOBS.get(dataset_name, f"platform/{dataset_name}/*.csv")
        rows: List[Dict[str, str]] = []
        for csv_path in sorted(self.normalized_root.glob(pattern)):
            for row in iter_csv_rows(csv_path):
                trade_date = str(row.get("trade_date", "") or csv_path.stem)
                if start_date <= trade_date <= end_date:
                    if asset_family and str(row.get("asset_family", "")) != asset_family:
                        continue
                    rows.append(dict(row))
        rows.sort(key=lambda item: (str(item.get("trade_date", "")), str(item.get("instrument_id", "")), str(item.get("symbol", "")), str(item.get("contract", ""))))
        return rows

    def _load_platform_rows(self, dataset_name: str, trade_date: str) -> List[Dict[str, str]]:
        csv_path = self.platform_dir / dataset_name / f"{trade_date}.csv"
        if csv_path.exists():
            return [dict(row) for row in iter_csv_rows(csv_path)]
        paths = sorted((self.platform_dir / dataset_name).glob("*.csv"))
        if not paths:
            return []
        return [dict(row) for row in iter_csv_rows(paths[-1])]

    def _merge_platform_rows(self, dataset_name: str, trade_date: str, rows: List[Dict[str, str]], key_fields: Sequence[str]) -> List[Dict[str, str]]:
        csv_path = self.platform_dir / dataset_name / f"{trade_date}.csv"
        existing = [dict(row) for row in iter_csv_rows(csv_path)] if csv_path.exists() else []
        if not existing:
            return rows
        merged: Dict[Tuple[str, ...], Dict[str, str]] = {}
        for row in existing + rows:
            key = tuple(str(row.get(field, "")) for field in key_fields)
            merged[key] = dict(row)
        return list(merged.values())

    def _resolve_date(self, date_value: str) -> str:
        text = str(date_value or "").strip()
        if text and text != "latest":
            return parse_trade_date(text).isoformat()
        candidates = []
        for dataset_name in RESEARCH_SOURCE_DATASETS + ["source_health", "asset_coverage", "validation_results"]:
            dataset_dir = self.platform_dir / dataset_name
            if dataset_dir.exists():
                candidates.extend(path.stem for path in dataset_dir.glob("*.csv"))
        return sorted(candidates)[-1] if candidates else now_shanghai().date().isoformat()

    def _resolve_window(self, *, date_value: str, start_date: str, end_date: str) -> Tuple[str, str]:
        if start_date and end_date:
            start = self._resolve_date(start_date) if str(start_date).strip() == "latest" else parse_trade_date(start_date).isoformat()
            end = self._resolve_date(end_date) if str(end_date).strip() == "latest" else parse_trade_date(end_date).isoformat()
            return start, end
        end = self._resolve_date(end_date or date_value)
        return end, end

    @staticmethod
    def _run_id(prefix: str) -> str:
        return f"{prefix}-{_sha1_text(iso_timestamp())}"

    @staticmethod
    def _extract_dataset_values(rows: List[Dict[str, str]]) -> List[float]:
        values: List[float] = []
        for row in rows:
            for field in PRICE_FIELDS:
                value = _float(row.get(field))
                if value is not None:
                    values.append(value)
                    break
        return values

    @staticmethod
    def _group_price_series(rows: List[Dict[str, str]]) -> Dict[str, List[Tuple[str, float, Dict[str, str]]]]:
        groups: Dict[str, List[Tuple[str, float, Dict[str, str]]]] = defaultdict(list)
        for row in rows:
            symbol = str(row.get("instrument_id") or row.get("symbol") or row.get("contract") or "").strip()
            if not symbol:
                continue
            value = next((_float(row.get(field)) for field in PRICE_FIELDS if _float(row.get(field)) is not None), None)
            if value is None:
                continue
            groups[symbol].append((str(row.get("trade_date", "")), value, dict(row)))
        for symbol in list(groups):
            groups[symbol].sort(key=lambda item: item[0])
        return groups

    @staticmethod
    def _returns(values: Sequence[float]) -> List[float]:
        result = []
        for index in range(1, len(values)):
            previous = values[index - 1]
            if previous:
                result.append(values[index] / previous - 1)
        return result

    @staticmethod
    def _stddev(values: Sequence[float]) -> float:
        if len(values) <= 1:
            return 0.0
        mean_value = sum(values) / len(values)
        return math.sqrt(sum((value - mean_value) ** 2 for value in values) / (len(values) - 1))

    @staticmethod
    def _max_drawdown(values: Sequence[float]) -> float:
        peak = values[0] if values else 0.0
        drawdown = 0.0
        for value in values:
            peak = max(peak, value)
            if peak:
                drawdown = min(drawdown, value / peak - 1)
        return drawdown

    @staticmethod
    def _curve_slope(rows: List[Dict[str, str]]) -> Optional[float]:
        points = []
        for row in rows:
            tenor_years = _float(row.get("tenor_years"))
            yield_value = _float(row.get("yield") or row.get("value"))
            if tenor_years is not None and yield_value is not None:
                points.append((tenor_years, yield_value))
        if len(points) < 2:
            return None
        points.sort()
        return points[-1][1] - points[0][1]

    @staticmethod
    def _parse_params(params_json: object) -> Dict[str, object]:
        if isinstance(params_json, dict):
            return dict(params_json)
        text = str(params_json or "").strip()
        if not text:
            return {}
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("--params must be a JSON object")
        return parsed

    @staticmethod
    def _fmt_optional(value) -> str:
        parsed = _float(value)
        return "" if parsed is None else f"{parsed:.8f}"

    @staticmethod
    def _first_float(row: Dict[str, str], fields: Sequence[str]) -> Optional[float]:
        for field in fields:
            value = _float(row.get(field))
            if value is not None:
                return value
        return None

    @staticmethod
    def _normal_cdf(value: float) -> float:
        return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))

    @staticmethod
    def _normal_pdf(value: float) -> float:
        return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)

    def _bs_metrics(self, s: float, k: float, t: float, r: float, sigma: float, option_type: str) -> Tuple[float, float, float, float, float]:
        if t <= 0 or sigma <= 0 or s <= 0 or k <= 0:
            intrinsic = max(s - k, 0.0) if option_type == "call" else max(k - s, 0.0)
            delta = 1.0 if option_type == "call" and s > k else -1.0 if option_type == "put" and s < k else 0.0
            return intrinsic, delta, 0.0, 0.0, 0.0
        sqrt_t = math.sqrt(t)
        d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
        d2 = d1 - sigma * sqrt_t
        if option_type == "put":
            price = k * math.exp(-r * t) * self._normal_cdf(-d2) - s * self._normal_cdf(-d1)
            delta = self._normal_cdf(d1) - 1.0
            theta = -s * self._normal_pdf(d1) * sigma / (2 * sqrt_t) + r * k * math.exp(-r * t) * self._normal_cdf(-d2)
        else:
            price = s * self._normal_cdf(d1) - k * math.exp(-r * t) * self._normal_cdf(d2)
            delta = self._normal_cdf(d1)
            theta = -s * self._normal_pdf(d1) * sigma / (2 * sqrt_t) - r * k * math.exp(-r * t) * self._normal_cdf(d2)
        gamma = self._normal_pdf(d1) / (s * sigma * sqrt_t)
        vega = s * self._normal_pdf(d1) * sqrt_t
        return price, delta, gamma, vega, theta / 365.0

    def _implied_volatility(self, market_price: float, s: float, k: float, t: float, r: float, option_type: str) -> Optional[float]:
        low, high = 1e-6, 5.0
        low_price = self._bs_metrics(s, k, t, r, low, option_type)[0]
        high_price = self._bs_metrics(s, k, t, r, high, option_type)[0]
        if not (low_price <= market_price <= high_price):
            return None
        for _ in range(80):
            mid = (low + high) / 2
            price = self._bs_metrics(s, k, t, r, mid, option_type)[0]
            if price < market_price:
                low = mid
            else:
                high = mid
        return (low + high) / 2

    def _binomial_price(self, s: float, k: float, t: float, r: float, sigma: float, option_type: str, *, steps: int, american: bool) -> float:
        dt = t / steps if steps else t
        if dt <= 0:
            return max(s - k, 0.0) if option_type == "call" else max(k - s, 0.0)
        up = math.exp(sigma * math.sqrt(dt))
        down = 1 / up
        discount = math.exp(-r * dt)
        probability = (math.exp(r * dt) - down) / (up - down)
        probability = min(max(probability, 0.0), 1.0)
        values = []
        for index in range(steps + 1):
            price = s * (up ** (steps - index)) * (down ** index)
            values.append(max(price - k, 0.0) if option_type == "call" else max(k - price, 0.0))
        for step in range(steps - 1, -1, -1):
            next_values = []
            for index in range(step + 1):
                continuation = discount * (probability * values[index] + (1 - probability) * values[index + 1])
                if american:
                    price = s * (up ** (step - index)) * (down ** index)
                    exercise = max(price - k, 0.0) if option_type == "call" else max(k - price, 0.0)
                    continuation = max(continuation, exercise)
                next_values.append(continuation)
            values = next_values
        return values[0]

    def _bond_price_from_ytm(self, *, ytm: float, coupon_rate: float, maturity_years: float, face_value: float, frequency: int) -> float:
        periods = max(1, int(round(maturity_years * frequency)))
        coupon = face_value * coupon_rate / frequency
        price = 0.0
        for period in range(1, periods + 1):
            cashflow = coupon + (face_value if period == periods else 0.0)
            price += cashflow / ((1 + ytm / frequency) ** period)
        return price

    def _bond_ytm(self, *, price: float, coupon_rate: float, maturity_years: float, face_value: float, frequency: int) -> Optional[float]:
        low, high = -0.95, 1.0
        for _ in range(100):
            mid = (low + high) / 2
            mid_price = self._bond_price_from_ytm(ytm=mid, coupon_rate=coupon_rate, maturity_years=maturity_years, face_value=face_value, frequency=frequency)
            if mid_price > price:
                low = mid
            else:
                high = mid
        result = (low + high) / 2
        return result if -0.95 < result < 1.0 else None

    def _bond_duration_convexity(self, *, price: float, coupon_rate: float, maturity_years: float, face_value: float, ytm: float, frequency: int) -> Tuple[float, float, float]:
        periods = max(1, int(round(maturity_years * frequency)))
        coupon = face_value * coupon_rate / frequency
        weighted = 0.0
        convexity_sum = 0.0
        for period in range(1, periods + 1):
            cashflow = coupon + (face_value if period == periods else 0.0)
            discount = (1 + ytm / frequency) ** period
            present = cashflow / discount
            time_years = period / frequency
            weighted += time_years * present
            convexity_sum += present * period * (period + 1)
        duration = weighted / price if price else 0.0
        modified = duration / (1 + ytm / frequency) if frequency else duration
        convexity = convexity_sum / (price * (frequency ** 2) * ((1 + ytm / frequency) ** 2)) if price and frequency else 0.0
        return duration, modified, convexity

    def _spread_metric(self, source_rows: List[Dict[str, str]], params: Dict[str, object]) -> Tuple[Optional[float], str]:
        near = _float(params.get("near_price"))
        far = _float(params.get("far_price"))
        if near is not None and far is not None:
            return far - near, ""
        values = []
        for row in source_rows:
            close_value = self._first_float(row, PRICE_FIELDS)
            basis_value = self._first_float(row, ("settlement", "pre_close", "pre_settlement"))
            if close_value is not None and basis_value is not None:
                values.append(close_value - basis_value)
        if values:
            return values[-1], ""
        groups = self._group_price_series(source_rows)
        latest = [(symbol, items[-1][1]) for symbol, items in groups.items() if items]
        latest.sort()
        if len(latest) >= 2:
            return latest[-1][1] - latest[0][1], ""
        return None, "requires near_price/far_price params or at least two priced contracts"

    def _returns_by_symbol(self, groups: Dict[str, List[Tuple[str, float, Dict[str, str]]]]) -> Dict[str, List[float]]:
        result = {}
        for symbol, items in groups.items():
            values = [value for _date, value, _row in items]
            returns = self._returns(values)
            if returns:
                result[symbol] = returns
        return result

    @staticmethod
    def _portfolio_returns(returns_by_symbol: Dict[str, List[float]]) -> List[float]:
        if not returns_by_symbol:
            return []
        max_len = max(len(values) for values in returns_by_symbol.values())
        result = []
        for index in range(max_len):
            bucket = [values[index] for values in returns_by_symbol.values() if index < len(values)]
            if bucket:
                result.append(sum(bucket) / len(bucket))
        return result

    def _portfolio_weights(self, *, template_name: str, groups: Dict[str, List[Tuple[str, float, Dict[str, str]]]]) -> Dict[str, float]:
        returns_by_symbol = self._returns_by_symbol(groups)
        symbols = sorted(returns_by_symbol)
        if not symbols:
            return {}
        scores: Dict[str, float] = {}
        for symbol in symbols:
            returns = returns_by_symbol[symbol]
            mean_return = sum(returns) / len(returns) if returns else 0.0
            vol = self._stddev(returns) or 1e-9
            if template_name == "risk_parity":
                score = 1 / vol
            elif template_name in {"mean_variance", "momentum"}:
                score = max(mean_return, 0.0) / vol
            elif template_name == "mean_reversion":
                score = max(-mean_return, 0.0) / vol
            else:
                score = 1.0
            scores[symbol] = max(score, 0.0)
        total = sum(scores.values())
        if total <= 0:
            return {symbol: 1 / len(symbols) for symbol in symbols}
        return {symbol: score / total for symbol, score in scores.items()}

    def _correlation(self, left: Sequence[float], right: Sequence[float]) -> Optional[float]:
        size = min(len(left), len(right))
        if size < 2:
            return None
        left_values = list(left[-size:])
        right_values = list(right[-size:])
        left_mean = sum(left_values) / size
        right_mean = sum(right_values) / size
        numerator = sum((left_values[index] - left_mean) * (right_values[index] - right_mean) for index in range(size))
        left_den = math.sqrt(sum((value - left_mean) ** 2 for value in left_values))
        right_den = math.sqrt(sum((value - right_mean) ** 2 for value in right_values))
        if not left_den or not right_den:
            return None
        return numerator / (left_den * right_den)

    @staticmethod
    def _merge_statuses(statuses: Iterable[str]) -> str:
        normalized = [str(status or "").strip() for status in statuses if str(status or "").strip()]
        if not normalized:
            return ""
        if all(status == "success" for status in normalized):
            return "success"
        if any(status == "success" for status in normalized) and all(status in {"success", "no_data", "not_applicable"} for status in normalized):
            return "success"
        if any(status == "failed" for status in normalized):
            return "failed"
        if any(status == "partial_success" for status in normalized):
            return "partial_success"
        if any(status == "pending_retry" for status in normalized):
            return "pending_retry"
        if any(status == "success" for status in normalized):
            return "partial_success"
        if all(status == "not_applicable" for status in normalized):
            return "not_applicable"
        if all(status == "no_data" for status in normalized):
            return "no_data"
        return normalized[0]


class SchedulerRunner:
    def __init__(
        self,
        *,
        project_root: Path = PROJECT_ROOT,
        schedules_path: Path = SCHEDULES_STATE_PATH,
        runs_path: Path = SCHEDULER_RUNS_STATE_PATH,
        platform_dir: Path = PLATFORM_NORMALIZED_DIR,
        subprocess_runner=subprocess.run,
    ):
        self.project_root = project_root
        self.schedules_path = schedules_path
        self.runs_path = runs_path
        self.platform_dir = platform_dir
        self.subprocess_runner = subprocess_runner
        ensure_directory(self.schedules_path.parent)
        ensure_directory(self.runs_path.parent)

    def read_schedules(self) -> Dict[str, object]:
        if not self.schedules_path.exists():
            payload = {"updated_at": iso_timestamp(), "schedules": self.default_schedules()}
            self._write_json(self.schedules_path, payload)
            return payload
        payload = json.loads(self.schedules_path.read_text(encoding="utf-8"))
        if self._merge_default_schedules(payload):
            payload["updated_at"] = iso_timestamp()
            self._write_json(self.schedules_path, payload)
        return payload

    def read_runs(self) -> Dict[str, object]:
        if not self.runs_path.exists():
            return {"updated_at": "", "runs": []}
        return json.loads(self.runs_path.read_text(encoding="utf-8"))

    def set_enabled(self, *, schedule_id: str, enabled: bool) -> Dict[str, object]:
        payload = self.read_schedules()
        for schedule in payload.get("schedules", []):
            if str(schedule.get("schedule_id")) == schedule_id:
                schedule["enabled"] = bool(enabled)
                schedule["updated_at"] = iso_timestamp()
                break
        payload["updated_at"] = iso_timestamp()
        self._write_json(self.schedules_path, payload)
        return {"status": "success", "schedule_id": schedule_id, "enabled": bool(enabled)}

    def tick(self, *, run_all_due: bool = True, schedule_id: str = "") -> Dict[str, object]:
        schedules_payload = self.read_schedules()
        now = now_shanghai()
        due_schedules = []
        for schedule in schedules_payload.get("schedules", []):
            if schedule_id and str(schedule.get("schedule_id")) != schedule_id:
                continue
            if not bool(schedule.get("enabled", False)):
                continue
            due_at = str(schedule.get("next_run_at", "") or "")
            is_due = not due_at or due_at <= now.isoformat()
            if is_due or schedule_id:
                due_schedules.append(schedule)
            if schedule_id:
                break
        if not run_all_due and due_schedules:
            due_schedules = due_schedules[:1]
        run_rows = []
        for schedule in due_schedules:
            run_rows.append(self._execute_schedule(schedule))
            schedule["last_run_at"] = run_rows[-1]["finished_at"]
            schedule["next_run_at"] = self._next_run_at(str(schedule.get("cadence", "daily")), now)
            schedule["updated_at"] = iso_timestamp()
        schedules_payload["updated_at"] = iso_timestamp()
        self._write_json(self.schedules_path, schedules_payload)
        runs_payload = self.read_runs()
        runs = list(runs_payload.get("runs", []) or [])
        runs.extend(run_rows)
        runs_payload = {"updated_at": iso_timestamp(), "runs": runs[-200:]}
        self._write_json(self.runs_path, runs_payload)
        self.materialize_runs()
        statuses = [row.get("status", "") for row in run_rows]
        status = "success" if run_rows and all(item == "success" for item in statuses) else "no_data" if not run_rows else "partial_success"
        return {"status": status, "run_count": len(run_rows), "runs": run_rows, "updated_at": runs_payload["updated_at"]}

    def materialize_runs(self) -> Dict[str, object]:
        payload = self.read_runs()
        rows = []
        trade_date = now_shanghai().date().isoformat()
        for run in payload.get("runs", []) or []:
            rows.append({field: str(run.get(field, "")) for field in SCHEDULER_RUNS_STANDARD_FIELDS})
        return _write_platform_dataset(
            dataset_name=SCHEDULER_RUNS_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=SCHEDULER_RUNS_STANDARD_FIELDS,
            key_fields=["trade_date", "schedule_id", "run_id"],
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )

    def _execute_schedule(self, schedule: Dict[str, object]) -> Dict[str, str]:
        started_at = iso_timestamp()
        run_id = f"scheduler-{_sha1_text(started_at + str(schedule.get('schedule_id', '')))}"
        try:
            result_summary = self._run_action(str(schedule.get("action_name", "")))
            status = "success"
            message = ""
        except Exception as exc:
            result_summary = ""
            status = "failed"
            message = str(exc)
        finished_at = iso_timestamp()
        return {
            "trade_date": now_shanghai().date().isoformat(),
            "schedule_id": str(schedule.get("schedule_id", "")),
            "task_name": str(schedule.get("task_name", "")),
            "action_name": str(schedule.get("action_name", "")),
            "enabled": str(bool(schedule.get("enabled", False))).lower(),
            "due_at": str(schedule.get("next_run_at", "")),
            "started_at": started_at,
            "finished_at": finished_at,
            "status": status,
            "engineering_status": "success" if status == "success" else "partial",
            "message": message,
            "result_summary": result_summary,
            "next_run_at": self._next_run_at(str(schedule.get("cadence", "daily")), now_shanghai()),
            "source_id": "platform.scheduler",
            "source_url": "state/schedules.json",
            "source_type": "derived",
            "retrieved_at": finished_at,
            "raw_path": "state/scheduler_runs.json",
            "parser_version": PARSER_VERSION,
            "checksum": _sha1_text(f"{run_id}:{status}:{message}"),
            "run_id": run_id,
        }

    def _run_action(self, action_name: str) -> str:
        command_sets = {
            "full_latest": [
                ["sync-daily", "--date", "latest", "--instrument-group", "all"],
                ["sync-public-assets", "--date", "latest"],
                ["sync-public-references", "--date", "latest"],
                ["sync-public-bonds", "--date", "latest"],
                ["sync-crypto-observation", "--date", "latest"],
                ["sync-platform-metadata", "--date", "latest"],
                ["build-db"],
            ],
            "sync_platform_metadata": [["sync-platform-metadata", "--date", "latest"]],
            "build_db": [["build-db"]],
            "quality_diagnose": [["quality-diagnose", "--date", "latest"]],
            "quality_score": [["quality-score", "--date", "latest"]],
            "report_generate": [["report-generate", "--date", "latest", "--report-type", "comprehensive"]],
            "weekly_factor_performance": [["factor-performance", "--factor", "momentum", "--start", "latest", "--end", "latest", "--dataset", "daily_ohlcv"]],
            "weekly_backtest_run": [["backtest-run", "--strategy", "momentum", "--start", "latest", "--end", "latest", "--dataset", "daily_ohlcv"]],
            "monthly_history_sample": [["history-sync", "--scope", "public_assets", "--mode", "1y"]],
            "monthly_ml_evaluation": [["ml-run", "--template", "linear_regression", "--start", "latest", "--end", "latest", "--dataset", "daily_ohlcv"]],
            "regression_phase2": [["regression-smoke", "--profile", "phase2"]],
        }
        commands = command_sets.get(action_name)
        if not commands:
            raise ValueError(f"unsupported schedule action: {action_name}")
        summaries = []
        for args in commands:
            completed = self.subprocess_runner(
                [sys.executable, "-m", "futures_workflow", *args],
                cwd=str(self.project_root),
                capture_output=True,
                text=True,
                check=False,
            )
            stdout = str(getattr(completed, "stdout", "") or "").strip()
            stderr = str(getattr(completed, "stderr", "") or "").strip()
            if int(getattr(completed, "returncode", 0) or 0) != 0:
                raise RuntimeError(stderr or stdout or f"scheduler action failed: {' '.join(args)}")
            summaries.append(args[0])
        return ",".join(summaries)

    @staticmethod
    def default_schedules() -> List[Dict[str, object]]:
        now = now_shanghai().isoformat()
        return [
            {"schedule_id": "daily_full_latest", "task_name": "每日 latest 全量同步", "action_name": "full_latest", "cadence": "daily", "enabled": False, "next_run_at": now},
            {"schedule_id": "daily_platform_metadata", "task_name": "每日平台元数据同步", "action_name": "sync_platform_metadata", "cadence": "daily", "enabled": True, "next_run_at": now},
            {"schedule_id": "daily_build_db", "task_name": "每日 DuckDB 重建", "action_name": "build_db", "cadence": "daily", "enabled": True, "next_run_at": now},
            {"schedule_id": "daily_quality_diagnose", "task_name": "每日质量诊断", "action_name": "quality_diagnose", "cadence": "daily", "enabled": True, "next_run_at": now},
            {"schedule_id": "daily_quality_score", "task_name": "每日数据质量评分", "action_name": "quality_score", "cadence": "daily", "enabled": True, "next_run_at": now},
            {"schedule_id": "daily_report_generate", "task_name": "每日报告生成", "action_name": "report_generate", "cadence": "daily", "enabled": True, "next_run_at": now},
            {"schedule_id": "weekly_factor_performance", "task_name": "每周因子表现", "action_name": "weekly_factor_performance", "cadence": "weekly", "enabled": False, "next_run_at": now},
            {"schedule_id": "weekly_backtest_run", "task_name": "每周策略回测", "action_name": "weekly_backtest_run", "cadence": "weekly", "enabled": False, "next_run_at": now},
            {"schedule_id": "weekly_regression_phase2", "task_name": "每周 phase2 回归", "action_name": "regression_phase2", "cadence": "weekly", "enabled": False, "next_run_at": now},
            {"schedule_id": "monthly_history_sample", "task_name": "每月历史补样", "action_name": "monthly_history_sample", "cadence": "monthly", "enabled": False, "next_run_at": now},
            {"schedule_id": "monthly_ml_evaluation", "task_name": "每月 ML 评估", "action_name": "monthly_ml_evaluation", "cadence": "monthly", "enabled": False, "next_run_at": now},
        ]

    @staticmethod
    def _merge_default_schedules(payload: Dict[str, object]) -> bool:
        schedules = list(payload.get("schedules", []) or [])
        known_ids = {str(item.get("schedule_id", "")) for item in schedules}
        changed = False
        for default in SchedulerRunner.default_schedules():
            if str(default.get("schedule_id", "")) in known_ids:
                continue
            schedules.append(default)
            changed = True
        if changed:
            payload["schedules"] = schedules
        return changed

    @staticmethod
    def _next_run_at(cadence: str, now_value) -> str:
        delta = timedelta(days=30 if cadence == "monthly" else 7 if cadence == "weekly" else 1)
        return (now_value + delta).isoformat()

    @staticmethod
    def _write_json(path: Path, payload: Dict[str, object]) -> None:
        ensure_directory(path.parent)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
