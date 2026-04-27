# VALIDATION.md

# 2026-04-27 研究项目闭环验证快照

- 新增验证范围：
  - `project-run` 必须自动串起因子实验、正式回测、策略排行榜、报告生成和复现包导出。
  - `report-generate` 必须同步物化 `report_insights / recommendation_items`。
  - `/projects` 和 `/reports` 必须展示实验对比、自动解读和下一步建议。
- 新增测试覆盖完整闭环，要求生成 `factor_experiments / backtest_* / strategy_leaderboard / research_reports / report_insights / recommendation_items / project_runs / reproducible_packages`。
- 已实跑真实 smoke：`project-create -> project-run` 在 `daily_ohlcv` 上成功完成闭环。

# 2026-04-27 Agent 插件化验证快照

- 新增验证范围：
  - `PluginRegistry` 注册、列出、校验插件声明。
  - `AgentOrchestrator` 生成计划时停在 `awaiting_confirmation`，不执行长任务。
  - `quality-gate` 能区分 `pass / warning / blocked`，并落出 readiness 与 risk flags。
  - `agent-run` 确认后串联数据资产、质量守门、Feature、因子、ML、回测、报告和血缘步骤。
  - `model-registry-build / model-drift-check` 可从 ML Benchmark 结果生成模型注册与漂移事件。
- 已新增 `tests/test_agent_platform.py`，覆盖插件注册、计划草案、质量门控、确认运行、模型注册与漂移。
- 已实跑：
  - `plugin-list --date latest`：成功，`plugin_registry = 10` 行。
  - `agent-plan --goal ... --start 2026-04-16 --end 2026-04-25 --dataset daily_ohlcv`：成功，状态 `awaiting_confirmation`。
  - `agent-run --task-id ...`：成功，8 个插件步骤执行并落表。
  - `model-registry-build --date 2026-04-25`：成功，`model_registry = 12` 行。
  - `model-drift-check --date 2026-04-25`：成功，`model_drift_events = 12` 行。
  - `validate-platform-metadata --date 2026-04-25`：成功。
  - `build-db`：成功，当前 DuckDB `dataset_count = 125`。

## 2026-04-26 Pro Max 验证快照

- Pro Max 新增验证范围：
  - 数据资产地图：`dataset_inventory / dataset_field_profile`
  - 数据血缘：`data_lineage`
  - SLA 与知识库：`dataset_sla_rules / sla_violations / knowledge_index`
  - Feature Store 与 ML：`ml_feature_store / ml_benchmarks / ml_validation_folds / ml_classification_results`
  - 因子实验：`factor_experiments / parameter_scans / strategy_leaderboard`
  - 组合与项目：`portfolio_experiments / scenario_simulations / research_projects / project_runs / reproducible_packages`
- 最新验证基线：
  - `python3 -m unittest discover -s tests`：`227` 个测试通过
  - `python3 -m py_compile $(find src -name "*.py")`：通过
  - `PYTHONPATH=src python3 -m futures_workflow validate --date 2026-04-16`：成功
  - `PYTHONPATH=src python3 -m futures_workflow validate-platform-metadata --date 2026-04-25`：成功
  - `PYTHONPATH=src python3 -m futures_workflow environment-check`：成功
  - `PYTHONPATH=src python3 -m futures_workflow build-db`：成功，当前 DuckDB `dataset_count = 107`
  - GUI smoke：`/ /crawl /history /quality /strategies /factor-lab /portfolio /projects /data-map /lineage /scheduler /reports /knowledge /api/summary.json /healthz` 全部 `200 OK`
