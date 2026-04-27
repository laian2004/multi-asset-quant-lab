# DATASETS.md

# 2026-04-27 研究项目闭环数据口径

- `project_runs` 现在代表一次完整研究项目运行，默认会串起因子实验、正式回测、策略排行榜、报告生成和复现包导出；`artifact_count` 反映本次闭环产生的数据/产物数量。
- `report_insights` 不再只由 Agent 任务生成；普通 `report-generate` 和项目闭环也会写入自动解读。
- `recommendation_items` 记录报告或项目运行后的下一步建议，例如补跑 ML Benchmark、复核质量告警、生成策略排行榜或检查压力情景。
- `/projects` 读取 `research_projects / project_runs / experiment_runs / report_insights / recommendation_items / reproducible_packages`，用于展示项目、实验对比、自动解读、建议和复现包。
- `/reports` 读取 `research_reports / report_artifacts / artifact_manifest / report_insights / recommendation_items`，用于展示报告索引、图表附件、产物血缘、自动解读和建议。

# 2026-04-27 Agent 与插件数据集口径

- 本轮新增 Agent/插件平台表全部位于 `data/normalized/platform/<dataset>/<trade_date>.csv`，并进入 storage manifest、registry、source catalog、DuckDB、GUI、export 与 validation。
- 新增数据集：`agent_tasks / agent_steps / plugin_registry / plugin_runs / research_memory / experiment_notes / decision_log / quality_gates / research_readiness / input_risk_flags / task_queue / task_logs / task_retries / report_insights / recommendation_items / model_registry / feature_versions / model_drift_events`。
- 语义分层：
  - `plugin_registry / plugin_runs`：产品内插件白名单与每次插件执行结果。
  - `agent_tasks / agent_steps / task_queue / task_logs / task_retries`：Agent 任务、步骤、队列、日志与重试状态。
  - `quality_gates / research_readiness / input_risk_flags`：研究输入质量守门与风险说明。
  - `research_memory / experiment_notes / decision_log`：研究记忆、实验备注和重要决策留痕。
  - `report_insights / recommendation_items`：报告自动解读与下一步建议。
  - `model_registry / feature_versions / model_drift_events`：模型注册、特征版本和漂移事件。
- 当前 DuckDB `dataset_count = 125`；合法空表如 `task_retries / input_risk_flags` 仍按 schema-only success 进入平台校验。

## 2026-04-26 Pro Max 数据集口径

- 当前 DuckDB manifest 已索引 `107` 个数据集；Pro Max 新增数据集全部按 platform normalized dataset 管理，并进入 registry / source catalog / DuckDB / GUI / export / validation。
- 新增数据资产、血缘、SLA 与知识库表：
  - `dataset_inventory`
  - `dataset_field_profile`
  - `data_lineage`
  - `dataset_sla_rules`
  - `sla_violations`
  - `knowledge_index`
- 新增 Feature Store、ML Benchmark 与时间序列验证表：
  - `ml_feature_store`
  - `ml_benchmarks`
  - `ml_validation_folds`
  - `ml_classification_results`
- 新增因子实验、参数扫描与策略排行表：
  - `factor_experiments`
  - `parameter_scans`
  - `strategy_leaderboard`
- 新增组合研究、情景推演、研究项目与复现包表：
  - `portfolio_experiments`
  - `scenario_simulations`
  - `research_projects`
  - `project_runs`
  - `reproducible_packages`
- GUI 页面映射：
  - `/data-map` 读取 `dataset_inventory / dataset_field_profile / dataset_sla_rules / sla_violations`
  - `/lineage` 读取 `data_lineage / artifact_manifest / experiment_runs`
  - `/factor-lab` 读取 `ml_feature_store / factor_experiments / parameter_scans / strategy_leaderboard`
  - `/portfolio` 读取 `portfolio_allocations / portfolio_experiments / scenario_simulations / stress_test_results`
  - `/projects` 读取 `research_projects / project_runs / reproducible_packages`
  - `/knowledge` 读取 `knowledge_index`

## 2026-04-25 当前口径

- 本文档中的多资产平台数据集，当前统一按“第一版 latest-view 平台”解释：
  - 已进入 collector / registry / GUI / DuckDB / export / validation 的数据集算已落地
  - 不把“尚未扩到逐券全历史”误写成工程未完成
- 本轮大版本新增“研究运营平台”数据集，同样作为正式 platform normalized dataset 管理：
  - `research_metrics`
  - `factor_signals`
  - `strategy_backtests`
  - `paper_portfolios`
  - `quality_diagnostics`
  - `scheduler_runs`
  - `research_reports`
  - `algorithm_outputs`
  - `option_analytics`
  - `bond_analytics`
  - `curve_analytics`
  - `risk_metrics`
  - `portfolio_allocations`
  - `backtest_equity_curves`
  - `backtest_positions`
  - `backtest_trades`
  - `strategy_comparisons`
  - `anomaly_events`
  - `ml_model_runs`
  - `ml_predictions`
  - `ml_feature_importance`
  - `model_diagnostics`
  - `backtest_input_quality`
  - `experiment_runs`
  - `factor_performance`
  - `stress_test_results`
  - `artifact_manifest`
  - `dataset_quality_scores`
  - `report_artifacts`
- 当前平台状态表最新结论：
  - `run_health` 当前正式记录 `status=partial_success` 与 `engineering_status=success`
  - `source_health` 当前只剩一个外部 `blocked_issue`：`cffex.options_exercise_results / publication_lag`
  - `asset_coverage.exchange_derivatives_cn` 当前为 `engineering_status=done`、`runtime_status=pending_retry`、`external_issue_count=1`
  - `build-db` 当前已索引 `107` 个数据集

## Current normalized datasets

