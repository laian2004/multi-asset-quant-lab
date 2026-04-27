# SOURCES.md

# 2026-04-27 Agent 插件源口径

- 本轮新增能力全部是平台内部 `derived` source，不新增外部付费源、登录源、验证码源，也不改变抓取层 `official > official_browser_bootstrap > fallback_online` 的优先级。
- Agent/插件相关 source_id 统一采用 `platform.*` 口径，例如 `platform.plugin_registry`、`platform.plugin_run`、`platform.agent`、`platform.quality_gate`、`platform.research_memory`、`platform.model_registry`、`platform.model_drift`。
- `plugin_registry` 是产品内插件白名单，不代表外部数据源；它只把已有数据、质量、算法、ML、回测、报告、血缘和项目能力统一编排。
- 现有唯一允许的外部 runtime 阻塞仍是 `cffex.options_exercise_results / publication_lag`，Agent 层只负责展示和传播该事实，不会把外部阻塞伪装成成功。

## 2026-04-26 Pro Max 源状态结论

- Pro Max 新增能力全部是本地 `derived` source，不新增付费源、登录源、验证码源，也不改变 canonical 抓取优先级。
- 新增 derived source families：
  - `platform.dataset_inventory`
  - `platform.dataset_field_profile`
  - `platform.data_lineage`
  - `platform.dataset_sla_rules`
  - `platform.sla_violations`
  - `platform.knowledge_index`
  - `platform.ml_feature_store`
  - `platform.ml_benchmarks`
  - `platform.ml_validation_folds`
  - `platform.ml_classification_results`
  - `platform.factor_experiments`
  - `platform.parameter_scans`
  - `platform.strategy_leaderboard`
  - `platform.portfolio_experiments`
  - `platform.scenario_simulations`
  - `platform.research_projects`
  - `platform.project_runs`
  - `platform.reproducible_packages`
- 这些 source 的输入只来自：
  - 本地 normalized CSV
  - 本地 DuckDB
  - 本地 state 文件
  - 本地 reports / exports artifact
- ML Benchmark 中的 `lightgbm / catboost` 当前使用本地 sklearn 兼容适配器保证可运行；source catalog 仍标记为本地研究派生产物，不声称来自 LightGBM/CatBoost 官方服务或外部数据源。
- 当前唯一允许保留的外部 runtime 阻塞仍是 `cffex.options_exercise_results / publication_lag`，不因 Pro Max 研究层扩展而改变。

## 2026-04-25 当前源状态结论

- 新增研究运营层全部是 `derived` 来源，不新增付费源、登录源、验证码源：
  - `platform.research_metrics`
  - `platform.factor_signals`
  - `platform.strategy_backtests`
  - `platform.paper_portfolios`
  - `platform.quality_diagnostics`
  - `platform.scheduler`
  - `platform.research_reports`
  - `platform.algorithm_outputs`
  - `platform.option_analytics`
  - `platform.bond_analytics`
  - `platform.curve_analytics`
  - `platform.risk_metrics`
  - `platform.portfolio_allocations`
  - `platform.backtest_equity_curves`
  - `platform.backtest_positions`
  - `platform.backtest_trades`
  - `platform.strategy_comparisons`
  - `platform.anomaly_events`
  - `platform.ml_model_runs`
  - `platform.ml_predictions`
  - `platform.ml_feature_importance`
  - `platform.model_diagnostics`
  - `platform.backtest_input_quality`
  - `platform.experiment_runs`
  - `platform.factor_performance`
  - `platform.stress_test_results`
  - `platform.artifact_manifest`
  - `platform.dataset_quality_scores`
  - `platform.report_artifacts`
- 这些 derived source 的输入来自本地 DuckDB、normalized CSV 与 state 文件：
  - 不会修改 canonical 原始抓取语义
  - 不会把研究/策略结果伪装成官方市场数据
  - 不开放任意 Python 脚本执行，只运行 `AlgorithmRegistry` 白名单内置模板
  - ML 模型只读取本地 normalized / DuckDB 数据，当前覆盖线性回归、Ridge、Lasso、PCA、KMeans、随机森林、XGBoost 与 regime detection
  - 报告附件和 artifact manifest 只记录本地产物血缘，不新增外部数据源
  - 不连接真实交易账户
- 本轮没有改变 canonical source precedence：
  - `official > official_browser_bootstrap > fallback_online`
  - `fallback_archive` 仍只用于 audit / repair / deep-history 辅助