- 新增链路验收结果：
  - `inventory-build --date latest`：成功，`dataset_inventory = 107` 行，`dataset_field_profile = 1918` 行
  - `knowledge-build --date latest`：成功，`knowledge_index = 148` 行
  - `sla-check --date latest`：成功，`dataset_sla_rules = 107` 行，`sla_violations = 20` 行
  - `feature-run --dataset daily_ohlcv`：成功，`ml_feature_store = 274370` 行
  - `ml-benchmark --models linear_regression,ridge,lasso,random_forest,xgboost,lightgbm,catboost,svm,mlp`：成功，`ml_benchmarks = 9` 行
  - `ml-validate --template ridge`：成功，`ml_validation_folds = 3` 行，`ml_classification_results = 1` 行
  - `factor-experiment / parameter-scan / strategy-leaderboard`：成功
  - `portfolio-run / scenario-sim`：成功
  - `project-create / project-run / package-export / lineage-build`：成功
- 新增质量规则：
  - Feature Store 重复运行应保持同一窗口同一特征幂等，不生成重复键。
  - Walk-forward validation 不允许穿越未来；fold 必须记录 `train_start/train_end/test_start/test_end`。
  - 高级模型缺依赖时不能静默跳过；当前用可运行 adapter 或本地 sklearn 实现保持 CLI/GUI/validation 链路可执行。
  - 研究项目与可复现包必须记录 `run_id / checksum / source_datasets / parameters`，便于血缘反查。

## 2026-04-25 最新验证快照

- 本轮大版本新增研究运营验证范围：
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
- 最新验证基线：
  - `python3 -m unittest discover -s tests`：`227` 个测试通过
  - `python3 -m py_compile $(find src -name "*.py")`：通过
  - `PYTHONPATH=src python3 -m futures_workflow validate --date 2026-04-16`：成功
  - `PYTHONPATH=src python3 -m futures_workflow validate-platform-metadata --date 2026-04-25`：成功
  - `PYTHONPATH=src python3 -m futures_workflow environment-check`：成功
  - `PYTHONPATH=src python3 -m futures_workflow build-db`：成功，当前 DuckDB `dataset_count = 107`
- 新增链路验收结果：
  - `research-run --date latest --dataset daily_ohlcv`：成功
  - `factor-run --start 2026-04-20 --end 2026-04-24 --factor momentum --dataset daily_ohlcv`：成功，`factor_signals` 产出 `6657` 行
  - `strategy-backtest --start 2026-04-20 --end 2026-04-24 --strategy momentum --initial-cash 1000000 --fee-bps 2 --dataset daily_ohlcv`：成功
  - `paper-sim --date latest --strategy momentum --initial-cash 1000000 --dataset daily_ohlcv`：成功
  - `quality-diagnose --date 2026-04-24`：成功，当前只保留 `info / warning`，无 `critical`
  - `scheduler-tick --schedule-id daily_quality_diagnose --one`：成功，`scheduler_runs` 产出 `1` 行
  - `report-generate --date 2026-04-25 --report-type comprehensive`：成功，生成 Markdown + HTML + SVG 图表附件
  - `algorithm-run --template black_scholes_price ...`：成功，生成 `algorithm_outputs / option_analytics`
  - `algorithm-run --template volume_turnover ...`：成功，生成扩展因子算法输出
  - `risk-run --template var_cvar ...`：成功，生成 `risk_metrics`
  - `portfolio-optimize --template risk_parity ...`：成功，生成 `portfolio_allocations`
  - `backtest-run --strategy momentum ...`：成功，生成净值曲线、持仓、交易和策略对比
  - `ml-run`：`linear_regression / ridge / lasso / pca / kmeans / random_forest / xgboost / regime_detection` 已完成 smoke，输出 `ml_model_runs / ml_predictions / ml_feature_importance / model_diagnostics`
  - `ml-run --tune`：Ridge 与 RandomForest 已完成真实本地数据 smoke，`model_diagnostics` 写入 `train_count / test_count / prediction_count / mae / rmse`，`best_params` 写入 `validation_r2`
  - `factor-performance --factor momentum ...`：成功，生成 `factor_performance`
  - `stress-test --template equity_down ...`：成功，生成 `stress_test_results`
  - `quality-score --date 2026-04-25`：成功，生成 `dataset_quality_scores`
  - `artifact-list --date 2026-04-25`：成功，可追溯 `report_artifacts / artifact_manifest`