说明：
- 当前 GUI 读取这些 normalized 数据集与 `state/` 状态文件做本地浏览
- 当前 GUI 已拆成 `/` 浏览页、`/crawl` 抓取页、`/history` 历史研究页、`/quality` 质量页、`/strategies` 策略页、`/scheduler` 调度页与 `/reports` 报告页；数据预览仍来自 normalized dataset，抓取动作集中在 `/crawl`
- `/crawl` 里的“一键抓取当前已接入的全部数据”会刷新这些已落地 normalized datasets 对应的 latest-view 输出，但不承诺逐券全历史全部补齐
- `/strategies` 里的算法入口采用内置模板清单，不开放任意 Python 脚本执行；当前输出会落到 `research_metrics / factor_signals / algorithm_outputs / option_analytics / bond_analytics / curve_analytics / risk_metrics / portfolio_allocations / backtest_* / strategy_comparisons / paper_portfolios / ml_model_runs / ml_predictions / ml_feature_importance / model_diagnostics / factor_performance / stress_test_results / experiment_runs`
- `/scheduler` 顶部按钮执行所有到期任务，单行“手动运行”才执行指定 `schedule_id`
- `/reports` 默认展示最新已生成报告日期，并通过只读白名单路由打开 `daily_report.html / daily_report.md / quality_diagnostics.md`；报告图表附件和血缘会写入 `report_artifacts / artifact_manifest`
- 当前 GUI 还会从当前选中数据集的 CSV 中抽取低基数字段枚举值，用于生成 `market / exchange / instrument_type` 等筛选下拉项
- 当前 GUI 还会读取 `state/pregrab_runs.json`，展示逐交易所窗口预抓的最近摘要；它是运行状态文件，不是 normalized dataset
- 当前 GUI 还会读取 `state/window_runs.json`，展示多资产历史窗口同步的最近摘要；它同样是运行状态文件，不是 normalized dataset
- “多资产平台注册表”本身不是 normalized dataset，它只是平台层注册信息，用于明确 implemented / planned 边界
- 平台级派生表现在已经独立落地为 normalized dataset：`instrument_master / bond_master / bond_quotes / fx_quotes / commodity_spot_quotes / crypto_global_quotes / daily_ohlcv / fund_nav / reits_quotes / trading_calendar / yield_curves / asset_coverage / source_type_overview / issue_category_overview / validation_results / source_health / run_health / run_history / coverage_history / source_health_history / research_metrics / factor_signals / strategy_backtests / paper_portfolios / quality_diagnostics / scheduler_runs / research_reports / algorithm_outputs / option_analytics / bond_analytics / curve_analytics / risk_metrics / portfolio_allocations / backtest_equity_curves / backtest_positions / backtest_trades / strategy_comparisons / anomaly_events / ml_model_runs / ml_predictions / ml_feature_importance / model_diagnostics / backtest_input_quality / experiment_runs / factor_performance / stress_test_results / artifact_manifest / dataset_quality_scores / report_artifacts / dataset_inventory / dataset_field_profile / data_lineage / dataset_sla_rules / sla_violations / knowledge_index / ml_feature_store / ml_benchmarks / ml_validation_folds / ml_classification_results / factor_experiments / parameter_scans / strategy_leaderboard / portfolio_experiments / scenario_simulations / research_projects / project_runs / reproducible_packages`

## Operational state artifacts

### `pregrab_runs`
- path: `state/pregrab_runs.json`
- semantics: 逐交易所窗口预抓的正式摘要状态文件，供 GUI 抓取工作台与后续验收回看最近 `production / trial` 运行结果
- notes:
  - 该文件不是 normalized dataset，也不会进入 DuckDB manifest
  - `trial` 模式只保留这里的摘要，不保留隔离 root 下的临时抓取数据
  - 摘要当前会记录 `status / engineering_status / blocked_issues / cleanup_status / exchange_results`

### `window_runs`
- path: `state/window_runs.json`
- semantics: 多资产历史窗口同步的正式摘要状态文件，供 GUI 历史研究页与质量页查看最近 `latest/1y/3y` 风格窗口任务
- notes:
  - 该文件不是 normalized dataset，但会进入平台派生表的历史统计链路
  - 摘要当前会记录 `status / engineering_status / window_start / window_end / issue_category_counts / blocked_issues / date_counts / dataset_results`

### `schedules`
- path: `state/schedules.json`
- semantics: 本地 tick 调度任务定义，供 CLI `scheduler-tick` 与 GUI `/scheduler` 读取
- notes:
  - 当前不启动常驻后台进程，不依赖云端任务系统
  - 默认任务包含 daily platform metadata、daily DuckDB build、daily quality diagnose、daily report、weekly regression phase2 等

### `scheduler_runs`
- path: `state/scheduler_runs.json`
- semantics: 本地调度运行历史状态文件，会物化为 platform normalized dataset `scheduler_runs`
- notes:
  - 记录 `schedule_id / action_name / due_at / started_at / finished_at / status / engineering_status`
  - 可由 GUI `/scheduler` 手动触发单个任务

## Platform metadata datasets

### `instrument_master`
- path: `data/normalized/platform/instrument_master/{trade_date}.csv`
- semantics: 平台级 instrument master，把场内衍生品、公开资产、债券、外汇参考与 crypto 观察统一映射成可浏览的主表
- source family: `derived`
- current source: `contracts_snapshot + latest public asset/reference/bond/crypto outputs`
- notes: 当前严格沿用 `master-data-first` 语义；场内衍生品 formal 主数据优先，公开资产族以最近一次成功输出映射为第一版 instrument master，不伪装成交易所官方合约表

### `validation_results`
- path: `data/normalized/platform/validation_results/{trade_date}.csv`
- semantics: 平台级验证结果表，汇总衍生品 canonical、公开资产、公开参考、公开债券与 crypto 观察的最新 validate 结果
- source family: `derived`
- current source: `workflow.validate + public runners validate`
- notes: 当前字段已显式包含 `master_data_completeness / result_chain_semantics_ok / contracts_latest_consistency_ok / blocked_issue_count / blocked_issues / no_data_reason / not_applicable_reason`

