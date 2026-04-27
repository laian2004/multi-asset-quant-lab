# PLANS.md

# 2026-04-27 研究项目系统、实验对比与报告解读执行结果

- 已按“继续扩”的方向把项目系统补成闭环，而不是新增孤立页面：
  - `project-run` 自动执行因子实验、正式回测、策略排行榜、报告和复现包。
  - `report-generate` 自动生成 `report_insights / recommendation_items`。
  - `/projects` 和 `/reports` 直接展示自动解读、下一步建议和实验对比。
- 这条主线把“研究项目模板 -> 实验对比 -> 报告解读 -> 复现包”打通，适合作为后续 Agent 自动研究流的默认产物链路。
- 后续可以继续增强：
  - 项目模板库细分为 ETF 动量、期货期限结构、债券曲线、多资产风险平价、ML Benchmark 等。
  - 项目运行支持多模板批量扫描，并把结果自动写入策略/模型排行榜。
  - 报告解读进一步接入更丰富的图表和自然语言摘要。

# 2026-04-27 产品内插件化与 Agent 工作台执行结果

- 本轮计划已按“产品内部插件化，不做外部 Codex 插件包”的方向落地。
- 已完成：
  - 内部 `PluginRegistry`，统一声明 `plugin_id / category / label / inputs / outputs / required_datasets / risk_level / supports_dry_run / produces_artifacts`。
  - `AgentOrchestrator`，支持先生成计划与风险说明，再由用户确认执行长任务。
  - GUI `/agent` 工作台，展示任务、步骤、质量门控、队列、日志、插件清单、研究记忆、报告解读、建议、模型注册和漂移。
  - CLI：`agent-plan / agent-run / agent-status / agent-cancel / agent-retry / plugin-list / plugin-run / quality-gate / memory-search / model-registry-build / model-drift-check`。
  - 18 个新增 Agent/插件数据集进入平台元数据和 DuckDB；当前 `build-db dataset_count = 125`。
- 下一步如果继续增强，重点不再是“有没有 Agent 页面”，而是增强 Agent 的自然语言目标解析、更多插件适配器、任务并发/暂停恢复、更细的成本/耗时估计和更强的报告自动解读。

## 2026-04-26 Pro Max 全量必做执行结果

- Pro Max 计划中的新增模块已经按“全部必做”口径落地，不再标记 optional：
  - 数据资产地图、字段画像、数据血缘、SLA 检查、知识库索引。
  - Feature Store、ML Benchmark、时间序列验证、分类任务。
  - 因子实验、参数扫描、策略排行榜。
  - 组合研究、情景推演、研究项目、项目运行、可复现包。
  - GUI 新页面 `/data-map /lineage /factor-lab /portfolio /projects /knowledge`。
- 新增 CLI 已落地：
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
- 当前验收：
  - 单元测试：`227` 个通过
  - 编译：通过
  - 主干校验：`2026-04-16 success`
  - 平台元数据校验：`2026-04-25 success`
  - 环境检查：`success`
  - DuckDB：`dataset_count = 107`
  - GUI smoke：15 个入口全部 `200 OK`
- 后续增量建议不再是“补齐 Pro Max 计划”，而是继续做更深体验和性能：
  - 把 `/api/summary.json` 拆成分页接口，减少一次性返回体积。
  - 将 `ml_feature_store` 大表查询默认切到 DuckDB 分页。
  - 增加图表缓存和前端懒加载。
  - 如本机安装原生 LightGBM/CatBoost，再把当前 sklearn adapter 替换为原生 estimator。

## 2026-04-25 大版本扩展执行结果

- 本轮选择的 `1 / 2 / 3 / 4 / 6 / 7` 已完成首版落地，不包含第 5 项 API 服务层。
- 已交付范围：
  - 研究分析层：`research-run`、`research_metrics`、GUI `/history` 延展入口。
  - 因子与模拟交易层：`factor-run`、`strategy-backtest`、`paper-sim`、`factor_signals`、`strategy_backtests`、`paper_portfolios`、GUI `/strategies`。
  - 质量运营层：`quality-diagnose`、`quality_diagnostics`、GUI `/quality` 诊断摘要。
  - 本地任务调度层：`scheduler-tick`、`state/schedules.json`、`state/scheduler_runs.json`、`scheduler_runs`、GUI `/scheduler`。
  - Notebook 工作区：`notebooks/` 与 `examples/research_helpers.py`。
  - 报告与告警摘要：`report-generate`、`research_reports`、`reports/YYYY-MM-DD/*.md|*.html`、GUI `/reports`。
