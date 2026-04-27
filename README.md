# 国内多资产数据平台

# 2026-04-27 研究项目闭环与报告自动解读增强

- `/projects` 已从“项目记录页”增强为“研究项目闭环页”：`project-run` 会自动串起 `factor-experiment -> backtest-run -> strategy-leaderboard -> report-generate -> package-export`，并把项目运行、实验结果、报告解读、下一步建议和复现包集中展示。
- `report-generate` 现在会同步物化 `report_insights / recommendation_items`：自动解释质量告警、最佳模型、最值得观察的因子、策略排行榜首位、最脆弱压力情景和数据质量评分，并给出下一步建议。
- `/reports` 新增“自动解读”和“下一步建议”区块；`/projects` 新增“实验对比 / 自动解读 / 下一步建议”区块。
- 已完成真实 smoke：`project-create -> project-run` 在 `daily_ohlcv` 上成功生成因子实验、正式回测、策略排行榜、研究报告、报告解读、建议和可复现包。
- 最新验证：`python3 -m unittest discover -s tests` 通过 `232` 个测试；`validate-platform-metadata --date 2026-04-25`、`environment-check`、`build-db` 均成功，DuckDB `dataset_count = 125`。

# 2026-04-27 产品内插件化 Agent 平台升级结论

- 本轮已在现有 Pro Max 平台上新增“产品内插件化 + Agent 中心”，不做外部 Codex 插件封装；入口是 GUI `/agent` 和 CLI `agent-* / plugin-* / quality-gate / memory-search / model-*`。
- Agent 默认先生成 `draft_plan`、质量门控、风险说明和待确认任务；只有用户点击“确认并运行任务”或执行 `agent-run --task-id ...` 后，才会运行 Feature Store、因子实验、ML Benchmark、正式回测、报告和血缘等长任务。
- 新增平台数据集已进入 registry / source catalog / DuckDB / GUI / export / validation：`agent_tasks / agent_steps / plugin_registry / plugin_runs / research_memory / experiment_notes / decision_log / quality_gates / research_readiness / input_risk_flags / task_queue / task_logs / task_retries / report_insights / recommendation_items / model_registry / feature_versions / model_drift_events`。
- 当前 DuckDB 构建成功，索引数据集数提升为 `125`；Agent smoke 已跑通 `plugin-list -> agent-plan -> agent-run -> model-registry-build -> model-drift-check -> quality-gate`。
- 研究、ML、回测、报告和推荐仍只用于本地研究模拟：不连接券商、不真实下单、不提供投资建议。

## 2026-04-26 Pro Max 全量升级结论

- 当前项目已从“本地研究运营平台第一版”继续升级为“本地量化投研平台 Pro Max”：
  - 新增数据资产地图、字段画像、数据血缘、SLA 检查、知识库索引。
  - 新增 Feature Store、ML Benchmark、时间序列验证、分类任务结果。
  - 新增因子实验室、参数扫描、策略排行榜。
  - 新增组合研究、情景推演、研究项目、项目运行与可复现包。
  - GUI 新增 `/data-map`、`/lineage`、`/factor-lab`、`/portfolio`、`/projects`、`/knowledge`。
- 新增 CLI：
  - `inventory-build`
  - `lineage-build`
  - `feature-run`
  - `ml-benchmark`
  - `ml-validate`
  - `factor-experiment`
  - `parameter-scan`
  - `strategy-leaderboard`
  - `portfolio-run`
  - `scenario-sim`
  - `project-create`
  - `project-run`
  - `package-export`
  - `sla-check`
  - `knowledge-build`
- 新增 normalized datasets：
  - `dataset_inventory`
  - `dataset_field_profile`
  - `data_lineage`
  - `dataset_sla_rules`
  - `sla_violations`
  - `knowledge_index`
  - `ml_feature_store`
  - `ml_benchmarks`
  - `ml_validation_folds`
  - `ml_classification_results`
  - `factor_experiments`
  - `parameter_scans`
  - `strategy_leaderboard`
  - `portfolio_experiments`
  - `scenario_simulations`
  - `research_projects`
  - `project_runs`
  - `reproducible_packages`
- 最新验证基线：
  - `python3 -m unittest discover -s tests`：`227` 个测试全部通过
  - `python3 -m py_compile $(find src -name "*.py")`：通过
  - `PYTHONPATH=src python3 -m futures_workflow validate --date 2026-04-16`：成功
  - `PYTHONPATH=src python3 -m futures_workflow validate-platform-metadata --date 2026-04-25`：成功
  - `PYTHONPATH=src python3 -m futures_workflow environment-check`：成功
  - `PYTHONPATH=src python3 -m futures_workflow build-db`：成功，当前 DuckDB 已索引 `107` 个数据集
  - GUI smoke：`/ /crawl /history /quality /strategies /factor-lab /portfolio /projects /data-map /lineage /scheduler /reports /knowledge /api/summary.json /healthz` 全部 `200 OK`
- ML 与高级模型当前采用本地可运行白名单模板：
  - `linear_regression / ridge / lasso / pca / kmeans / random_forest / xgboost / lightgbm / catboost / svm / mlp / regime_detection`
  - `lightgbm` 与 `catboost` 在无额外二进制依赖时使用本地 sklearn 兼容适配器，保持 CLI、GUI、benchmark、validation 可运行；不会把适配器输出伪装成官方第三方包结果。
  - 所有模型只读取本地 normalized / DuckDB / Feature Store，不连接真实交易，不提供投资建议。

## 2026-04-25 大版本升级结论

- 当前项目已从“本地数据库 + 抓取 GUI”升级为“成熟本地投研平台”的第一阶段：
  - 继续保留 `/` 总览浏览页、`/crawl` 抓取工作台、`/history` 历史研究页、`/quality` 质量运营页。
  - 新增 `/strategies` 策略研究页、`/scheduler` 本地调度页、`/reports` 报告页。
  - 新增 Notebook / examples 研究入口：`notebooks/` 与 `examples/research_helpers.py`。
- 新增 CLI：
  - `research-run`
  - `factor-run`
  - `strategy-backtest`
  - `paper-sim`
  - `quality-diagnose`
  - `scheduler-tick`
  - `report-generate`
  - `algorithm-run`
  - `risk-run`
  - `portfolio-optimize`
  - `backtest-run`
  - `history-sync`
  - `ml-run`
  - `experiment-list`
  - `factor-performance`
  - `stress-test`
  - `quality-score`
  - `artifact-list`
- 新增平台 normalized datasets：
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
- 新增本地状态与报告输出：
  - `state/schedules.json`
  - `state/scheduler_runs.json`
  - `reports/YYYY-MM-DD/daily_report.md`
  - `reports/YYYY-MM-DD/daily_report.html`
- 最新验证基线：
  - `python3 -m unittest discover -s tests`：`227` 个测试全部通过
  - `PYTHONPATH=src python3 -m futures_workflow validate --date 2026-04-16`：成功
  - `PYTHONPATH=src python3 -m futures_workflow validate-platform-metadata --date 2026-04-25`：成功
  - `PYTHONPATH=src python3 -m futures_workflow environment-check`：成功
  - `PYTHONPATH=src python3 -m futures_workflow build-db`：成功，当前 DuckDB 已索引 `107` 个数据集
