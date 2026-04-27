import csv
import hashlib
import json
from datetime import timedelta
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import akshare as ak

from .config import PROJECT_ROOT, PUBLIC_BONDS_NORMALIZED_DIR, PUBLIC_BOND_STATE_PATH, RAW_DIR
from .constants import (
    FAILED_STATUS,
    INTERBANK_BOND_DEAL_DATASET,
    INTERBANK_BOND_QUOTE_DATASET,
    NOT_APPLICABLE_STATUS,
    NO_DATA_STATUS,
    PARTIAL_SUCCESS_STATUS,
    PENDING_RETRY_STATUS,
    PUBLIC_BOND_STANDARD_FIELDS,
    PUBLIC_BOND_SUMMARY_FIELDS,
    SSE_BOND_CASH_SUMMARY_DATASET,
    SSE_BOND_DEAL_SUMMARY_DATASET,
    SUCCESS_STATUS,
    YIELD_CURVE_DATASET,
)
from .normalize.csv_utils import write_dict_rows_csv
from .utils import compact_trade_date, ensure_directory, format_trade_date, iso_timestamp, normalize_number, normalize_text, now_shanghai, parse_trade_date, previous_weekday, relative_to_project


PARSER_VERSION = "public_bonds_v1"
YIELD_TENOR_MAP = {
    "3月": "3M",
    "6月": "6M",
    "1年": "1Y",
    "3年": "3Y",
    "5年": "5Y",
    "7年": "7Y",
    "10年": "10Y",
    "30年": "30Y",
}


