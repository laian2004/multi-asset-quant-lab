import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.storage import build_duckdb_database, export_dataset


class StorageTests(unittest.TestCase):
    def test_build_duckdb_database_indexes_known_datasets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            normalized_root = root / "data" / "normalized"
            futures_path = normalized_root / "daily_quotes" / "2026-04-16.csv"
            futures_path.parent.mkdir(parents=True, exist_ok=True)
            futures_path.write_text(
                "trade_date,exchange,contract\n2026-04-16,SHFE,CU2605\n",
                encoding="utf-8-sig",
            )
            public_path = normalized_root / "public_references" / "fx_reference_rates" / "2026-04-17.csv"
            public_path.parent.mkdir(parents=True, exist_ok=True)
            public_path.write_text(
                "trade_date,asset_family,reference_type,market,exchange,symbol,name,base_currency,quote_currency,tenor,value,change_bp,unit,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-17,fx_money_market_cn,fx_reference_rate,cn_fx_reference,BOC,USD/CNY,美元/人民币参考价,USD,CNY,spot_reference,686.22,,CNY per 100 foreign currency units,akshare.currency_boc_safe,https://www.boc.cn/sourcedb/whpj/,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_references/fx_reference_rates/20260417.json,public_references_v1,abc,run1\n",
                encoding="utf-8-sig",
            )
            rmb_middle_path = normalized_root / "public_references" / "rmb_middle_rates" / "2021-05-13.csv"
            rmb_middle_path.parent.mkdir(parents=True, exist_ok=True)
            rmb_middle_path.write_text(
                "trade_date,asset_family,reference_type,market,exchange,symbol,name,base_currency,quote_currency,tenor,value,change_bp,unit,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2021-05-13,fx_money_market_cn,rmb_central_parity,cn_rmb_central_parity,PBOC,USD/CNY,美元/人民币中间价,USD,CNY,spot_reference,6.4525,-0.1,CNY per 1 foreign currency unit,akshare.macro_china_rmb,https://datacenter.jin10.com/reportType/dc_rmb_data,fallback_online,2026-04-20T11:00:00+08:00,data/raw/public_references/rmb_middle_rates/20210513.json,public_references_v1,rmb1,runrmb\n",
                encoding="utf-8-sig",
            )
            reserve_path = normalized_root / "public_references" / "reserve_reference_series" / "2026-04-17.csv"
            reserve_path.parent.mkdir(parents=True, exist_ok=True)
            reserve_path.write_text(
                "trade_date,asset_family,reference_type,market,exchange,symbol,name,base_currency,quote_currency,tenor,value,change_bp,unit,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-03-01,fx_money_market_cn,reserve_reference,cn_reserve_reference,SAFE,SAFE:FOREX_RESERVE,国家外汇储备（东方财富）,USD,USD,monthly_snapshot,33421.23,-2.49,100M USD,akshare.macro_china_fx_gold,https://data.eastmoney.com/cjsj/hjwh.html,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_references/reserve_reference_series/20260417.json,public_references_v1,def,run2\n",
                encoding="utf-8-sig",
            )
            fx_pair_path = normalized_root / "public_references" / "fx_pair_quotes" / "2026-04-19.csv"
            fx_pair_path.parent.mkdir(parents=True, exist_ok=True)
            fx_pair_path.write_text(
                "trade_date,asset_family,reference_type,market,exchange,symbol,name,base_currency,quote_currency,tenor,value,change_bp,unit,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,fx_money_market_cn,fx_pair_quote,cn_fx_pair,CFETS,AUD/USD,AUD/USD 外币对即期报价,AUD,USD,spot,0.715,,,akshare.fx_pair_quote,http://www.chinamoney.com.cn/chinese/mkdatapfx/,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_references/fx_pair_quotes/20260419.json,public_references_v1,ghi,run3\n",
                encoding="utf-8-sig",
            )
            fx_swap_path = normalized_root / "public_references" / "fx_swap_quotes" / "2026-04-19.csv"
            fx_swap_path.parent.mkdir(parents=True, exist_ok=True)
            fx_swap_path.write_text(
                "trade_date,asset_family,reference_type,market,exchange,symbol,name,base_currency,quote_currency,tenor,value,change_bp,unit,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,fx_money_market_cn,fx_swap_quote,cn_fx_swap,CFETS,USD/CNY,USD/CNY 远掉报价 1W,USD,CNY,1W,-9.5,,pips,akshare.fx_swap_quote,http://www.chinamoney.com.cn/chinese/mkdatapfx/,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_references/fx_swap_quotes/20260419.json,public_references_v1,jkl,run4\n",
                encoding="utf-8-sig",
            )
            fx_c_swap_path = normalized_root / "public_references" / "fx_c_swap_curve" / "2026-04-19.csv"
            fx_c_swap_path.parent.mkdir(parents=True, exist_ok=True)
            fx_c_swap_path.write_text(
                "trade_date,asset_family,reference_type,market,exchange,symbol,name,base_currency,quote_currency,tenor,value,change_bp,unit,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-08,fx_money_market_cn,fx_c_swap_curve,cn_fx_swap_curve,CFETS,USD/CNY:C_SWAP,USD/CNY C-Swap 定盘曲线 ON,USD,CNY,ON,-4.35,,pips,cfets.fx_c_swap_curve,https://www.chinamoney.org.cn/chinese/bkcurvfsw,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_references/fx_c_swap_curve/20260419.json,public_references_v1,mno,run5\n",
                encoding="utf-8-sig",
            )
            cn_us_path = normalized_root / "public_references" / "cn_us_treasury_yields" / "2026-04-17.csv"
            cn_us_path.parent.mkdir(parents=True, exist_ok=True)
            cn_us_path.write_text(
                "trade_date,asset_family,reference_type,market,exchange,symbol,name,base_currency,quote_currency,tenor,value,change_bp,unit,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-17,bonds_rates_cn,sovereign_yield_reference,cross_market_treasury_yield,EASTMONEY,CN_GOVT_2Y,中国国债收益率2年,CN,YIELD,2Y,1.55,,percent,akshare.bond_zh_us_rate,https://data.eastmoney.com/cjsj/zmgzsyl.html,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_references/cn_us_treasury_yields/20260417.json,public_references_v1,pqs,run7\n",
                encoding="utf-8-sig",
            )
            carbon_path = normalized_root / "public_assets" / "carbon_market_snapshot" / "2026-04-19.csv"
            carbon_path.parent.mkdir(parents=True, exist_ok=True)
            carbon_path.write_text(
                "trade_date,asset_family,asset_type,market,exchange,symbol,name,last_price,change_amount,change_pct,open,high,low,prev_close,volume,amount,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,commodity_energy_cn,carbon_spot,cn_carbon,上海,上海:CEA,上海碳排放配额现货,72.5,,,,,,,900,65250,akshare.energy_carbon_domestic,http://www.tanjiaoyi.com/,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_assets/carbon_market_snapshot/20260419.json,public_assets_v1,pqr,run6\n",
                encoding="utf-8-sig",
            )
            instrument_master_path = normalized_root / "platform" / "instrument_master" / "2026-04-19.csv"
            instrument_master_path.parent.mkdir(parents=True, exist_ok=True)
            instrument_master_path.write_text(
                "trade_date,instrument_id,asset_family,market,exchange,instrument_type,symbol,name,currency,listing_date,delisting_date,status,underlying_id,contract_multiplier,price_tick,quote_unit,trading_unit,delivery_type,exercise_type,option_type,strike_price,expire_date,last_trade_date,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,SHFE:CU2605,exchange_derivatives_cn,cn_derivatives,SHFE,future,CU2605,沪铜主力,CNY,,,active,,,,,,,,,,,shfe.contracts_snapshot,https://www.shfe.com.cn/,official,2026-04-19T15:00:00+08:00,data/raw/shfe/contracts_snapshot/20260419.json,platform_metadata_v1,inst1,run8\n",
                encoding="utf-8-sig",
            )
            daily_ohlcv_path = normalized_root / "platform" / "daily_ohlcv" / "2026-04-19.csv"
            daily_ohlcv_path.parent.mkdir(parents=True, exist_ok=True)
            daily_ohlcv_path.write_text(
                "trade_date,instrument_id,asset_family,market,exchange,instrument_type,symbol,name,currency,open,high,low,close,pre_close,settlement,pre_settlement,volume,amount,open_interest,turnover_rate,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,SSE:600000,equities_funds_cn,cn_equities,SSE,stock,600000,浦发银行,CNY,10,10.2,9.9,10.1,10,,,,1000,10000,,,akshare.stock_zh_a_spot,https://vip.stock.finance.sina.com.cn/mkt/#hs_a,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_assets/equities_spot_snapshot/20260419.json,platform_metadata_v1,ohlcv1,run12\n",
                encoding="utf-8-sig",
            )
            fund_nav_path = normalized_root / "platform" / "fund_nav" / "2026-04-19.csv"
            fund_nav_path.parent.mkdir(parents=True, exist_ok=True)
            fund_nav_path.write_text(
                "trade_date,instrument_id,asset_family,market,exchange,symbol,name,fund_type,nav,nav_change,nav_change_pct,nav_date,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,CN_FUNDS:000001,equities_funds_cn,cn_funds,CN_FUNDS,000001,华夏成长混合,open_fund,1.121,0.003,0.27,2026-04-19,akshare.fund_open_fund_daily_em,https://fund.eastmoney.com/fund.html#os_0;isall_0;ft_;pt_1,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_assets/open_fund_nav_snapshot/20260419.json,platform_metadata_v1,nav1,run13\n",
                encoding="utf-8-sig",
            )
            reits_quotes_path = normalized_root / "platform" / "reits_quotes" / "2026-04-19.csv"
            reits_quotes_path.parent.mkdir(parents=True, exist_ok=True)
            reits_quotes_path.write_text(
                "trade_date,instrument_id,asset_family,market,exchange,symbol,name,open,high,low,close,pre_close,volume,amount,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,SSE:180101,equities_funds_cn,cn_reits,SSE,180101,博时蛇口产园REIT,1.886,1.9,1.872,1.9,1.887,32113,6062173.81,akshare.reits_realtime_em,https://quote.eastmoney.com/center/gridlist.html#fund_reits_all,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_assets/reits_spot_snapshot/20260419.json,platform_metadata_v1,reit1,run14\n",
                encoding="utf-8-sig",
            )
            trading_calendar_path = normalized_root / "platform" / "trading_calendar" / "2026-04-19.csv"
            trading_calendar_path.parent.mkdir(parents=True, exist_ok=True)
            trading_calendar_path.write_text(
                "trade_date,calendar_id,asset_family,market,exchange,is_trading_day,day_status,source_trade_date,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,cn_equities,equities_funds_cn,cn_equities,MULTI,true,success,2026-04-19,platform.public_assets_calendar,data/normalized/public_assets/equities_spot_snapshot/2026-04-19.csv,fallback_online,2026-04-19T15:00:00+08:00,,platform_metadata_v1,cal1,run15\n",
                encoding="utf-8-sig",
            )
            run_health_path = normalized_root / "platform" / "run_health" / "2026-04-19.csv"
            run_health_path.parent.mkdir(parents=True, exist_ok=True)
            run_health_path.write_text(
                "trade_date,workflow_name,scope,status,engineering_status,updated_at,checked_dates,date_statuses,window_statuses,window_sample_counts,window_sampled_dates,needs_repair_dates,issue_category_counts,blocked_issue_count,blocked_issues,platform_sync_status,platform_validation_status,build_db_status,gui_smoke_status,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,regression_smoke,platform_release_gate,success,success,2026-04-20T10:30:00+08:00,\"2010-04-16,2015-04-16,2021-04-16,2026-04-16\",\"{\"\"2010-04-16\"\": \"\"success\"\"}\",\"{\"\"latest_7_trading_days\"\": \"\"success\"\"}\",\"{\"\"latest_7_trading_days\"\": 4}\",\"{\"\"latest_7_trading_days\"\": [\"\"2026-04-14\"\", \"\"2026-04-15\"\", \"\"2026-04-16\"\", \"\"2026-04-17\"\"]}\",,\"{\"\"result_chain_publication_lag\"\": 1}\",1,options_exercise_results: missing exchanges [CFFEX] are pending official publication,success,success,success,success,platform.regression_smoke,state/regression_smoke.json,derived,2026-04-20T10:31:00+08:00,state/regression_smoke.json,platform_metadata_v1,rh1,run19\n",
                encoding="utf-8-sig",
            )
            asset_coverage_path = normalized_root / "platform" / "asset_coverage" / "2026-04-19.csv"
            asset_coverage_path.parent.mkdir(parents=True, exist_ok=True)
            asset_coverage_path.write_text(
                "trade_date,asset_family,family_label,phase,registry_status,runtime_status,latest_trade_date,expected_dataset_count,observed_dataset_count,success_dataset_count,non_success_dataset_count,total_row_count,coverage_ratio,datasets,missing_datasets,status_counts,markets,notes,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,exchange_derivatives_cn,国内场内衍生品,B,implemented,success,2026-04-16,8,8,8,0,20923,8/8,\"[\"\"futures_daily_quotes\"\"]\",[],\"{\"\"success\"\": 8}\",\"[\"\"SHFE\"\"]\",ok,platform.asset_coverage,state/platform_metadata.json,derived,2026-04-20T10:31:00+08:00,state/platform_metadata.json,platform_metadata_v1,ac1,run19\n",
                encoding="utf-8-sig",
            )
            source_type_overview_path = normalized_root / "platform" / "source_type_overview" / "2026-04-19.csv"
            source_type_overview_path.parent.mkdir(parents=True, exist_ok=True)
            source_type_overview_path.write_text(
                "trade_date,source_type,source_count,dataset_count,success_count,non_success_count,blocked_issue_count,latest_trade_date,status_counts,source_ids,source_id,source_url,source_type_origin,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,official,2,2,1,1,1,2026-04-17,\"{\"\"success\"\": 1, \"\"pending_retry\"\": 1}\",\"[\"\"shfe.futures\"\", \"\"cffex.options_exercise_results\"\"]\",platform.source_type_overview,state/platform_metadata.json,derived,2026-04-20T10:31:00+08:00,state/platform_metadata.json,platform_metadata_v1,sto1,run19\n",
                encoding="utf-8-sig",
            )
            issue_category_overview_path = normalized_root / "platform" / "issue_category_overview" / "2026-04-19.csv"
            issue_category_overview_path.parent.mkdir(parents=True, exist_ok=True)
            issue_category_overview_path.write_text(
                "trade_date,issue_category,source_count,dataset_count,blocked_issue_count,latest_trade_date,status_counts,source_type_counts,source_ids,datasets,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,blocked_issue,3,2,3,2026-04-17,\"{\"\"no_data\"\": 2, \"\"pending_retry\"\": 1}\",\"{\"\"official\"\": 3}\",\"[\"\"cffex.options_exercise_results\"\", \"\"cffex.futures_delivery_results\"\", \"\"czce.options_exercise_results\"\"]\",\"[\"\"options_exercise_results\"\", \"\"futures_delivery_results\"\"]\",platform.issue_category_overview,state/platform_metadata.json,derived,2026-04-20T10:31:00+08:00,state/platform_metadata.json,platform_metadata_v1,ico1,run19\n",
                encoding="utf-8-sig",
            )
            yield_curves_path = normalized_root / "platform" / "yield_curves" / "2026-04-19.csv"
            yield_curves_path.parent.mkdir(parents=True, exist_ok=True)
            yield_curves_path.write_text(
                "trade_date,asset_family,market,exchange,curve_name,curve_type,tenor,tenor_years,yield,change_bp,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,bonds_rates_cn,cn_yield_curve,CHINABOND,中债国债收益率曲线,china_bond,10Y,10,2.28,1,akshare.bond_china_yield,https://yield.chinabond.com.cn/,fallback_online,2026-04-19T15:00:00+08:00,data/raw/public_bonds/yield_curve_points/20260419.json,platform_metadata_v1,yv1,run16\n",
                encoding="utf-8-sig",
            )
            validation_results_path = normalized_root / "platform" / "validation_results" / "2026-04-19.csv"
            validation_results_path.parent.mkdir(parents=True, exist_ok=True)
            validation_results_path.write_text(
                "trade_date,scope,dataset,source_trade_date,status,row_count,schema_ok,duplicate_keys,missing_raw_paths_count,completeness_ok,master_data_completeness,result_chain_semantics_ok,contracts_latest_consistency_ok,source_provenance_ok,expected_markets,observed_markets,no_data_reason,not_applicable_reason,output_path,validated_at\n"
                "2026-04-19,derivatives_canonical,futures_daily_quotes,2026-04-16,success,837,true,0,0,true,true,true,,true,SHFE|CFFEX,SHFE|CFFEX,,,data/normalized/daily_quotes/2026-04-16.csv,2026-04-19T15:00:00+08:00\n",
                encoding="utf-8-sig",
            )
            source_health_path = normalized_root / "platform" / "source_health" / "2026-04-19.csv"
            source_health_path.parent.mkdir(parents=True, exist_ok=True)
            source_health_path.write_text(
                "trade_date,source_id,asset_family,market,exchange,dataset,source_type,priority,source_url,last_status,last_trade_date,last_success_trade_date,output_path,message\n"
                "2026-04-19,shfe.futures,exchange_derivatives_cn,cn_futures,SHFE,futures_daily_quotes,official,1,https://www.shfe.com.cn/data/tradedata/future/dailydata/,success,2026-04-16,2026-04-16,data/normalized/daily_quotes/2026-04-16.csv,\n",
                encoding="utf-8-sig",
            )
            crypto_assets_path = normalized_root / "crypto_global" / "crypto_assets" / "2026-04-19.csv"
            crypto_assets_path.parent.mkdir(parents=True, exist_ok=True)
            crypto_assets_path.write_text(
                "trade_date,asset_family,market,exchange,symbol,name,category,market_cap_rank,circulating_supply,total_supply,max_supply,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id,legal_note\n"
                "2026-04-19,crypto_global_observation,global_crypto,COINGECKO,BTC,Bitcoin,,1,20017871,20017871,21000000,coingecko.coins_markets_public,https://api.coingecko.com/api/v3/coins/markets,fallback_online,2026-04-19T15:00:00+08:00,data/raw/crypto_global/crypto_assets/20260419.json,crypto_observation_v2,ca1,run9,仅作全球公开市场数据研究与行情观察，不提供交易、撮合、开户、引流或任何境内虚拟货币经营服务。\n",
                encoding="utf-8-sig",
            )
            crypto_daily_path = normalized_root / "crypto_global" / "crypto_daily_quotes" / "2026-04-19.csv"
            crypto_daily_path.parent.mkdir(parents=True, exist_ok=True)
            crypto_daily_path.write_text(
                "trade_date,asset_family,market,exchange,symbol,name,price_usd,market_cap,total_volume,high_24h,low_24h,change_pct_24h,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id,legal_note\n"
                "2026-04-19,crypto_global_observation,global_crypto,COINGECKO,BTC,Bitcoin,75286,1506768120286,49810566286,,,,coingecko.coin_history_public,https://api.coingecko.com/api/v3/coins/{id}/history,fallback_online,2026-04-19T15:00:00+08:00,data/raw/crypto_global/crypto_daily_quotes/20260419.json,crypto_observation_v2,cd1,run10,仅作全球公开市场数据研究与行情观察，不提供交易、撮合、开户、引流或任何境内虚拟货币经营服务。\n",
                encoding="utf-8-sig",
            )
            crypto_derivatives_path = normalized_root / "crypto_global" / "crypto_derivatives_public" / "2026-04-19.csv"
            crypto_derivatives_path.parent.mkdir(parents=True, exist_ok=True)
            crypto_derivatives_path.write_text(
                "trade_date,asset_family,market,exchange,symbol,underlying_symbol,contract_type,price_usd,index_price_usd,basis,spread,funding_rate,open_interest_usd,volume_24h_usd,last_traded_at,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id,legal_note\n"
                "2026-04-19,crypto_global_observation,crypto_derivatives_public,CME Group,BTC,BTC,future,75286,75300,14,1,,123456789,99887766,1776610229,coingecko.derivatives_public,https://api.coingecko.com/api/v3/derivatives,fallback_online,2026-04-19T15:00:00+08:00,data/raw/crypto_global/crypto_derivatives_public/20260419.json,crypto_observation_v2,cp1,run11,仅作全球公开市场数据研究与行情观察，不提供交易、撮合、开户、引流或任何境内虚拟货币经营服务。\n",
                encoding="utf-8-sig",
            )
            crypto_holdings_path = normalized_root / "crypto_global" / "crypto_bitcoin_holdings_public" / "2026-04-19.csv"
            crypto_holdings_path.parent.mkdir(parents=True, exist_ok=True)
            crypto_holdings_path.write_text(
                "trade_date,asset_family,market,exchange,symbol,company_name_en,company_name_zh,region,holder_category,market_cap_usd,btc_market_cap_ratio,holding_cost_usd,holding_ratio,holding_btc,holding_value_usd,source_query_date,announcement_url,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id,legal_note\n"
                "2026-04-19,crypto_global_observation,crypto_public_bitcoin_holdings,NADQ,MSTR:NADQ,MicroStrategy,,美国,上市公司,1000000000,0.3,900000000,0.725,152333,4624824000,2023-07-13,Filing,akshare.crypto_bitcoin_hold_report,https://crypto-akshare.akfamily.xyz/data/crypto/crypto.html,fallback_online,2026-04-20T09:00:00+08:00,data/raw/crypto_global/crypto_bitcoin_holdings_public/20260419.json,crypto_observation_v2,ch1,run17,仅作全球公开市场数据研究与行情观察，不提供交易、撮合、开户、引流或任何境内虚拟货币经营服务。\n",
                encoding="utf-8-sig",
            )
            crypto_cme_path = normalized_root / "crypto_global" / "crypto_cme_bitcoin_report" / "2023-08-30.csv"
            crypto_cme_path.parent.mkdir(parents=True, exist_ok=True)
            crypto_cme_path.write_text(
                "trade_date,asset_family,market,exchange,commodity,report_type,electronic_contracts,pit_contracts,block_contracts,volume,open_interest,open_interest_change,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id,legal_note\n"
                "2023-08-30,crypto_global_observation,crypto_cme_public_report,CME,比特币,期货,7895,,366,8261,15408,-764,akshare.crypto_bitcoin_cme,https://datacenter.jin10.com/reportType/dc_cme_btc_report,fallback_online,2026-04-20T09:10:00+08:00,data/raw/crypto_global/crypto_cme_bitcoin_report/20230830.json,crypto_observation_v2,cc1,run18,仅作全球公开市场数据研究与行情观察，不提供交易、撮合、开户、引流或任何境内虚拟货币经营服务。\n",
                encoding="utf-8-sig",
            )
            database_path = root / "data" / "db" / "market_data.duckdb"
            result = build_duckdb_database(database_path=database_path, normalized_root=normalized_root)
            datasets = {item["dataset"] for item in result["datasets"]}
            self.assertIn("futures_daily_quotes", datasets)
            self.assertIn("fx_reference_rates", datasets)
            self.assertIn("rmb_middle_rates", datasets)
            self.assertIn("reserve_reference_series", datasets)
            self.assertIn("fx_pair_quotes", datasets)
            self.assertIn("fx_swap_quotes", datasets)
            self.assertIn("fx_c_swap_curve", datasets)
            self.assertIn("cn_us_treasury_yields", datasets)
            self.assertIn("carbon_market_snapshot", datasets)
            self.assertIn("instrument_master", datasets)
            self.assertIn("daily_ohlcv", datasets)
            self.assertIn("fund_nav", datasets)
            self.assertIn("reits_quotes", datasets)
            self.assertIn("trading_calendar", datasets)
            self.assertIn("run_health", datasets)
            self.assertIn("asset_coverage", datasets)
            self.assertIn("source_type_overview", datasets)
            self.assertIn("issue_category_overview", datasets)
            self.assertIn("yield_curves", datasets)
            self.assertIn("validation_results", datasets)
            self.assertIn("source_health", datasets)
            self.assertIn("crypto_assets", datasets)
            self.assertIn("crypto_daily_quotes", datasets)
            self.assertIn("crypto_derivatives_public", datasets)
            self.assertIn("crypto_bitcoin_holdings_public", datasets)
            self.assertIn("crypto_cme_bitcoin_report", datasets)
            self.assertTrue(database_path.exists())

    def test_export_dataset_writes_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            normalized_root = root / "data" / "normalized"
            futures_path = normalized_root / "daily_quotes" / "2026-04-16.csv"
            futures_path.parent.mkdir(parents=True, exist_ok=True)
            futures_path.write_text(
                "trade_date,exchange,contract\n2026-04-16,SHFE,CU2605\n",
                encoding="utf-8-sig",
            )
            database_path = root / "data" / "db" / "market_data.duckdb"
            build_duckdb_database(database_path=database_path, normalized_root=normalized_root)
            output_path = root / "exports" / "futures.json"
            result = export_dataset(
                dataset_name="futures_daily_quotes",
                output_format="json",
                trade_date="2026-04-16",
                database_path=database_path,
                output_path=output_path,
            )
            self.assertEqual(result["row_count"], 1)
            self.assertTrue(output_path.exists())
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["contract"], "CU2605")

    def test_export_dataset_writes_csv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            normalized_root = root / "data" / "normalized"
            futures_path = normalized_root / "daily_quotes" / "2026-04-16.csv"
            futures_path.parent.mkdir(parents=True, exist_ok=True)
            futures_path.write_text(
                "trade_date,exchange,contract\n2026-04-16,SHFE,CU2605\n",
                encoding="utf-8-sig",
            )
            database_path = root / "data" / "db" / "market_data.duckdb"
            build_duckdb_database(database_path=database_path, normalized_root=normalized_root)
            output_path = root / "exports" / "futures.csv"
            result = export_dataset(
                dataset_name="futures_daily_quotes",
                output_format="csv",
                trade_date="2026-04-16",
                database_path=database_path,
                output_path=output_path,
            )
            self.assertEqual(result["row_count"], 1)
            self.assertTrue(output_path.exists())
            text = output_path.read_text(encoding="utf-8-sig")
            self.assertIn("trade_date,exchange,contract", text)
            self.assertIn("2026-04-16,SHFE,CU2605", text)

    def test_export_dataset_writes_parquet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            normalized_root = root / "data" / "normalized"
            futures_path = normalized_root / "daily_quotes" / "2026-04-16.csv"
            futures_path.parent.mkdir(parents=True, exist_ok=True)
            futures_path.write_text(
                "trade_date,exchange,contract\n2026-04-16,SHFE,CU2605\n",
                encoding="utf-8-sig",
            )
            database_path = root / "data" / "db" / "market_data.duckdb"
            build_duckdb_database(database_path=database_path, normalized_root=normalized_root)
            output_path = root / "exports" / "futures.parquet"
            result = export_dataset(
                dataset_name="futures_daily_quotes",
                output_format="parquet",
                trade_date="2026-04-16",
                database_path=database_path,
                output_path=output_path,
            )
            self.assertEqual(result["row_count"], 1)
            self.assertTrue(output_path.exists())
            self.assertGreater(output_path.stat().st_size, 0)

    def test_export_dataset_applies_generic_filters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            normalized_root = root / "data" / "normalized"
            options_path = normalized_root / "options" / "daily_quotes" / "2026-04-16.csv"
            options_path.parent.mkdir(parents=True, exist_ok=True)
            options_path.write_text(
                "trade_date,exchange,contract,option_type\n"
                "2026-04-16,SSE,510050C2604M02650,call\n"
                "2026-04-16,SZSE,159919C2104M04000A,call\n",
                encoding="utf-8-sig",
            )
            database_path = root / "data" / "db" / "market_data.duckdb"
            build_duckdb_database(database_path=database_path, normalized_root=normalized_root)
            output_path = root / "exports" / "filtered_options.json"
            result = export_dataset(
                dataset_name="options_daily_quotes",
                output_format="json",
                trade_date="2026-04-16",
                filters={"exchange": "SSE", "option_type": "call"},
                database_path=database_path,
                output_path=output_path,
            )
            self.assertEqual(result["row_count"], 1)
            self.assertEqual(result["filters"], {"exchange": "SSE", "option_type": "call"})
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            self.assertEqual(payload[0]["exchange"], "SSE")


if __name__ == "__main__":
    unittest.main()