- 算法与策略层只做本地研究、金融数学建模、风险评估与模拟交易：
  - 默认按日频收盘价口径运行。
  - GUI `/strategies` 只暴露内置白名单模板，不开放任意 Python 脚本执行。
  - 当前模板覆盖：动量、反转、波动率、成交量/换手、期限结构、基差、横截面排序、Black-Scholes、二叉树、债券 YTM/久期/凸性、收益率曲线、VaR/CVaR、相关性、风险平价、均值-方差、正式回测明细、压力测试、线性回归、Ridge、Lasso、PCA、KMeans、随机森林、XGBoost 与 regime detection。
  - `ml-run --tune` 会在本地验证集上做小网格选参，并记录 `validation_r2 / train_count / test_count / prediction_count / mae / rmse` 等训练诊断；默认有 `max_samples` 保护，避免研究页误触发超大训练。
  - 不连接券商，不做真实下单，不提供投资建议。
  - 字段不足的数据集会输出 `not_applicable`，不会伪装成功。
- 调度层采用本地 tick 模式：
  - `scheduler-tick` 会读取 `state/schedules.json` 并执行到期任务。
  - GUI `/scheduler` 顶部按钮表示“运行所有到期任务”，每行“手动运行”才是指定单个任务。
  - 当前不启动常驻后台服务，也不依赖云端任务系统。
- 报告层当前输出本地 HTML + Markdown + 本地图表附件：
  - GUI `/reports` 默认展示最新已生成报告日期，并可只读打开 `daily_report.html / daily_report.md / quality_diagnostics.md`。
  - `report-generate --report-type` 当前支持 `daily / factor / backtest / risk / quality / ml / comprehensive`，并会把图表附件写入 `report_artifacts` 与 `artifact_manifest`。
  - 首版只做本地告警摘要，不发送邮件、飞书或 Slack。

## 2026-04-24 工程收口结论（历史基线）

- 当前仓库已按“工程 100%”口径收口：
  - `A1 / A2 / A3 / B / C / GUI / DuckDB / Export / 测试 / 文档` 的仓库内可控能力已经稳定打通。
  - 多资产层按“第一版 latest-view 平台”口径完成，不宣称逐券全历史已经全部接齐。
- 当前 runtime 仍诚实保留唯一外部阻塞：
  - `cffex.options_exercise_results`
  - `issue_category = blocked_issue`
  - `issue_root_cause = publication_lag`
  - 官方月报返回 HTML 错页而非 PDF 时，系统会保持 `pending_retry`，不会压成 `no_data` 或伪装成 `success`。
- 最近一次真实回归结果：
  - `state/regression_smoke.json`、`run_health`、GUI 当前一致显示 `status=partial_success`
  - 同时一致显示 `engineering_status=success`
  - `issue_category_counts={"result_chain_publication_lag": 1}`
  - `blocked_issues=["options_exercise_results: missing exchanges [CFFEX] are pending official publication"]`
- 最新验证基线：
  - `python3 -m unittest discover -s tests`：`215` 个测试全部通过
  - `PYTHONPATH=src python3 -m futures_workflow validate --date 2026-04-16`：全绿
  - `PYTHONPATH=src python3 -m futures_workflow validate-platform-metadata --date 2026-04-24`：全绿
  - `PYTHONPATH=src python3 -m futures_workflow environment-check`：成功，当前 environment health 为 `success / success`
  - `PYTHONPATH=src python3 -m futures_workflow build-db`：成功，当前 DuckDB 已索引 `60` 个数据集
- 新增预抓能力：
  - `python3 -m futures_workflow pregrab-window ...` 已落地，可按交易所 + 时间窗口执行 `instrument_group=all` 的正式抓取或试跑验证
  - GUI 已新增“逐交易所预抓工作台”，并已拆分到独立页面 `/crawl`，支持 `production` 保留输出与 `trial` 自动清理
  - `trial` 结果只会把摘要写入 `state/pregrab_runs.json`，不会保留临时抓取数据
- 二期首批底座已落地：
  - GUI 已新增 `/history` 历史研究页与 `/quality` 质量运营页
  - `sync-public-assets / sync-public-references / sync-public-bonds / sync-crypto-observation` 现已支持 `--start / --end` 历史窗口参数
  - `regression-smoke` 现已支持 `--profile core|phase2`
  - `state/window_runs.json` 已成为多资产历史窗口同步的正式状态文件
  - 平台派生表已新增 `run_history / coverage_history / source_health_history`
- 平台级状态对齐结果：
  - `source_health` 当前只剩 `1` 条 `blocked_issue`，即 `cffex.options_exercise_results / publication_lag`
  - `asset_coverage.exchange_derivatives_cn` 当前为 `engineering_status=done`、`runtime_status=pending_retry`、`external_issue_count=1`
  - 其余当前已落地资产族按 latest-view 口径已进入 GUI / DuckDB / export / validation

## 快速开始

直接运行：

