import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import akshare as ak
import requests

from .config import PROJECT_ROOT, PUBLIC_REFERENCES_NORMALIZED_DIR, PUBLIC_REFERENCE_STATE_PATH, RAW_DIR
from .constants import (
    CN_US_TREASURY_RATE_DATASET,
    FAILED_STATUS,
    FX_C_SWAP_CURVE_DATASET,
    FX_PAIR_DATASET,
    FX_REFERENCE_DATASET,
    RMB_MIDDLE_RATE_DATASET,
    FX_SPOT_DATASET,
    FX_SWAP_DATASET,
    LPR_REFERENCE_DATASET,
    MONEY_MARKET_DATASET,
    NO_DATA_STATUS,
    NOT_APPLICABLE_STATUS,
    PARTIAL_SUCCESS_STATUS,
    PENDING_RETRY_STATUS,
    PRECIOUS_METAL_REFERENCE_DATASET,
    PUBLIC_REFERENCE_STANDARD_FIELDS,
    RESERVE_REFERENCE_DATASET,
    REPO_REFERENCE_DATASET,
    SUCCESS_STATUS,
)
from .normalize.csv_utils import write_dict_rows_csv
from .utils import compact_trade_date, ensure_directory, format_trade_date, iso_timestamp, normalize_number, normalize_text, now_shanghai, parse_trade_date, previous_weekday, relative_to_project


PARSER_VERSION = "public_references_v1"

FX_CURRENCY_MAP = {
    "美元": "USD",
    "欧元": "EUR",
    "日元": "JPY",
    "港元": "HKD",
    "英镑": "GBP",
    "澳元": "AUD",
    "新西兰元": "NZD",
    "新加坡元": "SGD",
    "瑞士法郎": "CHF",
    "加元": "CAD",
    "澳门元": "MOP",
    "林吉特": "MYR",
    "卢布": "RUB",
    "兰特": "ZAR",
    "韩元": "KRW",
    "迪拉姆": "AED",
    "里亚尔": "SAR",
    "福林": "HUF",
    "兹罗提": "PLN",
    "丹麦克朗": "DKK",
    "瑞典克朗": "SEK",
    "挪威克朗": "NOK",
    "里拉": "TRY",
    "比索": "PHP",
    "泰铢": "THB",
}

RMB_CURRENCY_MAP = {
    **FX_CURRENCY_MAP,
    "人民币": "CNY",
    "100日元": "100JPY",
}

SHIBOR_TENOR_LABELS = {
    "O/N": "隔夜",
    "1W": "1 周",
    "2W": "2 周",
    "1M": "1 个月",
    "3M": "3 个月",
    "6M": "6 个月",
    "9M": "9 个月",
    "1Y": "1 年",
}

MONTH_TEXT_PATTERN = re.compile(r"^(?P<year>\d{4})年(?P<month>\d{1,2})月份$")
PERIOD_TEXT_PATTERN = re.compile(r"^(?P<year>\d{4})\.(?P<month>\d{1,2})$")
CN_US_TREASURY_PATTERN = re.compile(r"(?P<country>中国|美国).*?(?P<tenor>\d+(?:\.\d+)?)(?P<unit>年|月)")


