import hashlib
import json
import time
from io import StringIO
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

import akshare as ak
import pandas as pd
import requests

from .config import PROJECT_ROOT, PUBLIC_ASSETS_NORMALIZED_DIR, PUBLIC_ASSET_STATE_PATH, RAW_DIR
from .constants import (
    BSE_EQUITIES_SNAPSHOT_DATASET,
    CARBON_MARKET_SNAPSHOT_DATASET,
    CONVERTIBLE_BOND_SNAPSHOT_DATASET,
    ETF_SNAPSHOT_DATASET,
    EQUITIES_SNAPSHOT_DATASET,
    FAILED_STATUS,
    NO_DATA_STATUS,
    NOT_APPLICABLE_STATUS,
    PARTIAL_SUCCESS_STATUS,
    PENDING_RETRY_STATUS,
    PUBLIC_ASSET_STANDARD_FIELDS,
    LOF_SNAPSHOT_DATASET,
    MONEY_FUND_SNAPSHOT_DATASET,
    OPEN_FUND_SNAPSHOT_DATASET,
    REITS_SNAPSHOT_DATASET,
    SGE_SPOT_DAILY_DATASET,
    SUCCESS_STATUS,
)
from .normalize.csv_utils import write_dict_rows_csv
from .utils import compact_trade_date, ensure_directory, format_trade_date, iso_timestamp, normalize_number, normalize_text, now_shanghai, parse_trade_date, relative_to_project


PARSER_VERSION = "public_assets_v1"
CARBON_MARKET_LOCATIONS = ["湖北", "上海", "北京", "重庆", "广东", "天津", "深圳", "福建"]
CARBON_MARKET_URL = "http://k.tanjiaoyi.com:8080/KDataController/getHouseDatasInAverage.do"
CARBON_MARKET_PARAMS = {
    "lcnK": "53f75bfcefff58e4046ccfa42171636c",
    "brand": "TAN",
}
SINA_QUOTE_URL = "https://hq.sinajs.cn/list={query}"
GTIMG_QUOTE_URL = "https://qt.gtimg.cn/q={query}"
LOF_REFERENCE_URL = "https://fund.eastmoney.com/LOF_jzzzl.html"
QUOTE_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn/",
}
SINA_BATCH_SIZE = 120
GTIMG_BATCH_SIZE = 80