```bash
python3 -m futures_workflow fetch-date --date 2026-04-16
python3 -m futures_workflow fetch-date --date 2026-04-16 --instrument-group options
python3 -m futures_workflow fetch-date --date 2026-04-16 --instrument-group all --exchange CFFEX
python3 -m futures_workflow fetch-date --date 2026-04-16 --exchange SHFE --variety CU
python3 -m futures_workflow fetch-date --date 2026-04-16 --instrument-group options --exchange SSE
python3 -m futures_workflow fetch-date --date 2026-04-16 --variety SHFE:CU --variety DCE:A
python3 -m futures_workflow validate --date 2026-04-16
python3 -m futures_workflow sync-daily --date latest
python3 -m futures_workflow backfill --start 2026-04-01 --end 2026-04-16
python3 -m futures_workflow gui --host 127.0.0.1 --port 8765
futures-workflow-gui --host 127.0.0.1 --port 8765
python3 -m futures_workflow sync-public-assets --date latest --family equities_spot_snapshot --family etf_spot_snapshot --family reits_spot_snapshot
python3 -m futures_workflow validate-public-assets --date 2026-04-19 --family equities_spot_snapshot --family etf_spot_snapshot --family reits_spot_snapshot
python3 -m futures_workflow sync-public-references --date latest
python3 -m futures_workflow validate-public-references --date 2026-04-17
python3 -m futures_workflow sync-public-bonds --date latest
python3 -m futures_workflow validate-public-bonds --date 2026-04-17
python3 -m futures_workflow sync-crypto-observation --date latest
python3 -m futures_workflow validate-crypto-observation --date 2026-04-19
python3 -m futures_workflow sync-platform-metadata --date latest
python3 -m futures_workflow validate-platform-metadata --date 2026-04-24
python3 -m futures_workflow environment-check
python3 -m futures_workflow sync-public-assets --start 2026-04-01 --end 2026-04-24 --family equities_spot_snapshot
python3 -m futures_workflow sync-public-references --start 2026-04-01 --end 2026-04-24 --family fx_reference_rates
python3 -m futures_workflow sync-public-bonds --start 2026-04-01 --end 2026-04-24 --family yield_curve_points
python3 -m futures_workflow sync-crypto-observation --start 2026-04-01 --end 2026-04-24 --family crypto_daily_quotes
python3 -m futures_workflow regression-smoke --profile phase2 --skip-build-db
python3 -m futures_workflow research-run --date latest --dataset daily_ohlcv
python3 -m futures_workflow factor-run --start 2026-04-20 --end 2026-04-24 --factor momentum --dataset daily_ohlcv
python3 -m futures_workflow strategy-backtest --start 2026-04-20 --end 2026-04-24 --strategy momentum --initial-cash 1000000 --fee-bps 2 --dataset daily_ohlcv
python3 -m futures_workflow paper-sim --date latest --strategy momentum --initial-cash 1000000 --dataset daily_ohlcv
python3 -m futures_workflow quality-diagnose --date latest
python3 -m futures_workflow scheduler-tick --schedule-id daily_quality_diagnose --one
python3 -m futures_workflow report-generate --date latest
python3 -m futures_workflow algorithm-run --template black_scholes_price --start 2026-04-20 --end 2026-04-24 --dataset daily_ohlcv --params '{"underlying_price":100,"strike_price":100,"maturity_years":0.5,"risk_free_rate":0.02,"volatility":0.2,"option_type":"call"}'
python3 -m futures_workflow algorithm-run --template volume_turnover --start 2026-04-20 --end 2026-04-24 --dataset daily_ohlcv
python3 -m futures_workflow risk-run --template var_cvar --start 2026-04-20 --end 2026-04-24 --dataset daily_ohlcv --params '{"confidence":0.95}'
python3 -m futures_workflow portfolio-optimize --template risk_parity --start 2026-04-20 --end 2026-04-24 --dataset daily_ohlcv --params '{"initial_cash":1000000}'
python3 -m futures_workflow backtest-run --strategy momentum --start 2026-04-20 --end 2026-04-24 --dataset daily_ohlcv --initial-cash 1000000 --fee-bps 2 --slippage-bps 1
python3 -m futures_workflow history-sync --scope public_assets --mode 1y
python3 -m futures_workflow inventory-build --date latest
python3 -m futures_workflow lineage-build --date latest
python3 -m futures_workflow feature-run --start 2026-04-16 --end 2026-04-25 --dataset daily_ohlcv
python3 -m futures_workflow ml-benchmark --start 2026-04-16 --end 2026-04-25 --dataset daily_ohlcv --models linear_regression,ridge,lasso,random_forest,xgboost,lightgbm,catboost,svm,mlp
python3 -m futures_workflow ml-validate --template ridge --start 2026-04-16 --end 2026-04-25 --dataset daily_ohlcv
python3 -m futures_workflow factor-experiment --factor momentum --start 2026-04-16 --end 2026-04-25 --dataset daily_ohlcv
python3 -m futures_workflow parameter-scan --template momentum --start 2026-04-16 --end 2026-04-25 --dataset daily_ohlcv
python3 -m futures_workflow strategy-leaderboard --date latest
python3 -m futures_workflow portfolio-run --template risk_parity --start 2026-04-16 --end 2026-04-25 --dataset daily_ohlcv
python3 -m futures_workflow scenario-sim --template equity_down --start 2026-04-16 --end 2026-04-25 --dataset daily_ohlcv
python3 -m futures_workflow project-create --name ProMaxDemo --description 本地投研平台验证 --date 2026-04-25
python3 -m futures_workflow project-run --project-id <project_id> --template momentum --start 2026-04-16 --end 2026-04-25 --dataset daily_ohlcv
python3 -m futures_workflow package-export --run-id <run_id>
python3 -m futures_workflow sla-check --date latest
python3 -m futures_workflow knowledge-build --date latest
python3 -m futures_workflow list-sources --asset-family precious_metals_spot_cn
python3 -m futures_workflow audit --date 2026-04-16
python3 -m futures_workflow audit --all
python3 -m futures_workflow repair --date 2026-04-16
python3 -m futures_workflow repair --all
python3 -m futures_workflow regression-smoke --skip-build-db
python3 -m futures_workflow pregrab-window --start 2026-01-21 --end 2026-04-21 --exchange SHFE --mode trial
python3 -m futures_workflow pregrab-window --start 2026-01-21 --end 2026-04-21 --exchange CFFEX --exchange DCE --exchange SSE --exchange SZSE --mode production
python3 -m futures_workflow build-db
python3 -m futures_workflow export --dataset futures_daily_quotes --date 2026-04-17 --format json
python3 -m futures_workflow export --dataset options_daily_quotes --date 2026-04-16 --format parquet --filter exchange=SSE --filter contract=510050C2604M02650
python3 -m futures_workflow serve-gui --host 127.0.0.1 --port 8765
```

## 目录说明

- `config/sources.yaml`：数据源配置与静态映射
- `data/raw/`：交易所原始响应
- `data/archives/`：历史镜像归档输入，仅用于深历史修复/离线补洞，不参与 canonical success
- `data/normalized/daily_quotes/`：兼容保留的期货日行情输出
- `data/normalized/options/daily_quotes/`：期权日行情输出
- `data/normalized/derivatives/daily_quotes/`：统一衍生品总表
- `data/normalized/master/contracts/`：合约快照
- `data/normalized/master/contracts_latest.csv`：最近一次成功 canonical all-scope 运行生成的最新合约视图
- `data/normalized/queries/{selection_id}/`：带筛选条件的 query 输出
- `data/normalized/results/`：期权行权结果与期货结果表
- `data/normalized/views/`：链矩阵与标的汇总宽表
- `data/normalized/public_assets/`：股票 / ETF / REITs 公开快照输出
- `data/normalized/public_references/`：外汇 / 利率 / 储备 / 贵金属公开参考表输出
- `data/normalized/public_bonds/`：银行间债券成交 / 报价 / 曲线输出
- `data/normalized/crypto_global/`：全球加密资产观察输出
- `data/normalized/platform/`：平台级派生元数据与校验结果输出
- `data/db/market_data.duckdb`：本地 DuckDB 索引库
- `data/exports/`：CSV / JSON / Parquet 导出目录
- `data/logs/`：运行日志与失败日志
- `state/checkpoints.json`：运行状态、重试队列
- `state/query_runs/`：query 运行状态与 checkpoint
- `state/public_assets.json`：公开资产快照运行状态
- `state/public_references.json`：公开参考表运行状态
- `state/public_bonds.json`：公开债券与曲线运行状态
- `state/crypto_global.json`：全球加密观察运行状态
- `state/platform_metadata.json`：平台元数据与验证结果运行状态
- `state/pregrab_runs.json`：逐交易所窗口预抓摘要，供 GUI 直接展示最近 `production / trial` 运行结果
- `state/window_runs.json`：多资产历史窗口同步摘要，供 GUI 历史研究页与质量页展示最近窗口任务结果
- `state/schedules.json`：本地调度任务定义，供 `/scheduler` 与 `scheduler-tick` 复用
- `state/scheduler_runs.json`：本地调度运行记录，会物化为 `scheduler_runs`
- `reports/`：本地 Markdown / HTML 研究运营报告归档
- `notebooks/`：研究模板 Notebook
- `examples/`：DuckDB / normalized 数据读取 helper 与示例脚本

当前桌面环境若系统临时目录异常，测试或 `trial` 预抓可显式指定：

```bash
TMPDIR=/Users/mac/Documents/实习？/.tmp-tests python3 -m unittest discover -s tests
```

## 调度示例

每天晚间 19:05 按北京时间增量更新：

```cron
5 19 * * 1-5 cd /path/to/project && /usr/bin/python3 -m futures_workflow sync-daily --date latest >> cron.log 2>&1
```

## 说明

