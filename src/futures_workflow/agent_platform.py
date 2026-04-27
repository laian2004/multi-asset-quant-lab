import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .config import NORMALIZED_ROOT, PLATFORM_NORMALIZED_DIR, PROJECT_ROOT, REPORTS_DIR
from .constants import (
    AGENT_STEPS_DATASET,
    AGENT_STEPS_STANDARD_FIELDS,
    AGENT_TASKS_DATASET,
    AGENT_TASKS_STANDARD_FIELDS,
    DECISION_LOG_DATASET,
    DECISION_LOG_STANDARD_FIELDS,
    EXPERIMENT_NOTES_DATASET,
    EXPERIMENT_NOTES_STANDARD_FIELDS,
    FEATURE_VERSIONS_DATASET,
    FEATURE_VERSIONS_STANDARD_FIELDS,
    INPUT_RISK_FLAGS_DATASET,
    INPUT_RISK_FLAGS_STANDARD_FIELDS,
    ML_BENCHMARKS_DATASET,
    MODEL_DRIFT_EVENTS_DATASET,
    MODEL_DRIFT_EVENTS_STANDARD_FIELDS,
    MODEL_REGISTRY_DATASET,
    MODEL_REGISTRY_STANDARD_FIELDS,
    PLUGIN_REGISTRY_DATASET,
    PLUGIN_REGISTRY_STANDARD_FIELDS,
    PLUGIN_RUNS_DATASET,
    PLUGIN_RUNS_STANDARD_FIELDS,
    QUALITY_GATES_DATASET,
    QUALITY_GATES_STANDARD_FIELDS,
    RECOMMENDATION_ITEMS_DATASET,
    RECOMMENDATION_ITEMS_STANDARD_FIELDS,
    REPORT_INSIGHTS_DATASET,
    REPORT_INSIGHTS_STANDARD_FIELDS,
    RESEARCH_MEMORY_DATASET,
    RESEARCH_MEMORY_STANDARD_FIELDS,
    RESEARCH_READINESS_DATASET,
    RESEARCH_READINESS_STANDARD_FIELDS,
    TASK_LOGS_DATASET,
    TASK_LOGS_STANDARD_FIELDS,
    TASK_QUEUE_DATASET,
    TASK_QUEUE_STANDARD_FIELDS,
    TASK_RETRIES_DATASET,
    TASK_RETRIES_STANDARD_FIELDS,
)
from .normalize.csv_utils import write_dict_rows_csv
from .research_platform import ResearchPlatformRunner, _write_platform_dataset
from .storage import DATASET_GLOBS
from .utils import ensure_directory, iso_timestamp, iter_csv_rows, now_shanghai, parse_trade_date, safe_json_dumps


PARSER_VERSION = "agent_platform_v1"


@dataclass(frozen=True)
class PluginSpec:
    plugin_id: str
    category: str
    label: str
    inputs: List[str]
    outputs: List[str]
    required_datasets: List[str]
    risk_level: str
    supports_dry_run: bool
    produces_artifacts: bool
    description: str


class PluginRegistry:
    """产品内部插件白名单。

    插件只声明和编排仓库内已有能力，不开放任意 Python 脚本执行。
    """

    _PLUGINS: Tuple[PluginSpec, ...] = (
        PluginSpec(
            plugin_id="data.inventory",
            category="data",
            label="数据资产地图",
            inputs=["date"],
            outputs=["dataset_inventory", "dataset_field_profile"],
            required_datasets=[],
            risk_level="low",
            supports_dry_run=True,
            produces_artifacts=False,
            description="扫描 normalized/DuckDB 数据资产，生成数据集清单和字段画像。",
        ),
        PluginSpec(
            plugin_id="quality.gate",
            category="quality",
            label="质量守门",
            inputs=["dataset", "asset_family", "start_date", "end_date"],
            outputs=["quality_gates", "research_readiness", "input_risk_flags"],
            required_datasets=[],
            risk_level="low",
            supports_dry_run=True,
            produces_artifacts=False,
            description="检查研究输入是否足够、是否为空、是否需要先补数据。",
        ),
        PluginSpec(
            plugin_id="feature.run",
            category="feature",
            label="Feature Store 生成",
            inputs=["dataset", "asset_family", "start_date", "end_date", "params"],
            outputs=["ml_feature_store", "feature_versions"],
            required_datasets=[],
            risk_level="medium",
            supports_dry_run=False,
            produces_artifacts=True,
            description="基于 normalized/DuckDB 数据生成可复用研究特征。",
        ),
        PluginSpec(
            plugin_id="factor.experiment",
            category="factor",
            label="因子实验",
            inputs=["dataset", "asset_family", "start_date", "end_date", "params"],
            outputs=["factor_experiments", "factor_performance"],
            required_datasets=[],
            risk_level="medium",
            supports_dry_run=False,
            produces_artifacts=True,
            description="运行内置因子实验并记录因子表现。",
        ),
        PluginSpec(
            plugin_id="ml.benchmark",
            category="ml",
            label="ML Benchmark",
            inputs=["dataset", "asset_family", "start_date", "end_date", "params"],
            outputs=["ml_benchmarks", "ml_model_runs", "model_diagnostics"],
            required_datasets=[],
            risk_level="medium",
            supports_dry_run=False,
            produces_artifacts=True,
            description="运行白名单机器学习模型榜单，字段不足时诚实降级。",
        ),
        PluginSpec(
            plugin_id="backtest.run",
            category="backtest",
            label="正式回测",
            inputs=["dataset", "asset_family", "start_date", "end_date", "params"],
            outputs=["backtest_equity_curves", "backtest_positions", "backtest_trades", "strategy_comparisons"],
            required_datasets=[],
            risk_level="medium",
            supports_dry_run=False,
            produces_artifacts=True,
            description="运行日频研究回测，不连接券商、不真实下单。",
        ),
        PluginSpec(
            plugin_id="report.generate",
            category="report",
            label="报告生成",
            inputs=["date", "report_type"],
            outputs=["research_reports", "report_artifacts", "report_insights"],
            required_datasets=[],
            risk_level="low",
            supports_dry_run=False,
            produces_artifacts=True,
            description="生成本地 HTML/Markdown 报告和自动解读。",
        ),
        PluginSpec(
            plugin_id="lineage.build",
            category="lineage",
            label="数据血缘",
            inputs=["date"],
            outputs=["data_lineage", "artifact_manifest"],
            required_datasets=[],
            risk_level="low",
            supports_dry_run=False,
            produces_artifacts=True,
            description="为算法、报告、项目与可复现包记录血缘。",
        ),
        PluginSpec(
            plugin_id="project.package",
            category="project",
            label="可复现包",
            inputs=["date", "run_id"],
            outputs=["reproducible_packages"],
            required_datasets=[],
            risk_level="low",
            supports_dry_run=False,
            produces_artifacts=True,
            description="导出本地研究可复现包。",
        ),
        PluginSpec(
            plugin_id="agent.workflow",
            category="agent",
            label="Agent 工作流",
            inputs=["goal", "dataset", "asset_family", "start_date", "end_date", "mode"],
            outputs=["agent_tasks", "agent_steps", "plugin_runs", "task_logs"],
            required_datasets=[],
            risk_level="medium",
            supports_dry_run=True,
            produces_artifacts=True,
            description="把用户目标拆成可确认、可重试、可追踪的本地研究任务。",
        ),
    )

    def __init__(self, plugins: Optional[Iterable[PluginSpec]] = None):
        self._plugins = {plugin.plugin_id: plugin for plugin in (plugins or self._PLUGINS)}

    def list(self, *, category: str = "") -> List[PluginSpec]:
        result = list(self._plugins.values())
        if category:
            result = [plugin for plugin in result if plugin.category == category]
        return sorted(result, key=lambda item: item.plugin_id)

    def get(self, plugin_id: str) -> PluginSpec:
        key = str(plugin_id or "").strip()
        if key not in self._plugins:
            raise ValueError(f"unsupported plugin_id: {key}")
        return self._plugins[key]

    def to_rows(self, *, trade_date: str, run_id: str) -> List[Dict[str, str]]:
        rows = []
        for plugin in self.list():
            checksum_text = json.dumps(asdict(plugin), ensure_ascii=False, sort_keys=True)
            rows.append(
                {
                    "trade_date": trade_date,
                    "plugin_id": plugin.plugin_id,
                    "category": plugin.category,
                    "label": plugin.label,
                    "inputs": safe_json_dumps(plugin.inputs),
                    "outputs": safe_json_dumps(plugin.outputs),
                    "required_datasets": safe_json_dumps(plugin.required_datasets),
                    "risk_level": plugin.risk_level,
                    "supports_dry_run": str(bool(plugin.supports_dry_run)),
                    "produces_artifacts": str(bool(plugin.produces_artifacts)),
                    "status": "success",
                    "reason": plugin.description,
                    **_provenance("platform.plugin_registry", f"platform://plugins/{plugin.plugin_id}", "", checksum_text, run_id=run_id),
                }
            )
        return rows