### `source_health`
- path: `data/normalized/platform/source_health/{trade_date}.csv`
- semantics: 平台级 source 健康表，汇总 source registry、最近状态、最近成功日与输出路径
- source family: `derived`
- current source: `source catalog + checkpoints + public runner state`
- notes: 仅反映最近一次已记录状态，不会把 `pending_retry / no_data` 伪装成 success；当前字段已显式包含 `issue_category / blocked_reason`，并已覆盖 `futures_delivery_results / options_exercise_results` 等结果链 source 条目

### `asset_coverage`
- path: `data/normalized/platform/asset_coverage/{trade_date}.csv`
- semantics: 平台各资产族覆盖总览派生表，汇总资产族最新运行状态、覆盖比例、成功/非成功数据集数量与缺失数据集
- source family: `derived`
- current source: `asset family registry + dataset registry + derivatives checkpoint + public runner latest summaries + platform metadata state`
- notes: 当前需要同时看 `engineering_status` 与 `runtime_status`；外部 `publication_lag / dns_failure / proxy_failure` 只影响 runtime，不再拖低工程收口状态

### `run_health`
- path: `data/normalized/platform/run_health/{trade_date}.csv`
- semantics: 平台最近一次 `regression-smoke` 的正式派生表
- source family: `derived`
- current source: `state/regression_smoke.json`
- notes: 当前已显式包含 `status / engineering_status / window_statuses / window_sample_counts / window_sampled_dates / blocked_issue_count / blocked_issues`，用于把连续窗口回归和“运行状态 vs 工程收口状态”一起落表；`2026-04-21` 最新实跑为 `status=partial_success`、`engineering_status=success`

### `run_history`
- path: `data/normalized/platform/run_history/{trade_date}.csv`
- semantics: 平台运行历史派生表，把 `regression_smoke / pregrab_runs / window_runs / environment_check` 等最新运行摘要按任务类型展开为统一历史视图
- source family: `derived`
- current source: `state/regression_smoke.json + state/pregrab_runs.json + state/window_runs.json + environment health state`

### `coverage_history`
- path: `data/normalized/platform/coverage_history/{trade_date}.csv`
- semantics: 平台覆盖率历史派生表，把各资产族覆盖比例、运行状态和外部阻塞数量做成时间序列
- source family: `derived`
- current source: `asset_coverage + platform metadata state`

### `source_health_history`
- path: `data/normalized/platform/source_health_history/{trade_date}.csv`
- semantics: 平台 source 健康历史派生表，把最近 source health 快照按 source_id 追加成可趋势查看的历史表
- source family: `derived`
- current source: `source_health + platform metadata state`

### `research_metrics`
- path: `data/normalized/platform/research_metrics/{trade_date}.csv`
- semantics: 研究指标表，记录收益率、波动率、成交量变化、滚动均值、回撤、相关性、期限结构斜率等首版指标
- source family: `derived`
- current source: `DuckDB / normalized platform datasets`
- notes: 字段不足的数据集会记录 `metric_status=not_applicable`，不会伪装成成功。

### `factor_signals`
- path: `data/normalized/platform/factor_signals/{trade_date}.csv`
- semantics: 因子信号表，统一保存日频因子值与方向
- source family: `derived`
- current source: `daily_ohlcv / yield_curves / 可用平台行情表`
- notes: 当前模板包含动量、均值回归、波动率过滤、跨期价差、收益率曲线斜率等研究方向的首版框架。

### `algorithm_outputs`
- path: `data/normalized/platform/algorithm_outputs/{trade_date}.csv`
- semantics: 统一算法输出表，保存所有内置算法模板的 `status / reason / parameters / metric_value`
- source family: `derived`
- current source: `AlgorithmRegistry + normalized platform datasets`
- notes: 这是 GUI `/strategies` 的总入口输出；字段或参数不足时写 `not_applicable`，不伪装成功。

### `option_analytics`
- path: `data/normalized/platform/option_analytics/{trade_date}.csv`
- semantics: 期权金融数学分析表，保存 Black-Scholes、隐含波动率、希腊值与二叉树定价结果
- source family: `derived`
- current source: `algorithm-run`

### `bond_analytics`
- path: `data/normalized/platform/bond_analytics/{trade_date}.csv`
- semantics: 债券金融数学分析表，保存 YTM、Macaulay 久期、修正久期和凸性
- source family: `derived`
- current source: `algorithm-run`

### `curve_analytics`
- path: `data/normalized/platform/curve_analytics/{trade_date}.csv`
- semantics: 收益率曲线分析表，保存曲线斜率、期限利差等模型结果
- source family: `derived`
- current source: `algorithm-run`

### `risk_metrics`
- path: `data/normalized/platform/risk_metrics/{trade_date}.csv`
- semantics: 组合风险指标表，保存 VaR/CVaR、相关性、最大回撤、波动率目标、仓位约束等指标
- source family: `derived`
- current source: `risk-run`

### `portfolio_allocations`
- path: `data/normalized/platform/portfolio_allocations/{trade_date}.csv`
- semantics: 组合配置权重表，保存风险平价、均值-方差等本地研究配置结果
- source family: `derived`
- current source: `portfolio-optimize`
- notes: 只用于研究，不代表真实账户仓位。

### `backtest_equity_curves / backtest_positions / backtest_trades / strategy_comparisons`
- path: `data/normalized/platform/{dataset}/{trade_date}.csv`
- semantics: 正式回测引擎输出，分别保存净值曲线、持仓明细、交易明细与策略对比指标
- source family: `derived`
- current source: `backtest-run`
- notes: 首版为日频收盘价口径，支持手续费、滑点、换手、持仓和交易明细；不连接真实交易。