- 新增质量规则：
  - 合法 `no_data / not_applicable` 只能作为 `info` 展示，不再误报为 `critical`
  - 外部阻塞与 `pending_retry` 作为 `warning`
  - schema 错误、raw 缺失、真实 `failed` 才作为 `critical`
  - 算法模板字段不足或参数不足必须输出 `not_applicable + reason`，不得写成假成功
  - 正式回测在无足够价格序列时必须输出 `not_applicable`，不得生成伪净值

## 2026-04-24 工程收口验证快照（历史基线）

- 当前工程收口口径已经固定：
  - `run_health.status` 反映 runtime 真状态
  - `run_health.engineering_status` 反映工程收口状态
- 最近一次完整验证基线：
  - `python3 -m unittest discover -s tests`：`215` 个测试通过
  - `PYTHONPATH=src python3 -m futures_workflow validate --date 2026-04-16`：成功
  - `PYTHONPATH=src python3 -m futures_workflow validate-platform-metadata --date 2026-04-24`：成功
  - `PYTHONPATH=src python3 -m futures_workflow environment-check`：成功
  - `PYTHONPATH=src python3 -m futures_workflow build-db`：成功，当前 DuckDB `dataset_count = 60`
- 最近一次 `regression-smoke --skip-build-db` 已真实落盘到 `state/regression_smoke.json`，并同步物化到 `run_health`：
  - `status = partial_success`
  - `engineering_status = success`
  - `issue_category_counts = {"result_chain_publication_lag": 1}`
  - `blocked_issues = ["options_exercise_results: missing exchanges [CFFEX] are pending official publication"]`
- 当前 broader audit / source health 验收结果：
  - `needs_repair_dates = []`
  - `source_health` 当前只剩一条 `blocked_issue`
  - 该阻塞必须是 `cffex.options_exercise_results / publication_lag`
- 最近一次真实 `pregrab-window` smoke：
  - `SHFE 2026-04-14..2026-04-21 trial = status=success, engineering_status=success`
  - `CFFEX 2026-04-17 trial = status=partial_success, engineering_status=success`
  - `publication_lag` 当前在预抓口径下被视为“外部阻塞已正确识别”，不会单独拖垮工程通过
- 二期首批历史化验证基线：
  - `state/window_runs.json` 已落地并被 GUI `/history` 读取
  - `run_history / coverage_history / source_health_history` 已进入 `validate-platform-metadata`
  - `2026-04-24` 的 `instrument_master missing_raw_paths` 已通过补回 `2026-04-15` 的 `CFFEX / CZCE` 官方 raw 修复完成

## Validation dimensions

Validation is not schema-only.