- 当前仓库已经从“期货工作流”演进成“多资产数据平台骨架 + 已落地的场内衍生品 canonical 数据面”
- 当前多资产层已经新增一批真实非衍生品数据链路：
  - A 股快照、ETF 快照、REITs 快照
  - 开放式基金净值快照、货币基金收益快照
  - 北交所股票快照、可转债快照
  - 国内碳市场 as-of 快照
  - 人民币外汇参考价、人民币汇率中间价、人民币外汇即期报价、外币对即期报价、人民币外汇远掉报价、USD/CNY C-Swap 曲线、Shibor、LPR、回购利率参考表
  - 外汇与黄金储备参考序列
  - 银行间现券成交、做市报价、中债收益率曲线
  - 上海金 / 上海银基准价参考表
  - 全球加密资产观察快照
- 现已支持 `--instrument-group {futures,options,all}`，默认仍为 `futures`
- 支持按交易所、产品、标的、合约筛选：`--exchange SHFE --variety CU`、`--product SSE:510050`、`--underlying SHFE:CU2605`、`--contract CFFEX:HO2604-C-2500`
- 带筛选条件的运行只会写到 `data/normalized/queries/{selection_id}/...`，不会改写 canonical 全市场输出
- `validate` 现在会校验 completeness，不再只看 schema
- `contracts_snapshot` 已按“主数据优先、行情补充”写出，fallback quote metadata 不再冒充正式主数据
- `contracts_latest.csv` 只会在成功的 canonical `--instrument-group all` 运行完成后更新，不会再被 partial/query 运行污染
- `contracts_latest.csv` 现在会直接复制最新成功 canonical all-scope 的 `contracts_snapshot` 文件内容，不再使用独立写出路径，因此字段集、行数、主键与 `source trade date` 都会与源快照完全一致
- 抓取层现在默认启用“保守访问”策略：按 host 节流、轻微随机抖动、命中保护页后退避，不再高并发硬打在线源
- 对已成功抓过的历史日期，`SSE / SZSE / DCE` 期权 raw 与对应主数据现在会优先复用缓存，减少对同一交易日的重复访问
- `SSE` 期权对近期/当前日期新增了官方行情路径，会优先尝试 `yunhq.sse.com.cn:32042` 的官方链表接口，再回落到旧的在线 fallback
- 交易所上市前的日期会记为 `not_applicable`，不再拖累整天状态
- 期权上市前日期也会单独记为 `not_applicable`，不会再把 `2010/2015` 这类早期年份误记成期权 `no_data`
- `SZSE` 历史期权在官方 summary 与附近缓存都不可用时，会继续退回配置里的已知标的代码表做候选发现；它不会伪造 contract，只是扩大历史标的发现面
- `SSE / SZSE` 期权现在还会把单个 numeric symbol 的在线 metadata 与到期日写入独立缓存；后续同 symbol / 同到期月重跑时会优先复用这些缓存，减少对新浪链路的重复触发
- `SSE` 期权在官方 risk rows 临时失败时，会继续尝试附近 `contracts_snapshot` raw 中的官方合约风险行；`SZSE` 期权也会把附近 `contracts_snapshot` raw 里的标的代码当成历史发现补充
- `SZSE` 现在还会把附近 `contracts_snapshot` 已确认过的 `symbol -> contract/strike/expire` 回填进本地 metadata cache，后续历史重跑能直接吃本地 symbol 主数据，不必再次 live 请求 metadata
- `SZSE` 历史期权现在还会从本地 `equity_options_history` 里筛出“目标交易日确实有日线数据”的 numeric symbol，按保守上限做 metadata 探测并沉淀缓存；默认只探测 24 个未缓存 symbol，命中 12 个匹配后就停
- `SZSE` 历史期权 discovery 现在还会优先尝试官方 `option_drhy` 的 `txtQueryDate` 历史分页；如果官方分页能返回历史合约代码，就会直接把 `symbol -> contract/strike/expire/underlying` 写入本地 metadata cache，再拼对应 numeric symbol 的历史日线
- `SZSE` 历史 contract lookup 现在还会校验返回页的 `metadata.subname` 是否与请求日期一致；如果官方接口回的是“当前日期页面”而不是历史页面，就会直接忽略，避免把 2026 当前合约误缓存到 2021 这类历史日期下
- 当前期货覆盖 `SHFE/INE`、`CFFEX`、`CZCE`、`DCE`、`GFEX`
- 当前期权覆盖 `SHFE`、`CFFEX`、`CZCE`、`GFEX`、`DCE`、`SSE`、`SZSE`
- 以交易所官方入口为主，DCE 采用“浏览器拿 cookie + 新版 JSON 接口优先 + 旧导出接口保底”
- DCE 期权在官方链路失败时，会自动切到 `stock2.finance.sina.com.cn` 的商品期权链表与历史日线接口
- SZSE 期权采用“官方合约主数据 + 在线日线”组合；若同日期在线源被限流，会自动复用已经成功写下的 raw 响应
- `SSE / SZSE / DCE` 的历史缓存现在不仅覆盖 quote raw，也覆盖对应的主数据 raw；同一历史日期重跑时会优先走缓存
- 新增 `sync-public-assets / validate-public-assets`，当前已支持：
  - `equities_spot_snapshot`：A 股全市场快照，当前走 `AkShare stock_zh_a_spot` 的公开链路
  - `bse_equities_spot_snapshot`：北交所股票快照，当前优先走 `AkShare stock_bj_a_spot_em`，若 Eastmoney 代理链路抖动会诚实回退到 `Tencent qt.gtimg.cn` 公共行情
  - `etf_spot_snapshot`：ETF 快照，当前走 `AkShare fund_etf_spot_ths`
  - `open_fund_nav_snapshot`：开放式基金净值快照，当前走 `AkShare fund_open_fund_daily_em`
  - `money_market_fund_snapshot`：货币基金收益快照，当前走 `AkShare fund_money_fund_daily_em`
  - `lof_spot_snapshot`：LOF 基金快照，当前优先走 `AkShare fund_lof_spot_em`，若 Eastmoney 代理链路抖动会用公开 LOF 列表页 + `Sina hq` 公共行情诚实回退
  - `reits_spot_snapshot`：REITs 快照，当前优先走 `AkShare reits_realtime_em`，若实时页不可达会复用最近成功 symbol universe 并回退到 `Sina hq` 公共行情
  - `convertible_bond_spot_snapshot`：可转债快照，当前走 `AkShare bond_zh_hs_cov_spot`
  - `sge_spot_daily_quotes`：上金所现货日行情，当前走 `AkShare spot_hist_sge`
  - `carbon_market_snapshot`：国内碳市场 as-of 快照，当前优先走碳交易网公开行情接口并按请求日选择最近已发布地区点位
- 新增 `sync-public-references / validate-public-references`，当前已支持：
  - `fx_reference_rates`：人民币外汇参考价，当前走 `AkShare currency_boc_safe`
  - `rmb_middle_rates`：人民币汇率中间价参考表，当前走 `AkShare macro_china_rmb`
  - `fx_spot_quotes`：人民币外汇即期报价，当前走 `AkShare fx_spot_quote`
  - `fx_pair_quotes`：外币对即期报价，当前走 `AkShare fx_pair_quote`
  - `fx_swap_quotes`：人民币外汇远掉报价，当前走 `AkShare fx_swap_quote`
  - `fx_c_swap_curve`：USD/CNY C-Swap 曲线，当前优先走 ChinaMoney 公开 JSON
  - `money_market_rates`：Shibor 参考表，当前走 `AkShare macro_china_shibor_all`
  - `reserve_reference_series`：外汇与黄金储备参考序列，当前走 `AkShare macro_china_fx_gold / macro_china_foreign_exchange_gold`
  - `loan_prime_rates`：LPR 参考表，当前走 `AkShare macro_china_lpr`
  - `repo_reference_rates`：回购定盘利率 / 银银间回购定盘利率参考表，当前走 `AkShare repo_rate_query`
  - `cn_us_treasury_yields`：中美国债收益率参考表，当前走 `AkShare bond_zh_us_rate`
  - `precious_metal_reference_quotes`：上海金 / 上海银基准价参考表，当前走 `AkShare spot_golden_benchmark_sge / spot_silver_benchmark_sge`