### `strategy_backtests`
- path: `data/normalized/platform/strategy_backtests/{trade_date}.csv`
- semantics: 策略回测表，保存日频模拟回测净值、收益、回撤、换手、持仓数量与交易成本
- source family: `derived`
- current source: `factor_signals + platform price datasets`
- notes: 只做研究模拟，不连接真实交易。

### `paper_portfolios`
- path: `data/normalized/platform/paper_portfolios/{trade_date}.csv`
- semantics: 模拟交易组合状态表，保存现金、持仓、市值、权益与当日模拟交易记录
- source family: `derived`
- current source: `strategy template + latest platform price datasets`
- notes: 只代表本地纸面组合，不代表真实账户或投资建议。

### `quality_diagnostics`
- path: `data/normalized/platform/quality_diagnostics/{trade_date}.csv`
- semantics: 质量诊断表，展开最近失败源、外部阻塞、合法空表、覆盖率变化、schema/raw 异常等诊断项
- source family: `derived`
- current source: `source_health + asset_coverage + validation_results`
- notes: 合法 `no_data / not_applicable` 归 `info`，外部阻塞归 `warning`，真实 schema/raw/failed 问题归 `critical`。

### `anomaly_events`
- path: `data/normalized/platform/anomaly_events/{trade_date}.csv`
- semantics: 异常事件表，保存异常价格、异常成交量、source health 非成功等可运营事件
- source family: `derived`
- current source: `quality-diagnose`

### `scheduler_runs`
- path: `data/normalized/platform/scheduler_runs/{trade_date}.csv`
- semantics: 本地调度运行表，从 `state/scheduler_runs.json` 物化而来
- source family: `derived`
- current source: `state/scheduler_runs.json`

### `research_reports`
- path: `data/normalized/platform/research_reports/{trade_date}.csv`
- semantics: 本地研究运营报告索引表，指向 `reports/YYYY-MM-DD/daily_report.md` 与 `.html`
- source family: `derived`
- current source: `report-generate`

### `ml_model_runs / ml_predictions / ml_feature_importance / model_diagnostics`
- path: `data/normalized/platform/{dataset}/{trade_date}.csv`
- semantics: 机器学习研究输出，分别保存模型运行摘要、预测值、特征重要性和诊断指标
- source family: `derived`
- current source: `ml-run`
- notes:
  - 当前模板包括 `linear_regression / ridge / lasso / pca / kmeans / random_forest / xgboost / regime_detection`
  - `--tune` 会用训练/测试切分上的验证分数选择小网格参数，并把 `validation_r2` 写入 `best_params`
  - `model_diagnostics` 会记录 `raw_sample_count / sample_count / feature_count / train_count / test_count / prediction_count / mae / rmse`
  - 默认 `max_samples` 保护为 5000，可通过 `params` 显式调整
  - XGBoost 在本机可用时会真实运行；若依赖不可用则稳定写 `not_applicable`
  - 所有输出只用于本地研究，不用于真实交易或投资建议

### `backtest_input_quality`
- path: `data/normalized/platform/backtest_input_quality/{trade_date}.csv`
- semantics: 正式回测运行前的输入质量检查，记录字段不足、样本不足、无价格日等问题
- source family: `derived`
- current source: `backtest-run`

### `experiment_runs`
- path: `data/normalized/platform/experiment_runs/{trade_date}.csv`
- semantics: 统一实验追踪表，记录算法、因子、回测、ML、压力测试、质量评分和报告任务的 `run_id / parameters / status / artifact_count`
- source family: `derived`
- current source: `research platform runners`

### `factor_performance`
- path: `data/normalized/platform/factor_performance/{trade_date}.csv`
- semantics: 因子表现评估表，保存 IC、Rank IC、分组收益、覆盖率、胜率和换手率等首版指标
- source family: `derived`
- current source: `factor-performance`

### `stress_test_results`
- path: `data/normalized/platform/stress_test_results/{trade_date}.csv`
- semantics: 压力测试结果表，保存权益下跌、波动率放大、相关性上升、利率平移、汇率冲击和 crypto 极端波动等情景结果
- source family: `derived`
- current source: `stress-test`

### `dataset_quality_scores`
- path: `data/normalized/platform/dataset_quality_scores/{trade_date}.csv`
- semantics: 数据质量评分表，聚合 completeness、freshness、source health 与 anomaly 分数，供 GUI `/quality` 和报告图表使用
- source family: `derived`
- current source: `quality-score`

### `report_artifacts / artifact_manifest`
- path: `data/normalized/platform/{dataset}/{trade_date}.csv`
- semantics: 报告附件索引与产物血缘表，记录本地图表、报告产物、源数据集、参数和 checksum
- source family: `derived`
- current source: `report-generate`

### `source_type_overview`
- path: `data/normalized/platform/source_type_overview/{trade_date}.csv`
- semantics: 平台 source_type 运行总览派生表，聚合 `official / fallback_online / derived / official_browser_bootstrap` 等来源族的源数量、数据集数量、success/非success 统计与 blocked issue 数量
- source family: `derived`
- current source: `source_health`

### `issue_category_overview`
- path: `data/normalized/platform/issue_category_overview/{trade_date}.csv`
- semantics: 平台问题类别运行总览派生表，聚合 `healthy / no_data / retry_or_error / blocked_issue` 等类别对应的源数量、数据集数量、blocked 数量、状态统计与源类型统计
- source family: `derived`
- current source: `source_health`

### `bond_master`
- path: `data/normalized/platform/bond_master/{trade_date}.csv`
- semantics: 平台级债券主数据第一版视图，把银行间成交/报价、收益率曲线和交易所债券摘要映射成统一可浏览的 bond master
- source family: `derived`
- current source: `latest public bond outputs`
- notes: 当前字段仍以公开可得字段为主，`issuer / maturity_date` 等拿不到时保持留空，不伪造