- 当前验收：
  - 单元测试：`227` 个通过
  - 平台元数据校验：`2026-04-25 success`
  - DuckDB：`dataset_count = 107`
  - 环境检查：`success / success`
- 后续若继续扩展，优先级建议：
  - 把 `/history` 的图表能力做深
  - 增加更多策略模板和组合对比
  - 把调度接到系统 cron 或桌面 automation
  - 把报告增加图表与趋势对比
  - 最后再考虑 API 服务层

## 2026-04-24 二期开工状态（历史基线）

- 一期“工程 `100%` 收口”结论保持不变，不回退。
- 二期当前已正式落地第一批底座能力：
  - GUI 新页面：`/history /quality`
  - 历史窗口状态：`state/window_runs.json`
  - 平台历史派生表：`run_history / coverage_history / source_health_history`
  - CLI 历史窗口参数：`sync-public-assets|references|bonds|crypto --start --end`
  - 回归 profile：`regression-smoke --profile core|phase2`
  - 环境检查：`environment-check`
- 当前真实验证基线：
  - `python3 -m unittest discover -s tests`：`215` 个测试通过
  - `PYTHONPATH=src python3 -m futures_workflow validate-platform-metadata --date 2026-04-24`：成功
  - `PYTHONPATH=src python3 -m futures_workflow build-db`：成功，DuckDB `dataset_count = 60`

## 2026-04-22 当前收口结论

- 当前计划已经从“继续补大功能块”切换到“工程口径稳定收口”。
- 本轮 done 定义已经固定为：
  - 工程 `100%`
  - runtime 诚实保留唯一外部阻塞 `cffex.options_exercise_results / publication_lag`
- 当前真实状态：
  - `regression-smoke`、`state/regression_smoke.json`、`run_health`、GUI 已全部对齐
  - `status = partial_success`
  - `engineering_status = success`
  - `blocked_issues = ["options_exercise_results: missing exchanges [CFFEX] are pending official publication"]`
  - `source_health` 当前只剩一个 `blocked_issue`
  - `asset_coverage.exchange_derivatives_cn` 已固定为 `engineering_status=done`、`runtime_status=pending_retry`
  - `pregrab-window` 与 `state/pregrab_runs.json` 已落地，GUI 已可直接发起逐交易所窗口预抓
  - `trial` 预抓已支持隔离 storage root + 自动清理，`production` 预抓则保留正式输出
- 因此下面各 phase 的“Remaining scope”仅表示未来扩展方向，不再代表本轮工程未完成。

## Current phased plan

### Phase A1
Stabilize the existing on-exchange derivatives platform core.

Deliverables:
- canonical/query output isolation
- query-specific state and manifests
- completeness-aware validation
- canonical audit and repair flow
- rebuild polluted canonical dates
- protect `contracts_latest.csv` from query runs

Acceptance:
- filtered runs never overwrite canonical outputs
- `validate` can detect truncated exchange coverage
- polluted canonical sample dates can be audited and rebuilt
- canonical state and query state are separated

### Phase A2
Formalize master-data and result-chain semantics.

Current status:
- `contracts_snapshot` has moved to master-data-first semantics
- `contracts_latest` now updates only after successful canonical all-scope runs
- `options_exercise_results` is no longer quote-derived
- `futures_delivery_results` is no longer quote-derived