- 新增 `sync-public-bonds / validate-public-bonds`，当前已支持：
  - `interbank_bond_deal_snapshot`：银行间现券成交快照，当前走 `AkShare bond_spot_deal`
  - `interbank_bond_quote_snapshot`：银行间做市报价快照，当前走 `AkShare bond_spot_quote`
  - `yield_curve_points`：中债收益率曲线点位，当前走 `AkShare bond_china_yield`
  - `sse_bond_deal_summary`：上交所债券成交概览，当前走 `AkShare bond_deal_summary_sse`
  - `sse_bond_cash_summary`：上交所债券现券概览，当前走 `AkShare bond_cash_summary_sse`
- 公开资产快照同样会落 raw、normalized 和 state，并能直接在 GUI 里浏览
- 公开参考表同样会落 raw、normalized 和 state，并能直接在 GUI 里浏览
- 新增 `sync-crypto-observation / validate-crypto-observation`，当前已支持：
  - `crypto_global_snapshot`：CoinGecko 公共快照，当前覆盖 BTC / ETH / USDT / USDC / BNB / SOL / XRP / DOGE 的研究观察样本
  - `crypto_assets`：基于同日 CoinGecko snapshot 物化出的加密资产主表
  - `crypto_daily_quotes`：CoinGecko history 优先、同日 snapshot 诚实回退的日度观察表
  - `crypto_derivatives_public`：CoinGecko public derivatives 公开衍生品观察表；若 CoinGecko 衍生品端点临时不可得，会依次尝试同次 `CME` 公开报告与 `OKX` 公共永续合约行情兜底，仍保留真实 provenance
  - `crypto_bitcoin_holdings_public`：基于 `AkShare crypto_bitcoin_hold_report` 的全球公开比特币持仓参考表，记录上市公司/公开主体持仓量、持仓占比、持仓市值与源站查询日期
  - `crypto_cme_bitcoin_report`：基于 `AkShare crypto_bitcoin_cme` 的 CME 比特币公开报告，记录期货/期权成交量、未平仓合约与持仓变化
- crypto 相关数据会落到独立的 `data/normalized/crypto_global/` 与 `state/crypto_global.json`，并在 GUI 中单独标注 legal note，不与国内 canonical 市场混淆
- 新增 `sync-platform-metadata / validate-platform-metadata`，当前已支持：
  - `instrument_master`：把场内衍生品、公开资产、债券、外汇参考、crypto 观察统一映射成平台级 instrument master
  - `bond_master`：把银行间成交/报价与交易所债券摘要统一映射成平台级债券主数据视图
  - `bond_quotes`：把银行间成交/报价与交易所债券摘要统一映射成平台级债券报价表
  - `fx_quotes`：把人民币外汇参考价、人民币汇率中间价、即期、外币对、远掉与 C-Swap 曲线统一映射成平台级外汇报价表
  - `yield_curves`：把中债收益率曲线点位与中美国债收益率观察统一映射成平台级收益率曲线表
  - `commodity_spot_quotes`：把上金所现货、上海金银基准价与国内碳市场快照统一映射成平台级现货/基准价表
  - `crypto_global_quotes`：把 `crypto_global_snapshot / crypto_daily_quotes / crypto_derivatives_public` 统一映射成平台级全球加密报价表
  - `daily_ohlcv`：把场内衍生品日线、股票/ETF/REITs/可转债快照与 crypto 日线观察统一映射成平台级日线行情表
  - `fund_nav`：把开放式基金净值与货币基金收益快照统一映射成平台级基金净值表
  - `reits_quotes`：把公募 REITs 快照统一映射成平台级 REITs 行情表
  - `trading_calendar`：把衍生品、股票、外汇参考、债券利率与 crypto 的最近已知交易日状态统一映射成平台级交易日日历快照
  - `validation_results`：把 derivatives/public-assets/public-references/public-bonds/crypto 的最新验证结果统一落表
  - `source_health`：把 source registry 与最近一次状态统一落表，供 GUI / DuckDB / 导出使用
- CZCE 老年份官方静态文件不可用时，会自动切到 `AkShare get_futures_daily` fallback
- 当 DCE 官方接口仍失败时，会自动切到混合 fallback：
  - 近期优先使用 Sina 历史日线
  - `2021-01-01` 之后的较早日期会补充 EDB 单合约日线
  - fallback 缓存位于 `data/raw/dce/fallback_contract_histories/` 和 `data/raw/dce/fallback_edb_rows/`
- `data/archives/` 下的 deep-history 归档仍可保留给 repair / offline tooling，但不参与 canonical success
- canonical success 路径只允许 `source_type = official | official_browser_bootstrap | fallback_online`
- `futures_delivery_results` 现在会固定产出；当前已接入 `SHFE / INE`、`GFEX` 与 `DCE` 的首批官方交割结果端点
  - 例如 `2026-04-16` 已真实产出 `GFEX` 交割结果 `2` 行
  - `SHFE` 同日已命中官方交割结果端点并参与 `success` 聚合
  - `INE` 已按上期所官方月度交割结果拆分为独立市场语义，不再混在 `SHFE` 里含混处理
  - `DCE` 已新增官方月度市场报告 PDF 交割结果链：例如 `2019-04-16` 会基于官方月报真实落出 `JD1905 / FB1905` 两条交割结果
  - 其余交易所在未配置官方结果端点前，会继续以 `no_data / pending_retry / blocked_issue` 的诚实语义暴露缺口，不伪装成“全市场 success”
- `options_exercise_results` 现在只认官方结果链；若未配置或当日无官方结果发布，则输出仅含表头的空 CSV
  - 当空表原因是“官方当日确无结果发布”时，语义为合法 `no_data`
  - `CFFEX` 已新增官方月报 PDF 聚合结果链：例如 `2021-04-16` 会基于官方月度报告真实落出 `1` 行产品级行权结果
  - `DCE` 已新增官方月度市场报告 PDF 聚合结果链：例如 `2019-04-16` 会基于官方月报真实落出 `M1905` 系列的 `CALL / PUT` 两条聚合行权结果
  - `SSE` 已新增官方“行权交收信息”接口：例如 `2021-04-28` 可真实落出 `4` 行按标的拆分的认购/认沽聚合结果
  - `SZSE` 已新增官方“行权交收统计”接口：例如 `2026-03-26` 当前可真实落出 `8` 行按标的拆分的认购/认沽聚合结果
  - 当空表原因是“官方结果端点尚未接齐”时，`validate` 会诚实反映成 `pending_retry / blocked_issue`，而不是伪装成 success
- CSV 编码为 `UTF-8-SIG`，方便直接用 Excel 打开

## GUI