### `bond_quotes`
- path: `data/normalized/platform/bond_quotes/{trade_date}.csv`
- semantics: 平台级债券报价第一版视图，把银行间成交/报价和交易所债券摘要统一到一张表
- source family: `derived`
- current source: `latest public bond outputs`
- notes: 当前属于 latest-view，不等于逐券全历史行情库

### `fx_quotes`
- path: `data/normalized/platform/fx_quotes/{trade_date}.csv`
- semantics: 平台级外汇报价第一版视图，把人民币外汇参考价、人民币汇率中间价、即期、外币对、远掉与 C-Swap 曲线统一到一张表
- source family: `derived`
- current source: `latest public reference outputs`
- notes: 当前 `bid / ask / mid` 仅在上游公开字段可得时填写；其余场景保留 `value`

### `commodity_spot_quotes`
- path: `data/normalized/platform/commodity_spot_quotes/{trade_date}.csv`
- semantics: 平台级现货与基准价第一版视图，把上金所现货、上海金银基准价与国内碳市场快照统一到一张表
- source family: `derived`
- current source: `latest public asset/reference outputs`
- notes: 当前明确区分 `precious_metal_spot / precious_metal_reference / carbon`

### `crypto_global_quotes`
- path: `data/normalized/platform/crypto_global_quotes/{trade_date}.csv`
- semantics: 平台级全球加密报价第一版视图，把 spot snapshot、daily quotes 与公开衍生品观察统一到一张表
- source family: `derived`
- current source: `latest crypto observation outputs`
- notes: 仅作研究与行情观察，不属于国内合法交易所 canonical 市场

### `daily_ohlcv`
- path: `data/normalized/platform/daily_ohlcv/{trade_date}.csv`
- semantics: 平台级统一日线行情表，把场内衍生品日线、股票/ETF/REITs/可转债快照与 crypto 日线观察统一成一张日线表
- source family: `derived`
- current source: `futures_daily_quotes + options_daily_quotes + latest public asset snapshots + crypto observation outputs`
- notes: 当前属于“统一 latest/history 混合日线表”第一版；会尽量保留上游 `instrument_type / exchange / source_*`，不把不同资产强行扁平到完全同口径

### `fund_nav`
- path: `data/normalized/platform/fund_nav/{trade_date}.csv`
- semantics: 平台级基金净值表，把开放式基金净值快照与货币基金收益快照统一到一张表
- source family: `derived`
- current source: `open_fund_nav_snapshot + money_market_fund_snapshot`
- notes: 当前 `nav_type` 会区分普通开放式基金净值与货币基金万份收益/七日年化等公开口径，不伪装成同一字段语义

### `reits_quotes`
- path: `data/normalized/platform/reits_quotes/{trade_date}.csv`
- semantics: 平台级公募 REITs 行情表
- source family: `derived`
- current source: `reits_spot_snapshot`
- notes: 当前属于 latest-view 第一版，重点是统一 REITs 在 GUI / DuckDB / export 里的可浏览性与 provenance

### `trading_calendar`
- path: `data/normalized/platform/trading_calendar/{trade_date}.csv`
- semantics: 平台级交易日日历快照，汇总衍生品、股票、外汇参考、债券利率与 crypto 的最近已知交易日状态
- source family: `derived`
- current source: `derivatives checkpoints + latest public runner summaries`
- notes: 当前是“最近已知状态快照”，不是交易所官方全量历史日历库；会诚实区分 `success / partial_success / no_data / not_applicable / pending_retry`

### `yield_curves`
- path: `data/normalized/platform/yield_curves/{trade_date}.csv`
- semantics: 平台级收益率曲线表，把中债收益率曲线点位与中美国债收益率观察统一成一张期限曲线表
- source family: `derived`
- current source: `yield_curve_points + cn_us_treasury_yields`
- notes: 当前第一版重点是统一 `curve_name / curve_type / tenor / yield`，不把银行间成交/报价错误混进曲线表

## Public snapshot datasets

### `equities_spot_snapshot`
- path: `data/normalized/public_assets/equities_spot_snapshot/{trade_date}.csv`
- semantics: A 股全市场公开快照
- source family: `fallback_online`
- current source: `AkShare stock_zh_a_spot`
- notes: 当前以当日快照为主，同日重跑优先复用 raw cache

### `etf_spot_snapshot`
- path: `data/normalized/public_assets/etf_spot_snapshot/{trade_date}.csv`
- semantics: ETF 公开快照
- source family: `fallback_online`
- current source: `AkShare fund_etf_spot_ths`

### `lof_spot_snapshot`
- path: `data/normalized/public_assets/lof_spot_snapshot/{trade_date}.csv`
- semantics: LOF 基金公开快照
- source family: `fallback_online`
- current source: `AkShare fund_lof_spot_em`, fallback `Eastmoney LOF list page + Sina hq`
- notes: 当前 latest 默认会优先走 `AkShare`，若 Eastmoney 代理链路断连则诚实回退到公开 LOF 列表页 + `Sina hq` 批量行情；`source_id/source_url/source_type` 会保留真实回退来源

### `open_fund_nav_snapshot`
- path: `data/normalized/public_assets/open_fund_nav_snapshot/{trade_date}.csv`
- semantics: 开放式基金净值快照
- source family: `fallback_online`
- current source: `AkShare fund_open_fund_daily_em`
- notes: 当前为 latest-only 日快照，`last_price` 对应最新单位净值，`prev_close` 对应前一日单位净值

### `money_market_fund_snapshot`
- path: `data/normalized/public_assets/money_market_fund_snapshot/{trade_date}.csv`
- semantics: 货币基金收益快照
- source family: `fallback_online`
- current source: `AkShare fund_money_fund_daily_em`
- notes: 当前 `last_price` 口径对应最新万份收益，`prev_close` 对应前一日万份收益