class PublicBondRunner:
    def __init__(self, *, state_path: Path = PUBLIC_BOND_STATE_PATH):
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
            expected_fields = self._fieldnames_for_dataset(family_name)
            dataset_validation = {
                "csv_exists": bool(csv_path and csv_path.exists()),
                "schema_ok": False,
                "row_count": 0,
                "missing_raw_paths": [],
            }
            if csv_path and csv_path.exists():
                rows = list(_iter_csv_rows(csv_path))
                dataset_validation["row_count"] = len(rows)
                fieldnames = list(rows[0].keys()) if rows else expected_fields
                dataset_validation["schema_ok"] = fieldnames == expected_fields
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
            INTERBANK_BOND_DEAL_DATASET: self._collect_interbank_deals,
            INTERBANK_BOND_QUOTE_DATASET: self._collect_interbank_quotes,
            YIELD_CURVE_DATASET: self._collect_yield_curve_points,
            SSE_BOND_DEAL_SUMMARY_DATASET: self._collect_sse_bond_deal_summary,
            SSE_BOND_CASH_SUMMARY_DATASET: self._collect_sse_bond_cash_summary,
        }

    def _collect_interbank_deals(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_snapshot(
            dataset_name=INTERBANK_BOND_DEAL_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.bond_spot_deal",
            source_url="https://www.chinamoney.com.cn/chinese/mkdatabond/",
            source_type="fallback_online",
            live_fetcher=lambda: ak.bond_spot_deal(),
            normalizer=self._normalize_interbank_deals,
            latest_only=True,
            force=force,
        )

    def _collect_interbank_quotes(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_snapshot(
            dataset_name=INTERBANK_BOND_QUOTE_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.bond_spot_quote",
            source_url="https://www.chinamoney.com.cn/chinese/mkdatabond/",
            source_type="fallback_online",
            live_fetcher=lambda: ak.bond_spot_quote(),
            normalizer=self._normalize_interbank_quotes,
            latest_only=True,
            force=force,
        )

    def _collect_yield_curve_points(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(YIELD_CURVE_DATASET, trade_date)
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                start_date = format_trade_date(trade_date - timedelta(days=7)).replace("-", "")
                end_date = trade_date_str.replace("-", "")
                frame = ak.bond_china_yield(start_date=start_date, end_date=end_date).fillna("")
                if "日期" not in frame.columns:
                    return {
                        "dataset": YIELD_CURVE_DATASET,
                        "trade_date": trade_date_str,
                        "status": FAILED_STATUS,
                        "message": "yield curve payload is missing 日期 column",
                    }
                frame["日期"] = frame["日期"].astype(str)
                target_frame = frame.loc[frame["日期"] == trade_date_str]
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
                        "dataset": YIELD_CURVE_DATASET,
                        "trade_date": trade_date_str,
                        "status": PENDING_RETRY_STATUS,
                        "message": str(exc),
                        "error": str(exc),
                    }

        rows = self._normalize_yield_curve_rows(
            trade_date_str=trade_date_str,
            payload=payload,
            source_id="akshare.bond_china_yield",
            source_url="https://yield.chinabond.com.cn/",
            source_type="fallback_online",
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        output_path = self._output_path(YIELD_CURVE_DATASET, trade_date)
        if not rows:
            write_dict_rows_csv(output_path, [], PUBLIC_BOND_STANDARD_FIELDS, ["trade_date", "curve_name", "tenor"])
            return {
                "dataset": YIELD_CURVE_DATASET,
                "trade_date": trade_date_str,
                "status": NO_DATA_STATUS,
                "row_count": 0,
                "output_path": relative_to_project(output_path, PROJECT_ROOT),
                "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
                "source_url": "https://yield.chinabond.com.cn/",
                "source_type": "fallback_online",
                "message": "yield curve source returned no rows for requested date",
            }
        write_dict_rows_csv(output_path, rows, PUBLIC_BOND_STANDARD_FIELDS, ["trade_date", "curve_name", "tenor"])
        return {
            "dataset": YIELD_CURVE_DATASET,
            "trade_date": trade_date_str,
            "status": SUCCESS_STATUS,
            "row_count": len(rows),
            "output_path": relative_to_project(output_path, PROJECT_ROOT),
            "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            "source_url": "https://yield.chinabond.com.cn/",
            "source_type": "fallback_online",
        }

    def _collect_sse_bond_deal_summary(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_summary_snapshot(
            dataset_name=SSE_BOND_DEAL_SUMMARY_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.bond_deal_summary_sse",
            source_url="http://bond.sse.com.cn/data/statistics/overview/turnover/",
            source_type="fallback_online",
            live_fetcher=lambda: ak.bond_deal_summary_sse(date=compact_trade_date(trade_date)),
            normalizer=self._normalize_sse_bond_deal_summary_rows,
            force=force,
        )

    def _collect_sse_bond_cash_summary(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_summary_snapshot(
            dataset_name=SSE_BOND_CASH_SUMMARY_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.bond_cash_summary_sse",
            source_url="http://bond.sse.com.cn/data/statistics/overview/bondow/",
            source_type="fallback_online",
            live_fetcher=lambda: ak.bond_cash_summary_sse(date=compact_trade_date(trade_date)),
            normalizer=self._normalize_sse_bond_cash_summary_rows,
            force=force,
        )

    def _collect_snapshot(
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
        latest_only: bool,
        force: bool,
    ) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(dataset_name, trade_date)
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            if latest_only and trade_date != previous_weekday(now_shanghai().date()):
                if raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": dataset_name,
                        "trade_date": trade_date_str,
                        "status": NOT_APPLICABLE_STATUS,
                        "message": "latest-only bond snapshot source without cached payload for requested historical date",
                    }
            else:
                try:
                    data_frame = live_fetcher()
                    payload = {
                        "records": json.loads(data_frame.to_json(orient="records", force_ascii=False)),
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
            write_dict_rows_csv(output_path, [], PUBLIC_BOND_STANDARD_FIELDS, ["trade_date", "dataset_type", "symbol", "curve_name", "tenor"])
            return {
                "dataset": dataset_name,
                "trade_date": trade_date_str,
                "status": NO_DATA_STATUS,
                "row_count": 0,
                "output_path": relative_to_project(output_path, PROJECT_ROOT),
                "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
                "source_url": source_url,
                "source_type": source_type,
                "message": "normalized rows are empty",
            }
        write_dict_rows_csv(output_path, rows, PUBLIC_BOND_STANDARD_FIELDS, ["trade_date", "dataset_type", "symbol", "curve_name", "tenor"])
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

    def _collect_summary_snapshot(
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
        force: bool,
    ) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(dataset_name, trade_date)
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                data_frame = live_fetcher().fillna("")
                payload = {
                    "records": json.loads(data_frame.to_json(orient="records", force_ascii=False)),
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
            write_dict_rows_csv(output_path, [], PUBLIC_BOND_SUMMARY_FIELDS, ["trade_date", "dataset_type", "category"])
            return {
                "dataset": dataset_name,
                "trade_date": trade_date_str,
                "status": NO_DATA_STATUS,
                "row_count": 0,
                "output_path": relative_to_project(output_path, PROJECT_ROOT),
                "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
                "source_url": source_url,
                "source_type": source_type,
                "message": "normalized rows are empty",
            }
        write_dict_rows_csv(output_path, rows, PUBLIC_BOND_SUMMARY_FIELDS, ["trade_date", "dataset_type", "category"])
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

    def _normalize_interbank_deals(
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
        rows: List[Dict[str, str]] = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            name = normalize_text(item.get("债券简称"))
            if not name:
                continue
            checksum_payload = json.dumps({"trade_date": trade_date_str, "dataset": INTERBANK_BOND_DEAL_DATASET, "symbol": name}, ensure_ascii=False, sort_keys=True).encode("utf-8")
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": "bonds_rates_cn",
                    "dataset_type": INTERBANK_BOND_DEAL_DATASET,
                    "market": "cn_interbank_bond",
                    "exchange": "CFETS",
                    "symbol": name,
                    "name": name,
                    "curve_name": "",
                    "counterparty": "",
                    "tenor": "",
                    "price": normalize_number(item.get("成交净价")),
                    "bid_price": "",
                    "ask_price": "",
                    "yield": normalize_number(item.get("最新收益率")),
                    "bid_yield": "",
                    "ask_yield": "",
                    "weighted_yield": normalize_number(item.get("加权收益率")),
                    "change_bp": normalize_number(item.get("涨跌")),
                    "volume": normalize_number(item.get("交易量")),
                    "source_id": source_id,
                    "source_url": source_url,
                    "source_type": source_type,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                    "run_id": run_id,
                }
            )
        return rows

    def _normalize_interbank_quotes(
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
        rows: List[Dict[str, str]] = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            name = normalize_text(item.get("债券简称"))
            if not name:
                continue
            counterparty = normalize_text(item.get("报价机构"))
            checksum_payload = json.dumps({"trade_date": trade_date_str, "dataset": INTERBANK_BOND_QUOTE_DATASET, "symbol": name, "counterparty": counterparty}, ensure_ascii=False, sort_keys=True).encode("utf-8")
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": "bonds_rates_cn",
                    "dataset_type": INTERBANK_BOND_QUOTE_DATASET,
                    "market": "cn_interbank_bond",
                    "exchange": "CFETS",
                    "symbol": name,
                    "name": name,
                    "curve_name": "",
                    "counterparty": counterparty,
                    "tenor": "",
                    "price": "",
                    "bid_price": normalize_number(item.get("买入净价")),
                    "ask_price": normalize_number(item.get("卖出净价")),
                    "yield": "",
                    "bid_yield": normalize_number(item.get("买入收益率")),
                    "ask_yield": normalize_number(item.get("卖出收益率")),
                    "weighted_yield": "",
                    "change_bp": "",
                    "volume": "",
                    "source_id": source_id,
                    "source_url": source_url,
                    "source_type": source_type,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                    "run_id": run_id,
                }
            )
        return rows

    def _normalize_yield_curve_rows(
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
        rows: List[Dict[str, str]] = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            curve_name = normalize_text(item.get("曲线名称"))
            if not curve_name:
                continue
            for source_tenor, normalized_tenor in YIELD_TENOR_MAP.items():
                value = normalize_number(item.get(source_tenor))
                if value == "":
                    continue
                checksum_payload = json.dumps(
                    {"trade_date": trade_date_str, "dataset": YIELD_CURVE_DATASET, "curve_name": curve_name, "tenor": normalized_tenor},
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode("utf-8")
                rows.append(
                    {
                        "trade_date": trade_date_str,
                        "asset_family": "bonds_rates_cn",
                        "dataset_type": YIELD_CURVE_DATASET,
                        "market": "cn_yield_curve",
                        "exchange": "CHINABOND",
                        "symbol": "",
                        "name": "",
                        "curve_name": curve_name,
                        "counterparty": "",
                        "tenor": normalized_tenor,
                        "price": "",
                        "bid_price": "",
                        "ask_price": "",
                        "yield": value,
                        "bid_yield": "",
                        "ask_yield": "",
                        "weighted_yield": "",
                        "change_bp": "",
                        "volume": "",
                        "source_id": source_id,
                        "source_url": source_url,
                        "source_type": source_type,
                        "retrieved_at": retrieved_at,
                        "raw_path": raw_path,
                        "parser_version": PARSER_VERSION,
                        "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                        "run_id": run_id,
                    }
                )
        return rows

    def _normalize_sse_bond_deal_summary_rows(
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
        rows: List[Dict[str, str]] = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            category = normalize_text(item.get("债券类型"))
            if not category:
                continue
            checksum_payload = json.dumps(
                {"trade_date": trade_date_str, "dataset": SSE_BOND_DEAL_SUMMARY_DATASET, "category": category},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": "bonds_rates_cn",
                    "dataset_type": SSE_BOND_DEAL_SUMMARY_DATASET,
                    "market": "cn_exchange_bonds",
                    "exchange": "SSE",
                    "category": category,
                    "name": category,
                    "count_value": normalize_number(item.get("当日成交笔数")),
                    "amount": normalize_number(item.get("当日成交金额")),
                    "market_value": normalize_number(item.get("当年成交金额")),
                    "par_value": normalize_number(item.get("当年成交笔数")),
                    "source_id": source_id,
                    "source_url": source_url,
                    "source_type": source_type,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                    "run_id": run_id,
                }
            )
        return rows

    def _normalize_sse_bond_cash_summary_rows(
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
        rows: List[Dict[str, str]] = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            category = normalize_text(item.get("债券现货"))
            if not category:
                continue
            checksum_payload = json.dumps(
                {"trade_date": trade_date_str, "dataset": SSE_BOND_CASH_SUMMARY_DATASET, "category": category},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": "bonds_rates_cn",
                    "dataset_type": SSE_BOND_CASH_SUMMARY_DATASET,
                    "market": "cn_exchange_bonds",
                    "exchange": "SSE",
                    "category": category,
                    "name": category,
                    "count_value": normalize_number(item.get("托管只数")),
                    "amount": "",
                    "market_value": normalize_number(item.get("托管市值")),
                    "par_value": normalize_number(item.get("托管面值")),
                    "source_id": source_id,
                    "source_url": source_url,
                    "source_type": source_type,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                    "run_id": run_id,
                }
            )
        return rows

    def _raw_path(self, dataset_name: str, trade_date) -> Path:
        return RAW_DIR / "public_bonds" / dataset_name / f"{compact_trade_date(trade_date)}.json"

    def _output_path(self, dataset_name: str, trade_date) -> Path:
        return PUBLIC_BONDS_NORMALIZED_DIR / dataset_name / f"{format_trade_date(trade_date)}.csv"

    def _update_state(self, trade_date: str, overall_status: str, summaries: Dict[str, Dict[str, object]]) -> None:
        payload = self._load_state()
        payload.setdefault("dates", {})[trade_date] = {
            "status": overall_status,
            "families": summaries,
            "updated_at": iso_timestamp(),
        }
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_state(self) -> Dict[str, object]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _normalize_families(self, families: Optional[Iterable[str]]) -> List[str]:
        available = list(self._collectors().keys())
        if not families:
            return available
        requested = []
        for family_name in families:
            if family_name in available and family_name not in requested:
                requested.append(family_name)
        return requested or available

    @staticmethod
    def _resolve_trade_date(trade_date_value: str):
        if trade_date_value == "latest":
            return previous_weekday(now_shanghai().date())
        return parse_trade_date(trade_date_value)

    @staticmethod
    def _fieldnames_for_dataset(dataset_name: str) -> List[str]:
        if dataset_name in {SSE_BOND_DEAL_SUMMARY_DATASET, SSE_BOND_CASH_SUMMARY_DATASET}:
            return PUBLIC_BOND_SUMMARY_FIELDS
        return PUBLIC_BOND_STANDARD_FIELDS


def _iter_csv_rows(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


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