class PublicAssetSnapshotRunner:
    def __init__(self, *, state_path: Path = PUBLIC_ASSET_STATE_PATH):
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
                fieldnames = list(rows[0].keys()) if rows else PUBLIC_ASSET_STANDARD_FIELDS
                dataset_validation["schema_ok"] = fieldnames == PUBLIC_ASSET_STANDARD_FIELDS
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
            EQUITIES_SNAPSHOT_DATASET: self._collect_equities_snapshot,
            BSE_EQUITIES_SNAPSHOT_DATASET: self._collect_bse_equities_snapshot,
            ETF_SNAPSHOT_DATASET: self._collect_etf_snapshot,
            LOF_SNAPSHOT_DATASET: self._collect_lof_snapshot,
            OPEN_FUND_SNAPSHOT_DATASET: self._collect_open_fund_snapshot,
            MONEY_FUND_SNAPSHOT_DATASET: self._collect_money_fund_snapshot,
            REITS_SNAPSHOT_DATASET: self._collect_reits_snapshot,
            CONVERTIBLE_BOND_SNAPSHOT_DATASET: self._collect_convertible_bond_snapshot,
            SGE_SPOT_DAILY_DATASET: self._collect_sge_spot_daily,
            CARBON_MARKET_SNAPSHOT_DATASET: self._collect_carbon_market_snapshot,
        }

    def _collect_equities_snapshot(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_snapshot(
            dataset_name=EQUITIES_SNAPSHOT_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.stock_zh_a_spot",
            source_url="https://vip.stock.finance.sina.com.cn/mkt/#hs_a",
            source_type="fallback_online",
            live_fetcher=lambda: ak.stock_zh_a_spot(),
            normalizer=self._normalize_equities_rows,
            latest_only=True,
            force=force,
        )

    def _collect_etf_snapshot(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        return self._collect_snapshot(
            dataset_name=ETF_SNAPSHOT_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.fund_etf_spot_ths",
            source_url="https://fund.10jqka.com.cn/datacenter/jz/kfs/etf/",
            source_type="fallback_online",
            live_fetcher=lambda: ak.fund_etf_spot_ths(date=trade_date_str),
            normalizer=self._normalize_etf_rows,
            latest_only=False,
            force=force,
        )

    def _collect_lof_snapshot(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_snapshot(
            dataset_name=LOF_SNAPSHOT_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.fund_lof_spot_em",
            source_url="https://fund.eastmoney.com/LOF_jzzzl.html",
            source_type="fallback_online",
            live_fetcher=self._fetch_lof_snapshot_frame,
            normalizer=self._normalize_lof_rows,
            latest_only=True,
            force=force,
        )

    def _collect_open_fund_snapshot(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_snapshot(
            dataset_name=OPEN_FUND_SNAPSHOT_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.fund_open_fund_daily_em",
            source_url="https://fund.eastmoney.com/fund.html#os_0;isall_0;ft_;pt_1",
            source_type="fallback_online",
            live_fetcher=lambda: ak.fund_open_fund_daily_em(),
            normalizer=self._normalize_open_fund_rows,
            latest_only=True,
            force=force,
        )

    def _collect_money_fund_snapshot(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_snapshot(
            dataset_name=MONEY_FUND_SNAPSHOT_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.fund_money_fund_daily_em",
            source_url="https://fund.eastmoney.com/HBJJ_pjsyl.html",
            source_type="fallback_online",
            live_fetcher=lambda: ak.fund_money_fund_daily_em(),
            normalizer=self._normalize_money_fund_rows,
            latest_only=True,
            force=force,
        )

    def _collect_bse_equities_snapshot(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_snapshot(
            dataset_name=BSE_EQUITIES_SNAPSHOT_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.stock_bj_a_spot_em",
            source_url="https://quote.eastmoney.com/center/gridlist.html#bj_a_board",
            source_type="fallback_online",
            live_fetcher=self._fetch_bse_snapshot_frame,
            normalizer=self._normalize_bse_equities_rows,
            latest_only=True,
            force=force,
        )

    def _collect_reits_snapshot(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_snapshot(
            dataset_name=REITS_SNAPSHOT_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.reits_realtime_em",
            source_url="https://quote.eastmoney.com/center/gridlist.html#fund_reits_all",
            source_type="fallback_online",
            live_fetcher=self._fetch_reits_snapshot_frame,
            normalizer=self._normalize_reits_rows,
            latest_only=True,
            force=force,
        )

    def _collect_convertible_bond_snapshot(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        return self._collect_snapshot(
            dataset_name=CONVERTIBLE_BOND_SNAPSHOT_DATASET,
            trade_date=trade_date,
            run_id=run_id,
            source_id="akshare.bond_zh_hs_cov_spot",
            source_url="https://quote.eastmoney.com/center/gridlist.html#convertible_bond",
            source_type="fallback_online",
            live_fetcher=lambda: ak.bond_zh_hs_cov_spot(),
            normalizer=self._normalize_convertible_bond_rows,
            latest_only=True,
            force=force,
        )

    def _collect_sge_spot_daily(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(SGE_SPOT_DAILY_DATASET, trade_date)
        source_id = "akshare.spot_hist_sge"
        source_url = "https://www.sge.com.cn/sjzx/mrhq"
        source_type = "fallback_online"
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                symbol_frame = ak.spot_symbol_table_sge().fillna("")
                symbols = [normalize_text(item) for item in symbol_frame.get("品种", []).tolist() if normalize_text(item)]
                records = []
                for symbol in symbols:
                    history = ak.spot_hist_sge(symbol=symbol).fillna("")
                    if "date" not in history.columns:
                        continue
                    history["date"] = history["date"].astype(str)
                    target = history.loc[history["date"] == trade_date_str]
                    if target.empty:
                        continue
                    target_record = json.loads(target.to_json(orient="records", force_ascii=False))[0]
                    prior = history.loc[history["date"] < trade_date_str]
                    prev_close = ""
                    if not prior.empty:
                        prev_close = normalize_number(prior.iloc[-1].get("close"))
                    target_record["symbol"] = symbol
                    target_record["prev_close"] = prev_close
                    records.append(target_record)
                    time.sleep(0.35)
                payload = {
                    "records": records,
                    "retrieved_at": iso_timestamp(),
                }
                ensure_directory(raw_path.parent)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                if raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": SGE_SPOT_DAILY_DATASET,
                        "trade_date": trade_date_str,
                        "status": PENDING_RETRY_STATUS,
                        "message": str(exc),
                        "error": str(exc),
                    }

        rows = self._normalize_sge_spot_rows(
            trade_date_str=trade_date_str,
            payload=payload,
            source_id=source_id,
            source_url=source_url,
            source_type=source_type,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        if not rows:
            return self._build_no_data_summary(
                dataset_name=SGE_SPOT_DAILY_DATASET,
                trade_date=trade_date,
                raw_path=raw_path,
                source_id=source_id,
                source_url=source_url,
                source_type=source_type,
                message="normalized rows are empty",
            )
        output_path = self._output_path(SGE_SPOT_DAILY_DATASET, trade_date)
        write_dict_rows_csv(output_path, rows, PUBLIC_ASSET_STANDARD_FIELDS, ["trade_date", "market", "exchange", "symbol"])
        return {
            "dataset": SGE_SPOT_DAILY_DATASET,
            "trade_date": trade_date_str,
            "status": SUCCESS_STATUS,
            "row_count": len(rows),
            "output_path": relative_to_project(output_path, PROJECT_ROOT),
            "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            "source_url": "https://www.sge.com.cn/sjzx/mrhq",
            "source_type": "fallback_online",
        }

    def _collect_carbon_market_snapshot(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(CARBON_MARKET_SNAPSHOT_DATASET, trade_date)
        source_id = "akshare.energy_carbon_domestic"
        source_url = "http://www.tanjiaoyi.com/"
        source_type = "fallback_online"
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                response = requests.get(CARBON_MARKET_URL, params=CARBON_MARKET_PARAMS, timeout=15)
                response.raise_for_status()
                text = response.text.strip()
                start = text.find("(")
                end = text.rfind(")")
                if start < 0 or end <= start:
                    raise ValueError("carbon market response is missing wrapper payload")
                data_json = json.loads(text[start + 1 : end])
                records = []
                for location in CARBON_MARKET_LOCATIONS:
                    location_rows = [item for item in data_json.get(location, []) if str(item.get("INDATE", "")) <= trade_date_str]
                    if not location_rows:
                        continue
                    latest_trade_date = max(str(item.get("INDATE", "")) for item in location_rows)
                    latest_candidates = [item for item in location_rows if str(item.get("INDATE", "")) == latest_trade_date]
                    latest_row = latest_candidates[-1]
                    records.append(latest_row)
                payload = {
                    "records": records,
                    "retrieved_at": iso_timestamp(),
                }
                ensure_directory(raw_path.parent)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                if raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": CARBON_MARKET_SNAPSHOT_DATASET,
                        "trade_date": trade_date_str,
                        "status": PENDING_RETRY_STATUS,
                        "message": str(exc),
                        "error": str(exc),
                    }

        rows = self._normalize_carbon_market_rows(
            trade_date_str=trade_date_str,
            payload=payload,
            source_id=source_id,
            source_url=source_url,
            source_type=source_type,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        if not rows:
            return self._build_no_data_summary(
                dataset_name=CARBON_MARKET_SNAPSHOT_DATASET,
                trade_date=trade_date,
                raw_path=raw_path,
                source_id=source_id,
                source_url=source_url,
                source_type=source_type,
                message="normalized rows are empty",
            )
        output_path = self._output_path(CARBON_MARKET_SNAPSHOT_DATASET, trade_date)
        write_dict_rows_csv(output_path, rows, PUBLIC_ASSET_STANDARD_FIELDS, ["trade_date", "market", "exchange", "symbol"])
        return {
            "dataset": CARBON_MARKET_SNAPSHOT_DATASET,
            "trade_date": trade_date_str,
            "status": SUCCESS_STATUS,
            "row_count": len(rows),
            "output_path": relative_to_project(output_path, PROJECT_ROOT),
            "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            "source_url": "http://www.tanjiaoyi.com/",
            "source_type": "fallback_online",
        }

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
        effective_source_id = source_id
        effective_source_url = source_url
        effective_source_type = source_type
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            if latest_only and trade_date != now_shanghai().date():
                if raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": dataset_name,
                        "trade_date": trade_date_str,
                        "status": NOT_APPLICABLE_STATUS,
                        "message": "latest-only snapshot source without cached payload for requested historical date",
                    }
            else:
                try:
                    data_frame = live_fetcher()
                    effective_source_id = normalize_text(data_frame.attrs.get("source_id")) or source_id
                    effective_source_url = normalize_text(data_frame.attrs.get("source_url")) or source_url
                    effective_source_type = normalize_text(data_frame.attrs.get("source_type")) or source_type
                    payload = {
                        "records": json.loads(data_frame.to_json(orient="records", force_ascii=False)),
                        "retrieved_at": iso_timestamp(),
                        "source_id": effective_source_id,
                        "source_url": effective_source_url,
                        "source_type": effective_source_type,
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

        effective_source_id = normalize_text(payload.get("source_id")) or effective_source_id
        effective_source_url = normalize_text(payload.get("source_url")) or effective_source_url
        effective_source_type = normalize_text(payload.get("source_type")) or effective_source_type
        rows = normalizer(
            trade_date_str=trade_date_str,
            payload=payload,
            source_id=effective_source_id,
            source_url=effective_source_url,
            source_type=effective_source_type,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        if not rows:
            return self._build_no_data_summary(
                dataset_name=dataset_name,
                trade_date=trade_date,
                raw_path=raw_path,
                source_id=effective_source_id,
                source_url=effective_source_url,
                source_type=effective_source_type,
                message="normalized rows are empty",
            )
        output_path = self._output_path(dataset_name, trade_date)
        write_dict_rows_csv(output_path, rows, PUBLIC_ASSET_STANDARD_FIELDS, ["trade_date", "market", "exchange", "symbol"])
        return {
            "dataset": dataset_name,
            "trade_date": trade_date_str,
            "status": SUCCESS_STATUS,
            "row_count": len(rows),
            "output_path": relative_to_project(output_path, PROJECT_ROOT),
            "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            "source_url": effective_source_url,
            "source_type": effective_source_type,
            "source_id": effective_source_id,
        }

    def _build_no_data_summary(
        self,
        *,
        dataset_name: str,
        trade_date,
        raw_path: Optional[Path],
        source_id: str,
        source_url: str,
        source_type: str,
        message: str,
    ) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        output_path = self._output_path(dataset_name, trade_date)
        write_dict_rows_csv(output_path, [], PUBLIC_ASSET_STANDARD_FIELDS, ["trade_date", "market", "exchange", "symbol"])
        summary = {
            "dataset": dataset_name,
            "trade_date": trade_date_str,
            "status": NO_DATA_STATUS,
            "message": message,
            "row_count": 0,
            "output_path": relative_to_project(output_path, PROJECT_ROOT),
            "source_id": source_id,
            "source_url": source_url,
            "source_type": source_type,
        }
        if raw_path is not None:
            summary["raw_path"] = relative_to_project(raw_path, PROJECT_ROOT)
        return summary

    def _fetch_bse_snapshot_frame(self):
        try:
            return ak.stock_bj_a_spot_em()
        except Exception:
            universe = [
                {
                    "symbol": normalize_text(item.get("证券代码")).upper(),
                    "name": normalize_text(item.get("证券简称")),
                    "exchange": "BSE",
                    "quote_symbol": f"bj{normalize_text(item.get('证券代码')).lower()}",
                }
                for item in ak.stock_info_bj_name_code().fillna("").to_dict(orient="records")
                if normalize_text(item.get("证券代码"))
            ]
            return self._frame_from_public_quotes(
                symbols=universe,
                provider="gtimg",
                source_id="tencent.qt_bj_quote_public",
                source_url="https://qt.gtimg.cn/",
                source_type="fallback_online",
            )

    def _fetch_lof_snapshot_frame(self):
        try:
            return ak.fund_lof_spot_em()
        except Exception:
            universe = self._fetch_lof_symbol_universe()
            return self._frame_from_public_quotes(
                symbols=universe,
                provider="sina",
                source_id="sina.hq_fund_quote_public",
                source_url="https://hq.sinajs.cn/",
                source_type="fallback_online",
            )

    def _fetch_reits_snapshot_frame(self):
        try:
            return ak.reits_realtime_em()
        except Exception:
            universe = self._load_recent_symbol_universe(REITS_SNAPSHOT_DATASET)
            if not universe:
                raise
            return self._frame_from_public_quotes(
                symbols=universe,
                provider="sina",
                source_id="sina.hq_reits_quote_public",
                source_url="https://hq.sinajs.cn/",
                source_type="fallback_online",
            )

    def _fetch_lof_symbol_universe(self) -> List[Dict[str, str]]:
        response = requests.get(LOF_REFERENCE_URL, headers=QUOTE_HEADERS, timeout=20)
        response.raise_for_status()
        response.encoding = "gb2312"
        tables = pd.read_html(StringIO(response.text))
        if not tables:
            raise ValueError("LOF universe page returned no tables")
        table = tables[-1].copy()
        flattened_columns = []
        for column in table.columns:
            if isinstance(column, tuple):
                flattened_columns.append(normalize_text(column[-1]))
            else:
                flattened_columns.append(normalize_text(column))
        table.columns = flattened_columns
        table = table.loc[:, ~pd.Index(table.columns).duplicated()]
        code_column = next((name for name in table.columns if "基金代码" in name), "")
        name_column = next((name for name in table.columns if "基金简称" in name), "")
        if not code_column or not name_column:
            raise ValueError("LOF universe table missing code/name columns")
        records: List[Dict[str, str]] = []
        for item in table.fillna("").to_dict(orient="records"):
            symbol = normalize_text(item.get(code_column)).upper()
            if not symbol:
                continue
            name = normalize_text(item.get(name_column))
            name = name.replace("估值图基金吧", "").strip()
            exchange = _infer_security_exchange(symbol)
            if exchange not in {"SSE", "SZSE"}:
                continue
            records.append(
                {
                    "symbol": symbol,
                    "name": name,
                    "exchange": exchange,
                    "quote_symbol": _security_quote_symbol(symbol),
                }
            )
        if not records:
            raise ValueError("LOF universe is empty after parsing Eastmoney reference page")
        return records

    def _load_recent_symbol_universe(self, dataset_name: str) -> List[Dict[str, str]]:
        summary = self.latest_summaries().get(dataset_name, {})
        output_path = normalize_text(summary.get("output_path"))
        if not output_path:
            return []
        csv_path = PROJECT_ROOT / output_path
        if not csv_path.exists():
            return []
        records: List[Dict[str, str]] = []
        for row in _iter_csv_rows(csv_path):
            symbol = normalize_text(row.get("symbol")).upper()
            if not symbol:
                continue
            exchange = normalize_text(row.get("exchange")) or _infer_security_exchange(symbol)
            records.append(
                {
                    "symbol": symbol,
                    "name": normalize_text(row.get("name")),
                    "exchange": exchange,
                    "quote_symbol": _security_quote_symbol(symbol, exchange=exchange),
                }
            )
        return records

    def _frame_from_public_quotes(
        self,
        *,
        symbols: List[Dict[str, str]],
        provider: str,
        source_id: str,
        source_url: str,
        source_type: str,
    ):
        if provider == "sina":
            rows = _fetch_sina_quote_rows(symbols)
        elif provider == "gtimg":
            rows = _fetch_gtimg_quote_rows(symbols)
        else:
            raise ValueError(f"Unsupported public quote provider: {provider}")
        if not rows:
            raise ValueError(f"{provider} public quote provider returned no rows")
        data_frame = pd.DataFrame(rows)
        data_frame.attrs["source_id"] = source_id
        data_frame.attrs["source_url"] = source_url
        data_frame.attrs["source_type"] = source_type
        return data_frame

    def _normalize_equities_rows(
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
            symbol = normalize_text(item.get("代码")).upper()
            if not symbol:
                continue
            rows.append(
                self._row(
                    trade_date=trade_date_str,
                    asset_family="equities_funds_cn",
                    asset_type="stock",
                    market="cn_equities",
                    exchange=_infer_equity_exchange(symbol),
                    symbol=symbol,
                    name=normalize_text(item.get("名称")),
                    last_price=normalize_number(item.get("最新价")),
                    change_amount=normalize_number(item.get("涨跌额")),
                    change_pct=normalize_number(item.get("涨跌幅")),
                    open_value=normalize_number(item.get("今开")),
                    high=normalize_number(item.get("最高")),
                    low=normalize_number(item.get("最低")),
                    prev_close=normalize_number(item.get("昨收")),
                    volume=normalize_number(item.get("成交量")),
                    amount=normalize_number(item.get("成交额")),
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                    run_id=run_id,
                )
            )
        return rows

    def _normalize_etf_rows(
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
            symbol = normalize_text(item.get("基金代码")).upper()
            if not symbol:
                continue
            effective_date = normalize_text(item.get("查询日期")) or normalize_text(item.get("最新-交易日")) or trade_date_str
            if effective_date.lower() == "nat":
                effective_date = trade_date_str
            rows.append(
                self._row(
                    trade_date=effective_date,
                    asset_family="equities_funds_cn",
                    asset_type="etf",
                    market="cn_etf",
                    exchange=_infer_security_exchange(symbol),
                    symbol=symbol,
                    name=normalize_text(item.get("基金名称")),
                    last_price=normalize_number(item.get("当前-单位净值") or item.get("最新-单位净值")),
                    change_amount=normalize_number(item.get("增长值")),
                    change_pct=normalize_number(item.get("增长率")),
                    open_value="",
                    high="",
                    low="",
                    prev_close=normalize_number(item.get("前一日-单位净值")),
                    volume="",
                    amount="",
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                    run_id=run_id,
                )
            )
        return rows

    def _normalize_bse_equities_rows(
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
            symbol = normalize_text(item.get("代码")).upper()
            if not symbol:
                continue
            rows.append(
                self._row(
                    trade_date=trade_date_str,
                    asset_family="equities_funds_cn",
                    asset_type="stock",
                    market="cn_equities",
                    exchange="BSE",
                    symbol=symbol,
                    name=normalize_text(item.get("名称")),
                    last_price=normalize_number(item.get("最新价")),
                    change_amount=normalize_number(item.get("涨跌额")),
                    change_pct=normalize_number(item.get("涨跌幅")),
                    open_value=normalize_number(item.get("今开")),
                    high=normalize_number(item.get("最高")),
                    low=normalize_number(item.get("最低")),
                    prev_close=normalize_number(item.get("昨收")),
                    volume=normalize_number(item.get("成交量")),
                    amount=normalize_number(item.get("成交额")),
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                    run_id=run_id,
                )
            )
        return rows

    def _normalize_lof_rows(
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
            symbol = normalize_text(item.get("代码")).upper()
            if not symbol:
                continue
            rows.append(
                self._row(
                    trade_date=trade_date_str,
                    asset_family="equities_funds_cn",
                    asset_type="lof",
                    market="cn_funds",
                    exchange=_infer_security_exchange(symbol),
                    symbol=symbol,
                    name=normalize_text(item.get("名称")),
                    last_price=normalize_number(item.get("最新价")),
                    change_amount=normalize_number(item.get("涨跌额")),
                    change_pct=normalize_number(item.get("涨跌幅")),
                    open_value=normalize_number(item.get("开盘价")),
                    high=normalize_number(item.get("最高价")),
                    low=normalize_number(item.get("最低价")),
                    prev_close=normalize_number(item.get("昨收")),
                    volume=normalize_number(item.get("成交量")),
                    amount=normalize_number(item.get("成交额")),
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                    run_id=run_id,
                )
            )
        return rows

    def _normalize_open_fund_rows(
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
            symbol = normalize_text(item.get("基金代码")).upper()
            if not symbol:
                continue
            latest_nav = next(
                (
                    normalize_number(item.get(column))
                    for column in item.keys()
                    if str(column).endswith("-单位净值") and normalize_number(item.get(column))
                ),
                "",
            )
            prev_nav_candidates = [
                normalize_number(item.get(column))
                for column in item.keys()
                if str(column).endswith("-单位净值") and normalize_number(item.get(column))
            ]
            prev_nav = prev_nav_candidates[1] if len(prev_nav_candidates) > 1 else ""
            rows.append(
                self._row(
                    trade_date=trade_date_str,
                    asset_family="equities_funds_cn",
                    asset_type="open_fund",
                    market="cn_funds",
                    exchange="CN_FUNDS",
                    symbol=symbol,
                    name=normalize_text(item.get("基金简称")),
                    last_price=latest_nav,
                    change_amount=normalize_number(item.get("日增长值")),
                    change_pct=normalize_number(item.get("日增长率")),
                    open_value="",
                    high="",
                    low="",
                    prev_close=prev_nav,
                    volume="",
                    amount="",
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                    run_id=run_id,
                )
            )
        return rows

    def _normalize_money_fund_rows(
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
            symbol = normalize_text(item.get("基金代码")).upper()
            if not symbol:
                continue
            latest_yield = next(
                (
                    normalize_number(item.get(column))
                    for column in item.keys()
                    if str(column).endswith("-万份收益") and normalize_number(item.get(column))
                ),
                "",
            )
            prev_yield_candidates = [
                normalize_number(item.get(column))
                for column in item.keys()
                if str(column).endswith("-万份收益") and normalize_number(item.get(column))
            ]
            prev_yield = prev_yield_candidates[1] if len(prev_yield_candidates) > 1 else ""
            rows.append(
                self._row(
                    trade_date=trade_date_str,
                    asset_family="equities_funds_cn",
                    asset_type="money_fund",
                    market="cn_funds",
                    exchange="CN_FUNDS",
                    symbol=symbol,
                    name=normalize_text(item.get("基金简称")),
                    last_price=latest_yield,
                    change_amount="",
                    change_pct=normalize_number(item.get("日涨幅")),
                    open_value="",
                    high="",
                    low="",
                    prev_close=prev_yield,
                    volume="",
                    amount="",
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                    run_id=run_id,
                )
            )
        return rows

    def _normalize_reits_rows(
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
            symbol = normalize_text(item.get("代码")).upper()
            if not symbol:
                continue
            rows.append(
                self._row(
                    trade_date=trade_date_str,
                    asset_family="equities_funds_cn",
                    asset_type="reits",
                    market="cn_reits",
                    exchange=_infer_security_exchange(symbol),
                    symbol=symbol,
                    name=normalize_text(item.get("名称")),
                    last_price=normalize_number(item.get("最新价")),
                    change_amount=normalize_number(item.get("涨跌额")),
                    change_pct=normalize_number(item.get("涨跌幅")),
                    open_value=normalize_number(item.get("开盘价")),
                    high=normalize_number(item.get("最高价")),
                    low=normalize_number(item.get("最低价")),
                    prev_close=normalize_number(item.get("昨收")),
                    volume=normalize_number(item.get("成交量")),
                    amount=normalize_number(item.get("成交额")),
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                    run_id=run_id,
                )
            )
        return rows

    def _normalize_convertible_bond_rows(
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
            symbol = normalize_text(item.get("code") or item.get("symbol")).upper()
            if not symbol:
                continue
            rows.append(
                self._row(
                    trade_date=trade_date_str,
                    asset_family="bonds_rates_cn",
                    asset_type="convertible_bond",
                    market="cn_exchange_bonds",
                    exchange=_infer_security_exchange(symbol),
                    symbol=symbol,
                    name=normalize_text(item.get("name")),
                    last_price=normalize_number(item.get("trade")),
                    change_amount=normalize_number(item.get("pricechange")),
                    change_pct=normalize_number(item.get("changepercent")),
                    open_value=normalize_number(item.get("open")),
                    high=normalize_number(item.get("high")),
                    low=normalize_number(item.get("low")),
                    prev_close=normalize_number(item.get("settlement")),
                    volume=normalize_number(item.get("volume")),
                    amount=normalize_number(item.get("amount")),
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                    run_id=run_id,
                )
            )
        return rows

    def _normalize_sge_spot_rows(
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
            symbol = normalize_text(item.get("symbol") or item.get("品种")).upper()
            if not symbol:
                continue
            open_value = normalize_number(item.get("open"))
            close_value = normalize_number(item.get("close"))
            prev_close = normalize_number(item.get("prev_close"))
            change_amount = ""
            change_pct = ""
            if close_value != "" and prev_close not in {"", "0", "0.0"}:
                try:
                    close_float = float(close_value)
                    prev_float = float(prev_close)
                    change_amount = normalize_number(close_float - prev_float)
                    if prev_float != 0:
                        change_pct = normalize_number((close_float - prev_float) / prev_float * 100)
                except ValueError:
                    pass
            rows.append(
                self._row(
                    trade_date=trade_date_str,
                    asset_family="precious_metals_spot_cn",
                    asset_type="precious_metal_spot",
                    market="sge_spot",
                    exchange="SGE",
                    symbol=symbol,
                    name=symbol,
                    last_price=close_value,
                    change_amount=change_amount,
                    change_pct=change_pct,
                    open_value=open_value,
                    high=normalize_number(item.get("high")),
                    low=normalize_number(item.get("low")),
                    prev_close=prev_close,
                    volume="",
                    amount="",
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
                    retrieved_at=retrieved_at,
                    raw_path=raw_path,
                    run_id=run_id,
                )
                )
        return rows

    def _normalize_carbon_market_rows(
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
            location = normalize_text(item.get("HOUSENAME"))
            price = normalize_number(item.get("deal"))
            if not location or not price:
                continue
            rows.append(
                self._row(
                    trade_date=normalize_text(item.get("INDATE")) or trade_date_str,
                    asset_family="commodity_energy_cn",
                    asset_type="carbon_spot",
                    market="cn_carbon",
                    exchange=location,
                    symbol=f"{location}:CEA",
                    name=f"{location}碳排放配额现货",
                    last_price=price,
                    change_amount="",
                    change_pct="",
                    open_value="",
                    high="",
                    low="",
                    prev_close="",
                    volume=normalize_number(item.get("DEALNUM")),
                    amount=normalize_number(item.get("DEALAMOUNT")),
                    source_id=source_id,
                    source_url=source_url,
                    source_type=source_type,
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
        asset_type: str,
        market: str,
        exchange: str,
        symbol: str,
        name: str,
        last_price: str,
        change_amount: str,
        change_pct: str,
        open_value: str,
        high: str,
        low: str,
        prev_close: str,
        volume: str,
        amount: str,
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
                "asset_type": asset_type,
                "symbol": symbol,
                "last_price": last_price,
                "source_id": source_id,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        return {
            "trade_date": trade_date,
            "asset_family": asset_family,
            "asset_type": asset_type,
            "market": market,
            "exchange": exchange,
            "symbol": symbol,
            "name": name,
            "last_price": last_price,
            "change_amount": change_amount,
            "change_pct": change_pct,
            "open": open_value,
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "volume": volume,
            "amount": amount,
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
        return RAW_DIR / "public_assets" / dataset_name / f"{compact_trade_date(trade_date)}.json"

    def _output_path(self, dataset_name: str, trade_date) -> Path:
        return PUBLIC_ASSETS_NORMALIZED_DIR / dataset_name / f"{format_trade_date(trade_date)}.csv"

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
            return now_shanghai().date()
        return parse_trade_date(trade_date_value)

    @staticmethod
    def _normalize_families(families: Optional[Iterable[str]]) -> List[str]:
        if not families:
            return [
                EQUITIES_SNAPSHOT_DATASET,
                BSE_EQUITIES_SNAPSHOT_DATASET,
                ETF_SNAPSHOT_DATASET,
                LOF_SNAPSHOT_DATASET,
                OPEN_FUND_SNAPSHOT_DATASET,
                MONEY_FUND_SNAPSHOT_DATASET,
                REITS_SNAPSHOT_DATASET,
                CONVERTIBLE_BOND_SNAPSHOT_DATASET,
                SGE_SPOT_DAILY_DATASET,
                CARBON_MARKET_SNAPSHOT_DATASET,
            ]
        normalized = []
        for value in families:
            for token in str(value).split(","):
                cleaned = token.strip()
                if cleaned:
                    normalized.append(cleaned)
        return normalized


def _infer_equity_exchange(symbol: str) -> str:
    code = symbol.lower()
    if code.startswith("sh"):
        return "SSE"
    if code.startswith("sz"):
        return "SZSE"
    if code.startswith("bj"):
        return "BSE"
    return _infer_security_exchange(symbol)


def _infer_security_exchange(symbol: str) -> str:
    code = normalize_text(symbol)
    if code.startswith(("50", "51", "58", "60", "68", "508", "180")):
        return "SSE"
    if code.startswith(("15", "16", "18", "30", "39")):
        return "SZSE"
    if code.startswith(("82", "83", "87", "88", "92")):
        return "BSE"
    return ""


def _iter_csv_rows(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        import csv

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


def _security_quote_symbol(symbol: str, *, exchange: str = "") -> str:
    code = normalize_text(symbol).lower()
    effective_exchange = normalize_text(exchange).upper() or _infer_security_exchange(symbol)
    if code.startswith(("sh", "sz", "bj")):
        return code
    if effective_exchange == "SSE":
        return f"sh{code}"
    if effective_exchange == "SZSE":
        return f"sz{code}"
    if effective_exchange == "BSE":
        return f"bj{code}"
    return code


def _chunked(values: List[Dict[str, str]], size: int) -> Iterable[List[Dict[str, str]]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _fetch_sina_quote_rows(symbols: List[Dict[str, str]]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for chunk in _chunked(symbols, SINA_BATCH_SIZE):
        query = ",".join(item.get("quote_symbol", "") for item in chunk if item.get("quote_symbol"))
        if not query:
            continue
        response = requests.get(SINA_QUOTE_URL.format(query=query), headers=QUOTE_HEADERS, timeout=20)
        response.raise_for_status()
        response.encoding = "gbk"
        payload_by_symbol: Dict[str, Dict[str, str]] = {}
        for line in response.text.split(";"):
            line = line.strip()
            if not line or '"' not in line:
                continue
            prefix, quoted = line.split('"', 1)
            quote_symbol = normalize_text(prefix.split("_")[-1].split("=")[0]).lower()
            raw = quoted.rsplit('"', 1)[0]
            fields = raw.split(",")
            if len(fields) < 10:
                continue
            payload_by_symbol[quote_symbol] = {
                "name": normalize_text(fields[0]),
                "open": normalize_number(fields[1]),
                "prev_close": normalize_number(fields[2]),
                "last_price": normalize_number(fields[3]),
                "high": normalize_number(fields[4]),
                "low": normalize_number(fields[5]),
                "volume": normalize_number(fields[8]),
                "amount": normalize_number(fields[9]),
            }
        for item in chunk:
            quote_symbol = normalize_text(item.get("quote_symbol")).lower()
            payload = payload_by_symbol.get(quote_symbol, {})
            last_price = normalize_number(payload.get("last_price"))
            prev_close = normalize_number(payload.get("prev_close"))
            if last_price in {"", "0", "0.0"} and prev_close in {"", "0", "0.0"}:
                continue
            change_amount, change_pct = _derive_change_fields(last_price, prev_close)
            rows.append(
                {
                    "代码": normalize_text(item.get("symbol")).upper(),
                    "名称": payload.get("name") or normalize_text(item.get("name")),
                    "最新价": last_price,
                    "涨跌额": change_amount,
                    "涨跌幅": change_pct,
                    "今开": normalize_number(payload.get("open")),
                    "最高": normalize_number(payload.get("high")),
                    "最低": normalize_number(payload.get("low")),
                    "昨收": prev_close,
                    "成交量": normalize_number(payload.get("volume")),
                    "成交额": normalize_number(payload.get("amount")),
                    "开盘价": normalize_number(payload.get("open")),
                    "最高价": normalize_number(payload.get("high")),
                    "最低价": normalize_number(payload.get("low")),
                }
            )
    return rows


def _fetch_gtimg_quote_rows(symbols: List[Dict[str, str]]) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for chunk in _chunked(symbols, GTIMG_BATCH_SIZE):
        query = ",".join(item.get("quote_symbol", "") for item in chunk if item.get("quote_symbol"))
        if not query:
            continue
        response = requests.get(GTIMG_QUOTE_URL.format(query=query), headers=QUOTE_HEADERS, timeout=20)
        response.raise_for_status()
        response.encoding = "gbk"
        payload_by_symbol: Dict[str, Dict[str, str]] = {}
        for line in response.text.split(";"):
            line = line.strip()
            if not line or '"' not in line:
                continue
            prefix, quoted = line.split('"', 1)
            quote_symbol = normalize_text(prefix.split("_")[-1].split("=")[0]).lower()
            raw = quoted.rsplit('"', 1)[0]
            fields = raw.split("~")
            if len(fields) < 36:
                continue
            volume = ""
            amount = ""
            summary_field = normalize_text(fields[35])
            if "/" in summary_field:
                summary_parts = summary_field.split("/")
                if len(summary_parts) >= 3:
                    volume = normalize_number(summary_parts[1])
                    amount = normalize_number(summary_parts[2])
            payload_by_symbol[quote_symbol] = {
                "name": normalize_text(fields[1]),
                "last_price": normalize_number(fields[3]),
                "prev_close": normalize_number(fields[4]),
                "open": normalize_number(fields[5]),
                "change_amount": normalize_number(fields[31]),
                "change_pct": normalize_number(fields[32]),
                "high": normalize_number(fields[33]),
                "low": normalize_number(fields[34]),
                "volume": volume or normalize_number(fields[6]),
                "amount": amount,
            }
        for item in chunk:
            quote_symbol = normalize_text(item.get("quote_symbol")).lower()
            payload = payload_by_symbol.get(quote_symbol, {})
            last_price = normalize_number(payload.get("last_price"))
            prev_close = normalize_number(payload.get("prev_close"))
            if last_price in {"", "0", "0.0"} and prev_close in {"", "0", "0.0"}:
                continue
            change_amount = normalize_number(payload.get("change_amount"))
            change_pct = normalize_number(payload.get("change_pct"))
            if not change_amount and not change_pct:
                change_amount, change_pct = _derive_change_fields(last_price, prev_close)
            rows.append(
                {
                    "代码": normalize_text(item.get("symbol")).upper(),
                    "名称": payload.get("name") or normalize_text(item.get("name")),
                    "最新价": last_price,
                    "涨跌额": change_amount,
                    "涨跌幅": change_pct,
                    "今开": normalize_number(payload.get("open")),
                    "最高": normalize_number(payload.get("high")),
                    "最低": normalize_number(payload.get("low")),
                    "昨收": prev_close,
                    "成交量": normalize_number(payload.get("volume")),
                    "成交额": normalize_number(payload.get("amount")),
                    "开盘价": normalize_number(payload.get("open")),
                    "最高价": normalize_number(payload.get("high")),
                    "最低价": normalize_number(payload.get("low")),
                }
            )
    return rows


def _derive_change_fields(last_price: str, prev_close: str) -> Tuple[str, str]:
    if last_price in {"", None} or prev_close in {"", None, "0", "0.0"}:
        return "", ""
    try:
        last_value = float(last_price)
        prev_value = float(prev_close)
    except (TypeError, ValueError):
        return "", ""
    change_amount = normalize_number(last_value - prev_value)
    change_pct = ""
    if prev_value != 0:
        change_pct = normalize_number((last_value - prev_value) / prev_value * 100)
    return change_amount, change_pct