### `reits_spot_snapshot`
- path: `data/normalized/public_assets/reits_spot_snapshot/{trade_date}.csv`
- semantics: REITs 公开快照
- source family: `fallback_online`
- current source: `AkShare reits_realtime_em`, fallback `recent successful universe + Sina hq`
- notes: 当前 latest 默认会优先走 `AkShare`，若实时页不可达则复用最近一次成功 REITs universe 并回退到 `Sina hq` 公共行情

### `bse_equities_spot_snapshot`
- path: `data/normalized/public_assets/bse_equities_spot_snapshot/{trade_date}.csv`
- semantics: 北交所股票公开快照
- source family: `fallback_online`
- current source: `AkShare stock_bj_a_spot_em`, fallback `Tencent qt.gtimg.cn`
- notes: 当前仍属 latest-only 快照源；若 `AkShare/Eastmoney` 在线源不可达，会诚实回退到 `Tencent qt.gtimg.cn` 公共行情，并保留真实 provenance

### `convertible_bond_spot_snapshot`
- path: `data/normalized/public_assets/convertible_bond_spot_snapshot/{trade_date}.csv`
- semantics: 交易所可转债公开快照
- source family: `fallback_online`
- current source: `AkShare bond_zh_hs_cov_spot`
- notes: 当前覆盖沪深深北可转债市场快照，属于 snapshot 层，不等于债券主数据已接齐

### `sge_spot_daily_quotes`
- path: `data/normalized/public_assets/sge_spot_daily_quotes/{trade_date}.csv`
- semantics: 上金所现货日行情
- source family: `fallback_online`
- current source: `AkShare spot_hist_sge`
- notes: 当前按品种逐个请求历史日行情，并在 normalized 层落成一行一个品种的日度 OHLC 记录；默认不放进稳定 public-assets bundle，需要显式选择或单独同步

### `carbon_market_snapshot`
- path: `data/normalized/public_assets/carbon_market_snapshot/{trade_date}.csv`
- semantics: 国内碳市场 as-of 快照
- source family: `fallback_online`
- current source: `碳交易网公开行情接口`
- notes: 当前按请求日选择每个地区最近已发布的一条成交记录，因此文件分区日可以晚于单行 `trade_date`

### Public snapshot common fields
- `trade_date`
- `asset_family`
- `asset_type`
- `market`
- `exchange`
- `symbol`
- `name`
- `last_price`
- `change_amount`
- `change_pct`
- `open/high/low/prev_close`
- `volume`
- `amount`
- `source_id`
- `source_url`
- `source_type`
- `retrieved_at`
- `raw_path`
- `parser_version`
- `checksum`
- `run_id`

## Public reference datasets

### `fx_reference_rates`
- path: `data/normalized/public_references/fx_reference_rates/{trade_date}.csv`
- semantics: 人民币外汇参考价表，当前口径为 BOC 历史参考价
- source family: `fallback_online`
- current source: `AkShare currency_boc_safe`
- notes: 当前值保留源站原始口径，即“每 100 外币折人民币”

### `rmb_middle_rates`
- path: `data/normalized/public_references/rmb_middle_rates/{trade_date}.csv`
- semantics: 人民币汇率中间价参考表
- source family: `fallback_online`
- current source: `AkShare macro_china_rmb`
- notes: 当前公开可得历史上限止于 `2021-05-13`；晚于该日期的请求会诚实返回 `no_data`，不会伪装成 current-live 覆盖

### `fx_spot_quotes`
- path: `data/normalized/public_references/fx_spot_quotes/{trade_date}.csv`
- semantics: 人民币外汇即期报价快照
- source family: `fallback_online`
- current source: `AkShare fx_spot_quote`
- notes: 当前 `value` 默认取买报价优先；若买报价缺失则回退到卖报价

### `fx_pair_quotes`
- path: `data/normalized/public_references/fx_pair_quotes/{trade_date}.csv`
- semantics: 外币对即期报价快照
- source family: `fallback_online`
- current source: `AkShare fx_pair_quote`
- notes: 当前按货币对直接输出 `bid / ask / mid` 语义；`unit` 统一写成 `quote_currency per base_currency`

### `fx_swap_quotes`
- path: `data/normalized/public_references/fx_swap_quotes/{trade_date}.csv`
- semantics: 人民币外汇远掉报价快照
- source family: `fallback_online`
- current source: `AkShare fx_swap_quote`
- notes: 当前展开为一行一个 `currency pair + tenor` 远掉点位，`value` 保留源站远掉报价原始口径

### `fx_c_swap_curve`
- path: `data/normalized/public_references/fx_c_swap_curve/{trade_date}.csv`
- semantics: USD/CNY C-Swap 曲线快照
- source family: `fallback_online`
- current source: `ChinaMoney fx-c-sw-curv-USD.CNY.json`
- notes: 当前属于 as-of 曲线快照，文件分区日为请求日，行内 `trade_date` 来自源站 `curveTime`

### `money_market_rates`
- path: `data/normalized/public_references/money_market_rates/{trade_date}.csv`
- semantics: Shibor 参考表
- source family: `fallback_online`
- current source: `AkShare macro_china_shibor_all`
- notes: 当前 `change_bp` 直接保留源站“涨跌幅”原始口径，不在 normalized 层二次换算

### `reserve_reference_series`
- path: `data/normalized/public_references/reserve_reference_series/{trade_date}.csv`
- semantics: 外汇与黄金储备参考序列快照
- source family: `fallback_online`
- current source: `AkShare macro_china_fx_gold / macro_china_foreign_exchange_gold`
- notes: 当前按请求日输出最近一期已发布的 `SAFE / PBOC` 公开口径，不伪装成官方统一口径；`SAFE:GOLD_RESERVE_VALUE` 为估值口径，`PBOC:GOLD_RESERVE_OUNCE` 为数量口径