Current validation checks:
- CSV existence
- schema field order
- duplicate key detection
- missing raw path detection
- expected exchange coverage
- observed exchange coverage
- completeness status
- selection-match status
- `contracts_latest` source-trade-date consistency
- `master_data_completeness`
- `result_chain_semantics_ok`
- `contracts_latest_consistency_ok`
- cached historical query/canonical reruns must remain provenance-consistent when raw sidecar metadata is present
- public snapshot datasets validate `schema_ok / row_count / missing_raw_paths` against their own state file `state/public_assets.json`
- public reference datasets validate `schema_ok / row_count / missing_raw_paths` against their own state file `state/public_references.json`
- public bond datasets validate `schema_ok / row_count / missing_raw_paths` against `state/public_bonds.json`
- crypto observation snapshot validates `schema_ok / row_count / missing_raw_paths` against `state/crypto_global.json`
- 对公开资产 / 参考 / 债券 / crypto，`success` 现在也要求“状态 + 文件存在 + schema 正确 + raw_path 完整”同时满足，不能只靠 state 文件
- 平台级 `validation_results` 现在会把 `master_data_completeness / result_chain_semantics_ok / contracts_latest_consistency_ok / blocked_issue_count / blocked_issues / no_data_reason / not_applicable_reason` 一起落表，供 GUI / DuckDB / export 浏览
- GUI 当前也会直接展示 `audit.issue_categories` 的结构化计数，方便把 `publication_lag / source_gap / historical_public_contract_gap` 与具体 issue 文本分开浏览
- GUI 当前也会直接展示 DuckDB manifest 摘要，便于对照 `build-db` 的最近构建结果与页面可浏览数据集
- GUI 当前还会根据当前预览数据集生成筛选枚举值，确保 `market / exchange / instrument_type` 这类字段可以直接选择而不是纯手输
- GUI 当前已拆成总览页 `/` 与独立抓取页 `/crawl`；所有“可点击抓取”动作都集中在 `/crawl`，避免浏览页误触发任务
- `/crawl` 当前还提供独立的“一键抓取当前已接入的全部数据”入口；它对应 latest-view 全量同步，不等于逐券全历史回补
- `validation_results` 现在不仅汇总 derivatives/public-assets/public-references/public-bonds/crypto，也会把平台统一表自身纳入 `scope=platform_metadata`，便于直接检查 `daily_ohlcv / fund_nav / reits_quotes / trading_calendar` 等平台派生表的质量状态
- 平台级 `source_health` 现在会把 `issue_category / blocked_reason / message` 一起落表，用来区分 healthy / partial / retry_or_error / no_data / not_applicable / blocked_issue
- 平台级派生表 `bond_master / bond_quotes / fx_quotes / commodity_spot_quotes / crypto_global_quotes / daily_ohlcv / fund_nav / reits_quotes / trading_calendar / yield_curves / run_history / coverage_history / source_health_history` 现在也进入 `validate-platform-metadata` 范围；要求 `schema_ok=true` 且 `missing_raw_paths=[]`
- 逐交易所窗口预抓现在也有正式验证维度：
  - `status`
  - `engineering_status`
  - `issue_category_counts`
  - `blocked_issues`
  - `cleanup_status`
  - 以及逐日 `success / no_data / not_applicable / blocked_external / failed` 计数
- GUI 中的“点击抓取成功”不等价于“所有源所有日期都 100% 成功”；当前仍需诚实保留 `cffex.options_exercise_results / publication_lag` 这一外部阻塞
- GUI 二期页面也已纳入 smoke 口径：
  - `/history` 必须能读取最近 `window_runs` 摘要
  - `/quality` 必须能读取最近 `run_history / coverage_history / source_health_history`

## Completeness rules

### Canonical runs
- outputs must cover all applicable expected exchanges for the dataset scope
- filtered/truncated coverage is invalid even if schema is correct

### Query runs
- outputs must only contain the selected scope
- expected exchanges are derived from the filtered applicable venue set

## `no_data` rules

- quote datasets:
  - `no_data` is only valid when the applicable source genuinely has no published quote data for that date
  - if applicable contracts are discovered but priced rows cannot be materialized, the state must remain `pending_retry` / `failed`, not degrade to `no_data`
- result datasets:
  - empty CSV with headers is valid when the semantic status is `no_data`
  - result datasets may have non-empty rows for only a subset of exchanges on the same date, as long as the remaining applicable exchanges are honestly recorded as `no_data` / `pending_retry` / `not_applicable`
  - generic official result collectors hit network/connection errors must remain `pending_retry`, not degrade into `no_data`
- pre-launch option dates:
  - must be treated as `not_applicable`, not `no_data`

## Duplicate key rules

- quote and contract/result tables use contract-oriented keys
- `options_chain_matrix` uses:
  - `trade_date + exchange + underlying_contract + expire_date + strike_price`
- `underlying_derivatives_summary` uses:
  - `trade_date + exchange + underlying_contract`