Remaining scope:
- add venue-by-venue official result endpoints
- `futures_delivery_results` 已完成首批落地：`SHFE / INE / GFEX / DCE` 官方交割结果端点已接入，下一步继续扩到 `CFFEX / CZCE`
- `options_exercise_results` 已接入 `CFFEX` 官方月报 PDF 聚合结果链与 `SSE` 官方“行权交收信息”接口，下一步继续扩到 `SHFE / CZCE / DCE / GFEX / SZSE`
- `options_exercise_results` 已接入 `CFFEX` 官方月报 PDF 聚合结果链、`DCE` 官方月度市场报告 PDF、`SSE` 官方“行权交收信息”接口，以及 `SZSE` 官方“行权交收统计”接口；下一步继续扩到 `SHFE / CZCE / GFEX`
- `CFFEX` 最近日期月报端点当前仍可能返回 HTML 错误页；这块已收紧为 `pending_retry / blocked_issue`，但端点稳定性仍需继续跟踪
- enrich official master-data field coverage beyond current blanks

### Phase A3
Harden remaining weak on-exchange options venues.

Current status:
- same-day cached reruns for validated dates are stable on `DCE / SSE / SZSE`
- historical-date cache-first is now enabled for `DCE / SSE / SZSE` option quote paths and for `SSE / SZSE` option master-data paths
- weak online hosts now use pacing / jitter / protective-block backoff
- `SSE` recent/current options quotes now have an official path on top of the existing fallback structure
- `SZSE` recent historical dates now use “目标交易日主数据 + 在线日线”发现路径，不再误用 current contract 表
- `SZSE` historical discovery now also has a configured-underlyings fallback when official summary and nearby cached underlyings are both unavailable
- `SSE / SZSE` option numeric-symbol metadata and expire-day lookups now persist into independent caches so historical reruns can reuse them without live re-discovery
- `SSE / SZSE` option sources now also consult nearby cached `contracts_snapshot` raw payloads as an auxiliary discovery layer
- `SZSE` nearby `contracts_snapshot` 命中的 `symbol -> contract/strike/expire` 现在也会自动回填到本地 metadata cache，继续收缩历史重跑对 live symbol metadata 的依赖
- `SZSE` 历史 symbol discovery 现在还会从本地 `equity_options_history` 中筛出“目标交易日确实有日线”的 numeric symbol，并按保守 probe 上限逐步积累 metadata cache
- `SZSE` 历史 symbol discovery 现在还会优先尝试官方 `option_drhy + txtQueryDate` 历史分页；只要能取到 dated contract rows，就会先回填 `equity_options_metadata`，再去拼 history dayline
- `DCE` recent latest-completed trade date now has a contract-table snapshot fallback path, and contract-history cache has been added for historical backfill reuse
- metadata-only option success is blocked
- option launch-date gating is now explicit for historical years

Remaining scope:
- DCE older uncached nearby-date stability
- SZSE broader uncached nearby-date stability and deeper historical symbol-metadata accumulation
- SSE options older uncached historical-date hardening beyond nearby `contracts_snapshot` reuse

### Phase B1
Complete the on-exchange derivatives platform.

Current status:
- representative dates `2010 / 2015 / 2021 / 2026` have been re-run under tightened semantics
- `2026-04-16` canonical all-scope validate is fully green
- `2026-04-17` canonical all-scope fetch + validate is fully green
- `2026-04-14` canonical all-scope fetch + validate is now fully green
- short all-scope backfill on `2026-04-14..2026-04-17` is now green end-to-end
- `sync-daily --date latest` futures smoke is green