class PublicReferenceRunner:
    def __init__(self, *, state_path: Path = PUBLIC_REFERENCE_STATE_PATH):
        self.state_path = state_path
        ensure_directory(self.state_path.parent)
        if not self.state_path.exists():
            self.state_path.write_text(json.dumps({"dates": {}}, ensure_ascii=False, indent=2), encoding="utf-8")

    def sync(self, trade_date_value: str = "latest", families: Optional[Iterable[str]] = None, force: bool = False) -> Dict[str, object]:
        trade_date = self._resolve_trade_date(trade_date_value)
        trade_date_str = format_trade_date(trade_date)
        requested = self._normalize_families(families)
        run_id = hashlib.sha1(f"{trade_date_str}|{iso_timestamp()}".encode("utf-8")).hexdigest()[:12]
        summaries: Dict[str, Dict[str, object]] = {}
        outputs: Dict[str, str] = {}
        row_counts: Dict[str, int] = {}

        for family_name, collector in self._collectors().items():
            if family_name not in requested:
                continue
            summary = collector(trade_date=trade_date, run_id=run_id, force=force)
            summaries[family_name] = summary
            if summary.get("status") == SUCCESS_STATUS:
                outputs[family_name] = str(summary.get("output_path", ""))
                row_counts[family_name] = int(summary.get("row_count", 0) or 0)

        statuses = {str(item.get("status", "")) for item in summaries.values()}
        if statuses and all(status == SUCCESS_STATUS for status in statuses):
            overall_status = SUCCESS_STATUS
        elif PENDING_RETRY_STATUS in statuses:
            overall_status = PENDING_RETRY_STATUS
        elif FAILED_STATUS in statuses:
            overall_status = FAILED_STATUS
        elif statuses and all(status == NOT_APPLICABLE_STATUS for status in statuses):
            overall_status = NOT_APPLICABLE_STATUS
        elif statuses and all(status == NO_DATA_STATUS for status in statuses):
            overall_status = NO_DATA_STATUS
        elif SUCCESS_STATUS in statuses or PARTIAL_SUCCESS_STATUS in statuses:
            overall_status = PARTIAL_SUCCESS_STATUS
        else:
            overall_status = NO_DATA_STATUS

        self._update_state(trade_date_str, overall_status, summaries)
        return {
            "trade_date": trade_date_str,
            "status": overall_status,
            "families": summaries,
            "outputs": outputs,
            "row_counts": row_counts,
            "run_id": run_id,
        }

    def validate(self, trade_date_value: str, families: Optional[Iterable[str]] = None) -> Dict[str, object]:
        trade_date = self._resolve_trade_date(trade_date_value)
        trade_date_str = format_trade_date(trade_date)
        requested = self._normalize_families(families)
        state = self._load_state().get("dates", {}).get(trade_date_str, {})
        family_summaries = state.get("families", {})
        datasets = {}
        statuses = []
        for family_name in requested:
            summary = family_summaries.get(family_name, {})
            output_path = summary.get("output_path", "")
            summary_status = str(summary.get("status", ""))
            csv_path = PROJECT_ROOT / output_path if output_path else None
            dataset_validation = {
                "csv_exists": bool(csv_path and csv_path.exists()),
                "schema_ok": False,
                "row_count": 0,
                "missing_raw_paths": [],
            }
            if csv_path and csv_path.exists():
                rows = list(_iter_csv_rows(csv_path))
                dataset_validation["row_count"] = len(rows)
                fieldnames = list(rows[0].keys()) if rows else PUBLIC_REFERENCE_STANDARD_FIELDS
                dataset_validation["schema_ok"] = fieldnames == PUBLIC_REFERENCE_STANDARD_FIELDS
                for row in rows:
                    raw_path = str(row.get("raw_path", "")).strip()
                    if raw_path and not (PROJECT_ROOT / raw_path).exists():
                        dataset_validation["missing_raw_paths"].append(raw_path)
            datasets[family_name] = dataset_validation
            if summary_status in {NO_DATA_STATUS, NOT_APPLICABLE_STATUS, PENDING_RETRY_STATUS, FAILED_STATUS}:
                statuses.append(summary_status)
            elif dataset_validation["csv_exists"] and dataset_validation["schema_ok"] and not dataset_validation["missing_raw_paths"]:
                statuses.append(SUCCESS_STATUS)
            else:
                statuses.append(FAILED_STATUS)
        return {
            "trade_date": trade_date_str,
            "status": _merge_statuses(statuses) if statuses else state.get("status", ""),
            "families": datasets,
        }

    def latest_summaries(self) -> Dict[str, Dict[str, object]]:
        state = self._load_state().get("dates", {})
        if not state:
            return {}
        latest_by_family: Dict[str, Dict[str, object]] = {}
        fallback_by_family: Dict[str, Dict[str, object]] = {}
        for trade_date in sorted(state.keys(), reverse=True):
            families = state[trade_date].get("families", {})
            for family_name, summary in families.items():
                fallback_by_family.setdefault(family_name, summary)
                status = str(summary.get("status", ""))
                row_count = int(summary.get("row_count", 0) or 0)
                if family_name not in latest_by_family and status == SUCCESS_STATUS and row_count > 0:
                    latest_by_family[family_name] = summary
        for family_name, summary in fallback_by_family.items():
            latest_by_family.setdefault(family_name, summary)
        return latest_by_family

    def latest_recorded_summaries(self) -> Dict[str, Dict[str, object]]:
        state = self._load_state().get("dates", {})
        if not state:
            return {}
        latest_by_family: Dict[str, Dict[str, object]] = {}
        for trade_date in sorted(state.keys(), reverse=True):
            families = state[trade_date].get("families", {})
            for family_name, summary in families.items():
                latest_by_family.setdefault(family_name, summary)
        return latest_by_family

    def _collectors(self) -> Dict[str, Callable[..., Dict[str, object]]]:
        return {
            FX_REFERENCE_DATASET: self._collect_fx_reference,
            RMB_MIDDLE_RATE_DATASET: self._collect_rmb_middle_rates,
            FX_SPOT_DATASET: self._collect_fx_spot_quotes,
            FX_PAIR_DATASET: self._collect_fx_pair_quotes,
            FX_SWAP_DATASET: self._collect_fx_swap_quotes,
            FX_C_SWAP_CURVE_DATASET: self._collect_fx_c_swap_curve,
            MONEY_MARKET_DATASET: self._collect_money_market_rates,
            LPR_REFERENCE_DATASET: self._collect_lpr_rates,
            REPO_REFERENCE_DATASET: self._collect_repo_rates,
            CN_US_TREASURY_RATE_DATASET: self._collect_cn_us_treasury_rates,
            PRECIOUS_METAL_REFERENCE_DATASET: self._collect_precious_metal_benchmarks,
            RESERVE_REFERENCE_DATASET: self._collect_reserve_reference_series,
        }

    def _collect_fx_reference(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_reference_table(
            dataset_name=FX_REFERENCE_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.currency_boc_safe",
            source_url="https://www.boc.cn/sourcedb/whpj/",
            source_type="fallback_online",
            live_fetcher=lambda: ak.currency_boc_safe(),
            normalizer=self._normalize_fx_rows,
            date_column="日期",
            force=force,
        )

    def _collect_rmb_middle_rates(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_reference_table(
            dataset_name=RMB_MIDDLE_RATE_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.macro_china_rmb",
            source_url="https://datacenter.jin10.com/reportType/dc_rmb_data",
            source_type="fallback_online",
            live_fetcher=lambda: ak.macro_china_rmb(),
            normalizer=self._normalize_rmb_middle_rows,
            date_column="日期",
            force=force,
        )

    def _collect_fx_spot_quotes(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_reference_table(
            dataset_name=FX_SPOT_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.fx_spot_quote",
            source_url="http://www.chinamoney.com.cn/chinese/mkdatapfx/",
            source_type="fallback_online",
            live_fetcher=lambda: ak.fx_spot_quote(),
            normalizer=self._normalize_fx_spot_rows,
            date_column=None,
            force=force,
        )

    def _collect_fx_pair_quotes(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_reference_table(
            dataset_name=FX_PAIR_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.fx_pair_quote",
            source_url="http://www.chinamoney.com.cn/chinese/mkdatapfx/",
            source_type="fallback_online",
            live_fetcher=lambda: ak.fx_pair_quote(),
            normalizer=self._normalize_fx_pair_rows,
            date_column=None,
            force=force,
        )

    def _collect_fx_swap_quotes(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_reference_table(
            dataset_name=FX_SWAP_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.fx_swap_quote",
            source_url="http://www.chinamoney.com.cn/chinese/mkdatapfx/",
            source_type="fallback_online",
            live_fetcher=lambda: ak.fx_swap_quote(),
            normalizer=self._normalize_fx_swap_rows,
            date_column=None,
            force=force,
        )

    def _collect_fx_c_swap_curve(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(FX_C_SWAP_CURVE_DATASET, trade_date)
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                response = requests.get(
                    "https://www.chinamoney.org.cn/r/cms/www/chinamoney/data/fx/fx-c-sw-curv-USD.CNY.json",
                    headers={"User-Agent": "Mozilla/5.0"},
                    timeout=20,
                )
                response.raise_for_status()
                payload = response.json()
                payload["retrieved_at"] = iso_timestamp()
                ensure_directory(raw_path.parent)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                if raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": FX_C_SWAP_CURVE_DATASET,
                        "trade_date": trade_date_str,
                        "status": PENDING_RETRY_STATUS,
                        "message": str(exc),
                        "error": str(exc),
                    }

        rows = self._normalize_fx_c_swap_rows(
            requested_trade_date=trade_date_str,
            payload=payload,
            source_id="cfets.fx_c_swap_curve",
            source_url="https://www.chinamoney.org.cn/chinese/bkcurvfsw",
            source_type="fallback_online",
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        output_path = self._output_path(FX_C_SWAP_CURVE_DATASET, trade_date)
        if not rows:
            write_dict_rows_csv(output_path, [], PUBLIC_REFERENCE_STANDARD_FIELDS, ["trade_date", "symbol", "tenor"])
            return {
                "dataset": FX_C_SWAP_CURVE_DATASET,
                "trade_date": trade_date_str,
                "status": NO_DATA_STATUS,
                "row_count": 0,
                "output_path": relative_to_project(output_path, PROJECT_ROOT),
                "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
                "source_url": "https://www.chinamoney.org.cn/chinese/bkcurvfsw",
                "source_type": "fallback_online",
                "message": "source returned no rows for requested date",
            }
        write_dict_rows_csv(output_path, rows, PUBLIC_REFERENCE_STANDARD_FIELDS, ["trade_date", "symbol", "tenor"])
        return {
            "dataset": FX_C_SWAP_CURVE_DATASET,
            "trade_date": trade_date_str,
            "status": SUCCESS_STATUS,
            "row_count": len(rows),
            "output_path": relative_to_project(output_path, PROJECT_ROOT),
            "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            "source_url": "https://www.chinamoney.org.cn/chinese/bkcurvfsw",
            "source_type": "fallback_online",
        }

    def _collect_money_market_rates(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_reference_table(
            dataset_name=MONEY_MARKET_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.macro_china_shibor_all",
            source_url="https://www.shibor.org/shibor/web/html/shibor.html",
            source_type="fallback_online",
            live_fetcher=lambda: ak.macro_china_shibor_all(),
            normalizer=self._normalize_shibor_rows,
            date_column="日期",
            force=force,
        )

    def _collect_lpr_rates(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(LPR_REFERENCE_DATASET, trade_date)
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                frame = ak.macro_china_lpr().fillna("")
                if "TRADE_DATE" not in frame.columns:
                    return {
                        "dataset": LPR_REFERENCE_DATASET,
                        "trade_date": trade_date_str,
                        "status": FAILED_STATUS,
                        "message": "source payload is missing TRADE_DATE column",
                    }
                frame["TRADE_DATE"] = frame["TRADE_DATE"].astype(str)
                eligible = frame.loc[frame["TRADE_DATE"] <= trade_date_str]
                if eligible.empty:
                    target_frame = frame.iloc[0:0]
                else:
                    latest_available = str(eligible["TRADE_DATE"].max())
                    target_frame = eligible.loc[eligible["TRADE_DATE"] == latest_available]
                payload = {
                    "records": json.loads(target_frame.to_json(orient="records", force_ascii=False)),
                    "retrieved_at": iso_timestamp(),
                }
                ensure_directory(raw_path.parent)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                if raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": LPR_REFERENCE_DATASET,
                        "trade_date": trade_date_str,
                        "status": PENDING_RETRY_STATUS,
                        "message": str(exc),
                        "error": str(exc),
                    }

        rows = self._normalize_lpr_rows(
            requested_trade_date=trade_date_str,
            payload=payload,
            source_id="akshare.macro_china_lpr",
            source_url="https://www.chinamoney.com.cn/chinese/bkccpr/",
            source_type="fallback_online",
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        output_path = self._output_path(LPR_REFERENCE_DATASET, trade_date)
        if not rows:
            write_dict_rows_csv(output_path, [], PUBLIC_REFERENCE_STANDARD_FIELDS, ["trade_date", "symbol", "tenor"])
            return {
                "dataset": LPR_REFERENCE_DATASET,
                "trade_date": trade_date_str,
                "status": NO_DATA_STATUS,
                "row_count": 0,
                "output_path": relative_to_project(output_path, PROJECT_ROOT),
                "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
                "source_url": "https://www.chinamoney.com.cn/chinese/bkccpr/",
                "source_type": "fallback_online",
                "message": "source returned no rows for requested date",
            }
        write_dict_rows_csv(output_path, rows, PUBLIC_REFERENCE_STANDARD_FIELDS, ["trade_date", "symbol", "tenor"])
        return {
            "dataset": LPR_REFERENCE_DATASET,
            "trade_date": trade_date_str,
            "status": SUCCESS_STATUS,
            "row_count": len(rows),
            "output_path": relative_to_project(output_path, PROJECT_ROOT),
            "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            "source_url": "https://www.chinamoney.com.cn/chinese/bkccpr/",
            "source_type": "fallback_online",
        }

    def _collect_repo_rates(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(REPO_REFERENCE_DATASET, trade_date)
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                fr_frame = ak.repo_rate_query(symbol="回购定盘利率").fillna("")
                fdr_frame = ak.repo_rate_query(symbol="银银间回购定盘利率").fillna("")
                if "date" not in fr_frame.columns or "date" not in fdr_frame.columns:
                    return {
                        "dataset": REPO_REFERENCE_DATASET,
                        "trade_date": trade_date_str,
                        "status": FAILED_STATUS,
                        "message": "source payload is missing date column",
                    }
                fr_frame = fr_frame.loc[fr_frame["date"].astype(str) == trade_date_str]
                fdr_frame = fdr_frame.loc[fdr_frame["date"].astype(str) == trade_date_str]
                payload = {
                    "fr_records": json.loads(fr_frame.to_json(orient="records", force_ascii=False)),
                    "fdr_records": json.loads(fdr_frame.to_json(orient="records", force_ascii=False)),
                    "retrieved_at": iso_timestamp(),
                }
                ensure_directory(raw_path.parent)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                if raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": REPO_REFERENCE_DATASET,
                        "trade_date": trade_date_str,
                        "status": PENDING_RETRY_STATUS,
                        "message": str(exc),
                        "error": str(exc),
                    }

        rows = self._normalize_repo_rows(
            trade_date_str=trade_date_str,
            payload=payload,
            source_id="akshare.repo_rate_hist",
            source_url="https://www.chinamoney.com.cn/chinese/bkcurvexrr/",
            source_type="fallback_online",
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        output_path = self._output_path(REPO_REFERENCE_DATASET, trade_date)
        if not rows:
            write_dict_rows_csv(output_path, [], PUBLIC_REFERENCE_STANDARD_FIELDS, ["trade_date", "symbol", "tenor"])
            return {
                "dataset": REPO_REFERENCE_DATASET,
                "trade_date": trade_date_str,
                "status": NO_DATA_STATUS,
                "row_count": 0,
                "output_path": relative_to_project(output_path, PROJECT_ROOT),
                "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
                "source_url": "https://www.chinamoney.com.cn/chinese/bkcurvexrr/",
                "source_type": "fallback_online",
                "message": "source returned no rows for requested date",
            }
        write_dict_rows_csv(output_path, rows, PUBLIC_REFERENCE_STANDARD_FIELDS, ["trade_date", "symbol", "tenor"])
        return {
            "dataset": REPO_REFERENCE_DATASET,
            "trade_date": trade_date_str,
            "status": SUCCESS_STATUS,
            "row_count": len(rows),
            "output_path": relative_to_project(output_path, PROJECT_ROOT),
            "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            "source_url": "https://www.chinamoney.com.cn/chinese/bkcurvexrr/",
            "source_type": "fallback_online",
        }

    def _collect_cn_us_treasury_rates(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_reference_table(
            dataset_name=CN_US_TREASURY_RATE_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.bond_zh_us_rate",
            source_url="https://data.eastmoney.com/cjsj/zmgzsyl.html",
            source_type="fallback_online",
            live_fetcher=lambda: ak.bond_zh_us_rate(start_date=compact_trade_date(trade_date)),
            normalizer=self._normalize_cn_us_treasury_rows,
            date_column="日期",
            force=force,
        )

    def _collect_precious_metal_benchmarks(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(PRECIOUS_METAL_REFERENCE_DATASET, trade_date)
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                gold_frame = ak.spot_golden_benchmark_sge().fillna("")
                silver_frame = ak.spot_silver_benchmark_sge().fillna("")
                gold_frame = gold_frame.loc[gold_frame["交易时间"].astype(str) == trade_date_str]
                silver_frame = silver_frame.loc[silver_frame["交易时间"].astype(str) == trade_date_str]
                payload = {
                    "gold_records": json.loads(gold_frame.to_json(orient="records", force_ascii=False)),
                    "silver_records": json.loads(silver_frame.to_json(orient="records", force_ascii=False)),
                    "retrieved_at": iso_timestamp(),
                }
                ensure_directory(raw_path.parent)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                if raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": PRECIOUS_METAL_REFERENCE_DATASET,
                        "trade_date": trade_date_str,
                        "status": PENDING_RETRY_STATUS,
                        "message": str(exc),
                        "error": str(exc),
                    }

        rows = self._normalize_precious_metal_rows(
            trade_date_str=trade_date_str,
            payload=payload,
            source_id="akshare.spot_benchmark_sge",
            source_url="https://www.sge.com.cn/",
            source_type="fallback_online",
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        output_path = self._output_path(PRECIOUS_METAL_REFERENCE_DATASET, trade_date)
        if not rows:
            write_dict_rows_csv(output_path, [], PUBLIC_REFERENCE_STANDARD_FIELDS, ["trade_date", "symbol"])
            return {
                "dataset": PRECIOUS_METAL_REFERENCE_DATASET,
                "trade_date": trade_date_str,
                "status": NO_DATA_STATUS,
                "row_count": 0,
                "output_path": relative_to_project(output_path, PROJECT_ROOT),
                "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
                "source_url": "https://www.sge.com.cn/",
                "source_type": "fallback_online",
                "message": "source returned no rows for requested date",
            }
        write_dict_rows_csv(output_path, rows, PUBLIC_REFERENCE_STANDARD_FIELDS, ["trade_date", "symbol", "tenor"])
        return {
            "dataset": PRECIOUS_METAL_REFERENCE_DATASET,
            "trade_date": trade_date_str,
            "status": SUCCESS_STATUS,
            "row_count": len(rows),
            "output_path": relative_to_project(output_path, PROJECT_ROOT),
            "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            "source_url": "https://www.sge.com.cn/",
            "source_type": "fallback_online",
        }

    def _collect_reserve_reference_series(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(RESERVE_REFERENCE_DATASET, trade_date)
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                eastmoney_frame = ak.macro_china_fx_gold().fillna("")
                pbc_frame = ak.macro_china_foreign_exchange_gold().fillna("")
                eastmoney_record = self._select_latest_reserve_record(
                    frame=eastmoney_frame,
                    date_column="月份",
                    trade_date_str=trade_date_str,
                    parser=self._parse_eastmoney_reserve_date,
                )
                pbc_record = self._select_latest_reserve_record(
                    frame=pbc_frame,
                    date_column="统计时间",
                    trade_date_str=trade_date_str,
                    parser=self._parse_period_trade_date,
                )
                payload = {
                    "eastmoney_records": [eastmoney_record] if eastmoney_record else [],
                    "pbc_records": [pbc_record] if pbc_record else [],
                    "retrieved_at": iso_timestamp(),
                }
                ensure_directory(raw_path.parent)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                if raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": RESERVE_REFERENCE_DATASET,
                        "trade_date": trade_date_str,
                        "status": PENDING_RETRY_STATUS,
                        "message": str(exc),
                        "error": str(exc),
                    }

        rows = self._normalize_reserve_rows(
            requested_trade_date=trade_date_str,
            payload=payload,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        output_path = self._output_path(RESERVE_REFERENCE_DATASET, trade_date)
        if not rows:
            write_dict_rows_csv(output_path, [], PUBLIC_REFERENCE_STANDARD_FIELDS, ["trade_date", "symbol"])
            return {
                "dataset": RESERVE_REFERENCE_DATASET,
                "trade_date": trade_date_str,
                "status": NO_DATA_STATUS,
                "row_count": 0,
                "output_path": relative_to_project(output_path, PROJECT_ROOT),
                "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
                "source_url": "https://data.eastmoney.com/cjsj/hjwh.html|https://finance.sina.com.cn/mac/#fininfo-5-0-31-2",
                "source_type": "fallback_online",
                "message": "source returned no rows for requested date",
            }
        write_dict_rows_csv(output_path, rows, PUBLIC_REFERENCE_STANDARD_FIELDS, ["trade_date", "symbol"])
        return {
            "dataset": RESERVE_REFERENCE_DATASET,
            "trade_date": trade_date_str,
            "status": SUCCESS_STATUS,
            "row_count": len(rows),
            "output_path": relative_to_project(output_path, PROJECT_ROOT),
            "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            "source_url": "https://data.eastmoney.com/cjsj/hjwh.html|https://finance.sina.com.cn/mac/#fininfo-5-0-31-2",
            "source_type": "fallback_online",
        }

    def _collect_reference_table(
        self,
        *,
        dataset_name: str,
        trade_date,
        run_id: str,
        source_id: str,
        source_url: str,
        source_type: str,
        live_fetcher: Callable[[], object],
        normalizer: Callable[..., List[Dict[str, str]]],
        date_column: Optional[str],
        force: bool,
    ) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(dataset_name, trade_date)
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                frame = live_fetcher()
                if date_column and date_column not in frame.columns:
                    return {
                        "dataset": dataset_name,
                        "trade_date": trade_date_str,
                        "status": FAILED_STATUS,
                        "message": f"source payload is missing {date_column} column",
                    }
                frame = frame.fillna("")
                if date_column:
                    target_frame = frame.loc[frame[date_column].astype(str) == trade_date_str]
                else:
                    target_frame = frame
                payload = {
                    "records": json.loads(target_frame.to_json(orient="records", force_ascii=False)),
                    "retrieved_at": iso_timestamp(),
                }
                ensure_directory(raw_path.parent)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                if raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": dataset_name,
                        "trade_date": trade_date_str,
                        "status": PENDING_RETRY_STATUS,
                        "message": str(exc),
                        "error": str(exc),
                    }

        rows = normalizer(
            trade_date_str=trade_date_str,
            payload=payload,
            source_id=source_id,
            source_url=source_url,
            source_type=source_type,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        output_path = self._output_path(dataset_name, trade_date)
        if not rows:
            write_dict_rows_csv(output_path, [], PUBLIC_REFERENCE_STANDARD_FIELDS, ["trade_date", "symbol"])
            return {
                "dataset": dataset_name,
                "trade_date": trade_date_str,
                "status": NO_DATA_STATUS,
                "row_count": 0,
                "output_path": relative_to_project(output_path, PROJECT_ROOT),
                "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
                "source_url": source_url,
                "source_type": source_type,
                "message": "source returned no rows for requested date",
            }
        write_dict_rows_csv(output_path, rows, PUBLIC_REFERENCE_STANDARD_FIELDS, ["trade_date", "symbol", "tenor"])
        return {
            "dataset": dataset_name,
            "trade_date": trade_date_str,
            "status": SUCCESS_STATUS,
            "row_count": len(rows),
            "output_path": relative_to_project(output_path, PROJECT_ROOT),
            "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            "source_url": source_url,
            "source_type": source_type,
        }

    def _normalize_fx_rows(
        self,
        *,
        trade_date_str: str,
        payload: Dict[str, object],
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            for column, currency_code in FX_CURRENCY_MAP.items():
                value = normalize_number(item.get(column))
                if not value:
                    continue
                symbol = f"{currency_code}/CNY"
                rows.append(
                    self._row(
                        trade_date=trade_date_str,
                        asset_family="fx_money_market_cn",
                        reference_type="fx_reference_rate",
                        market="cn_fx_reference",
                        exchange="BOC",
                        symbol=symbol,
                        name=f"{column}/人民币参考价",
                        base_currency=currency_code,
                        quote_currency="CNY",
                        tenor="spot_reference",
                        value=value,
                        change_bp="",
                        unit="CNY per 100 foreign currency units",
                        source_id=source_id,
                        source_url=source_url,
                        source_type=source_type,
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
        return rows

    def _normalize_fx_spot_rows(
        self,
        *,
        trade_date_str: str,
        payload: Dict[str, object],
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            symbol = normalize_text(item.get("货币对")).upper()
            if not symbol or "/" not in symbol:
                continue
            base_currency, quote_currency = symbol.split("/", 1)
            bid = normalize_number(item.get("买报价"))
            ask = normalize_number(item.get("卖报价"))
            if not bid and not ask:
                continue
            rows.append(
                self._row(
                    trade_date=trade_date_str,
                    asset_family="fx_money_market_cn",
                    reference_type="fx_spot_quote",
                    market="cn_fx_spot",
                    exchange="CFETS",
                    symbol=symbol,
                    name=f"{symbol} 即期报价",
                    base_currency=base_currency,
                    quote_currency=quote_currency,
                    tenor="spot",
                    value=bid or ask,
                    change_bp="",
                    unit=f"{quote_currency} per {base_currency}",
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                    run_id=run_id,
                )
        )
        return rows

    def _normalize_rmb_middle_rows(
        self,
        *,
        trade_date_str: str,
        payload: Dict[str, object],
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            for column_name, raw_value in item.items():
                column = normalize_text(column_name)
                if not column or column == "日期":
                    continue
                if column.endswith("_中间价"):
                    pair_label = column[: -len("_中间价")]
                    name_suffix = "中间价"
                elif column.endswith("_定价"):
                    pair_label = column[: -len("_定价")]
                    name_suffix = "定价"
                else:
                    continue
                base_currency, quote_currency = _split_rmb_middle_pair(pair_label)
                if not base_currency or not quote_currency:
                    continue
                value = normalize_number(raw_value)
                if not value:
                    continue
                change_bp = normalize_number(item.get(f"{pair_label}_涨跌幅"))
                symbol = f"{base_currency}/{quote_currency}"
                rows.append(
                    self._row(
                        trade_date=trade_date_str,
                        asset_family="fx_money_market_cn",
                        reference_type="rmb_central_parity",
                        market="cn_rmb_central_parity",
                        exchange="PBOC",
                        symbol=symbol,
                        name=f"{pair_label}{name_suffix}",
                        base_currency=base_currency,
                        quote_currency=quote_currency,
                        tenor="spot_reference",
                        value=value,
                        change_bp=change_bp,
                        unit=_rmb_middle_unit(base_currency, quote_currency),
                        source_id=source_id,
                        source_url=source_url,
                        source_type=source_type,
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
        return rows

    def _normalize_fx_pair_rows(
        self,
        *,
        trade_date_str: str,
        payload: Dict[str, object],
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            symbol = normalize_text(item.get("货币对")).upper().replace(" ", "")
            base_currency, quote_currency = _split_currency_pair(symbol)
            if not base_currency or not quote_currency:
                continue
            bid = normalize_number(item.get("买报价"))
            ask = normalize_number(item.get("卖报价"))
            value = _mid_value(bid, ask)
            if not value and not bid and not ask:
                continue
            rows.append(
                self._row(
                    trade_date=trade_date_str,
                    asset_family="fx_money_market_cn",
                    reference_type="fx_pair_quote",
                    market="cn_fx_pair",
                    exchange="CFETS",
                    symbol=symbol,
                    name=f"{symbol} 外币对即期报价",
                    base_currency=base_currency,
                    quote_currency=quote_currency,
                    tenor="spot",
                    value=value or bid or ask,
                    change_bp="",
                    unit=f"{quote_currency} per {base_currency}",
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                    run_id=run_id,
                )
            )
        return rows

    def _normalize_fx_swap_rows(
        self,
        *,
        trade_date_str: str,
        payload: Dict[str, object],
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        tenor_map = {
            "1周": "1W",
            "1月": "1M",
            "3月": "3M",
            "6月": "6M",
            "9月": "9M",
            "1年": "1Y",
        }
        for item in payload.get("records", []):
            symbol = normalize_text(item.get("货币对")).upper().replace(" ", "")
            base_currency, quote_currency = _split_currency_pair(symbol)
            if not base_currency or not quote_currency:
                continue
            for column, tenor in tenor_map.items():
                bid, ask = _split_bid_ask(item.get(column))
                value = _mid_value(bid, ask)
                if not value and not bid and not ask:
                    continue
                rows.append(
                    self._row(
                        trade_date=trade_date_str,
                        asset_family="fx_money_market_cn",
                        reference_type="fx_swap_quote",
                        market="cn_fx_swap",
                        exchange="CFETS",
                        symbol=symbol,
                        name=f"{symbol} 远掉报价 {tenor}",
                        base_currency=base_currency,
                        quote_currency=quote_currency,
                        tenor=tenor,
                        value=value or bid or ask,
                        change_bp="",
                        unit="pips",
                        source_id=source_id,
                        source_url=source_url,
                        source_type=source_type,
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
        return rows

    def _normalize_fx_c_swap_rows(
        self,
        *,
        requested_trade_date: str,
        payload: Dict[str, object],
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            trade_date = normalize_text(item.get("curveTime")).split(" ", 1)[0] or requested_trade_date
            tenor = normalize_text(item.get("tenor")).upper().replace(" ", "")
            value = normalize_number(item.get("swapPnt"))
            if not tenor or not value:
                continue
            rows.append(
                self._row(
                    trade_date=trade_date,
                    asset_family="fx_money_market_cn",
                    reference_type="fx_c_swap_curve",
                    market="cn_fx_swap_curve",
                    exchange="CFETS",
                    symbol="USD/CNY:C_SWAP",
                    name=f"USD/CNY C-Swap 定盘曲线 {tenor}",
                    base_currency="USD",
                    quote_currency="CNY",
                    tenor=tenor,
                    value=value,
                    change_bp="",
                    unit="pips",
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                    run_id=run_id,
                )
            )
        return rows

    def _normalize_shibor_rows(
        self,
        *,
        trade_date_str: str,
        payload: Dict[str, object],
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            for tenor, tenor_label in SHIBOR_TENOR_LABELS.items():
                value = normalize_number(item.get(f"{tenor}-定价"))
                if not value:
                    continue
                rows.append(
                    self._row(
                        trade_date=trade_date_str,
                        asset_family="fx_money_market_cn",
                        reference_type="money_market_rate",
                        market="cn_money_market",
                        exchange="SHIBOR",
                        symbol=f"SHIBOR:{tenor}",
                        name=f"Shibor {tenor_label}",
                        base_currency="CNY",
                        quote_currency="CNY",
                        tenor=tenor,
                        value=value,
                        change_bp=normalize_number(item.get(f"{tenor}-涨跌幅")),
                        unit="percent",
                        source_id=source_id,
                        source_url=source_url,
                        source_type=source_type,
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
        return rows

    def _normalize_lpr_rows(
        self,
        *,
        requested_trade_date: str,
        payload: Dict[str, object],
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            effective_trade_date = normalize_text(item.get("TRADE_DATE")) or requested_trade_date
            for tenor, field_name in (("1Y", "LPR1Y"), ("5Y", "LPR5Y")):
                value = normalize_number(item.get(field_name))
                if not value:
                    continue
                rows.append(
                    self._row(
                        trade_date=effective_trade_date,
                        asset_family="bonds_rates_cn",
                        reference_type="loan_prime_rate",
                        market="cn_policy_rates",
                        exchange="LPR",
                        symbol=f"LPR:{tenor}",
                        name=f"贷款市场报价利率 {tenor}",
                        base_currency="CNY",
                        quote_currency="CNY",
                        tenor=tenor,
                        value=value,
                        change_bp="",
                        unit="percent",
                        source_id=source_id,
                        source_url=source_url,
                        source_type=source_type,
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
        return rows

    def _normalize_repo_rows(
        self,
        *,
        trade_date_str: str,
        payload: Dict[str, object],
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("fr_records", []):
            for tenor in ("FR001", "FR007", "FR014"):
                value = normalize_number(item.get(tenor))
                if not value:
                    continue
                rows.append(
                    self._row(
                        trade_date=trade_date_str,
                        asset_family="bonds_rates_cn",
                        reference_type="repo_rate",
                        market="cn_money_market",
                        exchange="CFETS",
                        symbol=tenor,
                        name=tenor,
                        base_currency="CNY",
                        quote_currency="CNY",
                        tenor=tenor[-3:],
                        value=value,
                        change_bp="",
                        unit="percent",
                        source_id=source_id,
                        source_url=source_url,
                        source_type=source_type,
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
        for item in payload.get("fdr_records", []):
            for tenor in ("FDR001", "FDR007", "FDR014"):
                value = normalize_number(item.get(tenor))
                if not value:
                    continue
                rows.append(
                    self._row(
                        trade_date=trade_date_str,
                        asset_family="bonds_rates_cn",
                        reference_type="repo_rate",
                        market="cn_money_market",
                        exchange="CFETS",
                        symbol=tenor,
                        name=tenor,
                        base_currency="CNY",
                        quote_currency="CNY",
                        tenor=tenor[-3:],
                        value=value,
                        change_bp="",
                        unit="percent",
                        source_id=source_id,
                        source_url=source_url,
                        source_type=source_type,
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
        return rows

    def _normalize_precious_metal_rows(
        self,
        *,
        trade_date_str: str,
        payload: Dict[str, object],
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("gold_records", []):
            morning = normalize_number(item.get("早盘价"))
            evening = normalize_number(item.get("晚盘价"))
            if morning:
                rows.append(
                    self._row(
                        trade_date=trade_date_str,
                        asset_family="precious_metals_spot_cn",
                        reference_type="precious_metal_benchmark",
                        market="cn_precious_metals_reference",
                        exchange="SGE",
                        symbol="SGE:GOLD_BENCHMARK_AM",
                        name="上海金基准价早盘",
                        base_currency="XAU",
                        quote_currency="CNY",
                        tenor="AM",
                        value=morning,
                        change_bp="",
                        unit="CNY per gram",
                        source_id=source_id,
                        source_url=source_url,
                        source_type=source_type,
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
            if evening:
                rows.append(
                    self._row(
                        trade_date=trade_date_str,
                        asset_family="precious_metals_spot_cn",
                        reference_type="precious_metal_benchmark",
                        market="cn_precious_metals_reference",
                        exchange="SGE",
                        symbol="SGE:GOLD_BENCHMARK_PM",
                        name="上海金基准价晚盘",
                        base_currency="XAU",
                        quote_currency="CNY",
                        tenor="PM",
                        value=evening,
                        change_bp="",
                        unit="CNY per gram",
                        source_id=source_id,
                        source_url=source_url,
                        source_type=source_type,
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
        for item in payload.get("silver_records", []):
            morning = normalize_number(item.get("早盘价"))
            evening = normalize_number(item.get("晚盘价"))
            if morning:
                rows.append(
                    self._row(
                        trade_date=trade_date_str,
                        asset_family="precious_metals_spot_cn",
                        reference_type="precious_metal_benchmark",
                        market="cn_precious_metals_reference",
                        exchange="SGE",
                        symbol="SGE:SILVER_BENCHMARK_AM",
                        name="上海银基准价早盘",
                        base_currency="XAG",
                        quote_currency="CNY",
                        tenor="AM",
                        value=morning,
                        change_bp="",
                        unit="CNY per kilogram",
                        source_id=source_id,
                        source_url=source_url,
                        source_type=source_type,
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
            if evening:
                rows.append(
                    self._row(
                        trade_date=trade_date_str,
                        asset_family="precious_metals_spot_cn",
                        reference_type="precious_metal_benchmark",
                        market="cn_precious_metals_reference",
                        exchange="SGE",
                        symbol="SGE:SILVER_BENCHMARK_PM",
                        name="上海银基准价晚盘",
                        base_currency="XAG",
                        quote_currency="CNY",
                        tenor="PM",
                        value=evening,
                        change_bp="",
                        unit="CNY per kilogram",
                        source_id=source_id,
                        source_url=source_url,
                        source_type=source_type,
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
        return rows

    def _normalize_cn_us_treasury_rows(
        self,
        *,
        trade_date_str: str,
        payload: Dict[str, object],
        source_id: str,
        source_url: str,
        source_type: str,
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            for column, raw_value in item.items():
                if column == "日期":
                    continue
                value = normalize_number(raw_value)
                if value == "":
                    continue
                match = CN_US_TREASURY_PATTERN.search(normalize_text(column))
                if not match:
                    continue
                country = match.group("country")
                tenor = f"{match.group('tenor')}{'Y' if match.group('unit') == '年' else 'M'}"
                country_code = "CN" if country == "中国" else "US"
                rows.append(
                    self._row(
                        trade_date=trade_date_str,
                        asset_family="bonds_rates_cn",
                        reference_type="sovereign_yield_reference",
                        market="cross_market_treasury_yield",
                        exchange="EASTMONEY",
                        symbol=f"{country_code}_GOVT_{tenor}",
                        name=normalize_text(column),
                        base_currency=country_code,
                        quote_currency="YIELD",
                        tenor=tenor,
                        value=value,
                        change_bp="",
                        unit="percent",
                        source_id=source_id,
                        source_url=source_url,
                        source_type=source_type,
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
        return rows

    def _normalize_reserve_rows(
        self,
        *,
        requested_trade_date: str,
        payload: Dict[str, object],
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        rows: List[Dict[str, str]] = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("eastmoney_records", []):
            trade_date = self._parse_eastmoney_reserve_date(normalize_text(item.get("月份"))) or requested_trade_date
            gold_value = normalize_number(item.get("黄金储备-数值"))
            if gold_value:
                rows.append(
                    self._row(
                        trade_date=trade_date,
                        asset_family="fx_money_market_cn",
                        reference_type="reserve_reference",
                        market="cn_reserve_reference",
                        exchange="SAFE",
                        symbol="SAFE:GOLD_RESERVE_VALUE",
                        name="黄金储备估值（东方财富）",
                        base_currency="XAU",
                        quote_currency="USD",
                        tenor="monthly_snapshot",
                        value=gold_value,
                        change_bp=normalize_number(item.get("黄金储备-环比")),
                        unit="100M USD",
                        source_id="akshare.macro_china_fx_gold",
                        source_url="https://data.eastmoney.com/cjsj/hjwh.html",
                        source_type="fallback_online",
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
            fx_value = normalize_number(item.get("国家外汇储备-数值"))
            if fx_value:
                rows.append(
                    self._row(
                        trade_date=trade_date,
                        asset_family="fx_money_market_cn",
                        reference_type="reserve_reference",
                        market="cn_reserve_reference",
                        exchange="SAFE",
                        symbol="SAFE:FOREX_RESERVE",
                        name="国家外汇储备（东方财富）",
                        base_currency="USD",
                        quote_currency="USD",
                        tenor="monthly_snapshot",
                        value=fx_value,
                        change_bp=normalize_number(item.get("国家外汇储备-环比")),
                        unit="100M USD",
                        source_id="akshare.macro_china_fx_gold",
                        source_url="https://data.eastmoney.com/cjsj/hjwh.html",
                        source_type="fallback_online",
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
        for item in payload.get("pbc_records", []):
            trade_date = self._parse_period_trade_date(normalize_text(item.get("统计时间"))) or requested_trade_date
            gold_value = normalize_number(item.get("黄金储备"))
            if gold_value:
                rows.append(
                    self._row(
                        trade_date=trade_date,
                        asset_family="fx_money_market_cn",
                        reference_type="reserve_reference",
                        market="cn_reserve_reference",
                        exchange="PBOC",
                        symbol="PBOC:GOLD_RESERVE_OUNCE",
                        name="黄金储备（央行口径）",
                        base_currency="XAU",
                        quote_currency="XAU",
                        tenor="monthly_snapshot",
                        value=gold_value,
                        change_bp="",
                        unit="10k ounces",
                        source_id="akshare.macro_china_foreign_exchange_gold",
                        source_url="https://finance.sina.com.cn/mac/#fininfo-5-0-31-2",
                        source_type="fallback_online",
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
            fx_value = normalize_number(item.get("国家外汇储备"))
            if fx_value:
                rows.append(
                    self._row(
                        trade_date=trade_date,
                        asset_family="fx_money_market_cn",
                        reference_type="reserve_reference",
                        market="cn_reserve_reference",
                        exchange="PBOC",
                        symbol="PBOC:FOREX_RESERVE",
                        name="国家外汇储备（央行口径）",
                        base_currency="USD",
                        quote_currency="USD",
                        tenor="monthly_snapshot",
                        value=fx_value,
                        change_bp="",
                        unit="100M USD",
                        source_id="akshare.macro_china_foreign_exchange_gold",
                        source_url="https://finance.sina.com.cn/mac/#fininfo-5-0-31-2",
                        source_type="fallback_online",
                        retrieved_at=retrieved_at,
                        raw_path=raw_path,
                        run_id=run_id,
                    )
                )
        return rows

    def _row(
        self,
        *,
        trade_date: str,
        asset_family: str,
        reference_type: str,
        market: str,
        exchange: str,
        symbol: str,
        name: str,
        base_currency: str,
        quote_currency: str,
        tenor: str,
        value: str,
        change_bp: str,
        unit: str,
        source_id: str,
        source_url: str,
        source_type: str,
        retrieved_at: str,
        raw_path: str,
        run_id: str,
    ) -> Dict[str, str]:
        checksum_payload = json.dumps(
            {
                "trade_date": trade_date,
                "symbol": symbol,
                "tenor": tenor,
                "value": value,
                "source_id": source_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        return {
            "trade_date": trade_date,
            "asset_family": asset_family,
            "reference_type": reference_type,
            "market": market,
            "exchange": exchange,
            "symbol": symbol,
            "name": name,
            "base_currency": base_currency,
            "quote_currency": quote_currency,
            "tenor": tenor,
            "value": value,
            "change_bp": change_bp,
            "unit": unit,
            "source_id": source_id,
            "source_url": source_url,
            "source_type": source_type,
            "retrieved_at": retrieved_at,
            "raw_path": raw_path,
            "parser_version": PARSER_VERSION,
            "checksum": hashlib.sha1(checksum_payload).hexdigest(),
            "run_id": run_id,
        }

    def _raw_path(self, dataset_name: str, trade_date) -> Path:
        return RAW_DIR / "public_references" / dataset_name / f"{compact_trade_date(trade_date)}.json"

    def _output_path(self, dataset_name: str, trade_date) -> Path:
        return PUBLIC_REFERENCES_NORMALIZED_DIR / dataset_name / f"{format_trade_date(trade_date)}.csv"

    def _update_state(self, trade_date: str, status: str, families: Dict[str, Dict[str, object]]) -> None:
        payload = self._load_state()
        day_bucket = payload.setdefault("dates", {}).setdefault(
            trade_date,
            {
                "status": "",
                "families": {},
                "updated_at": "",
            },
        )
        merged = dict(day_bucket.get("families", {}))
        merged.update(families)
        family_statuses = {str(item.get("status", "")) for item in merged.values()}
        if family_statuses and all(value == SUCCESS_STATUS for value in family_statuses):
            final_status = SUCCESS_STATUS
        elif PENDING_RETRY_STATUS in family_statuses:
            final_status = PENDING_RETRY_STATUS
        elif FAILED_STATUS in family_statuses:
            final_status = FAILED_STATUS
        elif family_statuses and all(value == NOT_APPLICABLE_STATUS for value in family_statuses):
            final_status = NOT_APPLICABLE_STATUS
        elif family_statuses and all(value == NO_DATA_STATUS for value in family_statuses):
            final_status = NO_DATA_STATUS
        elif SUCCESS_STATUS in family_statuses or PARTIAL_SUCCESS_STATUS in family_statuses:
            final_status = PARTIAL_SUCCESS_STATUS
        else:
            final_status = status
        day_bucket["status"] = final_status
        day_bucket["families"] = merged
        day_bucket["updated_at"] = iso_timestamp()
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_state(self) -> Dict[str, object]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    @staticmethod
    def _resolve_trade_date(trade_date_value: str):
        if trade_date_value == "latest":
            current_date = now_shanghai().date()
            if current_date.weekday() >= 5:
                return previous_weekday(current_date)
            return current_date
        return parse_trade_date(trade_date_value)

    @staticmethod
    def _normalize_families(families: Optional[Iterable[str]]) -> List[str]:
        if not families:
            return [
                FX_REFERENCE_DATASET,
                RMB_MIDDLE_RATE_DATASET,
                FX_SPOT_DATASET,
                FX_PAIR_DATASET,
                FX_SWAP_DATASET,
                FX_C_SWAP_CURVE_DATASET,
                MONEY_MARKET_DATASET,
                LPR_REFERENCE_DATASET,
                REPO_REFERENCE_DATASET,
                CN_US_TREASURY_RATE_DATASET,
                PRECIOUS_METAL_REFERENCE_DATASET,
                RESERVE_REFERENCE_DATASET,
            ]
        normalized = []
        for value in families:
            for token in str(value).split(","):
                cleaned = token.strip()
                if cleaned:
                    normalized.append(cleaned)
        return normalized

    @staticmethod
    def _parse_eastmoney_reserve_date(value: str) -> str:
        match = MONTH_TEXT_PATTERN.match(value)
        if not match:
            return ""
        return f"{match.group('year')}-{int(match.group('month')):02d}-01"

    @staticmethod
    def _parse_period_trade_date(value: str) -> str:
        match = PERIOD_TEXT_PATTERN.match(value)
        if not match:
            return ""
        return f"{match.group('year')}-{int(match.group('month')):02d}-01"

    def _select_latest_reserve_record(self, *, frame, date_column: str, trade_date_str: str, parser: Callable[[str], str]) -> Dict[str, object]:
        if date_column not in frame.columns:
            return {}
        target = frame.copy()
        target["_normalized_trade_date"] = target[date_column].astype(str).map(lambda value: parser(normalize_text(value)))
        target = target.loc[target["_normalized_trade_date"].astype(str) <= trade_date_str]
        target = target.loc[target["_normalized_trade_date"].astype(str) != ""]
        if target.empty:
            return {}
        latest_available = str(target["_normalized_trade_date"].max())
        latest = target.loc[target["_normalized_trade_date"] == latest_available].iloc[0].to_dict()
        latest.pop("_normalized_trade_date", None)
        return latest


def _iter_csv_rows(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


def _split_currency_pair(symbol: str) -> tuple:
    text = normalize_text(symbol).upper().replace(" ", "")
    if not text or "/" not in text:
        return "", ""
    return text.split("/", 1)


def _split_bid_ask(value) -> tuple:
    text = normalize_text(value)
    if not text or "/" not in text:
        return "", ""
    left, right = text.split("/", 1)
    return normalize_number(left), normalize_number(right)


def _mid_value(bid: str, ask: str) -> str:
    if not bid and not ask:
        return ""
    if bid and ask:
        try:
            return f"{(float(bid) + float(ask)) / 2:.6f}".rstrip("0").rstrip(".")
        except ValueError:
            return bid or ask
    return bid or ask


def _split_rmb_middle_pair(pair_label: str) -> tuple[str, str]:
    text = normalize_text(pair_label)
    if "/" not in text:
        return "", ""
    base_label, quote_label = text.split("/", 1)
    return RMB_CURRENCY_MAP.get(base_label, ""), RMB_CURRENCY_MAP.get(quote_label, "")


def _rmb_middle_unit(base_currency: str, quote_currency: str) -> str:
    if base_currency == "CNY":
        return f"{quote_currency} per CNY"
    if base_currency == "100JPY":
        return "CNY per 100 JPY"
    return f"{quote_currency} per {base_currency}"


def _merge_statuses(statuses: List[str]) -> str:
    values = {value for value in statuses if value}
    if values and all(value == SUCCESS_STATUS for value in values):
        return SUCCESS_STATUS
    if PENDING_RETRY_STATUS in values:
        return PENDING_RETRY_STATUS
    if FAILED_STATUS in values:
        return FAILED_STATUS
    if values and all(value == NOT_APPLICABLE_STATUS for value in values):
        return NOT_APPLICABLE_STATUS
    if values and all(value == NO_DATA_STATUS for value in values):
        return NO_DATA_STATUS
    if SUCCESS_STATUS in values or PARTIAL_SUCCESS_STATUS in values:
        return PARTIAL_SUCCESS_STATUS
    return NO_DATA_STATUS