- 当前工程收口后，runtime 唯一允许保留的外部阻塞源仍是：
  - `source_id = cffex.options_exercise_results`
  - `source_type = official`
  - `issue_category = blocked_issue`
  - `issue_root_cause = publication_lag`
  - `last_status = pending_retry`

## 2026-04-24 工程收口源状态结论（历史基线）

- 当前工程收口后，平台只剩一个允许保留的外部阻塞源：
  - `source_id = cffex.options_exercise_results`
  - `source_type = official`
  - `issue_category = blocked_issue`
  - `issue_root_cause = publication_lag`
  - `last_status = pending_retry`
- 其余已经落地的数据源当前都已进入“已实现且可验证”的工程口径；即使 latest 某次因外部环境失败而触发 fallback，也必须继续保留真实 `source_id / source_url / source_type`。
- `exchange_derivatives_cn` 当前之所以仍是 runtime `pending_retry`，唯一原因就是上面这一条官方发布时间阻塞，而不是 collector / registry / GUI / DuckDB 未接通。
- GUI 当前会直接基于已落地数据集的真实列值生成 `market / exchange / instrument_type` 等筛选选项，避免用户在查看 source provenance 时只能手工输入。
- GUI 当前已把“抓取控制台 / 逐交易所预抓”拆到独立 `/crawl` 页面；因此总览页只读，抓取入口集中且不影响 provenance 展示
- GUI 二期已继续扩到 `/history /quality` 页面：
  - `/history` 读取 `window_runs` 与历史窗口输出
  - `/quality` 读取 `run_history / coverage_history / source_health_history` 与最近环境检查摘要
- `/crawl` 里的“一键抓取当前已接入的全部数据”会串行触发当前已接入 source families 的 latest-view 同步，但仍会诚实保留外部阻塞，不会把 `publication_lag` 伪装成成功
- GUI 当前还会把逐交易所窗口预抓结果单独展示为运行摘要；`trial` 模式只保留 `state/pregrab_runs.json`，不会把隔离 root 下的临时 raw/normalized 误当成正式源数据。

## Source precedence

Canonical success path may use:
1. `official`
2. `official_browser_bootstrap`
3. `fallback_online`

`fallback_archive` must not participate in canonical success semantics.

## Venue/source families

### Futures venues
- SHFE
- CFFEX
- CZCE
- GFEX
- DCE

### Options venues
- SHFE / INE options
- CFFEX options
- CZCE options
- DCE options
- GFEX options
- SSE options
- SZSE options
  - current priority:
    - official underlying summary `ysprdzb`
    - official contract pages `option_drhy` for current and dated historical lookup
    - nearby `contracts_snapshot` cache seeding
    - local `equity_options_history` symbol probe with bounded metadata lookup
    - Sina history dayline as `fallback_online`

### Public asset snapshot families
- A 股全市场快照
- 北交所股票快照
- ETF 快照
- 开放式基金净值快照
- 货币基金收益快照
- LOF 基金快照
- REITs 快照
- 可转债快照
- 上金所现货日行情
- 国内碳市场 as-of 快照

### Public reference families
- 人民币外汇参考价
- 人民币外汇即期报价
- 外币对即期报价
- 人民币外汇远掉报价
- USD/CNY C-Swap 曲线
- Shibor 参考表
- LPR 参考表
- 回购利率参考表
- 上海金 / 上海银基准价

### Public bond families
- 银行间现券成交快照
- 银行间做市报价快照
- 中债收益率曲线点位
- 上交所债券成交概览
- 上交所债券现券市场概览

### Crypto observation family
- CoinGecko 公共市场快照
- CoinGecko 公共 history
- CoinGecko 公共 derivatives

### Platform metadata family
- instrument master 派生表
- 统一日线行情表
- 统一基金净值表
- 统一 REITs 行情表
- 统一交易日日历快照
- 统一收益率曲线表
- 运行历史派生表
- 覆盖历史派生表
- source health 历史派生表
- validation results 派生表
- source health 派生表

## Canonical vs query source rules

- query runs may reuse the same raw inputs as canonical runs
- query runs must not rewrite canonical normalized outputs
- query runs must not rewrite canonical checkpoint state
- canonical repair may rebuild outputs from preserved raw payloads

## Current provenance rules