- 本地 GUI 入口：`python3 -m futures_workflow gui --host 127.0.0.1 --port 8765`
- 页面结构：
  - `/`：总览与浏览页，负责看数据集、质量状态、DuckDB manifest、回归摘要
  - `/crawl`：独立抓取工作台，负责点选触发抓取、回补、预抓与平台同步
  - `/history`：历史研究页，负责按数据集、日期范围和常用维度浏览历史窗口输出，并读取 `window_runs` 摘要
  - `/quality`：质量运营页，负责查看 `run_history / coverage_history / source_health_history` 与最近环境检查结果
  - `/strategies`：策略研究页，负责通过内置模板生成研究指标、因子信号、日频模拟回测和一日模拟组合
  - `/scheduler`：本地调度页，区分“运行所有到期任务”和“手动运行此任务”
  - `/reports`：报告中心，默认定位到最新报告日期，并支持只读打开 HTML / Markdown 报告文件
- 页面用途：
  - 浏览最新 canonical 日期、checkpoint 状态、`contracts_latest` 一致性
  - 查看当前各数据集的 schema / completeness / 行数摘要
  - 预览某个交易日的本地 CSV，并按 `asset_family / market / exchange / instrument_type / symbol / contract / currency / tenor` 做通用等值筛选
  - 顶部筛选区现在会根据当前数据集自动生成可选项：`asset_family / market / exchange / instrument_type / currency / tenor` 优先以下拉方式选择，`symbol / contract` 提供建议输入
  - 直接从 GUI 导出当前选中数据集的 `CSV / JSON / Parquet`
  - 浏览 query 运行列表
  - 浏览“多资产平台注册表”，明确哪些资产族已经落地、哪些仍是 planned
  - 浏览平台级统一表：`instrument_master / daily_ohlcv / fund_nav / reits_quotes / trading_calendar / yield_curves / validation_results / source_health`
  - 浏览 A 股 / 北交所 / ETF / REITs / 可转债快照，以及外汇 / Shibor / LPR / 回购利率 / 贵金属基准价参考表 / 债券与收益率曲线的最近状态和输出路径
  - 浏览全球加密资产观察快照，并明确看到 legal note
- 当前 GUI 不再只是只读浏览层：
  - 总览页 `/` 不再内嵌抓取表单，而是提供“打开独立抓取工作台”入口
  - 独立抓取页 `/crawl` 已支持单日抓取、区间回补、公开资产/参考/债券/crypto 同步、平台元数据同步、环境检查与 DuckDB 重建
  - 独立抓取页 `/crawl` 现已新增醒目的“一键抓取当前已接入的全部数据”入口，用于执行当前仓库已接入范围内的 latest-view 全量同步
  - 独立抓取页 `/crawl` 中的“逐交易所预抓工作台”已支持 `CFFEX / CZCE / DCE / GFEX / SHFE / SSE / SZSE` 多选
  - 窗口支持 `近 7 天 / 近 1 月 / 近 3 月 / 自定义`
  - 模式支持 `production` 与 `trial`
  - `trial` 会在隔离 root 下执行并自动清理，只把摘要持久化到 `state/pregrab_runs.json`
  - 预抓结果会同时展示 `runtime verdict` 与 `engineering verdict`，并单独标出 `publication_lag / 0 行行情 / cleanup_status`
  - 二期新增的历史窗口同步也已进入 `/crawl`，并把结果写入 `state/window_runs.json`
  - `/history` 现会直接读取历史窗口任务摘要与对应 normalized 输出做样本预览
  - `/quality` 现会直接读取 `run_history / coverage_history / source_health_history`，用于查看运行趋势、覆盖趋势与 source 健康趋势
  - `/strategies` 现会用下拉模板展示当前支持的算法能力，不开放任意 Python 脚本执行
  - `/scheduler` 现会展示当前到期任务数量与任务名，避免把全局 tick 误解成某个单任务执行
  - `/reports` 现会把报告文件展示为可点击链接，文件访问被限制在允许的本地报告文件白名单内
- 当前 GUI 的“可点击抓取”语义是：
  - 已落地链路可以直接触发抓取
  - “一键抓取当前已接入的全部数据”会串行执行：衍生品 latest canonical、公开资产、公开参考、公开债券、crypto 观察、平台元数据与 DuckDB
  - 但不宣称所有市场、所有日期、所有官方源都必定成功
  - 当前唯一明确外部阻塞仍是 `cffex.options_exercise_results / publication_lag`
- GUI 下载入口是只读导出层：底层仍复用 `build-db / export` 语义，不会改写 canonical / query 数据
- 当前正式数据链路仍以“国内场内衍生品”为主，但非衍生品侧已经不再只是占位：
  - 股票 / ETF / REITs 已有快照 collector
  - 外汇 / Shibor / 上海金银基准价已进入公开参考表 collector
  - 更深的债券行情、外汇即期/远期、基金历史净值、加密观察等仍待继续扩展

## 当前验证结论

- `2026-04-16 --instrument-group all`：checkpoint 仍为 `success`
- `2026-04-16 validate`
  - quote/master 主干表为 `schema_ok=true`、`duplicate_keys=0`、`missing_raw_paths=[]`
  - `contracts_latest` 与最新 canonical snapshot 一致，且 `source_trade_date = 2026-04-16`
  - `options_exercise_results = no_data`
    - 原因：`No option contracts expire or exercise on this trade date.`
  - `futures_delivery_results = success`
    - 当前 `row_count = 2`
- `2026-04-17 --instrument-group all`：当前主干回归已通过，最近一次 `regression-smoke --skip-build-db` 为 `partial_success`
  - 当前仍会诚实保留一个 `blocked_issue`
  - 真实原因是 `options_exercise_results / CFFEX` 官方月报尚处于 `publication_lag`
- `2026-04-17 validate`
  - quote / master / view 主干仍为 `schema_ok=true`、`duplicate_keys=0`、`missing_raw_paths=[]`、`completeness_ok=true`
  - `options_exercise_results = pending_retry`
  - `contracts_snapshot.master_data_completeness = true`
- `2026-04-14 --instrument-group all`：`success`
- `2026-04-14 validate`：`schema_ok=true`、`duplicate_keys=0`、`missing_raw_paths=[]`、`completeness_ok=true`
- `2026-04-17 --instrument-group options --exchange SSE`：`success`
  - 本次为无历史 raw 缓存样本，已真实走到 `SSE` 官方近期行情路径，`source_type=official`
- `2026-04-17 --instrument-group options --exchange SZSE`：`success`
  - 近期历史发现逻辑已改成“目标交易日主数据 + 在线日线”，不再错误依赖当日 current contract 表
- `2026-04-17 --instrument-group options --exchange DCE`：`success`
  - 当前依旧为 `fallback_online`，但最近交易日已能稳定命中成功 raw cache
- `audit --all`：当前会批量审计所有已有 canonical 日期；最近实测已扫出 `2010-04-16 / 2015-04-16 / 2021-04-16 / 2026-04-14 / 2026-04-15 / 2026-04-16 / 2026-04-17` 全部 `needs_repair = false`
- `repair --date 2026-04-16`：现在会显式按本地 raw/summary 强制重建该日 canonical 状态，不再要求先命中 `needs_repair`
- `repair` 现在还会在“结果链没有缓存 raw、但本地主行情行已能证明当日无到期/无交割”的场景下离线刷新旧 summary，不再把过时的 `No official ... endpoint configured.` 原样抄回去
- 结果链历史 raw 的离线重建兼容也已补强：非 UTF-8 文本缓存会按公开源常见编码自动解码，带 `&nbsp;` 的旧 XML/HTML 结果页也不会再让 repair 直接失败
- `2021-04-16 --instrument-group all`：`success`
  - `options_exercise_results = success`
  - 当前会基于 `CFFEX` 官方月报 PDF 真实产出 `1` 行产品级行权结果