## Audit and rebuild rules

- canonical audit compares current canonical outputs against expected exchange coverage
- audit 结果现在拆成两类：
  - `issues`：真正待修的 schema / 覆盖 / 缺文件问题
  - `blocked_issues`：已经明确归因为公开源不可得、且不应再伪装成 success 的已解释阻塞
- `audit --all` 现在还会聚合 `issue_category_counts`，当前分类至少包括：
  - `result_chain_publication_lag`
  - `result_chain_source_gap`
  - `historical_public_contract_gap`
  - `coverage_gap`
  - `schema_mismatch`
  - `missing_csv`
- 对结果链数据集：
  - “官方结果端点尚未配置”与“官方结果表当日明确未发布”都不应再被误判为 canonical 污染
  - 前者进入 `blocked_issues`，后者保持合法 `no_data`
  - 若官方端点返回 HTML 错误页、空内容或其他无法确认“确无结果”的响应，必须保持 `pending_retry`
  - 这类场景可以进入 `blocked_issues`，但不能压成 `no_data`
- polluted canonical dates are rebuilt from preserved raw payloads when available
- repaired dates must be recorded in `STATUS.md`
- repair tooling must not rewrite canonical state from archive-only success semantics
- `contracts_latest` is not rebuilt from arbitrary partial days; it must be anchored to the latest successful canonical all-scope snapshot
- 对 `2021-04-16` 这类历史代表日，如果缺口已经被明确收敛为“公开历史 contract source 不可得”，audit 应写入 `blocked_issues` 而不是继续保留模糊 `needs_repair`
- `repair --date <trade_date>` 现在会对显式传入日期执行基于本地 raw/summary 的强制重建，用于刷新结果链/状态语义升级后的 canonical day
- 对结果链数据集，`repair` 现在允许“无结果 raw 但有主行情行”的离线 summary 刷新：如果本地已能证明当日无到期/无交割，则应写成合法 `no_data`，而不是继续保留过时的 endpoint 配置文案
- 结果链离线重建现在也必须容忍历史缓存编码差异：非 UTF-8 文本 raw 与带 `&nbsp;` 的旧 XML/HTML 页面不能再让 repair 失败
- 当前最近一次完整 `regression-smoke` 已验证：
  - `2010 / 2015 / 2021 / 2026` 代表日期全部 `success`
  - `audit.needs_repair_dates = []`
  - 连续窗口 `latest_7_trading_days / latest_1m_trading_days / latest_1y_monthly_sample / latest_3y_quarterly_sample` 已正式进入回归摘要与 `run_health`
  - `regression-smoke` 现在会按交易日日历生成窗口目标集，并在缺失 canonical 样本时自动先执行 canonical all-scope 补样，再做 validate
  - `regression-smoke` / `state/regression_smoke.json` / `run_health` 现在会同时保留 `status` 与 `engineering_status`，用于区分 runtime 诚实状态与工程收口状态
  - 最近一次 `--skip-build-db` 仍会诚实保留 `2026-04-17` 的 `result_chain_publication_lag = 1`
  - `build_db.dataset_count = 60`
  - 当前结果链首批 official adapter 已覆盖 `SHFE / INE / GFEX / DCE` 的期货交割结果，以及 `CFFEX / DCE / SSE / SZSE` 的期权行权结果；未接齐交易所仍必须诚实保留 `pending_retry / blocked_issue / no_data`