Remaining scope:
- representative year backfills
- coherent backfill / sync / validate behavior
- `regression-smoke` 已作为新的 B 收口入口落地，会把代表日期 `validate`、`audit --all`、平台元数据同步/校验，以及可选 `build-db / GUI smoke` 串成一条命令
- `regression-smoke` 最近一次运行摘要现会持久化到 `state/regression_smoke.json`，供 GUI 与后续审计直接复用
- `regression-smoke` 已继续扩成“代表日期 + 连续窗口”收口入口，当前会额外固化 `latest_7_trading_days / latest_1m_trading_days / latest_1y_monthly_sample / latest_3y_quarterly_sample`
- `regression-smoke` 现在会按交易日日历生成窗口目标集，并在缺失 canonical 样本时自动执行 canonical all-scope 补样
- `regression-smoke` 现已拆成“运行状态”和“工程收口状态”双口径，便于在只剩外部 `publication_lag / source_gap` 时保持 runtime 诚实，同时单独判断工程收口
- `asset_coverage` 现已成为正式平台派生表，下一步继续用它辅助收口剩余官方结果链缺口与资产族覆盖深度
- `source_type_overview` 现已成为正式平台派生表，GUI / DuckDB / export 可直接查看各类 source_type 的运行总览
- `issue_category_overview` 现已成为正式平台派生表，GUI / DuckDB / export 可直接查看 `healthy / no_data / retry_or_error / blocked_issue` 等问题类别的运行总览
- reproducible outputs across datasets
- broader `audit --all / repair --all` based repair loops over the existing canonical date set
  - 当前现状：已有 canonical 日期已全部做到 `needs_repair = false`
  - `repair --date <trade_date>` 现已支持显式日期强制重建，用于状态语义升级后刷新 canonical day
  - `repair` 已新增离线结果链 summary refresh：无结果 raw 但主行情可证明“无到期结果”时，也会用当前语义刷新旧 checkpoint
  - 最近一次完整 `regression-smoke` 已为 `partial_success`
  - `2010 / 2015 / 2021 / 2026` 当前全部通过
  - 但最近一次 `--skip-build-db` 仍会诚实保留 `2026-04-17` 的 `result_chain_publication_lag = 1`

### Platform shell / GUI
Current status:
- multi-asset registry shell exists and is now visible in the local GUI
- local GUI can browse canonical/query outputs, dataset health, recent runs, and preview CSV data without mutating data state
- local GUI can now launch real crawl actions from a dedicated `/crawl` workspace instead of staying read-only
- local GUI now also exposes a dedicated “一键抓取当前已接入的全部数据” entry for the current latest-view full sync path
- local GUI can now launch exchange-window pregrab jobs with `production / trial` semantics and persist summaries into `state/pregrab_runs.json`
- local GUI can now also browse the latest A 股 / ETF / REITs public snapshot outputs
- local GUI can now also browse the latest人民币外汇参考价 / Shibor / 上海金银基准价参考表输出
- local GUI can now also browse the latest全球加密资产观察快照，并展示 legal note
- local GUI now has first-pass common filters for `asset_family / market / exchange / instrument_type / symbol / contract / currency / tenor`, and `export` can reuse those filters through `--filter key=value`
- local GUI filter controls are now dataset-driven: low-cardinality fields render as selects, while `symbol / contract` render with suggestions instead of raw free-text only
- `pregrab-window` 当前已完成第一版工程收口：
  - 默认范围固定为 `instrument_group=all`
  - 支持交易所多选与窗口预设
  - 支持 `runtime status + engineering status`
  - `CFFEX publication_lag` 会在预抓摘要中按外部阻塞展示，但不单独拖垮工程通过
  - 总览 `/` 与抓取页 `/crawl` 已完成职责拆分：前者只读浏览，后者执行抓取与预抓

Remaining scope:
- expand the GUI from derivatives-first browsing to future non-derivatives datasets as those collectors land
- keep the GUI honest about implemented vs planned family status

### Phase C1 and later
Add a separate interbank / OTC-visible derivatives module after Phase A and B are stable.