### `loan_prime_rates`
- path: `data/normalized/public_references/loan_prime_rates/{trade_date}.csv`
- semantics: LPR 参考表
- source family: `fallback_online`
- current source: `AkShare macro_china_lpr`
- notes: 当前采用 as-of 语义，请求日若未到当月发布时间，则回落到最近一次已发布 LPR 日期

### `repo_reference_rates`
- path: `data/normalized/public_references/repo_reference_rates/{trade_date}.csv`
- semantics: 回购定盘利率 / 银银间回购定盘利率参考表
- source family: `fallback_online`
- current source: `AkShare repo_rate_query`
- notes: 当前展开为 `FR001 / FR007 / FR014 / FDR001 / FDR007 / FDR014` 六个日点位

### `cn_us_treasury_yields`
- path: `data/normalized/public_references/cn_us_treasury_yields/{trade_date}.csv`
- semantics: 中美国债收益率参考表
- source family: `fallback_online`
- current source: `AkShare bond_zh_us_rate`
- notes: 当前按列名解析 `中国/美国 + 期限` 生成 `CN_GOVT_* / US_GOVT_*` 参考点位；`2026-04-17` 已保留真实 live 样本文件并进入 DuckDB / GUI / export 链路

### `precious_metal_reference_quotes`
- path: `data/normalized/public_references/precious_metal_reference_quotes/{trade_date}.csv`
- semantics: 上海金 / 上海银基准价参考表
- source family: `fallback_online`
- current source: `AkShare spot_golden_benchmark_sge / spot_silver_benchmark_sge`
- notes: 黄金按 `CNY per gram`，白银按 `CNY per kilogram`

## Public bond datasets

### `interbank_bond_deal_snapshot`
- path: `data/normalized/public_bonds/interbank_bond_deal_snapshot/{trade_date}.csv`
- semantics: 银行间现券成交快照
- source family: `fallback_online`
- current source: `AkShare bond_spot_deal`
- notes: 当前保留债券简称、净价、收益率、成交量等公开可得字段

### `interbank_bond_quote_snapshot`
- path: `data/normalized/public_bonds/interbank_bond_quote_snapshot/{trade_date}.csv`
- semantics: 银行间做市报价快照
- source family: `fallback_online`
- current source: `AkShare bond_spot_quote`
- notes: 当前保留报价机构、买卖净价、买卖收益率等公开可得字段

### `yield_curve_points`
- path: `data/normalized/public_bonds/yield_curve_points/{trade_date}.csv`
- semantics: 中债收益率曲线点位表
- source family: `fallback_online`
- current source: `AkShare bond_china_yield`
- notes: 当前展开为多期限点位行，支持 `3M / 6M / 1Y / 3Y / 5Y / 7Y / 10Y / 30Y`

### `sse_bond_deal_summary`
- path: `data/normalized/public_bonds/sse_bond_deal_summary/{trade_date}.csv`
- semantics: 上交所债券成交概览
- source family: `fallback_online`
- current source: `AkShare bond_deal_summary_sse`
- notes: 当前是一行一个债券类别的摘要表，保留当日成交笔数 / 当日成交金额 / 当年累计成交笔数 / 当年累计成交金额

### `sse_bond_cash_summary`
- path: `data/normalized/public_bonds/sse_bond_cash_summary/{trade_date}.csv`
- semantics: 上交所债券现券市场概览
- source family: `fallback_online`
- current source: `AkShare bond_cash_summary_sse`
- notes: 当前是一行一个债券类别的摘要表，保留托管只数 / 托管市值 / 托管面值

### Public bond common fields
- `trade_date`
- `asset_family`
- `dataset_type`
- `market`
- `exchange`
- `symbol`
- `name`
- `curve_name`
- `counterparty`
- `tenor`
- `price`
- `bid_price`
- `ask_price`
- `yield`
- `bid_yield`
- `ask_yield`
- `weighted_yield`
- `change_bp`
- `volume`
- `source_id`
- `source_url`
- `source_type`
- `retrieved_at`
- `raw_path`
- `parser_version`
- `checksum`
- `run_id`

### Public bond summary fields
- `trade_date`
- `asset_family`
- `dataset_type`
- `market`
- `exchange`
- `category`
- `name`
- `count_value`
- `amount`
- `market_value`
- `par_value`
- `source_id`
- `source_url`

## Crypto datasets

### `crypto_global_snapshot`
- path: `data/normalized/crypto_global/crypto_global_snapshot/{trade_date}.csv`
- semantics: 全球加密资产公开 snapshot，面向 GUI/研究观察
- source family: `fallback_online`
- current source: `CoinGecko coins/markets`
- notes: 与国内 canonical 市场分离，必须带 legal note

### `crypto_assets`
- path: `data/normalized/crypto_global/crypto_assets/{trade_date}.csv`
- semantics: 全球加密资产主表，记录 symbol/name/supply/market-cap-rank 等第一版 master 字段
- source family: `fallback_online`
- current source: `CoinGecko coins/markets`
- notes: 当前优先复用同日 snapshot raw，不重复打 CoinGecko 公共 markets 端点

### `crypto_daily_quotes`
- path: `data/normalized/crypto_global/crypto_daily_quotes/{trade_date}.csv`
- semantics: 全球加密资产日度观察表
- source family: `fallback_online`
- current source: `CoinGecko coin history`, same-day snapshot 诚实回退
- notes: 当 history 端点命中公开速率限制时，会回退到同日 snapshot raw，并保留真实 provenance，不伪装成 history 成功

### `crypto_derivatives_public`
- path: `data/normalized/crypto_global/crypto_derivatives_public/{trade_date}.csv`
- semantics: 全球公开可得加密衍生品观察表
- source family: `fallback_online`
- current source: `CoinGecko derivatives`, fallback `CME bitcoin report`, fallback `OKX public swaps`
- notes: 当前优先走 `CoinGecko derivatives`；若该端点临时不可得，会依次尝试同次 `CME` 比特币公开报告与 `OKX` 公共永续合约行情，并保持真实 `source_id/source_url/source_type`。只有三条公开链路都不可得时，才会诚实记为 `pending_retry`
- `source_type`
- `retrieved_at`
- `raw_path`
- `parser_version`
- `checksum`
- `run_id`