- `regression-smoke` 最近一次回归摘要现会持久化到 `state/regression_smoke.json`，供 GUI 和后续审计直接复用
- GUI 现会直接展示 source catalog 与 `source_type` 统计，便于把源注册、source health 和 blocked issues 放到一个只读面板里联查
- GUI 现还会直接展示最近的 `source_health` 异常源明细，帮助把 `pending_retry / blocked_issue / no_data` 的来源与原因对齐到具体 source_id
- 平台元数据现已新增 `run_health`，用于把最近一次 `regression-smoke` 的运行状态、工程收口状态、代表日期结果、连续窗口结果和阻塞类别落成正式派生表
- `run_health` 当前已进入 DuckDB manifest，可通过 GUI / export / DuckDB 一起联查最近一次回归状态
- 平台元数据现已新增 `asset_coverage`，用于把各资产族的最新运行状态、覆盖比例和缺失数据集物化成正式派生表
- 平台元数据现已新增 `source_type_overview`，用于把各类 source_type 的运行状态、源数量、数据集数量与 blocked issue 数量物化成正式派生表
- 平台元数据现已新增 `issue_category_overview`，用于把 `source_health` 中的 `healthy / no_data / retry_or_error / blocked_issue` 问题类别聚合成正式派生表
- GUI 现还会直接展示 `source_type_overview / issue_category_overview`，把 source catalog 的静态统计、真实运行状态和问题类别聚合到同一张只读表里联查

## Request-behavior rules

- weak online sources should prefer historical raw cache over repeated live requests for already-collected past dates
- pacing / jitter / protective-block backoff are operational safeguards, not success semantics
- a source returning a protective block should stop fan-out and fall back to cached raw when available rather than continuing burst requests
- when a venue adds an official near-current quote path, validation should preserve the true `source_type` and must not let cached fallback provenance masquerade as official
- cached option symbol metadata / expire-day lookups are only discovery aids; they do not by themselves make a quote date `success` unless priced rows are actually materialized

## Pregrab rules

- `pregrab-window` 固定按交易日日历展开，并对每个交易日执行 `fetch-date --instrument-group all` + `validate`
- 逐交易所窗口预抓允许两层结论同时存在：
  - `status`：runtime 真状态
  - `engineering_status`：工程通过状态
- 预抓通过口径固定为：
  - 每个交易日最终只能是 `success / no_data / not_applicable`
  - 或唯一例外是已被明确识别并归类的外部阻塞 `blocked_issue`
- `publication_lag`、明确 HTML 错页等外部阻塞必须进入：
  - `issue_category_counts`
  - `blocked_issues`
  - `blocked_external_count`
  但不应再被误判成内部 schema/completeness 失败
- `trial` 模式必须在隔离 storage root 下运行，结束后自动清理临时 `data/state/db/exports`；正式持久化对象只允许是 `state/pregrab_runs.json` 摘要

## Window run rules

- 多资产历史窗口同步统一写入 `state/window_runs.json`
- 当前 CLI 已支持：
  - `sync-public-assets --start --end`
  - `sync-public-references --start --end`
  - `sync-public-bonds --start --end`
  - `sync-crypto-observation --start --end`
- `window_runs` 当前至少记录：
  - `status`
  - `engineering_status`
  - `window_start / window_end`
  - `issue_category_counts`
  - `blocked_issues`
  - `date_counts`
  - `dataset_results`

## Environment health rules

- `environment-check` 当前会检查：
  - project/data/state/checkpoint 目录
  - DuckDB 目录可写性
  - Playwright runtime
  - `DCE / SSE / SZSE / Eastmoney / CoinGecko` 的 DNS 可达性
- 环境检查结果当前是独立状态，不会伪装成数据抓取成功
- `/crawl` 与 `/quality` 都会读取最近一次环境检查摘要

## Canonical/query rules

- filtered runs are query runs
- query validation reads query state under `state/query_runs/{selection_id}.json`
- canonical validation reads `state/checkpoints.json`
- `contracts_latest.csv` is only updated by successful canonical all-scope runs
- when validating an older canonical date, `contracts_latest` is checked against the latest successful canonical all-scope source date rather than the requested historical date itself

## Public snapshot rules