- every successful source run stores raw payloads under `data/raw/...`
- new raw writes also store sidecar provenance metadata where available so cached payload reuse can preserve `source_url` / `source_type`
- normalized outputs must point back to raw payloads through `raw_path`
- source type must reflect the real source family used
- `trial` 预抓必须在隔离 storage root 下执行；只有摘要 `state/pregrab_runs.json` 可以回写正式目录，临时 raw/normalized/state/db 必须自动清理
- 多资产历史窗口同步同样只把摘要写入 `state/window_runs.json`；正式 raw/normalized 仍按各数据集自己的 output 规则落地
- historical option applicability is gated by venue-level `options_launch_date` metadata where configured
- weak online sources now use host-level pacing, jitter, and protective-block backoff instead of bursty retry patterns
- new public snapshot datasets also preserve `source_id / source_url / source_type / retrieved_at / raw_path / parser_version / checksum / run_id`

## Current weak-source notes

- `DCE` options:
  - current validated success path is still largely `fallback_online`
  - historical dates now prefer cached quote raw before live requests
  - history fetches now stop after protective-block signals instead of continuing to fan out
  - uncached dates remain unstable
- `SSE` options:
  - current structure is official risk/contract discovery + official recent/current quote chain + online fallback dayline
  - recent uncached dates can now use `yunhq.sse.com.cn:32042` official quote endpoints instead of immediately depending on Sina
  - historical dates now prefer cached quote raw and cached master-data raw before live requests
  - if official risk rows fail temporarily, the source now also tries nearby cached `contracts_snapshot` raw payloads before declaring the date broken
  - when contracts are applicable but live dayline still returns 0 priced rows and no cache is available, the source now records `pending_retry` instead of softening that state into `no_data`
  - older uncached dates can still fail when fallback dayline returns no rows
- `SZSE` options:
  - current structure is official contract discovery + online dayline
  - historical dates now prefer cached quote raw and cached master-data raw before live requests
  - when official summary and nearby cached underlyings are both unavailable, historical discovery can fall back to configured underlying code maps before attempting online symbol discovery
  - cached `equity_options_metadata/*.json` and `equity_options_expire_days/*.json` are now reused to avoid re-hitting Sina metadata endpoints for the same numeric symbol / expiry pair
  - nearby cached `contracts_snapshot` raw payloads are now also used as an auxiliary underlying-discovery source
  - when nearby `contracts_snapshot` raw reveals `symbol -> contract/strike/expire`, that mapping is now also written back into `equity_options_metadata/*.json` so later historical reruns can reuse it directly
  - nearby `contracts_snapshot` raw payloads are now also bulk-seeded into `equity_options_metadata/*.json` before historical discovery starts, so the source can reuse formal `symbol -> contract/strike/expire` mappings without waiting for per-symbol live metadata probes
  - when all earlier discovery paths are empty, the source can now probe local `equity_options_history` files that actually contain the target trade date, then perform bounded metadata lookups to accumulate reusable symbol caches
  - deep-history live metadata probing is now additionally bounded by `equity_option_historical_probe_limit / equity_option_historical_probe_budget_seconds / equity_option_historical_probe_timeout_seconds`, so old-date repair attempts stay polite and do not turn into unbounded live scans
  - when no historical symbols can be discovered and no cached raw exists, the source now records `pending_retry` instead of degrading into a generic `error`
  - uncached dates can still fail when official investor API connection drops and no cached raw exists
- result datasets:
  - collectors are formal and official-only
  - `CFFEX` 期货与期权 XML parser 当前已统一做 HTML entity 清洗，至少兼容 `&nbsp; / &NBSP;`
  - `futures_delivery_results` 已开始接入首批官方端点：
    - `SHFE / INE`：`Delivery{trade_date}.dat` + `ExchangeDelivery{yyyymm}.dat`，并按合约前缀拆分 `SHFE` 与 `INE`
    - `GFEX`：`/u/interfacesWebTcDeliveryQuotes/loadList`
    - `DCE`：官方月度市场报告 PDF，当前按“DCE交割情况”解析到期合约聚合交割结果
  - `options_exercise_results` 已开始接入首批官方端点：
    - `CFFEX`：`monthlyReport/{yyyymm}/{yyyymm}MonthlyReport.pdf`，当前按官方月报 PDF 中“期权各产品行权数据统计”解析产品级聚合结果
    - `DCE`：官方月度市场报告 PDF，当前按“DCE期权行权情况”解析到期系列的 `CALL / PUT` 聚合结果
    - `SSE`：`https://query.sse.com.cn/commonQuery.do` + `sqlId=SSE_ZQPZ_YSP_GGQQZSXT_TJSJ_XQJGXX_SEARCH_L`，当前按标的证券拆分认购/认沽聚合行权量
    - `SZSE`：`https://www.szse.cn/api/report/ShowReport/data?SHOWTYPE=JSON&CATALOGID=option_jstj...`，当前按标的证券简称/代码拆分认购/认沽聚合行权量
    - `CFFEX` 最近日期若返回 `HTTP 200` 的 HTML 错误页而不是 PDF，当前会把 raw 诚实落成 `.html`，并记为 `pending_retry`
    - 同一天同一结果链源如果响应类型发生变化，collector 现在会清理旧扩展名 raw，只保留当前真实扩展，避免 `pdf/html/json/xml` 残留并存误导审计
    - 逐交易所窗口预抓当前会把这类 `publication_lag / HTML wrong page` 归类为外部阻塞，不再因为结果链 completeness 信号把它误算成内部工程失败
  - many venues still lack configured official result endpoints; where no endpoint is configured yet, the dataset must remain honest `no_data / pending_retry`, not fake `success`