Current status:
- public-asset snapshot collectors for `equities_spot_snapshot / etf_spot_snapshot / reits_spot_snapshot` have landed as the first non-derivatives slice
- public-asset snapshot collectors for `bse_equities_spot_snapshot / convertible_bond_spot_snapshot` have continued that first slice
- public-asset snapshot collectors for `open_fund_nav_snapshot / money_market_fund_snapshot` have extended the funds slice into real default datasets
- public precious-metals slice has now landed `sge_spot_daily_quotes` as an opt-in real collector
- public commodity/energy slice has now landed `carbon_market_snapshot` as the first真实国内碳市场 collector
- public-reference collectors for `fx_reference_rates / money_market_rates / precious_metal_reference_quotes` have landed as the second non-derivatives slice
- public-reference collectors for `fx_reference_rates / fx_spot_quotes / money_market_rates / loan_prime_rates / repo_reference_rates / precious_metal_reference_quotes` have landed as the second non-derivatives slice
- public-reference collectors for `reserve_reference_series` have further extended that slice into公开储备序列
- public-reference collectors for `fx_pair_quotes / fx_swap_quotes / fx_c_swap_curve` have extended the FX slice into多币对即期、远掉与曲线观察
- public-reference collectors for `cn_us_treasury_yields` have now landed real live output as part of the cross-market rates slice, and the dataset is visible in DuckDB / GUI / export
- public-reference collectors for `rmb_middle_rates` have now landed as the人民币汇率中间价切片，并以 `2021-05-13` 作为当前公开可得历史上限、对更晚日期诚实返回 `no_data`
- public-bond collectors for `interbank_bond_deal_snapshot / interbank_bond_quote_snapshot / yield_curve_points` have landed as the third non-derivatives slice
- public-bond collectors for `sse_bond_deal_summary / sse_bond_cash_summary` have extended the exchange-bond slice
- crypto observation collectors for `crypto_global_snapshot / crypto_assets / crypto_daily_quotes / crypto_derivatives_public / crypto_bitcoin_holdings_public / crypto_cme_bitcoin_report` have landed as the global-observation slice, and `crypto_derivatives_public` 已升级为 `CoinGecko -> CME -> OKX` 的诚实三级公开链路
- platform metadata derived datasets `instrument_master / validation_results / source_health` have landed and are visible in GUI / DuckDB / export
- platform metadata derived datasets have expanded further: `daily_ohlcv / fund_nav / reits_quotes / trading_calendar / yield_curves` are now real normalized tables and have entered GUI / DuckDB / export
- quality surfacing has tightened further: `validation_results` now carries `blocked_issue_count / blocked_issues`, `source_health` carries `issue_category / blocked_reason`, and GUI shows current-date `issues / blocked_issues`
- quality surfacing has tightened further again: `source_type_overview` now carries per-source-type source_count/dataset_count/success/non_success/blocked_issue_count and is visible in GUI / DuckDB / export
- quality surfacing has tightened further again: `issue_category_overview` now carries per-issue-category source_count/dataset_count/blocked_issue_count/status_counts/source_type_counts and is visible in GUI / DuckDB / export
- platform-derived unified views `bond_master / bond_quotes / fx_quotes / commodity_spot_quotes / crypto_global_quotes` have now landed, are visible in GUI preview options, and are indexed by DuckDB

Remaining scope:
- add exchange-bond / bond-master / deeper FX / deeper precious-metals / broader commodity-energy / richer crypto-observation collectors
- continue extending official result-chain endpoints for `futures_delivery_results / options_exercise_results`
  - 当前校验口径已经收紧：结果链端点未配置齐不会再被压成“假 success”
- keep `build-db / export / list-sources / audit / repair / serve-gui` coherent with the growing normalized dataset set
- keep tightening older `SZSE` historical metadata coverage with bounded live probing and contract-snapshot seeding, while preserving honest `pending_retry / blocked_issue` semantics if public sources still remain insufficient
- use `audit --all` issue categories to separate true canonical corruption from future `result_chain_publication_lag / result_chain_source_gap` and `historical_public_contract_gap`
- decide which of those should become snapshot datasets versus historical/reference datasets
- keep `sge_spot_daily_quotes` as an opt-in collector until it is stable enough for the default bundle

## Immediate next milestone

### Phase 2.1 衍生品深历史
- keep extending historical/representative-year windows beyond the now-green `2026-04-14..2026-04-17`
- harden older uncached-date behavior for `DCE / SSE / SZSE` options
- extend result-chain official adapters venue by venue while preserving honest `blocked_issue`

### Phase 2.2 多资产历史化
- expand `sync-public-assets|references|bonds|crypto --start --end` from first-pass date windows into more stable recent-1y / representative-3y collection
- keep extending real Phase C collectors while preserving A/B semantics; next likely slices are exchange-bond snapshots, richer precious-metals spot tables, and deeper crypto reference/history tables

### Phase 2.3 GUI 历史研究与质量运营
- keep enriching `/history` with dataset/date-range preview and export ergonomics
- keep enriching `/quality` with trend cards over `run_history / coverage_history / source_health_history`

### Phase 2.4 环境与回归闭环
- make `environment-check` part of regular `/crawl` and phase2 regression workflows
- keep `state/window_runs.json` coherent with GUI, DuckDB and platform metadata