- `audit --all` 现在还会返回 `issue_category_counts`
  - 当前 `needs_repair_dates = []`
- 最近一次完整 `regression-smoke` 当前已为 `partial_success`
  - 当前仍会诚实保留：
    - `issue_category_counts = {"result_chain_publication_lag": 1}`
    - `2026-04-17` 的 `blocked_issue`
  - 当前阻塞项是：
    - `options_exercise_results: missing exchanges [CFFEX] are pending official publication`
- 平台级 `validation_results` 现在会把 `blocked_issue_count / blocked_issues` 一起落表，便于 DuckDB / export / GUI 统一消费
- 平台级 `source_health` 现在会把 `issue_category / blocked_reason` 一起落表，弱源退避、公开源不可得和合法 `no_data` 可以直接区分
- `source_health` 现在也会显式纳入 `futures_delivery_results / options_exercise_results` 的 source 条目，结果链端点缺口不再藏在 dataset 汇总后面
- `source_health` 优先反映最近一次已记录的衍生品运行状态，而不是只盯最近 fully successful canonical 日期
- `2015-04-16 --instrument-group all`：`success`
- `2010-04-16 --instrument-group all`：`success`
- `sync-daily --date latest` 当前 futures 默认链路可成功跑到 `2026-04-17`
- 本地 GUI 现在可直接启动并浏览当前 canonical / query 输出
- `sync-public-assets --date latest`：`success`
  - A 股 `5505`
  - ETF `1533`
  - 开放式基金 `23052`
  - 货币基金 `538`
  - REITs `82`
  - 可转债 `359`
- `sync-public-assets --date 2026-04-19 --family carbon_market_snapshot`：`success`
  - `carbon_market_snapshot = 8`
- `sync-public-references --date latest` 在周末会自动回落到最近工作日；当前 `2026-04-17` 的人民币外汇参考价、人民币外汇即期报价与 Shibor 为 `success`，上海金银基准价为 `no_data`
- `sync-public-references --date 2021-05-13 --family rmb_middle_rates`：`success`
  - `rmb_middle_rates = 14`
- `sync-public-references --date latest --family rmb_middle_rates`：当前会诚实返回 `no_data`
  - 原因是当前公开 `AkShare macro_china_rmb` 可得历史上限止于 `2021-05-13`
- `sync-public-references --date 2026-04-17 --family fx_pair_quotes --family fx_swap_quotes --family fx_c_swap_curve`：`success`
  - `fx_pair_quotes = 16`
  - `fx_swap_quotes = 150`
  - `fx_c_swap_curve = 12`
- `sync-public-references --date 2026-04-17 --family loan_prime_rates --family repo_reference_rates`：`success`
- `sync-public-bonds --date 2026-04-17`：`success`
  - `interbank_bond_deal_snapshot = 3945`
  - `interbank_bond_quote_snapshot = 15`
  - `yield_curve_points = 23`
- `sync-public-references --date 2026-04-15 --family precious_metal_reference_quotes`：`success`
- `sync-crypto-observation --date latest`：`success`
- 本地 GUI 现在还能展示 A 股 / ETF / 开放式基金 / 货币基金 / REITs / 可转债 / 国内碳市场快照，以及外汇参考价 / 人民币汇率中间价 / 外汇即期报价 / 外币对即期报价 / 外汇远掉报价 / C-Swap 曲线 / Shibor / LPR / 回购利率 / 上海金银基准价参考表的最近状态和输出路径
- 本地 GUI 现在还能展示“中美国债收益率”这类跨市场利率参考表；`2026-04-17` 的真实 live 样本已经写入 raw / normalized / DuckDB，可直接在 GUI 中浏览
- 本地 GUI 现在还能展示外汇与黄金储备参考序列，并区分 `SAFE / PBOC` 两套公开口径
- 本地 GUI 现在还能展示北交所股票、可转债、上金所现货日行情，以及银行间债券成交 / 报价 / 收益率曲线 / 上交所债券摘要的最近状态和输出路径
- 本地 GUI 现在还能展示全球加密资产观察快照与 legal note
- 本地 GUI 现在还能展示平台级 `instrument_master / bond_master / bond_quotes / fx_quotes / commodity_spot_quotes / crypto_global_quotes / validation_results / source_health / run_health / asset_coverage / source_type_overview / issue_category_overview` 派生表
- GUI 现在新增“数据质量阻塞与修复”区块，会直接展示当前日期的 `issues / blocked_issues`，不再只依赖 CLI JSON
- GUI 现在还会直接展示 `issue_category_counts`，可以按 `result_chain_publication_lag / result_chain_source_gap / historical_public_contract_gap` 这类结构化类别查看当前阻塞
- GUI 现在还会直接展示 DuckDB manifest，包括数据库路径、已索引数据集数量，以及每个数据集的文件数/行数/最近构建时间
- `regression-smoke` 现在会把最近一次回归摘要持久化到 `state/regression_smoke.json`
- GUI 现在还能直接展示最近一次 `regression-smoke` 的运行时间、运行状态、工程收口状态、代表日期状态、连续窗口状态，以及结构化阻塞类别
- GUI 现在还能直接展示 source catalog 与 `source_type` 统计，便于核对 `official / fallback_online / derived` 的真实注册覆盖
- GUI 现在还能直接展示最近的 `source_health` 异常源明细，便于联查 `pending_retry / blocked_issue / no_data` 的来源和原因
- 平台元数据现已新增 `run_health`，会把最近一次 `regression-smoke` 的运行状态、工程收口状态、代表日期、连续窗口和阻塞类别一起物化成可浏览、可导出、可进 DuckDB 的派生表
- GUI 现已新增“逐交易所预抓工作台”，会把最近一次预抓摘要写入 `state/pregrab_runs.json` 并直接展示：
  - `exchange / window_start / window_end / mode`
  - `status / engineering_status`
  - `success_count / no_data_count / not_applicable_count / blocked_external_count / failed_count`
  - `cleanup_status`
  - `blocked_issues`
- `pregrab-window` 当前已经过真实 smoke：
  - `SHFE 2026-04-14..2026-04-21 trial = status=success, engineering_status=success`
  - `CFFEX 2026-04-17 trial = status=partial_success, engineering_status=success`
  - 其中 `CFFEX options_exercise_results / publication_lag` 已被归类为外部阻塞，不再被误判成工程失败