- public snapshot datasets:
  - `equities_spot_snapshot` currently uses `AkShare stock_zh_a_spot` and should be treated as a cautious once-per-day snapshot source because the upstream Sina chain is sensitive
  - `bse_equities_spot_snapshot` currently prefers `AkShare stock_bj_a_spot_em`; 当 Eastmoney 代理链路异常时，会诚实回退到 `Tencent qt.gtimg.cn` 公共行情，而不是直接把 latest 标成失败
  - `etf_spot_snapshot` currently uses `AkShare fund_etf_spot_ths`
  - `open_fund_nav_snapshot` currently uses `AkShare fund_open_fund_daily_em`
  - `money_market_fund_snapshot` currently uses `AkShare fund_money_fund_daily_em`
  - `lof_spot_snapshot` currently prefers `AkShare fund_lof_spot_em`; 当 Eastmoney 代理链路异常时，会用公开 LOF 列表页 + `Sina hq` 批量行情诚实回退
  - `reits_spot_snapshot` currently prefers `AkShare reits_realtime_em`; 当实时页异常时，会复用最近一次成功 symbol universe 并回退到 `Sina hq`
  - `convertible_bond_spot_snapshot` currently uses `AkShare bond_zh_hs_cov_spot`
  - `sge_spot_daily_quotes` currently uses `AkShare spot_hist_sge`; 当前会按品种串行抓取以保持更接近人工访问节奏，因此默认不加入稳定 public-assets bundle
  - `carbon_market_snapshot` currently uses a single public request to `tanjiaoyi.com` and selects the latest available row per domestic carbon market region not after the requested day
- public reference datasets:
  - `fx_reference_rates` currently uses `AkShare currency_boc_safe` and records the BOC historical reference-rate unit directly
  - `rmb_middle_rates` currently uses `AkShare macro_china_rmb`; 在当前公开可得口径下历史上限止于 `2021-05-13`，更晚请求必须诚实返回 `no_data`
  - `fx_spot_quotes` currently uses `AkShare fx_spot_quote`, source page来自 CFETS/ChinaMoney 人民币外汇即期报价
  - `fx_pair_quotes` currently uses `AkShare fx_pair_quote`
  - `fx_swap_quotes` currently uses `AkShare fx_swap_quote`
  - `fx_c_swap_curve` currently uses ChinaMoney public JSON for `USD/CNY C-Swap` because the current `AkShare fx_c_swap_cm` path is unstable in this local LibreSSL environment
  - `money_market_rates` currently uses `AkShare macro_china_shibor_all`
  - `reserve_reference_series` currently uses `AkShare macro_china_fx_gold / macro_china_foreign_exchange_gold`
  - `loan_prime_rates` currently uses `AkShare macro_china_lpr` with as-of fallback to the latest published LPR date
  - `repo_reference_rates` currently uses `AkShare repo_rate_query` for both 回购定盘利率 and 银银间回购定盘利率
  - `cn_us_treasury_yields` currently uses `AkShare bond_zh_us_rate` for cross-market China/US sovereign yield observations; `2026-04-17` has now been live-fetched successfully and preserved into raw / normalized / DuckDB outputs
  - `precious_metal_reference_quotes` currently uses `AkShare spot_golden_benchmark_sge / spot_silver_benchmark_sge`
  - public reference datasets write raw payloads under `data/raw/public_references/...` and state under `state/public_references.json`
- public bond datasets:
  - `interbank_bond_deal_snapshot` currently uses `AkShare bond_spot_deal`
  - `interbank_bond_quote_snapshot` currently uses `AkShare bond_spot_quote`
  - `yield_curve_points` currently uses `AkShare bond_china_yield`
  - `sse_bond_deal_summary` currently uses `AkShare bond_deal_summary_sse`
  - `sse_bond_cash_summary` currently uses `AkShare bond_cash_summary_sse`
  - public bond datasets write raw payloads under `data/raw/public_bonds/...` and state under `state/public_bonds.json`