### `crypto_bitcoin_holdings_public`
- path: `data/normalized/crypto_global/crypto_bitcoin_holdings_public/{trade_date}.csv`
- semantics: 全球公开比特币持仓参考表，记录上市公司或公开主体的持仓量、持仓占比、持仓市值与源站查询日期
- source family: `fallback_online`
- current source: `AkShare crypto_bitcoin_hold_report`
- notes: 当前属于 latest/cached 观察层；`trade_date` 是本地快照日，真实源站日期保留在 `source_query_date`，仅作全球公开研究观察

### `crypto_cme_bitcoin_report`
- path: `data/normalized/crypto_global/crypto_cme_bitcoin_report/{trade_date}.csv`
- semantics: CME 比特币公开报告，记录期货/期权成交量、未平仓合约与持仓变化
- source family: `fallback_online`
- current source: `AkShare crypto_bitcoin_cme`
- notes: 当前可按历史公开日期抓取；对未发布日期会诚实返回 `no_data`，仅作全球公开研究观察

### Public reference common fields
- `trade_date`
- `asset_family`
- `reference_type`
- `market`
- `exchange`
- `symbol`
- `name`
- `base_currency`
- `quote_currency`
- `tenor`
- `value`
- `change_bp`
- `unit`
- `source_id`
- `source_url`
- `source_type`
- `retrieved_at`
- `raw_path`
- `parser_version`
- `checksum`
- `run_id`

## Crypto observation datasets

### `crypto_global_snapshot`
- path: `data/normalized/crypto_global/crypto_global_snapshot/{trade_date}.csv`
- semantics: 全球公开加密资产观察快照
- source family: `fallback_online`
- current source: `CoinGecko public coins/markets`
- legal note: 仅作全球公开市场数据研究与行情观察，不提供交易、撮合、开户、引流或任何境内虚拟货币经营服务

### Crypto observation fields
- `trade_date`
- `asset_family`
- `market`
- `exchange`
- `symbol`
- `name`
- `price_usd`
- `change_amount_24h`
- `change_pct_24h`
- `high_24h`
- `low_24h`
- `total_volume`
- `market_cap`
- `market_cap_rank`
- `circulating_supply`
- `total_supply`
- `max_supply`
- `source_id`
- `source_url`
- `source_type`
- `retrieved_at`
- `raw_path`
- `parser_version`
- `checksum`
- `run_id`
- `legal_note`

### `futures_daily_quotes`
- path: `data/normalized/daily_quotes/{trade_date}.csv`
- canonical semantics: full-scope futures daily quotes only
- query semantics: filtered futures results under `data/normalized/queries/{selection_id}/futures/daily_quotes/`
- empty allowed: no, unless the date is semantically `no_data`

### `options_daily_quotes`
- path: `data/normalized/options/daily_quotes/{trade_date}.csv`
- query path: `data/normalized/queries/{selection_id}/options/daily_quotes/{trade_date}.csv`
- empty allowed: no, unless the date is semantically `no_data`

### `derivatives_daily_quotes`
- path: `data/normalized/derivatives/daily_quotes/{trade_date}.csv`
- canonical only from all-scope runs
- query path: `data/normalized/queries/{selection_id}/derivatives/daily_quotes/{trade_date}.csv`

### `contracts_snapshot`
- path: `data/normalized/master/contracts/{trade_date}.csv`
- canonical only from all-scope runs
- query path: `data/normalized/queries/{selection_id}/master/contracts/{trade_date}.csv`
- semantics: master-data-first snapshot; formal master fields stay blank when no official master source is available

### `contracts_latest`
- path: `data/normalized/master/contracts_latest.csv`
- may only be updated by successful canonical all-scope runs
- validation semantics: must match the latest successful canonical all-scope `contracts_snapshot`, not the arbitrary trade date being validated

### `options_exercise_results`
- path: `data/normalized/results/options_exercise/{trade_date}.csv`
- empty allowed: yes, when the semantic status is `no_data`
- semantics: official-only result-chain dataset; quote-side `exercise_volume` does not count as formal exercise results
- current official endpoint coverage:
  - `CFFEX`：官方月报 PDF 聚合结果链，当前解析“期权各产品行权数据统计”并落产品级结果行
  - `SSE`：官方“行权交收信息”接口，当前按标的证券拆分认购/认沽聚合行权结果

### `futures_delivery_results`
- path: `data/normalized/results/futures_delivery/{trade_date}.csv`
- empty allowed: yes, when the semantic status is `no_data`
- not allowed to be inferred from quote data
- semantics: official-only result-chain dataset; per-venue official endpoint coverage is still incomplete
- current official endpoint coverage:
  - `SHFE / INE`：基于上期所官方交割参数 + 月度交割结果 JSON，并按合约前缀拆分 `SHFE` 与 `INE`；若目标交易日对应月份中无该市场交割行，则保持 `no_data`
  - `GFEX`：已接入官方月度交割统计接口；`2026-04-16` 已真实产出 `2` 行

### `options_chain_matrix`
- path: `data/normalized/views/options_chain_matrix/{trade_date}.csv`
- wide view grouped by exchange + underlying + expiry + strike

### `underlying_derivatives_summary`
- path: `data/normalized/views/underlying_derivatives_summary/{trade_date}.csv`
- wide summary view linking futures and options around the same underlying

## Required provenance fields

Where applicable, normalized rows must preserve:
- `source_url`
- `source_type`
- `retrieved_at`
- `raw_path`

## Allowed empty semantics

- quote datasets:
  - empty output is not a valid success condition for applicable quote dates
- result datasets:
  - empty output may be valid when the dataset is semantically `no_data`
