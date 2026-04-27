import json
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = ROOT / ".tmp-tests"
TMP_ROOT.mkdir(parents=True, exist_ok=True)
tempfile.tempdir = str(TMP_ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.gui import DashboardApp


class _FakeCheckpointStore:
    def __init__(self):
        self.data = {
            "dates": {
                "2026-04-16": {
                    "status": "success",
                    "outputs": {
                        "options_daily_quotes": "data/normalized/options/daily_quotes/2026-04-16.csv",
                    },
                    "row_counts": {
                        "options_daily_quotes": 1,
                    },
                }
            }
        }

    def get_last_successful_trade_date(self):
        return "2026-04-16"

    def get_day(self, trade_date: str):
        return self.data["dates"].get(trade_date, {})


class _FakeRunner:
    def __init__(self):
        self.actions = []

    def validate(self, trade_date_value, selection=None):
        return {
            "trade_date": trade_date_value,
            "checkpoint_status": "success",
            "datasets": {
                "options_daily_quotes": {
                    "csv_exists": True,
                    "schema_ok": True,
                    "row_count": 1,
                    "duplicate_keys": 0,
                    "missing_raw_paths": [],
                    "expected_exchanges": ["SSE"],
                    "observed_exchanges": ["SSE"],
                    "completeness_ok": True,
                    "selection_match_ok": True,
                }
            },
            "contracts_latest": {
                "source_trade_date": "2026-04-16",
                "matches_source_snapshot": True,
            },
        }

    def fetch_date(self, trade_date_value, selection=None):
        self.actions.append(("fetch_date", trade_date_value, getattr(selection, "instrument_group", "")))
        return {"trade_date": trade_date_value, "status": "success", "outputs": {"derivatives_daily_quotes": "ok.csv"}}

    def backfill(self, start_value, end_value, selection=None):
        self.actions.append(("backfill", start_value, end_value, getattr(selection, "instrument_group", "")))
        return {"trade_date": end_value, "status": "success", "outputs": {"derivatives_daily_quotes": "ok.csv"}}

    def sync_daily(self, date_value="latest", selection=None):
        self.actions.append(("sync_daily", date_value, getattr(selection, "instrument_group", "")))
        return {"trade_date": "2026-04-21", "status": "success"}

    def audit_canonical_date(self, trade_date_value):
        return {
            "trade_date": trade_date_value,
            "needs_repair": False,
            "issues": [],
            "blocked_issues": [
                "options_exercise_results: missing exchanges [SSE, SZSE] are blocked by official result-chain source unavailability"
            ],
            "issue_categories": {
                "result_chain_source_gap": 1,
            },
            "outputs": {},
        }


class _FakePublicRunner:
    def __init__(self):
        self.sync_calls = []

    def latest_summaries(self):
        return {
            "bse_equities_spot_snapshot": {
                "status": "success",
                "row_count": 318,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/public_assets/bse_equities_spot_snapshot/2026-04-19.csv",
            },
            "lof_spot_snapshot": {
                "status": "success",
                "row_count": 412,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/public_assets/lof_spot_snapshot/2026-04-19.csv",
            },
            "open_fund_nav_snapshot": {
                "status": "success",
                "row_count": 21654,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/public_assets/open_fund_nav_snapshot/2026-04-19.csv",
            },
            "money_market_fund_snapshot": {
                "status": "success",
                "row_count": 932,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/public_assets/money_market_fund_snapshot/2026-04-19.csv",
            },
            "sge_spot_daily_quotes": {
                "status": "success",
                "row_count": 13,
                "trade_date": "2026-04-17",
                "output_path": "data/normalized/public_assets/sge_spot_daily_quotes/2026-04-17.csv",
            },
            "convertible_bond_spot_snapshot": {
                "status": "success",
                "row_count": 359,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/public_assets/convertible_bond_spot_snapshot/2026-04-19.csv",
            },
            "carbon_market_snapshot": {
                "status": "success",
                "row_count": 8,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/public_assets/carbon_market_snapshot/2026-04-19.csv",
            },
            "reits_spot_snapshot": {
                "status": "success",
                "row_count": 82,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/public_assets/reits_spot_snapshot/2026-04-19.csv",
            }
        }

    def sync(self, trade_date_value="latest", families=None, force=False):
        self.sync_calls.append((trade_date_value, tuple(families or []), force))
        return {"trade_date": "2026-04-21", "status": "success", "outputs": {"equities_spot_snapshot": "ok.csv"}}


class _FakeReferenceRunner:
    def __init__(self):
        self.sync_calls = []

    def latest_summaries(self):
        return {
            "fx_reference_rates": {
                "status": "success",
                "row_count": 25,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/public_references/fx_reference_rates/2026-04-19.csv",
            },
            "fx_spot_quotes": {
                "status": "success",
                "row_count": 16,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/public_references/fx_spot_quotes/2026-04-19.csv",
            },
            "rmb_middle_rates": {
                "status": "success",
                "row_count": 14,
                "trade_date": "2021-05-13",
                "output_path": "data/normalized/public_references/rmb_middle_rates/2021-05-13.csv",
            },
            "fx_pair_quotes": {
                "status": "success",
                "row_count": 16,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/public_references/fx_pair_quotes/2026-04-19.csv",
            },
            "fx_swap_quotes": {
                "status": "success",
                "row_count": 150,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/public_references/fx_swap_quotes/2026-04-19.csv",
            },
            "fx_c_swap_curve": {
                "status": "success",
                "row_count": 12,
                "trade_date": "2026-04-08",
                "output_path": "data/normalized/public_references/fx_c_swap_curve/2026-04-19.csv",
            },
            "loan_prime_rates": {
                "status": "success",
                "row_count": 2,
                "trade_date": "2026-03-20",
                "output_path": "data/normalized/public_references/loan_prime_rates/2026-04-19.csv",
            },
            "reserve_reference_series": {
                "status": "success",
                "row_count": 4,
                "trade_date": "2026-03-01",
                "output_path": "data/normalized/public_references/reserve_reference_series/2026-04-19.csv",
            },
            "cn_us_treasury_yields": {
                "status": "success",
                "row_count": 2,
                "trade_date": "2026-04-17",
                "output_path": "data/normalized/public_references/cn_us_treasury_yields/2026-04-17.csv",
            }
        }

    def sync(self, trade_date_value="latest", families=None, force=False):
        self.sync_calls.append((trade_date_value, tuple(families or []), force))
        return {"trade_date": "2026-04-21", "status": "success", "outputs": {"fx_reference_rates": "ok.csv"}}


class _FakeBondRunner:
    def __init__(self):
        self.sync_calls = []

    def latest_summaries(self):
        return {
            "interbank_bond_deal_snapshot": {
                "status": "success",
                "row_count": 3945,
                "trade_date": "2026-04-17",
                "output_path": "data/normalized/public_bonds/interbank_bond_deal_snapshot/2026-04-17.csv",
            },
            "sse_bond_deal_summary": {
                "status": "success",
                "row_count": 12,
                "trade_date": "2026-04-17",
                "output_path": "data/normalized/public_bonds/sse_bond_deal_summary/2026-04-17.csv",
            },
        }

    def sync(self, trade_date_value="latest", families=None, force=False):
        self.sync_calls.append((trade_date_value, tuple(families or []), force))
        return {"trade_date": "2026-04-21", "status": "success", "outputs": {"interbank_bond_deal_snapshot": "ok.csv"}}


class _FakeCryptoRunner:
    def __init__(self):
        self.sync_calls = []

    def latest_summaries(self):
        return {
            "crypto_global_snapshot": {
                "dataset": "crypto_global_snapshot",
                "status": "success",
                "row_count": 7,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/crypto_global/crypto_global_snapshot/2026-04-19.csv",
            },
            "crypto_daily_quotes": {
                "dataset": "crypto_daily_quotes",
                "status": "success",
                "row_count": 7,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/crypto_global/crypto_daily_quotes/2026-04-19.csv",
            },
            "crypto_bitcoin_holdings_public": {
                "dataset": "crypto_bitcoin_holdings_public",
                "status": "success",
                "row_count": 59,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/crypto_global/crypto_bitcoin_holdings_public/2026-04-19.csv",
            },
            "crypto_cme_bitcoin_report": {
                "dataset": "crypto_cme_bitcoin_report",
                "status": "success",
                "row_count": 5,
                "trade_date": "2023-08-30",
                "output_path": "data/normalized/crypto_global/crypto_cme_bitcoin_report/2023-08-30.csv",
            },
        }

    def sync(self, trade_date_value="latest", force=False):
        self.sync_calls.append((trade_date_value, force))
        return {"trade_date": "2026-04-21", "status": "success", "outputs": {"crypto_global_snapshot": "ok.csv"}}


class _FakeSchedulerRunner:
    def __init__(self):
        self.calls = []

    def read_schedules(self):
        return {
            "updated_at": "2026-04-25T10:00:00+08:00",
            "schedules": [
                {
                    "schedule_id": "daily_build_db",
                    "task_name": "每日 DuckDB 重建",
                    "action_name": "build_db",
                    "cadence": "daily",
                    "enabled": True,
                    "next_run_at": "2026-04-20T10:00:00+08:00",
                }
            ],
        }

    def read_runs(self):
        return {"updated_at": "", "runs": []}

    def tick(self, run_all_due=True, schedule_id=""):
        self.calls.append(("tick", run_all_due, schedule_id))
        return {"status": "success", "run_count": 1, "runs": []}

    def set_enabled(self, schedule_id: str, enabled: bool):
        self.calls.append(("set_enabled", enabled, schedule_id))
        return {"status": "success", "schedule_id": schedule_id, "enabled": enabled}


class _FakePlatformMetadataRunner:
    def __init__(self):
        self.sync_calls = []

    def latest_summaries(self):
        return {
            "instrument_master": {
                "dataset": "instrument_master",
                "status": "success",
                "row_count": 12345,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/instrument_master/2026-04-19.csv",
            },
            "bond_master": {
                "dataset": "bond_master",
                "status": "success",
                "row_count": 2345,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/bond_master/2026-04-19.csv",
            },
            "bond_quotes": {
                "dataset": "bond_quotes",
                "status": "success",
                "row_count": 3456,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/bond_quotes/2026-04-19.csv",
            },
            "fx_quotes": {
                "dataset": "fx_quotes",
                "status": "success",
                "row_count": 88,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/fx_quotes/2026-04-19.csv",
            },
            "commodity_spot_quotes": {
                "dataset": "commodity_spot_quotes",
                "status": "success",
                "row_count": 21,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/commodity_spot_quotes/2026-04-19.csv",
            },
            "crypto_global_quotes": {
                "dataset": "crypto_global_quotes",
                "status": "success",
                "row_count": 8,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/crypto_global_quotes/2026-04-19.csv",
            },
            "daily_ohlcv": {
                "dataset": "daily_ohlcv",
                "status": "success",
                "row_count": 1024,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/daily_ohlcv/2026-04-19.csv",
            },
            "fund_nav": {
                "dataset": "fund_nav",
                "status": "success",
                "row_count": 22586,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/fund_nav/2026-04-19.csv",
            },
            "reits_quotes": {
                "dataset": "reits_quotes",
                "status": "success",
                "row_count": 82,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/reits_quotes/2026-04-19.csv",
            },
            "trading_calendar": {
                "dataset": "trading_calendar",
                "status": "success",
                "row_count": 5,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/trading_calendar/2026-04-19.csv",
            },
            "asset_coverage": {
                "dataset": "asset_coverage",
                "status": "success",
                "row_count": 8,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/asset_coverage/2026-04-19.csv",
            },
            "run_health": {
                "dataset": "run_health",
                "status": "success",
                "row_count": 1,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/run_health/2026-04-19.csv",
            },
            "run_history": {
                "dataset": "run_history",
                "status": "success",
                "row_count": 4,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/run_history/2026-04-19.csv",
            },
            "coverage_history": {
                "dataset": "coverage_history",
                "status": "success",
                "row_count": 8,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/coverage_history/2026-04-19.csv",
            },
            "validation_results": {
                "dataset": "validation_results",
                "status": "success",
                "row_count": 33,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/validation_results/2026-04-19.csv",
            },
            "source_health": {
                "dataset": "source_health",
                "status": "success",
                "row_count": 1,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/source_health/2026-04-19.csv",
            },
            "source_health_history": {
                "dataset": "source_health_history",
                "status": "success",
                "row_count": 3,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/source_health_history/2026-04-19.csv",
            },
            "source_type_overview": {
                "dataset": "source_type_overview",
                "status": "success",
                "row_count": 1,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/source_type_overview/2026-04-19.csv",
            },
            "issue_category_overview": {
                "dataset": "issue_category_overview",
                "status": "success",
                "row_count": 2,
                "trade_date": "2026-04-19",
                "output_path": "data/normalized/platform/issue_category_overview/2026-04-19.csv",
            },
        }

    def sync(self, trade_date_value="latest"):
        self.sync_calls.append(trade_date_value)
        return {"trade_date": "2026-04-21", "status": "success"}


def _fake_manifest_reader(_path):
    return [
        {
            "dataset": "yield_curves",
            "file_count": 1,
            "row_count": 23,
            "built_at": "2026-04-20T17:27:06.755163+08:00",
        },
        {
            "dataset": "crypto_cme_bitcoin_report",
            "file_count": 2,
            "row_count": 5,
            "built_at": "2026-04-20T17:27:02.876969+08:00",
        },
    ]


def _fake_pregrab_state_reader(**_kwargs):
    return {
        "updated_at": "2026-04-21T09:30:00+08:00",
        "runs": [
            {
                "run_id": "pregrab-1",
                "mode": "trial",
                "window_start": "2026-01-21",
                "window_end": "2026-04-21",
                "status": "partial_success",
                "engineering_status": "success",
                "cleanup_status": "cleaned",
                "exchange_results": {
                    "CFFEX": {
                        "exchange": "CFFEX",
                        "status": "partial_success",
                        "engineering_status": "success",
                        "elapsed_seconds": 15.2,
                        "day_count": 61,
                        "success_count": 60,
                        "no_data_count": 0,
                        "not_applicable_count": 0,
                        "blocked_external_count": 1,
                        "failed_count": 0,
                        "passed": False,
                        "engineering_passed": True,
                        "blocked_issues": ["publication lag"],
                        "failed_days": [],
                        "blocked_days": ["2026-04-17"],
                    }
                },
            }
        ],
    }


def _fake_window_state_reader(**_kwargs):
    return {
        "updated_at": "2026-04-21T11:00:00+08:00",
        "runs": [
            {
                "run_id": "window-1",
                "action_name": "sync_public_assets_window",
                "scope": "public_assets",
                "mode": "production",
                "target": "equities_spot_snapshot",
                "window_start": "2026-04-01",
                "window_end": "2026-04-21",
                "status": "partial_success",
                "engineering_status": "success",
                "elapsed_seconds": 12.3,
                "date_counts": {"success": 10, "pending_retry": 1},
                "issue_category_counts": {"dns_failure": 1},
                "blocked_issues": ["2026-04-08: pending_retry"],
                "details": {"date_results": {"2026-04-08": {"status": "pending_retry"}}},
                "updated_at": "2026-04-21T11:00:00+08:00",
            }
        ],
    }


def _fake_regression_state_reader():
    return {
        "updated_at": "2026-04-20T10:30:00+08:00",
        "result": {
            "status": "success",
            "engineering_status": "success",
            "dates": ["2010-04-16", "2015-04-16", "2021-04-16", "2026-04-16"],
            "date_statuses": {
                "2010-04-16": "success",
                "2015-04-16": "success",
                "2021-04-16": "success",
                "2026-04-16": "success",
            },
            "window_results": {
                "latest_7_trading_days": {
                    "status": "success",
                    "sample_count": 4,
                    "sampled_dates": ["2026-04-14", "2026-04-15", "2026-04-16", "2026-04-17"],
                    "status_counts": {"success": 4},
                }
            },
            "audit": {
                "needs_repair_dates": [],
                "issue_category_counts": {"result_chain_publication_lag": 1},
                "blocked_issues": ["options_exercise_results: missing exchanges [CFFEX] are pending official publication"],
            },
            "platform_sync_status": "success",
            "platform_validation_status": "success",
            "build_db_status": "success",
            "gui_smoke": {"has_yield_curves": True},
        },
    }


class DashboardAppTests(unittest.TestCase):
    def test_build_context_loads_preview_and_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_path = root / "data" / "normalized" / "options" / "daily_quotes" / "2026-04-16.csv"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text(
                "trade_date,asset_family,market,exchange,instrument_type,symbol,contract,currency,tenor\n"
                "2026-04-16,exchange_derivatives_cn,cn_options,SSE,option,510050C2604M02650,510050C2604M02650,CNY,1M\n"
                "2026-04-16,exchange_derivatives_cn,cn_options,SZSE,option,159919C2604M04000A,159919C2604M04000A,CNY,2M\n",
                encoding="utf-8-sig",
            )
            source_health_path = root / "data" / "normalized" / "platform" / "source_health" / "2026-04-19.csv"
            source_health_path.parent.mkdir(parents=True, exist_ok=True)
            source_health_path.write_text(
                "trade_date,source_id,asset_family,market,exchange,dataset,source_type,priority,source_url,last_status,last_trade_date,last_success_trade_date,output_path,issue_category,issue_root_cause,is_external_blocker,blocked_reason,message\n"
                "2026-04-19,cffex.options_exercise_results,exchange_derivatives_cn,cn_options,CFFEX,options_exercise_results,official,2,http://www.cffex.com.cn,pending_retry,2026-04-17,2021-04-16,data/normalized/results/options_exercise/2026-04-17.csv,blocked_issue,publication_lag,true,official publication lag,monthly report pending\n",
                encoding="utf-8-sig",
            )
            asset_coverage_path = root / "data" / "normalized" / "platform" / "asset_coverage" / "2026-04-19.csv"
            asset_coverage_path.parent.mkdir(parents=True, exist_ok=True)
            asset_coverage_path.write_text(
                "trade_date,asset_family,family_label,phase,registry_status,engineering_status,runtime_status,latest_trade_date,latest_success_trade_date,expected_dataset_count,observed_dataset_count,success_dataset_count,non_success_dataset_count,blocked_issue_count,external_issue_count,internal_issue_count,total_row_count,coverage_ratio,datasets,missing_datasets,status_counts,issue_root_cause_counts,markets,notes,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,exchange_derivatives_cn,国内场内衍生品,A/B,implemented,done,success,2026-04-16,2026-04-16,8,8,8,0,0,0,0,20923,8/8,\"[\"\"futures_daily_quotes\"\"]\",[],\"{\"\"success\"\": 8}\",\"{\"\"healthy\"\": 8}\",\"[\"\"SHFE\"\"]\",ok,platform.asset_coverage,state/platform_metadata.json,derived,2026-04-20T10:31:00+08:00,state/platform_metadata.json,platform_metadata_v1,ac1,run19\n",
                encoding="utf-8-sig",
            )
            source_type_overview_path = root / "data" / "normalized" / "platform" / "source_type_overview" / "2026-04-19.csv"
            source_type_overview_path.parent.mkdir(parents=True, exist_ok=True)
            source_type_overview_path.write_text(
                "trade_date,source_type,source_count,dataset_count,success_count,non_success_count,blocked_issue_count,latest_trade_date,status_counts,source_ids,source_id,source_url,source_type_origin,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,official,2,2,1,1,1,2026-04-17,\"{\"\"success\"\": 1, \"\"pending_retry\"\": 1}\",\"[\"\"shfe.futures\"\", \"\"cffex.options_exercise_results\"\"]\",platform.source_type_overview,state/platform_metadata.json,derived,2026-04-20T10:31:00+08:00,state/platform_metadata.json,platform_metadata_v1,sto1,run19\n",
                encoding="utf-8-sig",
            )
            issue_category_overview_path = root / "data" / "normalized" / "platform" / "issue_category_overview" / "2026-04-19.csv"
            issue_category_overview_path.parent.mkdir(parents=True, exist_ok=True)
            issue_category_overview_path.write_text(
                "trade_date,issue_category,source_count,dataset_count,blocked_issue_count,latest_trade_date,status_counts,source_type_counts,source_ids,datasets,source_id,source_url,source_type,retrieved_at,raw_path,parser_version,checksum,run_id\n"
                "2026-04-19,blocked_issue,3,2,3,2026-04-17,\"{\"\"no_data\"\": 2, \"\"pending_retry\"\": 1}\",\"{\"\"official\"\": 3}\",\"[\"\"cffex.options_exercise_results\"\", \"\"cffex.futures_delivery_results\"\", \"\"czce.options_exercise_results\"\"]\",\"[\"\"options_exercise_results\"\", \"\"futures_delivery_results\"\"]\",platform.issue_category_overview,state/platform_metadata.json,derived,2026-04-20T10:31:00+08:00,state/platform_metadata.json,platform_metadata_v1,ico1,run19\n",
                encoding="utf-8-sig",
            )
            app = DashboardApp(
                runner=_FakeRunner(),
                checkpoint_store=_FakeCheckpointStore(),
                public_asset_runner=_FakePublicRunner(),
                public_bond_runner=_FakeBondRunner(),
                public_reference_runner=_FakeReferenceRunner(),
                crypto_runner=_FakeCryptoRunner(),
                platform_metadata_runner=_FakePlatformMetadataRunner(),
                manifest_reader=_fake_manifest_reader,
                regression_state_reader=_fake_regression_state_reader,
                window_state_reader=_fake_window_state_reader,
                duckdb_path=root / "data" / "db" / "market_data.duckdb",
                project_root=root,
                query_state_dir=root / "state" / "query_runs",
            )
            context = app.build_context()

        self.assertEqual(context["selected_date"], "2026-04-16")
        self.assertEqual(context["latest_successful_trade_date"], "2026-04-16")
        self.assertEqual(context["preview"]["rows"][0]["contract"], "510050C2604M02650")
        self.assertEqual(context["selected_limit"], 20)
        self.assertEqual(context["filter_options"]["exchange"]["kind"], "select")
        self.assertEqual(context["filter_options"]["symbol"]["kind"], "datalist")
        self.assertIn("SSE", context["filter_options"]["exchange"]["choices"])
        self.assertIn("SZSE", context["filter_options"]["exchange"]["choices"])
        self.assertIn("cn_options", context["filter_options"]["market"]["choices"])
        self.assertIn("510050C2604M02650", context["filter_options"]["contract"]["choices"])
        self.assertTrue(any(item["family_id"] == "exchange_derivatives_cn" for item in context["asset_families"]))
        self.assertEqual(context["public_assets"][0]["dataset"], "bse_equities_spot_snapshot")
        self.assertTrue(any(item["dataset"] == "lof_spot_snapshot" for item in context["public_assets"]))
        self.assertTrue(any(item["dataset"] == "open_fund_nav_snapshot" for item in context["public_assets"]))
        self.assertTrue(any(item["dataset"] == "money_market_fund_snapshot" for item in context["public_assets"]))
        self.assertTrue(any(item["dataset"] == "sge_spot_daily_quotes" for item in context["public_assets"]))
        self.assertTrue(any(item["dataset"] == "carbon_market_snapshot" for item in context["public_assets"]))
        self.assertEqual(context["public_bonds"][0]["dataset"], "interbank_bond_deal_snapshot")
        self.assertTrue(any(item["dataset"] == "sse_bond_deal_summary" for item in context["public_bonds"]))
        self.assertTrue(any(item["dataset"] == "fx_reference_rates" for item in context["public_references"]))
        self.assertTrue(any(item["dataset"] == "fx_spot_quotes" for item in context["public_references"]))
        self.assertTrue(any(item["dataset"] == "rmb_middle_rates" for item in context["public_references"]))
        self.assertTrue(any(item["dataset"] == "fx_pair_quotes" for item in context["public_references"]))
        self.assertTrue(any(item["dataset"] == "fx_swap_quotes" for item in context["public_references"]))
        self.assertTrue(any(item["dataset"] == "fx_c_swap_curve" for item in context["public_references"]))
        self.assertTrue(any(item["dataset"] == "reserve_reference_series" for item in context["public_references"]))
        self.assertTrue(any(item["dataset"] == "cn_us_treasury_yields" for item in context["public_references"]))
        self.assertTrue(any(item["dataset"] == "reserve_reference_series" for item in context["preview_options"]))
        self.assertTrue(any(item["dataset"] == "cn_us_treasury_yields" for item in context["preview_options"]))
        self.assertTrue(any(item["dataset"] == "fx_c_swap_curve" for item in context["preview_options"]))
        self.assertTrue(any(item["dataset"] == "crypto_global_snapshot" for item in context["crypto_observation"]))
        self.assertTrue(any(item["dataset"] == "crypto_daily_quotes" for item in context["crypto_observation"]))
        self.assertTrue(any(item["dataset"] == "crypto_bitcoin_holdings_public" for item in context["crypto_observation"]))
        self.assertTrue(any(item["dataset"] == "crypto_cme_bitcoin_report" for item in context["crypto_observation"]))
        self.assertTrue(any(item["dataset"] == "instrument_master" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "bond_master" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "fx_quotes" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "commodity_spot_quotes" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "crypto_global_quotes" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "daily_ohlcv" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "fund_nav" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "reits_quotes" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "trading_calendar" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "asset_coverage" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "source_type_overview" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "issue_category_overview" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "run_health" for item in context["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "validation_results" for item in context["preview_options"]))
        self.assertEqual(context["duckdb_dataset_count"], 2)
        self.assertTrue(any(item["dataset"] == "yield_curves" for item in context["duckdb_manifest"]))
        self.assertEqual(context["regression_smoke"]["status"], "success")
        self.assertEqual(context["regression_smoke"]["engineering_status"], "success")
        self.assertEqual(context["window_runs"][0]["action_name"], "sync_public_assets_window")
        self.assertEqual(context["regression_smoke"]["audit"]["issue_category_counts"], {"result_chain_publication_lag": 1})
        self.assertEqual(
            context["regression_smoke"]["audit"]["blocked_issues"],
            ["options_exercise_results: missing exchanges [CFFEX] are pending official publication"],
        )
        self.assertEqual(context["regression_smoke"]["window_results"]["latest_7_trading_days"]["sample_count"], 4)
        self.assertTrue(any(item["source_id"] == "shfe.futures" for item in context["source_catalog"]))
        self.assertIn("official", context["source_type_counts"])
        self.assertTrue(any(item["source_id"] == "cffex.options_exercise_results" for item in context["source_health_rows"]))
        self.assertTrue(any(item["issue_root_cause"] == "publication_lag" for item in context["source_health_rows"]))
        self.assertTrue(any(item["is_external_blocker"] == "true" for item in context["source_health_rows"]))
        self.assertTrue(any(item["source_type"] == "official" for item in context["source_type_overview_rows"]))
        self.assertTrue(any(item["issue_category"] == "blocked_issue" for item in context["issue_category_overview_rows"]))
        self.assertTrue(any(item["asset_family"] == "exchange_derivatives_cn" for item in context["asset_coverage_rows"]))
        self.assertEqual(context["asset_coverage_status_counts"], {"success": 1})
        self.assertEqual(context["asset_coverage_engineering_counts"], {"done": 1})

    def test_build_context_applies_preview_filters(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_path = root / "data" / "normalized" / "options" / "daily_quotes" / "2026-04-16.csv"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text(
                "trade_date,asset_family,market,exchange,instrument_type,symbol,contract,currency,tenor\n"
                "2026-04-16,exchange_derivatives_cn,cn_options,SSE,option,510050C2604M02650,510050C2604M02650,CNY,1M\n"
                "2026-04-16,exchange_derivatives_cn,cn_options,SZSE,option,159919C2604M04000A,159919C2604M04000A,CNY,2M\n",
                encoding="utf-8-sig",
            )
            app = DashboardApp(
                runner=_FakeRunner(),
                checkpoint_store=_FakeCheckpointStore(),
                public_asset_runner=_FakePublicRunner(),
                public_bond_runner=_FakeBondRunner(),
                public_reference_runner=_FakeReferenceRunner(),
                crypto_runner=_FakeCryptoRunner(),
                platform_metadata_runner=_FakePlatformMetadataRunner(),
                manifest_reader=_fake_manifest_reader,
                regression_state_reader=_fake_regression_state_reader,
                window_state_reader=_fake_window_state_reader,
                duckdb_path=root / "data" / "db" / "market_data.duckdb",
                project_root=root,
                query_state_dir=root / "state" / "query_runs",
            )
            context = app.build_context(filters={"exchange": "SSE"})

        self.assertEqual(context["selected_filters"], {"exchange": "SSE"})
        self.assertEqual(len(context["preview"]["rows"]), 1)
        self.assertEqual(context["preview"]["rows"][0]["exchange"], "SSE")
        self.assertIn("SSE", context["filter_options"]["exchange"]["choices"])

    def test_wsgi_root_route_returns_html(self):
        app = DashboardApp(
            runner=_FakeRunner(),
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            window_state_reader=_fake_window_state_reader,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
        )
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(app({"PATH_INFO": "/", "QUERY_STRING": ""}, start_response)).decode("utf-8")
        self.assertEqual(captured["status"], "200 OK")
        self.assertIn("text/html", captured["headers"]["Content-Type"])
        self.assertIn("多资产数据平台 GUI", body)
        self.assertIn("公开参考数据", body)
        self.assertIn("北交所股票快照", body)
        self.assertIn("LOF 基金快照", body)
        self.assertIn("开放式基金净值快照", body)
        self.assertIn("货币基金收益快照", body)
        self.assertIn("上金所现货日行情", body)
        self.assertIn("国内碳市场快照", body)
        self.assertIn("可转债快照", body)
        self.assertIn("债券与收益率曲线", body)
        self.assertIn("上交所债券成交概览", body)
        self.assertIn("全球加密观察", body)
        self.assertIn("全球公开比特币持仓参考", body)
        self.assertIn("CME 比特币公开报告", body)
        self.assertIn("人民币外汇即期报价", body)
        self.assertIn("人民币汇率中间价", body)
        self.assertIn("外币对即期报价", body)
        self.assertIn("人民币外汇远掉报价", body)
        self.assertIn("USD/CNY C-Swap 曲线", body)
        self.assertIn("外汇与黄金储备参考序列", body)
        self.assertIn("中美国债收益率", body)
        self.assertIn("公开参考 / 外汇与黄金储备参考序列", body)
        self.assertIn("平台元数据与质量", body)
        self.assertIn("DuckDB 索引概览", body)
        self.assertIn("最近 regression-smoke", body)
        self.assertIn("result_chain_publication_lag", body)
        self.assertIn("运行中资产族状态", body)
        self.assertIn("工程收口状态", body)
        self.assertIn("源注册与 provenance", body)
        self.assertIn("根因", body)
        self.assertIn("外部阻塞", body)
        self.assertIn("阻塞原因", body)
        self.assertIn("源类型运行总览", body)
        self.assertIn("shfe.futures", body)
        self.assertIn("fallback_online", body)
        self.assertIn("success/非success", body)
        self.assertIn("crypto_cme_bitcoin_report", body)
        self.assertIn("数据质量阻塞与修复", body)
        self.assertIn("公开源阻塞", body)
        self.assertIn("打开独立抓取工作台", body)
        self.assertNotIn("开始逐交易所预抓", body)

    def test_wsgi_crawl_route_returns_standalone_crawl_page(self):
        app = DashboardApp(
            runner=_FakeRunner(),
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            pregrab_state_reader=_fake_pregrab_state_reader,
            window_state_reader=_fake_window_state_reader,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
        )
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(app({"PATH_INFO": "/crawl", "QUERY_STRING": ""}, start_response)).decode("utf-8")
        self.assertEqual(captured["status"], "200 OK")
        self.assertIn("text/html", captured["headers"]["Content-Type"])
        self.assertIn("抓取工作台", body)
        self.assertIn("抓取控制台", body)
        self.assertIn("开始逐交易所预抓", body)
        self.assertIn("历史窗口同步（多资产）", body)
        self.assertIn("环境健康检查", body)
        self.assertIn('name="return_path" value="/crawl"', body)
        self.assertIn("开始区间回补", body)
        self.assertIn("默认不选交易所时，衍生品抓取走 canonical all-scope", body)
        self.assertIn("SHFE / INE / CFFEX / CZCE / DCE / GFEX", body)
        self.assertIn("一键抓取当前已接入的全部数据", body)
        self.assertIn("latest-view 全量链路", body)
        self.assertIn("公开资产：A 股 / 北交所 / ETF / LOF / 开放式基金 / 货币基金 / REITs / 可转债 / 上金所现货 / 碳市场", body)

    def test_wsgi_history_route_returns_history_page(self):
        app = DashboardApp(
            runner=_FakeRunner(),
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            window_state_reader=_fake_window_state_reader,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
        )
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(app({"PATH_INFO": "/history", "QUERY_STRING": ""}, start_response)).decode("utf-8")
        self.assertEqual(captured["status"], "200 OK")
        self.assertIn("历史研究页", body)
        self.assertIn("运行历史", body)
        self.assertIn("资产覆盖历史", body)
        self.assertIn("source health 历史", body)

    def test_wsgi_quality_route_returns_quality_page(self):
        app = DashboardApp(
            runner=_FakeRunner(),
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            window_state_reader=_fake_window_state_reader,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
        )
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(app({"PATH_INFO": "/quality", "QUERY_STRING": ""}, start_response)).decode("utf-8")
        self.assertEqual(captured["status"], "200 OK")
        self.assertIn("质量趋势页", body)
        self.assertIn("窗口任务历史", body)
        self.assertIn("运行趋势", body)
        self.assertIn("覆盖率趋势", body)
        self.assertIn("数据质量评分", body)
        self.assertIn("异常事件", body)
        self.assertIn('name="action_name" value="quality_score"', body)

    def test_wsgi_strategies_route_exposes_algorithm_templates_and_empty_state(self):
        app = DashboardApp(
            runner=_FakeRunner(),
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            window_state_reader=_fake_window_state_reader,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
        )
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(app({"PATH_INFO": "/strategies", "QUERY_STRING": ""}, start_response)).decode("utf-8")
        self.assertEqual(captured["status"], "200 OK")
        self.assertIn("策略研究台", body)
        self.assertIn("算法工作台", body)
        self.assertIn("算法只做本地研究", body)
        self.assertIn("因子信号生成", body)
        self.assertIn('name="action_name" value="factor_run"', body)
        self.assertIn('name="action_name" value="algorithm_run"', body)
        self.assertIn('name="action_name" value="risk_run"', body)
        self.assertIn('name="action_name" value="portfolio_optimize"', body)
        self.assertIn('name="action_name" value="backtest_run"', body)
        self.assertIn('name="action_name" value="ml_run"', body)
        self.assertIn('name="action_name" value="factor_performance"', body)
        self.assertIn('name="action_name" value="stress_test"', body)
        self.assertIn("动量因子", body)
        self.assertIn("均值回归因子", body)
        self.assertIn("波动率过滤因子", body)
        self.assertIn("Black-Scholes 定价", body)
        self.assertIn("VaR / CVaR", body)
        self.assertIn("风险平价", body)
        self.assertIn("机器学习研究", body)
        self.assertIn("ML 训练诊断", body)
        self.assertIn("因子表现评估", body)
        self.assertIn("压力测试", body)
        self.assertIn("实验历史", body)
        self.assertIn("股票/ETF/基金/REITs 日频价格", body)
        self.assertIn("尚未生成因子信号", body)
        self.assertIn("尚未运行算法模板", body)
        self.assertIn("尚未生成风险指标", body)
        self.assertIn("尚未运行正式回测", body)
        self.assertIn("尚未运行 ML 研究", body)
        self.assertIn("暂无 ML 训练诊断", body)
        self.assertIn("尚未评估因子表现", body)
        self.assertIn("尚未运行压力测试", body)
        self.assertIn("尚未生成模拟组合", body)

    def test_wsgi_scheduler_route_clarifies_due_tasks_and_manual_run(self):
        scheduler = _FakeSchedulerRunner()
        app = DashboardApp(
            runner=_FakeRunner(),
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            window_state_reader=_fake_window_state_reader,
            scheduler_runner=scheduler,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
            run_jobs_async=False,
        )
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(app({"PATH_INFO": "/scheduler", "QUERY_STRING": ""}, start_response)).decode("utf-8")
        self.assertEqual(captured["status"], "200 OK")
        self.assertIn("运行所有到期任务", body)
        self.assertIn("到期任务 1 个", body)
        self.assertIn("每日 DuckDB 重建", body)
        self.assertIn("手动运行", body)

    def test_wsgi_scheduler_manual_run_calls_specific_schedule(self):
        scheduler = _FakeSchedulerRunner()
        app = DashboardApp(
            runner=_FakeRunner(),
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            window_state_reader=_fake_window_state_reader,
            scheduler_runner=scheduler,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
            run_jobs_async=False,
        )
        payload = b"action_name=scheduler_run_one&return_path=/scheduler&schedule_id=daily_build_db"
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body_iter = app(
            {
                "PATH_INFO": "/run",
                "REQUEST_METHOD": "POST",
                "QUERY_STRING": "",
                "CONTENT_LENGTH": str(len(payload)),
                "wsgi.input": io.BytesIO(payload),
            },
            start_response,
        )
        b"".join(body_iter)
        self.assertEqual(captured["status"], "303 See Other")
        self.assertEqual(dict(captured["headers"])["Location"], "/scheduler?schedule_id=daily_build_db")
        self.assertEqual(scheduler.calls[-1], ("tick", True, "daily_build_db"))

    def test_wsgi_reports_route_links_latest_report_and_serves_safe_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            report_dir = root / "reports" / "2026-04-25"
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / "daily_report.html").write_text("<h1>daily ok</h1>", encoding="utf-8")
            (report_dir / "daily_report.md").write_text("# daily ok", encoding="utf-8")
            app = DashboardApp(
                runner=_FakeRunner(),
                checkpoint_store=_FakeCheckpointStore(),
                public_asset_runner=_FakePublicRunner(),
                public_bond_runner=_FakeBondRunner(),
                public_reference_runner=_FakeReferenceRunner(),
                crypto_runner=_FakeCryptoRunner(),
                platform_metadata_runner=_FakePlatformMetadataRunner(),
                manifest_reader=_fake_manifest_reader,
                regression_state_reader=_fake_regression_state_reader,
                window_state_reader=_fake_window_state_reader,
                duckdb_path=root / "data" / "db" / "market_data.duckdb",
                project_root=root,
                query_state_dir=root / "state" / "query_runs",
                reports_dir=root / "reports",
            )
            captured = {}

            def start_response(status, headers):
                captured["status"] = status
                captured["headers"] = dict(headers)

            body = b"".join(app({"PATH_INFO": "/reports", "QUERY_STRING": ""}, start_response)).decode("utf-8")
            self.assertEqual(captured["status"], "200 OK")
            self.assertIn('value="2026-04-25"', body)
            self.assertIn("报告类型", body)
            self.assertIn("综合报告", body)
            self.assertIn("报告图表与附件", body)
            self.assertIn("产物血缘 Manifest", body)
            self.assertIn("/reports/file?date=2026-04-25&amp;file=daily_report.html", body)

            html_captured = {}

            def html_start_response(status, headers):
                html_captured["status"] = status
                html_captured["headers"] = dict(headers)

            html_body = b"".join(
                app(
                    {"PATH_INFO": "/reports/file", "QUERY_STRING": "date=2026-04-25&file=daily_report.html"},
                    html_start_response,
                )
            ).decode("utf-8")
            self.assertEqual(html_captured["status"], "200 OK")
            self.assertIn("text/html", html_captured["headers"]["Content-Type"])
            self.assertIn("daily ok", html_body)

            bad_captured = {}

            def bad_start_response(status, headers):
                bad_captured["status"] = status
                bad_captured["headers"] = dict(headers)

            bad_body = b"".join(
                app(
                    {"PATH_INFO": "/reports/file", "QUERY_STRING": "date=2026-04-25&file=../secret.txt"},
                    bad_start_response,
                )
            ).decode("utf-8")
            self.assertEqual(bad_captured["status"], "400 Bad Request")
            self.assertIn("unsupported report file", bad_body)

    def test_wsgi_root_route_renders_filter_selects_and_datalists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            csv_path = root / "data" / "normalized" / "options" / "daily_quotes" / "2026-04-16.csv"
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text(
                "trade_date,asset_family,market,exchange,instrument_type,symbol,contract,currency,tenor\n"
                "2026-04-16,exchange_derivatives_cn,cn_options,SSE,option,510050C2604M02650,510050C2604M02650,CNY,1M\n"
                "2026-04-16,exchange_derivatives_cn,cn_options,SZSE,option,159919C2604M04000A,159919C2604M04000A,CNY,2M\n",
                encoding="utf-8-sig",
            )
            app = DashboardApp(
                runner=_FakeRunner(),
                checkpoint_store=_FakeCheckpointStore(),
                public_asset_runner=_FakePublicRunner(),
                public_bond_runner=_FakeBondRunner(),
                public_reference_runner=_FakeReferenceRunner(),
                crypto_runner=_FakeCryptoRunner(),
                platform_metadata_runner=_FakePlatformMetadataRunner(),
                manifest_reader=_fake_manifest_reader,
                regression_state_reader=_fake_regression_state_reader,
                duckdb_path=root / "data" / "db" / "market_data.duckdb",
                project_root=root,
                query_state_dir=root / "state" / "query_runs",
            )
            captured = {}

            def start_response(status, headers):
                captured["status"] = status
                captured["headers"] = dict(headers)

            body = b"".join(app({"PATH_INFO": "/", "QUERY_STRING": ""}, start_response)).decode("utf-8")

        self.assertEqual(captured["status"], "200 OK")
        self.assertIn('<select name="asset_family">', body)
        self.assertIn('<select name="market">', body)
        self.assertIn('<select name="exchange">', body)
        self.assertIn('<select name="instrument_type">', body)
        self.assertIn('<select name="currency">', body)
        self.assertIn('<select name="tenor">', body)
        self.assertIn('list="filter-options-symbol"', body)
        self.assertIn('list="filter-options-contract"', body)
        self.assertIn("cn_options", body)
        self.assertIn("SSE", body)

    def test_post_run_starts_gui_crawl_job_and_records_result(self):
        runner = _FakeRunner()
        public_runner = _FakePublicRunner()
        app = DashboardApp(
            runner=runner,
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=public_runner,
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
            run_jobs_async=False,
        )
        body = "action_name=sync_public_assets&sync_date=latest".encode("utf-8")
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/run",
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": tempfile.SpooledTemporaryFile(),
        }
        environ["wsgi.input"].write(body)
        environ["wsgi.input"].seek(0)

        response = list(app(environ, start_response))

        self.assertEqual(captured["status"], "303 See Other")
        self.assertEqual(response, [b""])
        self.assertEqual(public_runner.sync_calls, [("latest", (), False)])
        self.assertEqual(len(app.jobs), 1)
        self.assertEqual(app.jobs[0]["action"], "sync_public_assets")
        self.assertEqual(app.jobs[0]["status"], "success")
        self.assertIn("trade_date", app.jobs[0]["result_text"])

    def test_build_context_includes_pregrab_runs(self):
        app = DashboardApp(
            runner=_FakeRunner(),
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            pregrab_state_reader=_fake_pregrab_state_reader,
            window_state_reader=_fake_window_state_reader,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
        )
        context = app.build_context()

        self.assertTrue(context["pregrab_runs"])
        self.assertEqual(context["pregrab_runs"][0]["exchange"], "CFFEX")
        self.assertEqual(context["pregrab_runs"][0]["cleanup_status"], "cleaned")
        self.assertTrue(context["window_runs"])
        self.assertEqual(context["window_runs"][0]["scope"], "public_assets")

    def test_post_run_pregrab_window_records_summary(self):
        captured_runs = []

        def fake_writer(result, **_kwargs):
            captured_runs.append(result)
            return {"runs": [result]}

        def fake_subprocess_runner(command, **_kwargs):
            self.assertIn("pregrab-window", command)
            self.assertIn("--exchange", command)
            payload = {
                "run_id": "pregrab-2",
                "mode": "trial",
                "window_start": "2026-01-21",
                "window_end": "2026-04-21",
                "status": "partial_success",
                "engineering_status": "success",
                "date_counts": {"success": 60, "blocked_issue": 1},
                "blocked_issues": ["publication lag"],
                "exchange_results": {
                    "CFFEX": {
                        "exchange": "CFFEX",
                        "status": "partial_success",
                        "engineering_status": "success",
                        "elapsed_seconds": 15.2,
                        "day_count": 61,
                        "success_count": 60,
                        "no_data_count": 0,
                        "not_applicable_count": 0,
                        "blocked_external_count": 1,
                        "failed_count": 0,
                        "passed": False,
                        "engineering_passed": True,
                        "blocked_issues": ["publication lag"],
                        "failed_days": [],
                        "blocked_days": ["2026-04-17"],
                    }
                },
            }
            return mock.Mock(returncode=0, stdout=json.dumps(payload, ensure_ascii=False), stderr="")

        app = DashboardApp(
            runner=_FakeRunner(),
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            pregrab_state_reader=_fake_pregrab_state_reader,
            pregrab_state_writer=fake_writer,
            subprocess_runner=fake_subprocess_runner,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
            run_jobs_async=False,
        )
        body = "action_name=pregrab_window&pregrab_preset=latest_3m&pregrab_mode=trial&pregrab_exchange=CFFEX&pregrab_exchange=DCE&end_date=2026-04-21".encode("utf-8")
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/run",
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": tempfile.SpooledTemporaryFile(),
        }
        environ["wsgi.input"].write(body)
        environ["wsgi.input"].seek(0)

        response = list(app(environ, start_response))

        self.assertEqual(captured["status"], "303 See Other")
        self.assertEqual(response, [b""])
        self.assertEqual(app.jobs[0]["action"], "pregrab_window")
        self.assertEqual(app.jobs[0]["status"], "partial_success")
        self.assertIn("engineering_status", app.jobs[0]["result_text"])
        self.assertEqual(len(captured_runs), 1)
        self.assertEqual(captured_runs[0]["cleanup_status"], "cleaned")

    def test_post_run_with_return_path_redirects_back_to_crawl_page(self):
        runner = _FakeRunner()
        app = DashboardApp(
            runner=runner,
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
            run_jobs_async=False,
        )
        body = "action_name=fetch_date&return_path=%2Fcrawl&run_date=2026-04-16&instrument_group=all".encode("utf-8")
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/run",
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": tempfile.SpooledTemporaryFile(),
        }
        environ["wsgi.input"].write(body)
        environ["wsgi.input"].seek(0)

        response = list(app(environ, start_response))

        self.assertEqual(captured["status"], "303 See Other")
        self.assertEqual(captured["headers"]["Location"], "/crawl")
        self.assertEqual(response, [b""])

    def test_wsgi_json_route_returns_summary_json(self):
        app = DashboardApp(
            runner=_FakeRunner(),
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            window_state_reader=_fake_window_state_reader,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
        )
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(app({"PATH_INFO": "/api/summary.json", "QUERY_STRING": ""}, start_response)).decode("utf-8")
        payload = json.loads(body)
        self.assertEqual(captured["status"], "200 OK")
        self.assertIn("application/json", captured["headers"]["Content-Type"])
        self.assertEqual(payload["selected_date"], "2026-04-16")
        self.assertEqual(payload["public_bonds"][0]["dataset"], "interbank_bond_deal_snapshot")
        self.assertTrue(any(item["dataset"] == "sge_spot_daily_quotes" for item in payload["public_assets"]))
        self.assertTrue(any(item["dataset"] == "carbon_market_snapshot" for item in payload["public_assets"]))
        self.assertTrue(any(item["dataset"] == "fx_reference_rates" for item in payload["public_references"]))
        self.assertTrue(any(item["dataset"] == "rmb_middle_rates" for item in payload["public_references"]))
        self.assertTrue(any(item["dataset"] == "cn_us_treasury_yields" for item in payload["public_references"]))
        self.assertTrue(any(item["dataset"] == "crypto_global_snapshot" for item in payload["crypto_observation"]))
        self.assertTrue(any(item["dataset"] == "crypto_bitcoin_holdings_public" for item in payload["crypto_observation"]))
        self.assertTrue(any(item["dataset"] == "crypto_cme_bitcoin_report" for item in payload["crypto_observation"]))
        self.assertTrue(any(item["dataset"] == "instrument_master" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "bond_master" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "fx_quotes" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "daily_ohlcv" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "fund_nav" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "reits_quotes" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "trading_calendar" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "asset_coverage" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "run_history" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "coverage_history" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "source_type_overview" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "issue_category_overview" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "run_health" for item in payload["platform_metadata"]))
        self.assertTrue(any(item["dataset"] == "source_health_history" for item in payload["platform_metadata"]))
        self.assertIsInstance(payload["asset_coverage_rows"], list)
        self.assertIsInstance(payload["asset_coverage_status_counts"], dict)
        self.assertIsInstance(payload["asset_coverage_engineering_counts"], dict)
        self.assertIsInstance(payload["source_type_overview_rows"], list)
        self.assertIsInstance(payload["issue_category_overview_rows"], list)
        self.assertIsInstance(payload["window_runs"], list)
        self.assertIsInstance(payload["run_history_rows"], list)
        self.assertIsInstance(payload["coverage_history_rows"], list)
        self.assertIsInstance(payload["source_health_history_rows"], list)
        self.assertEqual(payload["duckdb_dataset_count"], 2)
        self.assertTrue(any(item["dataset"] == "crypto_cme_bitcoin_report" for item in payload["duckdb_manifest"]))
        self.assertEqual(payload["regression_smoke"]["status"], "success")
        self.assertEqual(payload["regression_smoke"]["engineering_status"], "success")
        self.assertEqual(payload["window_runs"][0]["scope"], "public_assets")
        self.assertEqual(payload["regression_smoke"]["audit"]["issue_category_counts"], {"result_chain_publication_lag": 1})
        self.assertEqual(
            payload["regression_smoke"]["audit"]["blocked_issues"],
            ["options_exercise_results: missing exchanges [CFFEX] are pending official publication"],
        )
        self.assertEqual(payload["regression_smoke"]["window_results"]["latest_7_trading_days"]["status"], "success")
        self.assertTrue(any(item["source_id"] == "shfe.futures" for item in payload["source_catalog"]))
        self.assertIn("official", payload["source_type_counts"])
        self.assertIsInstance(payload["source_health_rows"], list)
        self.assertEqual(payload["audit"]["needs_repair"], False)
        self.assertTrue(payload["audit"]["blocked_issues"])
        self.assertEqual(payload["audit"]["issue_categories"], {"result_chain_source_gap": 1})

    def test_wsgi_download_route_exports_selected_dataset(self):
        app = DashboardApp(
            runner=_FakeRunner(),
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
        )
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            output_path = tmp_root / "options_daily_quotes" / "2026-04-16.csv"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("trade_date,exchange\n2026-04-16,SSE\n", encoding="utf-8-sig")
            app.project_root = tmp_root
            with mock.patch(
                "src.futures_workflow.gui.export_dataset",
                return_value={
                    "dataset": "options_daily_quotes",
                    "trade_date": "2026-04-16",
                    "output_format": "csv",
                    "row_count": 1,
                    "output_path": str(output_path.relative_to(tmp_root)),
                },
            ):
                body = b"".join(
                    app(
                        {
                            "PATH_INFO": "/download",
                            "QUERY_STRING": "dataset=options_daily_quotes&date=2026-04-16&format=csv&exchange=SSE",
                        },
                        start_response,
                    )
                ).decode("utf-8-sig")
        self.assertEqual(captured["status"], "200 OK")
        self.assertIn("attachment;", captured["headers"]["Content-Disposition"])
        self.assertIn("text/csv", captured["headers"]["Content-Type"])
        self.assertIn("trade_date,exchange", body)

    def test_wsgi_download_route_forwards_filters(self):
        app = DashboardApp(
            runner=_FakeRunner(),
            checkpoint_store=_FakeCheckpointStore(),
            public_asset_runner=_FakePublicRunner(),
            public_bond_runner=_FakeBondRunner(),
            public_reference_runner=_FakeReferenceRunner(),
            crypto_runner=_FakeCryptoRunner(),
            platform_metadata_runner=_FakePlatformMetadataRunner(),
            manifest_reader=_fake_manifest_reader,
            regression_state_reader=_fake_regression_state_reader,
            duckdb_path=ROOT / "data" / "db" / "market_data.duckdb",
            project_root=ROOT,
            query_state_dir=ROOT / "state" / "query_runs",
        )
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            output_path = tmp_root / "options_daily_quotes" / "2026-04-16.json"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("[]", encoding="utf-8")
            app.project_root = tmp_root
            with mock.patch(
                "src.futures_workflow.gui.export_dataset",
                return_value={
                    "dataset": "options_daily_quotes",
                    "trade_date": "2026-04-16",
                    "output_format": "json",
                    "row_count": 0,
                    "filters": {"exchange": "SSE", "contract": "510050C2604M02650"},
                    "output_path": str(output_path.relative_to(tmp_root)),
                },
            ) as export_mock:
                _ = b"".join(
                    app(
                        {
                            "PATH_INFO": "/download",
                            "QUERY_STRING": "dataset=options_daily_quotes&date=2026-04-16&format=json&exchange=SSE&contract=510050C2604M02650",
                        },
                        start_response,
                    )
                ).decode("utf-8")
        self.assertEqual(captured["status"], "200 OK")
        _, kwargs = export_mock.call_args
        self.assertEqual(kwargs["filters"], {"exchange": "SSE", "contract": "510050C2604M02650"})


if __name__ == "__main__":
    unittest.main()