- crypto observation dataset:
  - `crypto_global_snapshot` currently uses CoinGecko public `coins/markets`
  - `crypto_assets` currently reuses same-day `coins/markets` raw payload to materialize a first-version crypto instrument table
  - `crypto_daily_quotes` currently prefers CoinGecko `coins/{id}/history`; when the history endpoint hits public rate limits, it may honestly fall back to the same-day snapshot raw instead of pretending history was available
  - `crypto_derivatives_public` currently prefers CoinGecko public `derivatives`; 当该端点不可得时，会依次尝试同次 `CME` 比特币公开报告与 `OKX` 公共永续行情，只有三条公开链路都不可得时才记 `pending_retry`
  - `crypto_bitcoin_holdings_public` currently uses `AkShare crypto_bitcoin_hold_report`; `source_query_date` must be preserved as the public-source observation date and cannot be伪装成当日本地交易日
  - `crypto_cme_bitcoin_report` currently uses `AkShare crypto_bitcoin_cme`; empty report rows on a requested date are `no_data`, not `pending_retry`
  - crypto outputs write raw payloads under `data/raw/crypto_global/...` and state under `state/crypto_global.json`
  - they must remain explicitly separated from domestic canonical markets and always carry a legal note in docs / GUI
- platform metadata datasets:
  - `instrument_master` is derived from `contracts_snapshot` plus the latest successful public assets / references / bonds / crypto outputs
  - `daily_ohlcv` is derived from canonical derivatives daily quotes, latest public asset snapshots, and crypto observation outputs
  - `fund_nav` is derived from `open_fund_nav_snapshot + money_market_fund_snapshot`
  - `reits_quotes` is derived from `reits_spot_snapshot`
  - `trading_calendar` is derived from derivatives checkpoints plus the latest public runner summaries
  - `yield_curves` is derived from `yield_curve_points + cn_us_treasury_yields`
  - `bond_master / bond_quotes / fx_quotes / commodity_spot_quotes / crypto_global_quotes` are first-version unified latest-view tables derived from already-landed normalized datasets; they are not raw collectors and must preserve upstream provenance fields
  - `asset_coverage` is derived from the asset family registry, dataset registry, derivatives checkpoint outputs, latest public runner summaries, and platform metadata state
  - `run_history` is derived from `state/regression_smoke.json + state/pregrab_runs.json + state/window_runs.json + environment health state`
  - `coverage_history` is derived from `asset_coverage + platform metadata state`
  - `source_health_history` is derived from `source_health + platform metadata state`
  - `source_type_overview` is derived from `source_health` and aggregates real runtime counts by `source_type`
  - `issue_category_overview` is derived from `source_health` and aggregates real runtime counts by `issue_category`
  - `validation_results` is derived from `workflow.validate` and the public runner validation APIs
  - `source_health` is derived from the source catalog plus checkpoints/public runner state
  - `run_health` is derived from `state/regression_smoke.json` and now carries representative-date plus continuous-window regression summaries, together with separate runtime and engineering statuses
- these platform datasets are `derived` tables, not raw collectors, and they write to `data/normalized/platform/...` with state under `state/platform_metadata.json`
- `source_catalog` / `source_health` 现在也会显式登记这些 `derived` 数据集，这样 GUI 能直接看到平台统一表本身的来源族与健康状态
- current GUI download links reuse the same canonical DuckDB/export layer and therefore do not bypass provenance or overwrite rules
- `environment-check` 当前属于平台运行环境诊断源，不是行情 collector；但它的摘要会进入 `/crawl /quality` 与 `run_history`
- `validation_results` 现会把 derivatives canonical audit 里的 `blocked_issues` 一起带到落表字段 `blocked_issue_count / blocked_issues`
- `source_health` 现会把最近状态归类到 `issue_category`，并在公开源不可得时写入 `blocked_reason`
- `source_health` 现已覆盖结果链 source：`futures_delivery_results / options_exercise_results` 会以独立 source 条目出现在平台健康表中

## Anti-overwrite rules

- filtered runs write only under `data/normalized/queries/{selection_id}/...`
- canonical state remains in `state/checkpoints.json`
- query state lives in `state/query_runs/{selection_id}.json`
- `contracts_latest.csv` updates only from successful canonical all-scope runs