- 平台元数据现已新增 `asset_coverage`，会把各资产族的最新覆盖状态、覆盖比例、成功/非成功数据集数量和最新交易日物化成正式派生表
- 平台元数据现已新增 `source_type_overview`，会把各类 source_type 的源数量、数据集数量、success/非success 统计和 blocked issue 数量物化成正式派生表
- 平台元数据现已新增 `issue_category_overview`，会把 `source_health` 中的 `healthy / no_data / retry_or_error / blocked_issue` 问题类别聚合成正式派生表
- 当前 `build-db` 已能索引 `107` 个数据集，`run_health / run_history / coverage_history / source_health_history / asset_coverage / source_type_overview / issue_category_overview / research_metrics / factor_signals / strategy_backtests / paper_portfolios / quality_diagnostics / scheduler_runs / research_reports / algorithm_outputs / option_analytics / bond_analytics / curve_analytics / risk_metrics / portfolio_allocations / backtest_equity_curves / backtest_positions / backtest_trades / strategy_comparisons / anomaly_events / ml_model_runs / ml_predictions / ml_feature_importance / model_diagnostics / backtest_input_quality / experiment_runs / factor_performance / stress_test_results / artifact_manifest / dataset_quality_scores / report_artifacts / dataset_inventory / dataset_field_profile / data_lineage / dataset_sla_rules / sla_violations / knowledge_index / ml_feature_store / ml_benchmarks / ml_validation_folds / ml_classification_results / factor_experiments / parameter_scans / strategy_leaderboard / portfolio_experiments / scenario_simulations / research_projects / project_runs / reproducible_packages` 已进入 DuckDB manifest
- `validate-platform-metadata --date 2026-04-24` 当前已通过，上述平台派生表均为 `schema_ok=true`
- `sync-public-assets --date latest` 当前可真实落地 `equities / BSE / ETF / LOF / REITs / 可转债` 等快照；最新一次 `2026-04-21` 已通过 `Tencent/Sina` 公共 fallback 把 `bse_equities_spot_snapshot / lof_spot_snapshot / reits_spot_snapshot` 恢复到 `success`
- `sync-public-assets --date latest` 当前若某个公开快照源语义上确实无数据，也会像结果链一样落 header-only CSV；例如 `2026-04-21` 的 `sge_spot_daily_quotes` 当前就是合法 `no_data`，但已写出空表和 provenance，便于 GUI / DuckDB / validate 一致处理
- `sync-crypto-observation --date latest` 当前可真实落地 `crypto_global_snapshot / crypto_assets / crypto_daily_quotes / crypto_bitcoin_holdings_public / crypto_derivatives_public`；`crypto_derivatives_public` 在 CoinGecko 不可得时会诚实尝试 `CME -> OKX` 回退，仅在三条公开链路都不可得时才记 `pending_retry`
- `sync-crypto-observation --date 2023-08-30` 当前可真实落地 `crypto_cme_bitcoin_report`；`2023-08-30` 已写入 `5` 行 CME 比特币公开报告样本
- 新增 `build-db / export / list-sources / audit / repair / serve-gui` 命令，便于把 canonical 数据构建成 DuckDB、本地导出和做修复审计
- 新增 `regression-smoke` 命令，会把代表日期 `validate`、`audit --all`、平台元数据同步/校验，以及可选 `build-db / GUI smoke` 串成一条 B 收口回归链
- `regression-smoke` 当前还会额外固化连续窗口：
  - `latest_7_trading_days`
  - `latest_1m_trading_days`
  - `latest_1y_monthly_sample`
  - `latest_3y_quarterly_sample`
  并把这些窗口结果一起写入 `state/regression_smoke.json`、GUI 和 `run_health`
- `regression-smoke` 现在会按交易日日历生成这些窗口目标集，并在缺失 canonical 样本时自动先做 canonical all-scope 补样，再纳入窗口 validate
- `audit --all` 顶层现在会同步聚合 `issues / blocked_issues / issue_category_counts`，不会再出现类别统计有了但阻塞明细没进 state / run_health 的口径偏差
- 最近一次完整 `regression-smoke` 已为 `partial_success`
  - 代表日期 `2010 / 2015 / 2021 / 2026` 全部通过
  - `audit.needs_repair_dates = []`
  - 代表日期回归本身已通过，但最近一次 `--skip-build-db` 仍会诚实保留 `{"result_chain_publication_lag": 1}`
  - `platform_validation = success`
  - `gui_smoke.has_yield_curves = true`
  - 最近一次 `build-db` 已成功，`dataset_count = 107`
- 当前 `build-db` 会把 canonical normalized 数据映射成 DuckDB view；`export` 支持 `csv / json / parquet`，并支持用 `--filter key=value` 追加通用等值筛选
- 当前 `build-db` 已能索引 `107` 个数据集，现已新增纳入 `asset_coverage / source_type_overview / issue_category_overview / run_history / coverage_history / source_health_history / research_metrics / factor_signals / strategy_backtests / paper_portfolios / quality_diagnostics / scheduler_runs / research_reports / algorithm_outputs / option_analytics / bond_analytics / curve_analytics / risk_metrics / portfolio_allocations / backtest_equity_curves / backtest_positions / backtest_trades / strategy_comparisons / anomaly_events / ml_model_runs / ml_predictions / ml_feature_importance / model_diagnostics / backtest_input_quality / experiment_runs / factor_performance / stress_test_results / artifact_manifest / dataset_quality_scores / report_artifacts / dataset_inventory / dataset_field_profile / data_lineage / dataset_sla_rules / sla_violations / knowledge_index / ml_feature_store / ml_benchmarks / ml_validation_folds / ml_classification_results / factor_experiments / parameter_scans / strategy_leaderboard / portfolio_experiments / scenario_simulations / research_projects / project_runs / reproducible_packages`，并持续覆盖 `bond_master / bond_quotes / fx_quotes / commodity_spot_quotes / crypto_global_quotes / daily_ohlcv / fund_nav / reits_quotes / trading_calendar / yield_curves / run_health`
- `SZSE` 历史期权 discovery 继续收紧为“本地 history cache + nearby contracts_snapshot 批量回灌 metadata + 限量 live metadata probe”；当前默认仅在老历史公开源缺口场景下开启，且受 `equity_option_historical_probe_limit / budget_seconds / timeout_seconds` 三重约束，避免把历史修复变成无界 live 扫描

## 当前剩余重点

- `futures_delivery_results` 与 `options_exercise_results` 已经是正式独立数据集；其中 `futures_delivery_results` 已开始落地逐交易所官方结果端点，当前 `SHFE / INE / GFEX / DCE` 已接入首批端点，但全市场仍未全部接齐
- `options_exercise_results` 当前也不再是“纯空壳”：
  - `CFFEX` 已接入官方月报 PDF 聚合结果链
  - `DCE` 已接入官方月度市场报告 PDF 聚合结果链
  - `SSE` 已接入官方“行权交收信息” JSON 接口
  - 其余交易所官方结果端点仍待继续接齐
- `CFFEX` 最近日期月报链路还有一个真实边界：
  - 某些日期官方端点会返回 `HTTP 200` 的 HTML 错误页而不是 PDF
  - 当前实现会把这类 raw 诚实写成 `.html`
  - 并落成 `pending_retry / blocked_issue`，不再误判成 `no_data`
- `DCE / SZSE` 期权目前已经具备同日缓存稳定重跑能力，但“无缓存的任意近期交易日”仍未完全稳固
- `SSE` 近期无缓存日期已经新增官方路径，但更老的无缓存历史日期仍需要继续收尾
- 股票 / 北交所 / ETF / 开放式基金 / 货币基金 / REITs / 可转债 目前是“快照层”已接入；历史日线、主数据、财报、停复牌等更深链路还未继续展开
- 债券全量行情 / 曲线已经起步到“银行间成交 + 报价 + 曲线点位”，但交易所债、债券主数据、活跃券统计仍未接齐
- 外汇远期/掉期、贵金属现货更多品种仍未完成正式 collector 接入
- crypto 当前仅有“全球公开观察快照”，更丰富的 CME / 市值结构 / 历史序列仍待继续扩展