class AgentOrchestrator:
    def __init__(
        self,
        *,
        project_root: Path = PROJECT_ROOT,
        normalized_root: Path = NORMALIZED_ROOT,
        platform_dir: Path = PLATFORM_NORMALIZED_DIR,
        reports_dir: Path = REPORTS_DIR,
        registry: Optional[PluginRegistry] = None,
        research_runner: Optional[ResearchPlatformRunner] = None,
    ):
        self.project_root = project_root
        self.normalized_root = normalized_root
        self.platform_dir = platform_dir
        self.reports_dir = reports_dir
        self.registry = registry or PluginRegistry()
        self.research_runner = research_runner or ResearchPlatformRunner(
            project_root=project_root,
            normalized_root=normalized_root,
            platform_dir=platform_dir,
            reports_dir=reports_dir,
        )
        ensure_directory(self.platform_dir)

    def plugin_list(self, *, date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        run_id = _run_id("plugins")
        rows = self.registry.to_rows(trade_date=trade_date, run_id=run_id)
        summary = self._write_dataset(
            PLUGIN_REGISTRY_DATASET,
            trade_date,
            rows,
            PLUGIN_REGISTRY_STANDARD_FIELDS,
            ["trade_date", "plugin_id"],
        )
        return {"status": summary["status"], "trade_date": trade_date, "run_id": run_id, "plugins": [asdict(item) for item in self.registry.list()], "datasets": {PLUGIN_REGISTRY_DATASET: summary}}

    def quality_gate(
        self,
        *,
        dataset: str,
        start_date: str = "",
        end_date: str = "",
        asset_family: str = "",
        task_id: str = "",
    ) -> Dict[str, object]:
        start, end = self._resolve_window(start_date=start_date, end_date=end_date)
        run_id = _run_id("gate")
        rows = self._load_rows(dataset, start_date=start, end_date=end, asset_family=asset_family)
        sample_count = len(rows)
        missing_ratio = self._missing_ratio(rows)
        if sample_count == 0:
            gate_status = "blocked"
            severity = "critical"
            message = "未找到可用于研究的输入数据，需要先抓取或同步该窗口。"
            recommendation = "先在 /crawl 或 agent-run 中补齐数据，再运行算法/回测/ML。"
        elif sample_count < 20 or missing_ratio > 0.55:
            gate_status = "warning"
            severity = "warning"
            message = "输入数据较少或字段缺失较高，结果仅适合探索验证。"
            recommendation = "建议扩大窗口、检查 source health，或选择字段更完整的数据集。"
        else:
            gate_status = "pass"
            severity = "info"
            message = "输入数据通过首层质量守门，可以进入研究编排。"
            recommendation = "可以继续运行 Feature Store、因子、ML、回测和报告。"
        gate_id = _short_hash(f"{task_id}:{dataset}:{start}:{end}:{sample_count}:{missing_ratio}")
        gate_row = {
            "trade_date": end,
            "gate_id": gate_id,
            "task_id": task_id,
            "dataset": dataset,
            "asset_family": asset_family,
            "start_date": start,
            "end_date": end,
            "gate_status": gate_status,
            "severity": severity,
            "sample_count": str(sample_count),
            "missing_ratio": f"{missing_ratio:.6f}",
            "source_health_status": "unknown",
            "message": message,
            "recommendation": recommendation,
            **_provenance("platform.quality_gate", f"duckdb://{dataset}", "", f"{gate_id}:{message}", run_id=run_id),
        }
        readiness_score = "1.000000" if gate_status == "pass" else "0.600000" if gate_status == "warning" else "0.000000"
        readiness_row = {
            "trade_date": end,
            "readiness_id": f"readiness-{gate_id}",
            "task_id": task_id,
            "dataset": dataset,
            "asset_family": asset_family,
            "readiness_status": "ready" if gate_status == "pass" else "limited" if gate_status == "warning" else "blocked",
            "score": readiness_score,
            "gate_status": gate_status,
            "risk_flags": "[]" if gate_status == "pass" else safe_json_dumps([severity]),
            "message": message,
            **_provenance("platform.research_readiness", f"duckdb://{dataset}", "", f"{gate_id}:{readiness_score}", run_id=run_id),
        }
        risk_rows = []
        if gate_status != "pass":
            risk_rows.append(
                {
                    "trade_date": end,
                    "flag_id": f"risk-{gate_id}",
                    "task_id": task_id,
                    "dataset": dataset,
                    "risk_type": "insufficient_input" if sample_count == 0 else "thin_or_sparse_input",
                    "severity": severity,
                    "message": message,
                    "recommendation": recommendation,
                    "status": "open",
                    **_provenance("platform.input_risk", f"duckdb://{dataset}", "", f"{gate_id}:{severity}", run_id=run_id),
                }
            )
        summaries = {
            QUALITY_GATES_DATASET: self._write_dataset(QUALITY_GATES_DATASET, end, [gate_row], QUALITY_GATES_STANDARD_FIELDS, ["trade_date", "gate_id"]),
            RESEARCH_READINESS_DATASET: self._write_dataset(RESEARCH_READINESS_DATASET, end, [readiness_row], RESEARCH_READINESS_STANDARD_FIELDS, ["trade_date", "readiness_id"]),
            INPUT_RISK_FLAGS_DATASET: self._write_dataset(INPUT_RISK_FLAGS_DATASET, end, risk_rows, INPUT_RISK_FLAGS_STANDARD_FIELDS, ["trade_date", "flag_id"]),
        }
        return {
            "status": gate_status,
            "engineering_status": "success",
            "trade_date": end,
            "run_id": run_id,
            "gate": gate_row,
            "datasets": summaries,
        }

    def agent_plan(
        self,
        *,
        goal: str,
        start_date: str = "",
        end_date: str = "",
        dataset: str = "daily_ohlcv",
        asset_family: str = "",
        mode: str = "research",
        report_type: str = "comprehensive",
    ) -> Dict[str, object]:
        start, end = self._resolve_window(start_date=start_date, end_date=end_date)
        created_at = iso_timestamp()
        task_id = f"agent-{_short_hash(f'{goal}:{dataset}:{asset_family}:{start}:{end}:{created_at}')}"
        run_id = _run_id("agentplan")
        steps = self._draft_steps(task_id=task_id, dataset=dataset, asset_family=asset_family, start=start, end=end, report_type=report_type)
        risk_summary = self._risk_summary(goal=goal, steps=steps, dataset=dataset, start=start, end=end)
        draft_plan = [
            {
                "step_id": step["step_id"],
                "plugin_id": step["plugin_id"],
                "step_name": step["step_name"],
                "risk_level": step["risk_level"],
            }
            for step in steps
        ]
        task_row = {
            "trade_date": end,
            "task_id": task_id,
            "goal": goal,
            "asset_family": asset_family,
            "dataset": dataset,
            "start_date": start,
            "end_date": end,
            "mode": mode,
            "report_type": report_type,
            "status": "awaiting_confirmation",
            "engineering_status": "draft",
            "draft_plan": safe_json_dumps(draft_plan),
            "risk_summary": risk_summary,
            "created_at": created_at,
            "updated_at": created_at,
            "confirmed_at": "",
            **_provenance("platform.agent", f"platform://agent/{task_id}", "", f"{task_id}:{goal}:{draft_plan}", run_id=run_id),
        }
        step_rows = []
        for step in steps:
            row = dict(step)
            row.update(
                {
                    "trade_date": end,
                    "status": "draft",
                    "engineering_status": "draft",
                    "outputs": "{}",
                    "artifacts": "[]",
                    "reason": "等待用户确认后执行。",
                    "started_at": "",
                    "finished_at": "",
                    **_provenance("platform.agent_step", f"platform://agent/{task_id}/{step['step_id']}", "", f"{task_id}:{step['step_id']}", run_id=run_id),
                }
            )
            step_rows.append(row)
        queue_row = self._queue_row(end, task_id, "awaiting_confirmation", "等待确认，长任务尚未执行。", run_id)
        log_row = self._log_row(end, task_id, "", "info", "Agent 已生成草案计划，等待用户确认。", run_id)
        memory_row = self._memory_row(end, task_id, goal, "plan", "Agent 计划草案", risk_summary, "agent,plan,draft", run_id)
        decision_row = self._decision_row(end, task_id, "confirmation_required", "awaiting_confirmation", "长任务需要用户在 GUI 或 CLI 确认后执行。", run_id)
        summaries = {
            AGENT_TASKS_DATASET: self._write_dataset(AGENT_TASKS_DATASET, end, [task_row], AGENT_TASKS_STANDARD_FIELDS, ["trade_date", "task_id"]),
            AGENT_STEPS_DATASET: self._write_dataset(AGENT_STEPS_DATASET, end, step_rows, AGENT_STEPS_STANDARD_FIELDS, ["trade_date", "task_id", "step_id"]),
            TASK_QUEUE_DATASET: self._write_dataset(TASK_QUEUE_DATASET, end, [queue_row], TASK_QUEUE_STANDARD_FIELDS, ["trade_date", "queue_id"]),
            TASK_LOGS_DATASET: self._write_dataset(TASK_LOGS_DATASET, end, [log_row], TASK_LOGS_STANDARD_FIELDS, ["trade_date", "log_id"]),
            RESEARCH_MEMORY_DATASET: self._write_dataset(RESEARCH_MEMORY_DATASET, end, [memory_row], RESEARCH_MEMORY_STANDARD_FIELDS, ["trade_date", "memory_id"]),
            DECISION_LOG_DATASET: self._write_dataset(DECISION_LOG_DATASET, end, [decision_row], DECISION_LOG_STANDARD_FIELDS, ["trade_date", "decision_id"]),
        }
        self.plugin_list(date_value=end)
        return {
            "status": "awaiting_confirmation",
            "engineering_status": "draft",
            "task_id": task_id,
            "trade_date": end,
            "window_start": start,
            "window_end": end,
            "draft_plan": draft_plan,
            "risk_summary": risk_summary,
            "datasets": summaries,
        }

    def agent_status(self, *, task_id: str = "", date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        task_rows = self._find_rows(AGENT_TASKS_DATASET, task_id=task_id)
        if task_rows and (not date_value or date_value == "latest"):
            trade_date = sorted({str(row.get("trade_date", "")) for row in task_rows if row.get("trade_date")})[-1]
        steps = [row for row in self._find_rows(AGENT_STEPS_DATASET, task_id=task_id) if not task_id or str(row.get("task_id")) == str(task_id)]
        logs = [row for row in self._find_rows(TASK_LOGS_DATASET, task_id=task_id) if not task_id or str(row.get("task_id")) == str(task_id)]
        queue = [row for row in self._find_rows(TASK_QUEUE_DATASET, task_id=task_id) if not task_id or str(row.get("task_id")) == str(task_id)]
        return {"status": "success", "trade_date": trade_date, "task_id": task_id, "tasks": task_rows, "steps": steps, "logs": logs, "queue": queue}

    def agent_cancel(self, *, task_id: str) -> Dict[str, object]:
        task = self._latest_task(task_id)
        if not task:
            return {"status": "failed", "task_id": task_id, "reason": "task not found"}
        trade_date = str(task.get("trade_date", ""))
        run_id = _run_id("cancel")
        task["status"] = "cancelled"
        task["engineering_status"] = "cancelled"
        task["updated_at"] = iso_timestamp()
        queue_row = self._queue_row(trade_date, task_id, "cancelled", "用户取消任务。", run_id)
        log_row = self._log_row(trade_date, task_id, "", "warning", "Agent 任务已取消。", run_id)
        summaries = {
            AGENT_TASKS_DATASET: self._write_dataset(AGENT_TASKS_DATASET, trade_date, [task], AGENT_TASKS_STANDARD_FIELDS, ["trade_date", "task_id"]),
            TASK_QUEUE_DATASET: self._write_dataset(TASK_QUEUE_DATASET, trade_date, [queue_row], TASK_QUEUE_STANDARD_FIELDS, ["trade_date", "queue_id"]),
            TASK_LOGS_DATASET: self._write_dataset(TASK_LOGS_DATASET, trade_date, [log_row], TASK_LOGS_STANDARD_FIELDS, ["trade_date", "log_id"]),
        }
        return {"status": "cancelled", "task_id": task_id, "datasets": summaries}

    def agent_run(self, *, task_id: str) -> Dict[str, object]:
        task = self._latest_task(task_id)
        if not task:
            return {"status": "failed", "task_id": task_id, "reason": "task not found"}
        if str(task.get("status")) == "cancelled":
            return {"status": "cancelled", "task_id": task_id, "reason": "task is cancelled"}
        trade_date = str(task.get("trade_date", ""))
        run_id = _run_id("agentrun")
        now_text = iso_timestamp()
        task["status"] = "running"
        task["engineering_status"] = "running"
        task["updated_at"] = now_text
        task["confirmed_at"] = task.get("confirmed_at") or now_text
        task["run_id"] = run_id
        self._write_dataset(AGENT_TASKS_DATASET, trade_date, [task], AGENT_TASKS_STANDARD_FIELDS, ["trade_date", "task_id"])
        self._write_dataset(TASK_QUEUE_DATASET, trade_date, [self._queue_row(trade_date, task_id, "running", "Agent 任务已确认，开始执行。", run_id)], TASK_QUEUE_STANDARD_FIELDS, ["trade_date", "queue_id"])

        step_rows = self._task_steps(task_id)
        plugin_runs = []
        logs = [self._log_row(trade_date, task_id, "", "info", "开始执行 Agent 工作流。", run_id)]
        status_values: List[str] = []
        artifacts: List[Dict[str, object]] = []
        for step in sorted(step_rows, key=lambda row: int(str(row.get("step_order", "0") or 0))):
            step_result = self._execute_step(task=task, step=step, run_id=run_id)
            status_values.append(str(step_result.get("status", "")))
            artifacts.extend(step_result.get("artifacts", []) if isinstance(step_result.get("artifacts"), list) else [])
            plugin_runs.append(self._plugin_run_row(trade_date, run_id, str(step.get("plugin_id")), task_id, str(step.get("step_id")), step_result))
            step["status"] = str(step_result.get("status", "success"))
            step["engineering_status"] = str(step_result.get("engineering_status", "success"))
            step["outputs"] = safe_json_dumps(step_result)
            step["artifacts"] = safe_json_dumps(step_result.get("artifacts", []))
            step["reason"] = str(step_result.get("reason", ""))
            step["started_at"] = str(step_result.get("started_at", ""))
            step["finished_at"] = str(step_result.get("finished_at", ""))
            logs.append(self._log_row(trade_date, task_id, str(step.get("step_id")), "info", f"{step.get('step_name')} -> {step.get('status')}", run_id))

        final_status = self._merge_statuses(status_values)
        engineering_status = "success" if final_status in {"success", "partial_success", "warning", "pass"} else final_status
        task["status"] = "partial_success" if final_status == "warning" else final_status
        task["engineering_status"] = engineering_status
        task["updated_at"] = iso_timestamp()
        insight_rows = self._report_insights(trade_date, task_id, task, status_values, run_id)
        recommendation_rows = self._recommendations(trade_date, task_id, task, status_values, run_id)
        note_row = self._experiment_note(trade_date, task_id, run_id, task, status_values)
        memory_row = self._memory_row(trade_date, task_id, str(task.get("goal", "")), "run", "Agent 执行结果", f"任务状态：{task['status']}；步骤：{','.join(status_values)}", "agent,run,result", run_id)
        summaries = {
            AGENT_TASKS_DATASET: self._write_dataset(AGENT_TASKS_DATASET, trade_date, [task], AGENT_TASKS_STANDARD_FIELDS, ["trade_date", "task_id"]),
            AGENT_STEPS_DATASET: self._write_dataset(AGENT_STEPS_DATASET, trade_date, step_rows, AGENT_STEPS_STANDARD_FIELDS, ["trade_date", "task_id", "step_id"]),
            PLUGIN_RUNS_DATASET: self._write_dataset(PLUGIN_RUNS_DATASET, trade_date, plugin_runs, PLUGIN_RUNS_STANDARD_FIELDS, ["trade_date", "run_id", "plugin_id", "step_id"]),
            TASK_LOGS_DATASET: self._write_dataset(TASK_LOGS_DATASET, trade_date, logs, TASK_LOGS_STANDARD_FIELDS, ["trade_date", "log_id"]),
            TASK_QUEUE_DATASET: self._write_dataset(TASK_QUEUE_DATASET, trade_date, [self._queue_row(trade_date, task_id, str(task["status"]), "Agent 任务执行完成。", run_id)], TASK_QUEUE_STANDARD_FIELDS, ["trade_date", "queue_id"]),
            REPORT_INSIGHTS_DATASET: self._write_dataset(REPORT_INSIGHTS_DATASET, trade_date, insight_rows, REPORT_INSIGHTS_STANDARD_FIELDS, ["trade_date", "insight_id"]),
            RECOMMENDATION_ITEMS_DATASET: self._write_dataset(RECOMMENDATION_ITEMS_DATASET, trade_date, recommendation_rows, RECOMMENDATION_ITEMS_STANDARD_FIELDS, ["trade_date", "recommendation_id"]),
            EXPERIMENT_NOTES_DATASET: self._write_dataset(EXPERIMENT_NOTES_DATASET, trade_date, [note_row], EXPERIMENT_NOTES_STANDARD_FIELDS, ["trade_date", "note_id"]),
            RESEARCH_MEMORY_DATASET: self._write_dataset(RESEARCH_MEMORY_DATASET, trade_date, [memory_row], RESEARCH_MEMORY_STANDARD_FIELDS, ["trade_date", "memory_id"]),
        }
        return {"status": task["status"], "engineering_status": task["engineering_status"], "task_id": task_id, "run_id": run_id, "artifacts": artifacts, "datasets": summaries}

    def agent_retry(self, *, task_id: str, step_id: str) -> Dict[str, object]:
        task = self._latest_task(task_id)
        if not task:
            return {"status": "failed", "task_id": task_id, "reason": "task not found"}
        trade_date = str(task.get("trade_date", ""))
        run_id = _run_id("retry")
        retry_row = {
            "trade_date": trade_date,
            "retry_id": f"retry-{_short_hash(f'{task_id}:{step_id}:{iso_timestamp()}')}",
            "task_id": task_id,
            "step_id": step_id,
            "retry_count": "1",
            "status": "queued",
            "reason": "用户请求重试该步骤；当前实现会重新运行整个 Agent 工作流以保持血缘一致。",
            "created_at": iso_timestamp(),
            **_provenance("platform.task_retry", f"platform://agent/{task_id}/{step_id}", "", f"{task_id}:{step_id}:retry", run_id=run_id),
        }
        self._write_dataset(TASK_RETRIES_DATASET, trade_date, [retry_row], TASK_RETRIES_STANDARD_FIELDS, ["trade_date", "retry_id"])
        return self.agent_run(task_id=task_id)

    def plugin_run(self, *, plugin_id: str, params: Dict[str, object]) -> Dict[str, object]:
        plugin = self.registry.get(plugin_id)
        started = time.monotonic()
        start_ts = iso_timestamp()
        task_id = str(params.get("task_id", ""))
        step_id = str(params.get("step_id", ""))
        date_value = str(params.get("date") or params.get("end_date") or "latest")
        trade_date = self._resolve_date(date_value)
        run_id = _run_id("plugin")
        try:
            result = self._dispatch_plugin(plugin_id, params=params)
            status = str(result.get("status", "success"))
            engineering_status = str(result.get("engineering_status", "success"))
            reason = str(result.get("reason", ""))
        except Exception as exc:
            result = {"status": "failed", "reason": str(exc)}
            status = "failed"
            engineering_status = "failed"
            reason = str(exc)
        plugin_row = {
            "trade_date": trade_date,
            "run_id": run_id,
            "plugin_id": plugin.plugin_id,
            "task_id": task_id,
            "step_id": step_id,
            "status": status,
            "engineering_status": engineering_status,
            "started_at": start_ts,
            "finished_at": iso_timestamp(),
            "elapsed_seconds": f"{time.monotonic() - started:.6f}",
            "inputs": safe_json_dumps(params),
            "outputs": safe_json_dumps(result),
            "artifacts": safe_json_dumps(result.get("artifacts", [])) if isinstance(result, dict) else "[]",
            "reason": reason,
            **_provenance("platform.plugin_run", f"platform://plugins/{plugin.plugin_id}", "", f"{run_id}:{plugin_id}:{status}:{reason}", run_id=run_id),
        }
        summary = self._write_dataset(PLUGIN_RUNS_DATASET, trade_date, [plugin_row], PLUGIN_RUNS_STANDARD_FIELDS, ["trade_date", "run_id", "plugin_id", "step_id"])
        result["plugin_run"] = summary
        result["run_id"] = result.get("run_id") or run_id
        return result

    def memory_search(self, *, query: str, date_value: str = "latest") -> Dict[str, object]:
        query_text = str(query or "").strip().lower()
        rows = []
        for row in self._all_platform_rows(RESEARCH_MEMORY_DATASET):
            haystack = " ".join(str(row.get(field, "")) for field in ("goal", "title", "body", "tags")).lower()
            if not query_text or query_text in haystack:
                rows.append(row)
        rows = rows[-50:]
        return {"status": "success", "query": query, "trade_date": self._resolve_date(date_value), "count": len(rows), "rows": rows}

    def model_registry_build(self, *, date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        run_id = _run_id("modelreg")
        benchmark_rows = self._load_platform_rows(ML_BENCHMARKS_DATASET, trade_date)
        model_rows = []
        feature_versions = []
        if not benchmark_rows:
            model_rows.append(self._model_registry_row(trade_date, run_id, "model:not_applicable", "", "", "", "{}", "r2", "0", "not_applicable", "run ml-benchmark before model-registry-build"))
        for row in benchmark_rows:
            model_key = f"{row.get('template_name')}:{row.get('dataset')}:{row.get('run_id')}"
            model_id = f"model-{_short_hash(model_key)}"
            model_rows.append(
                self._model_registry_row(
                    trade_date,
                    run_id,
                    model_id,
                    str(row.get("template_name", "")),
                    str(row.get("dataset", "")),
                    str(row.get("target_field", "")),
                    str(row.get("feature_fields", "")),
                    str(row.get("score_metric", "")),
                    str(row.get("score_value", "")),
                    str(row.get("status", "")),
                    str(row.get("reason", "")),
                )
            )
        feature_names = sorted({str(row.get("feature_fields", "")) for row in benchmark_rows if row.get("feature_fields")})
        feature_versions.append(
            {
                "trade_date": trade_date,
                "feature_version_id": f"features-{_short_hash(f'{trade_date}:{feature_names}')}",
                "dataset": ",".join(sorted({str(row.get("dataset", "")) for row in benchmark_rows if row.get("dataset")})),
                "feature_names": safe_json_dumps(feature_names),
                "window_start": trade_date,
                "window_end": trade_date,
                "feature_count": str(len(feature_names)),
                "sample_count": str(sum(int(float(str(row.get("sample_count", "0") or "0"))) for row in benchmark_rows if str(row.get("sample_count", "0") or "0").replace(".", "", 1).isdigit())),
                "status": "success" if feature_names else "not_applicable",
                "reason": "" if feature_names else "no benchmark feature metadata available",
                **_provenance("platform.feature_versions", "platform://features", "", f"{trade_date}:{feature_names}", run_id=run_id),
            }
        )
        summaries = {
            MODEL_REGISTRY_DATASET: self._write_dataset(MODEL_REGISTRY_DATASET, trade_date, model_rows, MODEL_REGISTRY_STANDARD_FIELDS, ["trade_date", "model_id"]),
            FEATURE_VERSIONS_DATASET: self._write_dataset(FEATURE_VERSIONS_DATASET, trade_date, feature_versions, FEATURE_VERSIONS_STANDARD_FIELDS, ["trade_date", "feature_version_id"]),
        }
        return {"status": self._merge_statuses([summary["status"] for summary in summaries.values()]), "trade_date": trade_date, "run_id": run_id, "datasets": summaries}

    def model_drift_check(self, *, date_value: str = "latest") -> Dict[str, object]:
        trade_date = self._resolve_date(date_value)
        run_id = _run_id("drift")
        model_rows = self._load_platform_rows(MODEL_REGISTRY_DATASET, trade_date)
        if not model_rows:
            model_rows = [{"model_id": "model:not_applicable", "template_name": "", "dataset": "", "score_value": "0"}]
        drift_rows = []
        for row in model_rows:
            score = _float(row.get("score_value")) or 0.0
            drift_status = "stable" if score >= 0 else "watch"
            drift_key = f"{trade_date}:{row.get('model_id')}:{score}"
            drift_rows.append(
                {
                    "trade_date": trade_date,
                    "drift_id": f"drift-{_short_hash(drift_key)}",
                    "model_id": str(row.get("model_id", "")),
                    "template_name": str(row.get("template_name", "")),
                    "dataset": str(row.get("dataset", "")),
                    "drift_metric": "score_delta",
                    "baseline_value": str(score),
                    "current_value": str(score),
                    "drift_status": drift_status,
                    "severity": "info" if drift_status == "stable" else "warning",
                    "message": "首版漂移检查使用同日基线；后续有多期模型后会计算跨期漂移。",
                    **_provenance("platform.model_drift", "platform://model_drift", "", drift_key, run_id=run_id),
                }
            )
        summary = self._write_dataset(MODEL_DRIFT_EVENTS_DATASET, trade_date, drift_rows, MODEL_DRIFT_EVENTS_STANDARD_FIELDS, ["trade_date", "drift_id"])
        return {"status": summary["status"], "trade_date": trade_date, "run_id": run_id, "datasets": {MODEL_DRIFT_EVENTS_DATASET: summary}}

    def _execute_step(self, *, task: Dict[str, str], step: Dict[str, str], run_id: str) -> Dict[str, object]:
        plugin_id = str(step.get("plugin_id", ""))
        params = self._step_params(task, step)
        params["task_id"] = str(task.get("task_id", ""))
        params["step_id"] = str(step.get("step_id", ""))
        started_at = iso_timestamp()
        started = time.monotonic()
        result = self._dispatch_plugin(plugin_id, params=params)
        result["started_at"] = started_at
        result["finished_at"] = iso_timestamp()
        result["elapsed_seconds"] = f"{time.monotonic() - started:.6f}"
        if "engineering_status" not in result:
            result["engineering_status"] = "success" if str(result.get("status", "")) not in {"failed"} else "failed"
        return result

    def _dispatch_plugin(self, plugin_id: str, *, params: Dict[str, object]) -> Dict[str, object]:
        dataset = str(params.get("dataset") or "daily_ohlcv")
        asset_family = str(params.get("asset_family") or "")
        start = str(params.get("start_date") or params.get("start") or "")
        end = str(params.get("end_date") or params.get("end") or "")
        report_type = str(params.get("report_type") or "comprehensive")
        if plugin_id == "data.inventory":
            return self.research_runner.inventory_build(date_value=end or "latest")
        if plugin_id == "quality.gate":
            return self.quality_gate(dataset=dataset, start_date=start, end_date=end, asset_family=asset_family, task_id=str(params.get("task_id", "")))
        if plugin_id == "feature.run":
            result = self.research_runner.feature_run(start_date=start, end_date=end, dataset=dataset, asset_family=asset_family)
            self._write_feature_version_from_result(result, dataset=dataset, asset_family=asset_family)
            return result
        if plugin_id == "factor.experiment":
            return self.research_runner.factor_experiment(factor=str(params.get("factor") or "momentum"), start_date=start, end_date=end, dataset=dataset, asset_family=asset_family, params_json=safe_json_dumps(params.get("params", {})))
        if plugin_id == "ml.benchmark":
            return self.research_runner.ml_benchmark(start_date=start, end_date=end, dataset=dataset, asset_family=asset_family, models=str(params.get("models") or "ridge,random_forest,regime_detection"), params_json=safe_json_dumps({"max_samples": 300}))
        if plugin_id == "backtest.run":
            return self.research_runner.run_backtest(strategy=str(params.get("strategy") or "momentum"), start_date=start, end_date=end, dataset=dataset, asset_family=asset_family, initial_cash=float(params.get("initial_cash") or 1_000_000), fee_bps=float(params.get("fee_bps") or 2), slippage_bps=float(params.get("slippage_bps") or 1))
        if plugin_id == "report.generate":
            return self.research_runner.report_generate(date_value=end or "latest", report_type=report_type)
        if plugin_id == "lineage.build":
            return self.research_runner.lineage_build(date_value=end or "latest")
        if plugin_id == "project.package":
            return self.research_runner.package_export(run_id=str(params.get("run_id") or ""), date_value=end or "latest")
        if plugin_id == "agent.workflow":
            return {"status": "success", "engineering_status": "success", "reason": "Agent workflow is managed by agent-plan/agent-run."}
        raise ValueError(f"unsupported plugin_id: {plugin_id}")

    def _draft_steps(self, *, task_id: str, dataset: str, asset_family: str, start: str, end: str, report_type: str) -> List[Dict[str, str]]:
        plan = [
            ("data.inventory", "数据资产检查"),
            ("quality.gate", "质量守门"),
            ("feature.run", "Feature Store"),
            ("factor.experiment", "因子实验"),
            ("ml.benchmark", "ML Benchmark"),
            ("backtest.run", "正式回测"),
            ("report.generate", "报告生成"),
            ("lineage.build", "血缘记录"),
        ]
        rows = []
        for index, (plugin_id, step_name) in enumerate(plan, start=1):
            plugin = self.registry.get(plugin_id)
            rows.append(
                {
                    "task_id": task_id,
                    "step_id": f"step-{index:02d}",
                    "step_order": str(index),
                    "plugin_id": plugin_id,
                    "step_name": step_name,
                    "category": plugin.category,
                    "inputs": safe_json_dumps({"dataset": dataset, "asset_family": asset_family, "start_date": start, "end_date": end, "report_type": report_type}),
                    "risk_level": plugin.risk_level,
                }
            )
        return rows

    def _step_params(self, task: Dict[str, str], step: Dict[str, str]) -> Dict[str, object]:
        try:
            params = json.loads(str(step.get("inputs", "{}") or "{}"))
        except json.JSONDecodeError:
            params = {}
        params.setdefault("dataset", task.get("dataset", "daily_ohlcv"))
        params.setdefault("asset_family", task.get("asset_family", ""))
        params.setdefault("start_date", task.get("start_date", ""))
        params.setdefault("end_date", task.get("end_date", ""))
        params.setdefault("report_type", task.get("report_type", "comprehensive"))
        return params

    def _write_feature_version_from_result(self, result: Dict[str, object], *, dataset: str, asset_family: str) -> None:
        end = str(result.get("window_end") or result.get("trade_date") or self._resolve_date("latest"))
        run_id = str(result.get("run_id") or _run_id("featurever"))
        summary = ((result.get("datasets") or {}).get("ml_feature_store") or {}) if isinstance(result, dict) else {}
        row = {
            "trade_date": end,
            "feature_version_id": f"features-{_short_hash(f'{dataset}:{asset_family}:{end}:{run_id}')}",
            "dataset": dataset,
            "feature_names": "[]",
            "window_start": str(result.get("window_start") or end),
            "window_end": end,
            "feature_count": "",
            "sample_count": str(summary.get("row_count", "")),
            "status": str(result.get("status", "success")),
            "reason": "",
            **_provenance("platform.feature_versions", f"duckdb://{dataset}", "", f"{dataset}:{end}:{run_id}", run_id=run_id),
        }
        self._write_dataset(FEATURE_VERSIONS_DATASET, end, [row], FEATURE_VERSIONS_STANDARD_FIELDS, ["trade_date", "feature_version_id"])

    def _write_dataset(self, dataset_name: str, trade_date: str, rows: List[Dict[str, str]], fieldnames: List[str], key_fields: Sequence[str]) -> Dict[str, object]:
        normalized_rows = [{field: str(row.get(field, "")) for field in fieldnames} for row in rows]
        merged = self._merge_rows(dataset_name, trade_date, normalized_rows, key_fields)
        return _write_platform_dataset(
            dataset_name=dataset_name,
            trade_date=trade_date,
            rows=merged,
            fieldnames=fieldnames,
            key_fields=list(key_fields),
            platform_dir=self.platform_dir,
            project_root=self.project_root,
        )

    def _merge_rows(self, dataset_name: str, trade_date: str, rows: List[Dict[str, str]], key_fields: Sequence[str]) -> List[Dict[str, str]]:
        csv_path = self.platform_dir / dataset_name / f"{trade_date}.csv"
        existing = [dict(row) for row in iter_csv_rows(csv_path)] if csv_path.exists() else []
        merged: Dict[Tuple[str, ...], Dict[str, str]] = {}
        for row in existing + rows:
            key = tuple(str(row.get(field, "")) for field in key_fields)
            merged[key] = dict(row)
        return list(merged.values())

    def _load_rows(self, dataset_name: str, *, start_date: str, end_date: str, asset_family: str = "") -> List[Dict[str, str]]:
        pattern = DATASET_GLOBS.get(dataset_name, f"platform/{dataset_name}/*.csv")
        rows = []
        for csv_path in sorted(self.normalized_root.glob(pattern)):
            for row in iter_csv_rows(csv_path):
                trade_date = str(row.get("trade_date", "") or csv_path.stem)
                if start_date <= trade_date <= end_date:
                    if asset_family and str(row.get("asset_family", "")) != asset_family:
                        continue
                    rows.append(dict(row))
        return rows

    def _load_platform_rows(self, dataset_name: str, trade_date: str) -> List[Dict[str, str]]:
        csv_path = self.platform_dir / dataset_name / f"{trade_date}.csv"
        if csv_path.exists():
            return [dict(row) for row in iter_csv_rows(csv_path)]
        paths = sorted((self.platform_dir / dataset_name).glob("*.csv"))
        if not paths:
            return []
        return [dict(row) for row in iter_csv_rows(paths[-1])]

    def _all_platform_rows(self, dataset_name: str) -> List[Dict[str, str]]:
        rows = []
        for csv_path in sorted((self.platform_dir / dataset_name).glob("*.csv")):
            rows.extend(dict(row) for row in iter_csv_rows(csv_path))
        return rows

    def _find_rows(self, dataset_name: str, *, task_id: str = "") -> List[Dict[str, str]]:
        rows = self._all_platform_rows(dataset_name)
        if task_id:
            rows = [row for row in rows if str(row.get("task_id", "")) == str(task_id)]
        return rows

    def _latest_task(self, task_id: str) -> Dict[str, str]:
        rows = self._find_rows(AGENT_TASKS_DATASET, task_id=task_id)
        return dict(rows[-1]) if rows else {}

    def _task_steps(self, task_id: str) -> List[Dict[str, str]]:
        return [dict(row) for row in self._find_rows(AGENT_STEPS_DATASET, task_id=task_id)]

    def _resolve_date(self, date_value: str) -> str:
        text = str(date_value or "").strip()
        if text and text != "latest":
            return parse_trade_date(text).isoformat()
        candidates = []
        for dataset_name in ("daily_ohlcv", "source_health", "asset_coverage", AGENT_TASKS_DATASET, PLUGIN_REGISTRY_DATASET, ML_BENCHMARKS_DATASET):
            dataset_dir = self.platform_dir / dataset_name
            if dataset_dir.exists():
                candidates.extend(path.stem for path in dataset_dir.glob("*.csv"))
        return sorted(candidates)[-1] if candidates else now_shanghai().date().isoformat()

    def _resolve_window(self, *, start_date: str = "", end_date: str = "") -> Tuple[str, str]:
        if start_date and end_date:
            return parse_trade_date(start_date).isoformat(), parse_trade_date(end_date).isoformat()
        end = self._resolve_date(end_date or "latest")
        return end, end

    @staticmethod
    def _missing_ratio(rows: List[Dict[str, str]]) -> float:
        if not rows:
            return 1.0
        field_count = 0
        missing_count = 0
        for row in rows[:1000]:
            for value in row.values():
                field_count += 1
                if str(value or "").strip() == "":
                    missing_count += 1
        return missing_count / field_count if field_count else 1.0

    @staticmethod
    def _merge_statuses(statuses: Sequence[str]) -> str:
        normalized = {str(status or "") for status in statuses if str(status or "")}
        if not normalized:
            return "success"
        if normalized <= {"success", "pass"}:
            return "success"
        if normalized & {"failed", "blocked"}:
            return "partial_success" if normalized & {"success", "pass", "warning", "not_applicable"} else "failed"
        if normalized & {"warning", "not_applicable", "no_data"}:
            return "partial_success"
        return sorted(normalized)[0]

    @staticmethod
    def _risk_summary(*, goal: str, steps: List[Dict[str, str]], dataset: str, start: str, end: str) -> str:
        medium_steps = [step["step_name"] for step in steps if step.get("risk_level") == "medium"]
        return (
            f"目标：{goal}；数据集：{dataset}；窗口：{start} 至 {end}。"
            f" 将执行 {len(steps)} 个插件步骤，其中中等风险步骤包括：{', '.join(medium_steps)}。"
            " 所有研究、ML、回测和建议仅用于本地模拟，不连接券商、不真实下单、不构成投资建议。"
        )

    @staticmethod
    def _queue_row(trade_date: str, task_id: str, status: str, message: str, run_id: str) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "queue_id": f"queue-{_short_hash(f'{task_id}:{status}:{iso_timestamp()}')}",
            "task_id": task_id,
            "queue_status": status,
            "priority": "normal",
            "created_at": iso_timestamp(),
            "updated_at": iso_timestamp(),
            "started_at": iso_timestamp() if status == "running" else "",
            "finished_at": iso_timestamp() if status in {"success", "partial_success", "failed", "cancelled"} else "",
            "message": message,
            **_provenance("platform.task_queue", f"platform://agent/{task_id}", "", f"{task_id}:{status}:{message}", run_id=run_id),
        }

    @staticmethod
    def _log_row(trade_date: str, task_id: str, step_id: str, level: str, message: str, run_id: str) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "log_id": f"log-{_short_hash(f'{task_id}:{step_id}:{level}:{message}:{iso_timestamp()}')}",
            "task_id": task_id,
            "step_id": step_id,
            "level": level,
            "message": message,
            "created_at": iso_timestamp(),
            **_provenance("platform.task_log", f"platform://agent/{task_id}", "", f"{task_id}:{step_id}:{message}", run_id=run_id),
        }

    @staticmethod
    def _memory_row(trade_date: str, task_id: str, goal: str, memory_type: str, title: str, body: str, tags: str, run_id: str) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "memory_id": f"memory-{_short_hash(f'{task_id}:{memory_type}:{title}:{body}')}",
            "task_id": task_id,
            "goal": goal,
            "memory_type": memory_type,
            "title": title,
            "body": body,
            "tags": tags,
            "status": "success",
            **_provenance("platform.research_memory", f"platform://agent/{task_id}/memory", "", f"{task_id}:{memory_type}:{body}", run_id=run_id),
        }

    @staticmethod
    def _decision_row(trade_date: str, task_id: str, decision_type: str, decision: str, rationale: str, run_id: str) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "decision_id": f"decision-{_short_hash(f'{task_id}:{decision_type}:{decision}')}",
            "task_id": task_id,
            "decision_type": decision_type,
            "decision": decision,
            "rationale": rationale,
            "status": "success",
            "decided_at": iso_timestamp(),
            **_provenance("platform.decision_log", f"platform://agent/{task_id}/decision", "", f"{task_id}:{decision_type}:{decision}:{rationale}", run_id=run_id),
        }

    @staticmethod
    def _plugin_run_row(trade_date: str, run_id: str, plugin_id: str, task_id: str, step_id: str, result: Dict[str, object]) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "run_id": run_id,
            "plugin_id": plugin_id,
            "task_id": task_id,
            "step_id": step_id,
            "status": str(result.get("status", "")),
            "engineering_status": str(result.get("engineering_status", "success")),
            "started_at": str(result.get("started_at", "")),
            "finished_at": str(result.get("finished_at", "")),
            "elapsed_seconds": str(result.get("elapsed_seconds", "")),
            "inputs": "{}",
            "outputs": safe_json_dumps(result),
            "artifacts": safe_json_dumps(result.get("artifacts", [])),
            "reason": str(result.get("reason", "")),
            **_provenance("platform.plugin_run", f"platform://plugins/{plugin_id}", "", f"{run_id}:{plugin_id}:{step_id}:{result.get('status')}", run_id=run_id),
        }

    @staticmethod
    def _report_insights(trade_date: str, task_id: str, task: Dict[str, str], statuses: List[str], run_id: str) -> List[Dict[str, str]]:
        body = f"Agent 任务 {task_id} 完成，runtime 状态为 {task.get('status')}，工程状态为 {task.get('engineering_status')}。"
        return [
            {
                "trade_date": trade_date,
                "insight_id": f"insight-{_short_hash(f'{task_id}:{body}')}",
                "task_id": task_id,
                "report_id": str(task.get("report_type", "comprehensive")),
                "insight_type": "agent_summary",
                "title": "Agent 任务摘要",
                "body": body,
                "severity": "info" if str(task.get("status")) in {"success", "partial_success"} else "warning",
                "status": "success",
                **_provenance("platform.report_insight", f"platform://agent/{task_id}", "", f"{task_id}:{statuses}", run_id=run_id),
            }
        ]

    @staticmethod
    def _recommendations(trade_date: str, task_id: str, task: Dict[str, str], statuses: List[str], run_id: str) -> List[Dict[str, str]]:
        blocked = any(status in {"blocked", "failed"} for status in statuses)
        title = "先补齐输入数据" if blocked else "可继续扩展参数扫描和策略对比"
        body = "质量门控或执行步骤存在阻塞，建议先回到 /crawl 补窗口数据。" if blocked else "本次链路已打通，建议下一步对候选策略做参数扫描、压力测试与可复现包导出。"
        return [
            {
                "trade_date": trade_date,
                "recommendation_id": f"recommendation-{_short_hash(f'{task_id}:{title}:{body}')}",
                "task_id": task_id,
                "category": "agent_next_step",
                "title": title,
                "body": body,
                "priority": "high" if blocked else "medium",
                "status": "open",
                **_provenance("platform.recommendation", f"platform://agent/{task_id}", "", f"{task_id}:{title}:{body}", run_id=run_id),
            }
        ]

    @staticmethod
    def _experiment_note(trade_date: str, task_id: str, run_id: str, task: Dict[str, str], statuses: List[str]) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "note_id": f"note-{_short_hash(f'{task_id}:{run_id}:{statuses}')}",
            "task_id": task_id,
            "run_id": run_id,
            "note_type": "agent_run",
            "title": "Agent 编排实验记录",
            "body": f"目标：{task.get('goal')}；状态：{task.get('status')}；步骤状态：{','.join(statuses)}。",
            "status": "success",
            **_provenance("platform.experiment_note", f"platform://agent/{task_id}", "", f"{task_id}:{run_id}:{statuses}", run_id=run_id),
        }

    @staticmethod
    def _model_registry_row(
        trade_date: str,
        run_id: str,
        model_id: str,
        template_name: str,
        dataset: str,
        target_field: str,
        feature_fields: str,
        score_metric: str,
        score_value: str,
        status: str,
        reason: str,
    ) -> Dict[str, str]:
        return {
            "trade_date": trade_date,
            "model_id": model_id,
            "template_name": template_name,
            "dataset": dataset,
            "target_field": target_field,
            "feature_fields": feature_fields,
            "best_params": "{}",
            "score_metric": score_metric,
            "score_value": score_value,
            "status": status,
            "reason": reason,
            **_provenance("platform.model_registry", f"platform://models/{model_id}", "", f"{trade_date}:{model_id}:{score_value}:{status}", run_id=run_id),
        }


def _short_hash(value: str) -> str:
    return hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:12]


def _run_id(prefix: str) -> str:
    return f"{prefix}-{_short_hash(iso_timestamp())}"


def _float(value) -> Optional[float]:
    try:
        return float(str(value or "").replace(",", "").strip())
    except ValueError:
        return None


def _provenance(source_id: str, source_url: str, raw_path: str, checksum_text: str, *, run_id: str = "") -> Dict[str, str]:
    row = {
        "source_id": source_id,
        "source_url": source_url,
        "source_type": "derived",
        "retrieved_at": iso_timestamp(),
        "raw_path": raw_path,
        "parser_version": PARSER_VERSION,
        "checksum": _short_hash(checksum_text),
    }
    if run_id:
        row["run_id"] = run_id
    return row