- public snapshot datasets are currently independent of derivatives canonical/query semantics
- they still must preserve provenance and raw-path traceability
- latest-only snapshot sources may legitimately return `not_applicable` for uncached historical dates if that collector does not support historical backfill yet
- 某个 snapshot collector 若 primary 源在当前网络环境下偶发失败，应优先尝试已验证的公开 fallback；只有 primary/fallback 都不可得时，才记 `pending_retry`
- 某个 snapshot collector 若源站语义上确实无数据，应写 header-only CSV 并保留 `source_url / raw_path / source_type`，不能把“合法空表”误做成缺文件
- `sge_spot_daily_quotes` 当前同样保留为 opt-in：collector 已真实实现，但默认稳定 bundle 仍以证券/基金/REITs/可转债为主
- `carbon_market_snapshot` 当前属于 as-of 快照：文件分区日是请求日，但每个地区的单行 `trade_date` 允许是最近一个不晚于请求日的实际成交日

## Public reference rules

- public reference datasets are also independent of derivatives canonical/query semantics
- `latest` on weekend may resolve to the previous weekday when the source is a weekday reference table
- mixed `success + no_data` across public reference families must be recorded as `partial_success`, not collapsed into `no_data`
- GUI should prefer the latest successful non-empty reference output for display cards, while state still preserves explicit `no_data` dates honestly
- 快照型参考表不一定带源站日期列；例如 `fx_spot_quotes` 当前属于“按请求日落地”的即期报价快照，因此 validation 只要求 schema/provenance 完整，不强制要求源 payload 自带 `日期`
- `fx_pair_quotes / fx_swap_quotes` 当前同样属于“按请求日落地”的外汇快照，因此 validation 重点是 schema/provenance 完整，不强制要求源 payload 自带统一交易日列
- `fx_c_swap_curve` 当前属于“曲线 as-of 快照”语义：文件分区日是请求日，但单行 `trade_date` 允许来自源站 `curveTime`
- `rmb_middle_rates` 当前属于“历史中间价参考序列”语义：若请求日晚于公开可得历史上限，必须诚实返回 `no_data`，不能把缺少 current-live 样本误判为 `pending_retry`
- `reserve_reference_series` 当前属于“as-of 快照”语义：输出的是请求日之前最近一期已发布储备口径，因此单个输出文件内的 `trade_date` 可以早于文件分区日

## Public bond rules

- public bond datasets are independent of derivatives canonical/query semantics
- `yield_curve_points` can legitimately have more than one row per `trade_date`, because每个期限点位会展开成单独一行
- 若某个债券快照源当日连接异常，应记录 `pending_retry`，不能伪装成 `success`
- `bond_quotes` / `yield_curve_points` 的空表只在源站确无当日数据时允许记为 `no_data`
- `sse_bond_deal_summary / sse_bond_cash_summary` 属于摘要表，不沿用普通债券 quote schema，而是使用独立 summary schema

## Crypto observation rules

- crypto observation remains a separate global-observation family, not part of domestic canonical exchange markets
- historical uncached dates may legitimately return `not_applicable` while only latest snapshots are implemented
- GUI and docs must preserve the legal note; validation should not treat the presence of crypto data as proof of any domestic trading-service support
- `crypto_daily_quotes` 当前若 CoinGecko history 端点命中公开限流，可诚实回退到同日 snapshot raw，但必须保留真实 `source_url / source_type / raw_path`
- `crypto_derivatives_public` 当前若 CoinGecko public derivatives 命中 `HTTP 429`，必须继续尝试同次 `CME` 比特币公开报告与 `OKX` 公共永续行情；只有三条公开链路都不可得时，才记 `pending_retry`
- `crypto_bitcoin_holdings_public` 当前属于 latest/cached 公开观察表：分区日是本地采集日，真实源站日期必须保留在 `source_query_date`，不能伪装成同日全球市场成交日期
- `crypto_cme_bitcoin_report` 当前属于历史公开报告表：若指定报告日返回空表，应记为 `no_data`；若网络异常才记 `pending_retry`
