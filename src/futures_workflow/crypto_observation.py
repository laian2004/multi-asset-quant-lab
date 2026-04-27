import csv
import hashlib
import json
import time
from pathlib import Path
from typing import Dict, Iterable, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .config import CRYPTO_NORMALIZED_DIR, CRYPTO_STATE_PATH, PROJECT_ROOT, RAW_DIR
from .constants import (
    CRYPTO_ASSETS_DATASET,
    CRYPTO_ASSET_STANDARD_FIELDS,
    CRYPTO_BITCOIN_HOLDINGS_DATASET,
    CRYPTO_BITCOIN_HOLDING_STANDARD_FIELDS,
    CRYPTO_CME_BITCOIN_REPORT_DATASET,
    CRYPTO_CME_BITCOIN_REPORT_FIELDS,
    CRYPTO_DAILY_QUOTES_DATASET,
    CRYPTO_DAILY_QUOTE_STANDARD_FIELDS,
    CRYPTO_DERIVATIVE_PUBLIC_FIELDS,
    CRYPTO_DERIVATIVES_PUBLIC_DATASET,
    CRYPTO_GLOBAL_SNAPSHOT_DATASET,
    CRYPTO_GLOBAL_STANDARD_FIELDS,
    FAILED_STATUS,
    NOT_APPLICABLE_STATUS,
    NO_DATA_STATUS,
    PENDING_RETRY_STATUS,
    SUCCESS_STATUS,
)
from .normalize.csv_utils import write_dict_rows_csv
from .utils import compact_trade_date, ensure_directory, format_trade_date, iso_timestamp, normalize_number, normalize_text, now_shanghai, parse_trade_date, relative_to_project


PARSER_VERSION = "crypto_observation_v2"
LEGAL_NOTE = "仅作全球公开市场数据研究与行情观察，不提供交易、撮合、开户、引流或任何境内虚拟货币经营服务。"
SOURCE_ID = "coingecko.coins_markets_public"
SOURCE_URL = "https://api.coingecko.com/api/v3/coins/markets"
SOURCE_TYPE = "fallback_online"
DEFAULT_COIN_IDS = [
    "bitcoin",
    "ethereum",
    "tether",
    "usd-coin",
    "binancecoin",
    "solana",
    "xrp",
    "dogecoin",
]
DERIVATIVES_SOURCE_ID = "coingecko.derivatives_public"
DERIVATIVES_SOURCE_URL = "https://api.coingecko.com/api/v3/derivatives"
DERIVATIVES_SOURCE_TYPE = "fallback_online"
OKX_SWAP_SOURCE_ID = "okx.swap_tickers_public"
OKX_SWAP_SOURCE_URL = "https://www.okx.com/api/v5/market/tickers?instType=SWAP"
OKX_SWAP_INSTRUMENT_URL = "https://www.okx.com/api/v5/public/instruments?instType=SWAP"
OKX_SWAP_SOURCE_TYPE = "fallback_online"
BITCOIN_HOLDINGS_SOURCE_ID = "akshare.crypto_bitcoin_hold_report"
BITCOIN_HOLDINGS_SOURCE_URL = "https://crypto-akshare.akfamily.xyz/data/crypto/crypto.html"
BITCOIN_HOLDINGS_SOURCE_TYPE = "fallback_online"
CME_BITCOIN_REPORT_SOURCE_ID = "akshare.crypto_bitcoin_cme"
CME_BITCOIN_REPORT_SOURCE_URL = "https://datacenter.jin10.com/reportType/dc_cme_btc_report"
CME_BITCOIN_REPORT_SOURCE_TYPE = "fallback_online"
OKX_PRIORITY_UNDERLYINGS = {"BTC", "ETH", "BNB", "SOL", "XRP", "DOGE"}


class CryptoObservationRunner:
    def __init__(self, *, state_path: Path = CRYPTO_STATE_PATH):
        self.state_path = state_path
        ensure_directory(self.state_path.parent)
        if not self.state_path.exists():
            self.state_path.write_text(json.dumps({"dates": {}}, ensure_ascii=False, indent=2), encoding="utf-8")

    def sync(self, trade_date_value: str = "latest", force: bool = False) -> Dict[str, object]:
        trade_date = self._resolve_trade_date(trade_date_value)
        trade_date_str = format_trade_date(trade_date)
        run_id = hashlib.sha1(f"{trade_date_str}|{iso_timestamp()}".encode("utf-8")).hexdigest()[:12]

        snapshot_summary = self._collect_snapshot_dataset(trade_date=trade_date, run_id=run_id, force=force)
        asset_summary = self._collect_asset_dataset(trade_date=trade_date, run_id=run_id, force=force)
        daily_quote_summary = self._collect_daily_quote_dataset(trade_date=trade_date, run_id=run_id, force=force)
        bitcoin_holdings_summary = self._collect_bitcoin_holdings_dataset(trade_date=trade_date, run_id=run_id, force=force)
        cme_bitcoin_report_summary = self._collect_cme_bitcoin_report_dataset(trade_date=trade_date, run_id=run_id, force=force)
        derivatives_summary = self._collect_derivatives_public_dataset(
            trade_date=trade_date,
            run_id=run_id,
            force=force,
            cme_report_summary=cme_bitcoin_report_summary,
        )

        summaries = {
            CRYPTO_GLOBAL_SNAPSHOT_DATASET: snapshot_summary,
            CRYPTO_ASSETS_DATASET: asset_summary,
            CRYPTO_DAILY_QUOTES_DATASET: daily_quote_summary,
            CRYPTO_DERIVATIVES_PUBLIC_DATASET: derivatives_summary,
            CRYPTO_BITCOIN_HOLDINGS_DATASET: bitcoin_holdings_summary,
            CRYPTO_CME_BITCOIN_REPORT_DATASET: cme_bitcoin_report_summary,
        }
        overall_status = self._merge_statuses(item.get("status", "") for item in summaries.values())
        self._update_state(trade_date_str, overall_status, summaries)
        return {
            "trade_date": trade_date_str,
            "status": overall_status,
            "datasets": summaries,
            "run_id": run_id,
        }

    def validate(self, trade_date_value: str) -> Dict[str, object]:
        trade_date = self._resolve_trade_date(trade_date_value)
        trade_date_str = format_trade_date(trade_date)
        state = self._load_state().get("dates", {}).get(trade_date_str, {})
        dataset_summaries = self._state_datasets(state)
        validations: Dict[str, Dict[str, object]] = {}
        statuses = []
        for dataset_name, fieldnames in (
            (CRYPTO_GLOBAL_SNAPSHOT_DATASET, CRYPTO_GLOBAL_STANDARD_FIELDS),
            (CRYPTO_ASSETS_DATASET, CRYPTO_ASSET_STANDARD_FIELDS),
            (CRYPTO_DAILY_QUOTES_DATASET, CRYPTO_DAILY_QUOTE_STANDARD_FIELDS),
            (CRYPTO_DERIVATIVES_PUBLIC_DATASET, CRYPTO_DERIVATIVE_PUBLIC_FIELDS),
            (CRYPTO_BITCOIN_HOLDINGS_DATASET, CRYPTO_BITCOIN_HOLDING_STANDARD_FIELDS),
            (CRYPTO_CME_BITCOIN_REPORT_DATASET, CRYPTO_CME_BITCOIN_REPORT_FIELDS),
        ):
            summary = dataset_summaries.get(dataset_name, {})
            output_path = summary.get("output_path", "")
            csv_path = PROJECT_ROOT / output_path if output_path else None
            validation = {
                "csv_exists": bool(csv_path and csv_path.exists()),
                "schema_ok": False,
                "row_count": 0,
                "missing_raw_paths": [],
            }
            if csv_path and csv_path.exists():
                rows = list(_iter_csv_rows(csv_path))
                validation["row_count"] = len(rows)
                fieldnames_actual = list(rows[0].keys()) if rows else fieldnames
                validation["schema_ok"] = fieldnames_actual == fieldnames
                for row in rows:
                    raw_path = normalize_text(row.get("raw_path"))
                    if raw_path and not (PROJECT_ROOT / raw_path).exists():
                        validation["missing_raw_paths"].append(raw_path)
            validations[dataset_name] = validation
            summary_status = str(summary.get("status", ""))
            if summary_status in {NO_DATA_STATUS, NOT_APPLICABLE_STATUS, PENDING_RETRY_STATUS, FAILED_STATUS}:
                statuses.append(summary_status)
            elif validation["csv_exists"] and validation["schema_ok"] and not validation["missing_raw_paths"]:
                statuses.append(SUCCESS_STATUS)
            else:
                statuses.append(FAILED_STATUS)
        return {
            "trade_date": trade_date_str,
            "status": self._merge_statuses(statuses),
            "datasets": validations,
        }

    def latest_summary(self) -> Dict[str, object]:
        return self.latest_summaries().get(CRYPTO_GLOBAL_SNAPSHOT_DATASET, {})

    def latest_summaries(self) -> Dict[str, Dict[str, object]]:
        state = self._load_state().get("dates", {})
        if not state:
            return {}
        latest_by_dataset: Dict[str, Dict[str, object]] = {}
        fallback_by_dataset: Dict[str, Dict[str, object]] = {}
        for trade_date in sorted(state.keys(), reverse=True):
            dataset_map = self._state_datasets(state[trade_date])
            for dataset_name, summary in dataset_map.items():
                fallback_by_dataset.setdefault(dataset_name, summary)
                if dataset_name not in latest_by_dataset and summary.get("status") == SUCCESS_STATUS and int(summary.get("row_count", 0) or 0) > 0:
                    latest_by_dataset[dataset_name] = summary
        for dataset_name, summary in fallback_by_dataset.items():
            latest_by_dataset.setdefault(dataset_name, summary)
        return latest_by_dataset

    def latest_recorded_summaries(self) -> Dict[str, Dict[str, object]]:
        state = self._load_state().get("dates", {})
        if not state:
            return {}
        latest_by_dataset: Dict[str, Dict[str, object]] = {}
        for trade_date in sorted(state.keys(), reverse=True):
            dataset_map = self._state_datasets(state[trade_date])
            for dataset_name, summary in dataset_map.items():
                latest_by_dataset.setdefault(dataset_name, summary)
        return latest_by_dataset

    def _collect_snapshot_dataset(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(CRYPTO_GLOBAL_SNAPSHOT_DATASET, trade_date)
        payload = self._load_or_fetch_latest_only_payload(
            trade_date=trade_date,
            raw_path=raw_path,
            force=force,
            fetcher=self._fetch_live_snapshot_payload,
            dataset_name=CRYPTO_GLOBAL_SNAPSHOT_DATASET,
        )
        if isinstance(payload, dict) and payload.get("status"):
            return payload
        rows = self._normalize_snapshot_rows(
            trade_date_str=trade_date_str,
            payload=payload,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        return self._write_dataset(
            dataset_name=CRYPTO_GLOBAL_SNAPSHOT_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=CRYPTO_GLOBAL_STANDARD_FIELDS,
            key_fields=["trade_date", "symbol"],
            raw_path=raw_path,
            source_url=SOURCE_URL,
            source_type=SOURCE_TYPE,
        )

    def _collect_asset_dataset(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(CRYPTO_ASSETS_DATASET, trade_date)
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            snapshot_raw = self._raw_path(CRYPTO_GLOBAL_SNAPSHOT_DATASET, trade_date)
            if snapshot_raw.exists():
                payload = json.loads(snapshot_raw.read_text(encoding="utf-8"))
                ensure_directory(raw_path.parent)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                payload = self._load_or_fetch_latest_only_payload(
                    trade_date=trade_date,
                    raw_path=raw_path,
                    force=force,
                    fetcher=self._fetch_live_snapshot_payload,
                    dataset_name=CRYPTO_ASSETS_DATASET,
                )
        if isinstance(payload, dict) and payload.get("status"):
            return payload
        rows = self._normalize_asset_rows(
            trade_date_str=trade_date_str,
            payload=payload,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        return self._write_dataset(
            dataset_name=CRYPTO_ASSETS_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=CRYPTO_ASSET_STANDARD_FIELDS,
            key_fields=["trade_date", "symbol"],
            raw_path=raw_path,
            source_url=SOURCE_URL,
            source_type=SOURCE_TYPE,
        )

    def _collect_daily_quote_dataset(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(CRYPTO_DAILY_QUOTES_DATASET, trade_date)
        effective_raw_path = raw_path
        effective_source_url = "https://api.coingecko.com/api/v3/coins/{id}/history"
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                records = []
                for coin_id in DEFAULT_COIN_IDS:
                    history = self._fetch_history_payload(coin_id, trade_date_str)
                    history["coin_id"] = coin_id
                    records.append(history)
                    time.sleep(0.35)
                payload = {"records": records, "retrieved_at": iso_timestamp()}
                ensure_directory(raw_path.parent)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                snapshot_raw = self._raw_path(CRYPTO_GLOBAL_SNAPSHOT_DATASET, trade_date)
                if snapshot_raw.exists():
                    payload = json.loads(snapshot_raw.read_text(encoding="utf-8"))
                    effective_raw_path = snapshot_raw
                    effective_source_url = SOURCE_URL
                elif raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": CRYPTO_DAILY_QUOTES_DATASET,
                        "trade_date": trade_date_str,
                        "status": PENDING_RETRY_STATUS,
                        "message": str(exc),
                        "error": str(exc),
                    }
        rows = self._normalize_daily_quote_rows(
            trade_date_str=trade_date_str,
            payload=payload,
            raw_path=relative_to_project(effective_raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        return self._write_dataset(
            dataset_name=CRYPTO_DAILY_QUOTES_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=CRYPTO_DAILY_QUOTE_STANDARD_FIELDS,
            key_fields=["trade_date", "symbol"],
            raw_path=effective_raw_path,
            source_url=effective_source_url,
            source_type=SOURCE_TYPE,
        )

    def _collect_derivatives_public_dataset(self, *, trade_date, run_id: str, force: bool, cme_report_summary: Dict[str, object]) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(CRYPTO_DERIVATIVES_PUBLIC_DATASET, trade_date)
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            if trade_date != now_shanghai().date():
                if raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": CRYPTO_DERIVATIVES_PUBLIC_DATASET,
                        "trade_date": trade_date_str,
                        "status": NOT_APPLICABLE_STATUS,
                        "message": "crypto derivatives public dataset currently supports latest date or cached historical payloads only",
                    }
            else:
                try:
                    payload = self._fetch_derivatives_payload()
                    ensure_directory(raw_path.parent)
                    raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                except Exception as exc:
                    if raw_path.exists():
                        payload = json.loads(raw_path.read_text(encoding="utf-8"))
                    elif str(cme_report_summary.get("status", "")) == SUCCESS_STATUS:
                        cme_rows = self._load_cme_report_rows(cme_report_summary)
                        if cme_rows:
                            rows = self._normalize_derivative_rows_from_cme_report(
                                trade_date_str=trade_date_str,
                                rows=cme_rows,
                                raw_path=normalize_text(cme_report_summary.get("raw_path")),
                                run_id=run_id,
                            )
                            return self._write_dataset(
                                dataset_name=CRYPTO_DERIVATIVES_PUBLIC_DATASET,
                                trade_date=trade_date,
                                rows=rows,
                                fieldnames=CRYPTO_DERIVATIVE_PUBLIC_FIELDS,
                                key_fields=["trade_date", "exchange", "symbol", "contract_type"],
                                raw_path=self._resolve_project_path(normalize_text(cme_report_summary.get("raw_path"))),
                                source_url=CME_BITCOIN_REPORT_SOURCE_URL,
                                source_type=CME_BITCOIN_REPORT_SOURCE_TYPE,
                            )
                    else:
                        try:
                            payload = self._fetch_okx_swap_payload()
                            ensure_directory(raw_path.parent)
                            raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                        except Exception as okx_exc:
                            return {
                                "dataset": CRYPTO_DERIVATIVES_PUBLIC_DATASET,
                                "trade_date": trade_date_str,
                                "status": PENDING_RETRY_STATUS,
                                "message": str(exc),
                                "error": str(exc),
                                "fallback_error": str(okx_exc),
                            }
        if normalize_text(payload.get("source_id")) == OKX_SWAP_SOURCE_ID:
            rows = self._normalize_derivative_rows_from_okx_payload(
                trade_date_str=trade_date_str,
                payload=payload,
                raw_path=relative_to_project(raw_path, PROJECT_ROOT),
                run_id=run_id,
            )
            return self._write_dataset(
                dataset_name=CRYPTO_DERIVATIVES_PUBLIC_DATASET,
                trade_date=trade_date,
                rows=rows,
                fieldnames=CRYPTO_DERIVATIVE_PUBLIC_FIELDS,
                key_fields=["trade_date", "exchange", "symbol", "contract_type"],
                raw_path=raw_path,
                source_url=OKX_SWAP_SOURCE_URL,
                source_type=OKX_SWAP_SOURCE_TYPE,
            )
        rows = self._normalize_derivative_rows(
            trade_date_str=trade_date_str,
            payload=payload,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        return self._write_dataset(
            dataset_name=CRYPTO_DERIVATIVES_PUBLIC_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=CRYPTO_DERIVATIVE_PUBLIC_FIELDS,
            key_fields=["trade_date", "exchange", "symbol", "contract_type"],
            raw_path=raw_path,
            source_url=DERIVATIVES_SOURCE_URL,
            source_type=DERIVATIVES_SOURCE_TYPE,
        )

    def _load_cme_report_rows(self, summary: Dict[str, object]) -> List[Dict[str, str]]:
        output_path = normalize_text(summary.get("output_path"))
        if not output_path:
            return []
        csv_path = self._resolve_project_path(output_path)
        if not csv_path.exists():
            return []
        return list(_iter_csv_rows(csv_path))

    def _load_or_fetch_latest_only_payload(self, *, trade_date, raw_path: Path, force: bool, fetcher, dataset_name: str):
        trade_date_str = format_trade_date(trade_date)
        if raw_path.exists() and not force:
            return json.loads(raw_path.read_text(encoding="utf-8"))
        if trade_date != now_shanghai().date():
            if raw_path.exists():
                return json.loads(raw_path.read_text(encoding="utf-8"))
            return {
                "dataset": dataset_name,
                "trade_date": trade_date_str,
                "status": NOT_APPLICABLE_STATUS,
                "message": "latest-only crypto source without cached payload for requested historical date",
            }
        try:
            payload = fetcher()
            ensure_directory(raw_path.parent)
            raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            return payload
        except Exception as exc:
            if raw_path.exists():
                return json.loads(raw_path.read_text(encoding="utf-8"))
            return {
                "dataset": dataset_name,
                "trade_date": trade_date_str,
                "status": PENDING_RETRY_STATUS,
                "message": str(exc),
                "error": str(exc),
            }

    def _fetch_live_snapshot_payload(self) -> Dict[str, object]:
        query = urlencode(
            {
                "vs_currency": "usd",
                "ids": ",".join(DEFAULT_COIN_IDS),
                "order": "market_cap_desc",
                "per_page": str(len(DEFAULT_COIN_IDS)),
                "page": "1",
                "sparkline": "false",
                "price_change_percentage": "24h",
            }
        )
        request = Request(f"{SOURCE_URL}?{query}", headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=20) as response:
            records = json.loads(response.read().decode("utf-8"))
        return {"records": records, "retrieved_at": iso_timestamp()}

    def _fetch_history_payload(self, coin_id: str, trade_date_str: str) -> Dict[str, object]:
        day, month, year = trade_date_str.split("-")[2], trade_date_str.split("-")[1], trade_date_str.split("-")[0]
        query = urlencode({"date": f"{day}-{month}-{year}", "localization": "false"})
        request = Request(
            f"https://api.coingecko.com/api/v3/coins/{coin_id}/history?{query}",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))

    def _fetch_derivatives_payload(self) -> Dict[str, object]:
        request = Request(DERIVATIVES_SOURCE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=20) as response:
            records = json.loads(response.read().decode("utf-8"))
        return {"records": records, "retrieved_at": iso_timestamp()}

    def _fetch_okx_swap_payload(self) -> Dict[str, object]:
        headers = {"User-Agent": "Mozilla/5.0"}
        tickers_request = Request(OKX_SWAP_SOURCE_URL, headers=headers)
        instruments_request = Request(OKX_SWAP_INSTRUMENT_URL, headers=headers)
        with urlopen(tickers_request, timeout=20) as response:
            tickers_payload = json.loads(response.read().decode("utf-8"))
        with urlopen(instruments_request, timeout=20) as response:
            instruments_payload = json.loads(response.read().decode("utf-8"))
        return {
            "records": tickers_payload.get("data", []),
            "instruments": instruments_payload.get("data", []),
            "retrieved_at": iso_timestamp(),
            "source_id": OKX_SWAP_SOURCE_ID,
            "source_url": OKX_SWAP_SOURCE_URL,
            "source_type": OKX_SWAP_SOURCE_TYPE,
        }

    def _collect_bitcoin_holdings_dataset(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(CRYPTO_BITCOIN_HOLDINGS_DATASET, trade_date)
        payload = self._load_or_fetch_latest_only_payload(
            trade_date=trade_date,
            raw_path=raw_path,
            force=force,
            fetcher=self._fetch_bitcoin_holdings_payload,
            dataset_name=CRYPTO_BITCOIN_HOLDINGS_DATASET,
        )
        if isinstance(payload, dict) and payload.get("status"):
            return payload
        rows = self._normalize_bitcoin_holding_rows(
            trade_date_str=trade_date_str,
            payload=payload,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        return self._write_dataset(
            dataset_name=CRYPTO_BITCOIN_HOLDINGS_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=CRYPTO_BITCOIN_HOLDING_STANDARD_FIELDS,
            key_fields=["trade_date", "symbol", "holder_category"],
            raw_path=raw_path,
            source_url=BITCOIN_HOLDINGS_SOURCE_URL,
            source_type=BITCOIN_HOLDINGS_SOURCE_TYPE,
        )

    def _fetch_bitcoin_holdings_payload(self) -> Dict[str, object]:
        import akshare as ak

        dataframe = ak.crypto_bitcoin_hold_report()
        records = json.loads(dataframe.to_json(orient="records", force_ascii=False, date_format="iso"))
        return {"records": records, "retrieved_at": iso_timestamp()}

    def _collect_cme_bitcoin_report_dataset(self, *, trade_date, run_id: str, force: bool) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        raw_path = self._raw_path(CRYPTO_CME_BITCOIN_REPORT_DATASET, trade_date)
        if raw_path.exists() and not force:
            payload = json.loads(raw_path.read_text(encoding="utf-8"))
        else:
            try:
                payload = self._fetch_cme_bitcoin_report_payload(compact_trade_date(trade_date))
                ensure_directory(raw_path.parent)
                raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as exc:
                if raw_path.exists():
                    payload = json.loads(raw_path.read_text(encoding="utf-8"))
                else:
                    return {
                        "dataset": CRYPTO_CME_BITCOIN_REPORT_DATASET,
                        "trade_date": trade_date_str,
                        "status": PENDING_RETRY_STATUS,
                        "message": str(exc),
                        "error": str(exc),
                    }
        rows = self._normalize_cme_bitcoin_report_rows(
            trade_date_str=trade_date_str,
            payload=payload,
            raw_path=relative_to_project(raw_path, PROJECT_ROOT),
            run_id=run_id,
        )
        return self._write_dataset(
            dataset_name=CRYPTO_CME_BITCOIN_REPORT_DATASET,
            trade_date=trade_date,
            rows=rows,
            fieldnames=CRYPTO_CME_BITCOIN_REPORT_FIELDS,
            key_fields=["trade_date", "commodity", "report_type"],
            raw_path=raw_path,
            source_url=CME_BITCOIN_REPORT_SOURCE_URL,
            source_type=CME_BITCOIN_REPORT_SOURCE_TYPE,
        )

    def _fetch_cme_bitcoin_report_payload(self, trade_date_compact: str) -> Dict[str, object]:
        import akshare as ak

        dataframe = ak.crypto_bitcoin_cme(date=trade_date_compact)
        records = json.loads(dataframe.to_json(orient="records", force_ascii=False, date_format="iso"))
        return {"records": records, "retrieved_at": iso_timestamp(), "source_trade_date": trade_date_compact}

    def _normalize_snapshot_rows(self, *, trade_date_str: str, payload: Dict[str, object], raw_path: str, run_id: str) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            symbol = normalize_text(item.get("symbol")).upper()
            if not symbol:
                continue
            checksum_payload = json.dumps(
                {
                    "trade_date": trade_date_str,
                    "symbol": symbol,
                    "price_usd": normalize_number(item.get("current_price")),
                    "source_id": SOURCE_ID,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": "crypto_global_observation",
                    "market": "global_crypto",
                    "exchange": "COINGECKO",
                    "symbol": symbol,
                    "name": normalize_text(item.get("name")),
                    "price_usd": normalize_number(item.get("current_price")),
                    "change_amount_24h": normalize_number(item.get("price_change_24h")),
                    "change_pct_24h": normalize_number(item.get("price_change_percentage_24h")),
                    "high_24h": normalize_number(item.get("high_24h")),
                    "low_24h": normalize_number(item.get("low_24h")),
                    "total_volume": normalize_number(item.get("total_volume")),
                    "market_cap": normalize_number(item.get("market_cap")),
                    "market_cap_rank": normalize_number(item.get("market_cap_rank")),
                    "circulating_supply": normalize_number(item.get("circulating_supply")),
                    "total_supply": normalize_number(item.get("total_supply")),
                    "max_supply": normalize_number(item.get("max_supply")),
                    "source_id": SOURCE_ID,
                    "source_url": SOURCE_URL,
                    "source_type": SOURCE_TYPE,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                    "run_id": run_id,
                    "legal_note": LEGAL_NOTE,
                }
            )
        return rows

    def _normalize_asset_rows(self, *, trade_date_str: str, payload: Dict[str, object], raw_path: str, run_id: str) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            symbol = normalize_text(item.get("symbol")).upper()
            if not symbol:
                continue
            checksum_payload = json.dumps(
                {"trade_date": trade_date_str, "symbol": symbol, "source_id": SOURCE_ID},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": "crypto_global_observation",
                    "market": "global_crypto",
                    "exchange": "COINGECKO",
                    "symbol": symbol,
                    "name": normalize_text(item.get("name")),
                    "category": "",
                    "market_cap_rank": normalize_number(item.get("market_cap_rank")),
                    "circulating_supply": normalize_number(item.get("circulating_supply")),
                    "total_supply": normalize_number(item.get("total_supply")),
                    "max_supply": normalize_number(item.get("max_supply")),
                    "source_id": SOURCE_ID,
                    "source_url": SOURCE_URL,
                    "source_type": SOURCE_TYPE,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                    "run_id": run_id,
                    "legal_note": LEGAL_NOTE,
                }
            )
        return rows

    def _normalize_daily_quote_rows(self, *, trade_date_str: str, payload: Dict[str, object], raw_path: str, run_id: str) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            symbol = normalize_text(item.get("symbol")).upper()
            if not symbol:
                continue
            if "market_data" in item:
                market_data = item.get("market_data", {}) or {}
                current_price = (market_data.get("current_price") or {}).get("usd")
                market_cap = (market_data.get("market_cap") or {}).get("usd")
                total_volume = (market_data.get("total_volume") or {}).get("usd")
                high_24h = ""
                low_24h = ""
                change_pct_24h = ""
                source_id = "coingecko.coin_history_public"
                source_url = "https://api.coingecko.com/api/v3/coins/{id}/history"
            else:
                current_price = item.get("current_price")
                market_cap = item.get("market_cap")
                total_volume = item.get("total_volume")
                high_24h = normalize_number(item.get("high_24h"))
                low_24h = normalize_number(item.get("low_24h"))
                change_pct_24h = normalize_number(item.get("price_change_percentage_24h"))
                source_id = SOURCE_ID
                source_url = SOURCE_URL
            checksum_payload = json.dumps(
                {"trade_date": trade_date_str, "symbol": symbol, "price_usd": normalize_number(current_price)},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": "crypto_global_observation",
                    "market": "global_crypto",
                    "exchange": "COINGECKO",
                    "symbol": symbol,
                    "name": normalize_text(item.get("name")),
                    "price_usd": normalize_number(current_price),
                    "market_cap": normalize_number(market_cap),
                    "total_volume": normalize_number(total_volume),
                    "high_24h": high_24h,
                    "low_24h": low_24h,
                    "change_pct_24h": change_pct_24h,
                    "source_id": source_id,
                    "source_url": source_url,
                    "source_type": SOURCE_TYPE,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                    "run_id": run_id,
                    "legal_note": LEGAL_NOTE,
                }
            )
        return rows

    def _normalize_derivative_rows(self, *, trade_date_str: str, payload: Dict[str, object], raw_path: str, run_id: str) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        cme_rows: List[Dict[str, object]] = []
        other_rows: List[Dict[str, object]] = []
        for item in payload.get("records", []):
            market = normalize_text(item.get("market"))
            if "CME" in market.upper():
                cme_rows.append(item)
            elif normalize_text(item.get("index_id")).upper() in {"BTC", "ETH"}:
                other_rows.append(item)
        selected = cme_rows[:20] if cme_rows else other_rows[:20]
        for item in selected:
            symbol = normalize_text(item.get("symbol")).upper()
            if not symbol:
                continue
            checksum_payload = json.dumps(
                {"trade_date": trade_date_str, "exchange": normalize_text(item.get("market")), "symbol": symbol},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": "crypto_global_observation",
                    "market": "crypto_derivatives_public",
                    "exchange": normalize_text(item.get("market")),
                    "symbol": symbol,
                    "underlying_symbol": normalize_text(item.get("index_id")).upper(),
                    "contract_type": normalize_text(item.get("contract_type")),
                    "price_usd": normalize_number(item.get("price")),
                    "index_price_usd": normalize_number(item.get("index")),
                    "basis": normalize_number(item.get("basis")),
                    "spread": normalize_number(item.get("spread")),
                    "funding_rate": normalize_number(item.get("funding_rate")),
                    "open_interest_usd": normalize_number(item.get("open_interest")),
                    "volume_24h_usd": normalize_number(item.get("volume_24h")),
                    "last_traded_at": normalize_text(item.get("last_traded_at")),
                    "source_id": DERIVATIVES_SOURCE_ID,
                    "source_url": DERIVATIVES_SOURCE_URL,
                    "source_type": DERIVATIVES_SOURCE_TYPE,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                    "run_id": run_id,
                    "legal_note": LEGAL_NOTE,
                }
            )
        return rows

    def _normalize_derivative_rows_from_cme_report(
        self,
        *,
        trade_date_str: str,
        rows: List[Dict[str, str]],
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        normalized_rows: List[Dict[str, str]] = []
        retrieved_at = iso_timestamp()
        for item in rows:
            report_type = normalize_text(item.get("report_type"))
            volume = normalize_number(item.get("volume"))
            open_interest = normalize_number(item.get("open_interest"))
            if not report_type:
                continue
            contract_type = "futures" if "期货" in report_type else normalize_text(report_type).lower()
            symbol = f"BTC-{contract_type}".upper()
            checksum_payload = json.dumps(
                {"trade_date": trade_date_str, "exchange": "CME", "symbol": symbol, "volume": volume},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            normalized_rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": "crypto_global_observation",
                    "market": "crypto_derivatives_public",
                    "exchange": "CME",
                    "symbol": symbol,
                    "underlying_symbol": "BTC",
                    "contract_type": contract_type,
                    "price_usd": "",
                    "index_price_usd": "",
                    "basis": "",
                    "spread": "",
                    "funding_rate": "",
                    "open_interest_usd": open_interest,
                    "volume_24h_usd": volume,
                    "last_traded_at": "",
                    "source_id": CME_BITCOIN_REPORT_SOURCE_ID,
                    "source_url": CME_BITCOIN_REPORT_SOURCE_URL,
                    "source_type": CME_BITCOIN_REPORT_SOURCE_TYPE,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                    "run_id": run_id,
                    "legal_note": LEGAL_NOTE,
                }
            )
        return normalized_rows

    def _normalize_derivative_rows_from_okx_payload(
        self,
        *,
        trade_date_str: str,
        payload: Dict[str, object],
        raw_path: str,
        run_id: str,
    ) -> List[Dict[str, str]]:
        instrument_by_id = {
            normalize_text(item.get("instId")): item
            for item in payload.get("instruments", [])
            if normalize_text(item.get("instId"))
        }
        selected_records: List[Dict[str, object]] = []
        for item in payload.get("records", []):
            inst_id = normalize_text(item.get("instId"))
            if not inst_id:
                continue
            underlying = normalize_text(inst_id.split("-", 1)[0]).upper()
            if underlying not in OKX_PRIORITY_UNDERLYINGS:
                continue
            selected_records.append(item)
        selected_records.sort(key=lambda item: float(normalize_number(item.get("volCcy24h")) or 0.0), reverse=True)
        rows: List[Dict[str, str]] = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in selected_records[:20]:
            inst_id = normalize_text(item.get("instId"))
            instrument = instrument_by_id.get(inst_id, {})
            underlying = normalize_text(inst_id.split("-", 1)[0]).upper()
            bid_price = normalize_number(item.get("bidPx"))
            ask_price = normalize_number(item.get("askPx"))
            spread = ""
            if bid_price and ask_price:
                try:
                    spread = normalize_number(float(ask_price) - float(bid_price))
                except ValueError:
                    spread = ""
            checksum_payload = json.dumps(
                {"trade_date": trade_date_str, "exchange": "OKX", "symbol": inst_id},
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": "crypto_global_observation",
                    "market": "crypto_derivatives_public",
                    "exchange": "OKX",
                    "symbol": inst_id,
                    "underlying_symbol": underlying,
                    "contract_type": "swap",
                    "price_usd": normalize_number(item.get("last")),
                    "index_price_usd": "",
                    "basis": "",
                    "spread": spread,
                    "funding_rate": "",
                    "open_interest_usd": "",
                    "volume_24h_usd": normalize_number(item.get("volCcy24h")),
                    "last_traded_at": normalize_text(item.get("ts")),
                    "source_id": OKX_SWAP_SOURCE_ID,
                    "source_url": OKX_SWAP_SOURCE_URL,
                    "source_type": OKX_SWAP_SOURCE_TYPE,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                    "run_id": run_id,
                    "legal_note": LEGAL_NOTE,
                }
            )
        return rows

    def _normalize_bitcoin_holding_rows(self, *, trade_date_str: str, payload: Dict[str, object], raw_path: str, run_id: str) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            symbol = normalize_text(item.get("代码")).upper()
            if not symbol:
                continue
            exchange = _extract_symbol_exchange(symbol)
            checksum_payload = json.dumps(
                {
                    "trade_date": trade_date_str,
                    "symbol": symbol,
                    "holding_btc": normalize_number(item.get("持仓量")),
                    "source_query_date": normalize_text(item.get("查询日期")),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": "crypto_global_observation",
                    "market": "crypto_public_bitcoin_holdings",
                    "exchange": exchange,
                    "symbol": symbol,
                    "company_name_en": normalize_text(item.get("公司名称-英文")),
                    "company_name_zh": normalize_text(item.get("公司名称-中文")),
                    "region": normalize_text(item.get("国家/地区")),
                    "holder_category": normalize_text(item.get("分类")),
                    "market_cap_usd": normalize_number(item.get("市值")),
                    "btc_market_cap_ratio": normalize_number(item.get("比特币占市值比重")),
                    "holding_cost_usd": normalize_number(item.get("持仓成本")),
                    "holding_ratio": normalize_number(item.get("持仓占比")),
                    "holding_btc": normalize_number(item.get("持仓量")),
                    "holding_value_usd": normalize_number(item.get("当日持仓市值")),
                    "source_query_date": normalize_text(item.get("查询日期")),
                    "announcement_url": normalize_text(item.get("公告链接")),
                    "source_id": BITCOIN_HOLDINGS_SOURCE_ID,
                    "source_url": BITCOIN_HOLDINGS_SOURCE_URL,
                    "source_type": BITCOIN_HOLDINGS_SOURCE_TYPE,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                    "run_id": run_id,
                    "legal_note": LEGAL_NOTE,
                }
            )
        return rows

    def _normalize_cme_bitcoin_report_rows(self, *, trade_date_str: str, payload: Dict[str, object], raw_path: str, run_id: str) -> List[Dict[str, str]]:
        rows = []
        retrieved_at = str(payload.get("retrieved_at") or iso_timestamp())
        for item in payload.get("records", []):
            commodity = normalize_text(item.get("商品"))
            report_type = normalize_text(item.get("类型"))
            if not commodity or not report_type:
                continue
            checksum_payload = json.dumps(
                {
                    "trade_date": trade_date_str,
                    "commodity": commodity,
                    "report_type": report_type,
                    "volume": normalize_number(item.get("成交量")),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            rows.append(
                {
                    "trade_date": trade_date_str,
                    "asset_family": "crypto_global_observation",
                    "market": "crypto_cme_public_report",
                    "exchange": "CME",
                    "commodity": commodity,
                    "report_type": report_type,
                    "electronic_contracts": normalize_number(item.get("电子交易合约")),
                    "pit_contracts": normalize_number(item.get("场内成交合约")),
                    "block_contracts": normalize_number(item.get("场外成交合约")),
                    "volume": normalize_number(item.get("成交量")),
                    "open_interest": normalize_number(item.get("未平仓合约")),
                    "open_interest_change": normalize_number(item.get("持仓变化")),
                    "source_id": CME_BITCOIN_REPORT_SOURCE_ID,
                    "source_url": CME_BITCOIN_REPORT_SOURCE_URL,
                    "source_type": CME_BITCOIN_REPORT_SOURCE_TYPE,
                    "retrieved_at": retrieved_at,
                    "raw_path": raw_path,
                    "parser_version": PARSER_VERSION,
                    "checksum": hashlib.sha1(checksum_payload).hexdigest(),
                    "run_id": run_id,
                    "legal_note": LEGAL_NOTE,
                }
            )
        return rows

    def _write_dataset(
        self,
        *,
        dataset_name: str,
        trade_date,
        rows: List[Dict[str, str]],
        fieldnames: List[str],
        key_fields: List[str],
        raw_path: Path,
        source_url: str,
        source_type: str,
    ) -> Dict[str, object]:
        trade_date_str = format_trade_date(trade_date)
        output_path = self._output_path(dataset_name, trade_date)
        write_dict_rows_csv(output_path, rows, fieldnames, key_fields)
        status = SUCCESS_STATUS if rows else NO_DATA_STATUS
        summary = {
            "dataset": dataset_name,
            "trade_date": trade_date_str,
            "status": status,
            "row_count": len(rows),
            "output_path": relative_to_project(output_path, PROJECT_ROOT),
            "raw_path": relative_to_project(raw_path, PROJECT_ROOT),
            "source_url": source_url,
            "source_type": source_type,
        }
        if not rows:
            summary["message"] = "crypto source returned no rows"
        return summary

    def _raw_path(self, dataset_name: str, trade_date) -> Path:
        return RAW_DIR / "crypto_global" / dataset_name / f"{compact_trade_date(trade_date)}.json"

    def _output_path(self, dataset_name: str, trade_date) -> Path:
        return CRYPTO_NORMALIZED_DIR / dataset_name / f"{format_trade_date(trade_date)}.csv"

    def _resolve_project_path(self, path_value: str) -> Path:
        path = Path(path_value)
        if path.is_absolute():
            return path
        return PROJECT_ROOT / path

    def _update_state(self, trade_date: str, status: str, datasets: Dict[str, Dict[str, object]]) -> None:
        payload = self._load_state()
        payload.setdefault("dates", {})[trade_date] = {
            "status": status,
            "datasets": datasets,
            "updated_at": iso_timestamp(),
        }
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_state(self) -> Dict[str, object]:
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    @staticmethod
    def _state_datasets(state: Dict[str, object]) -> Dict[str, Dict[str, object]]:
        datasets = state.get("datasets")
        if isinstance(datasets, dict):
            return datasets
        legacy_dataset = state.get("dataset")
        if isinstance(legacy_dataset, dict):
            return {legacy_dataset.get("dataset", CRYPTO_GLOBAL_SNAPSHOT_DATASET): legacy_dataset}
        return {}

    @staticmethod
    def _resolve_trade_date(trade_date_value: str):
        if trade_date_value == "latest":
            return now_shanghai().date()
        return parse_trade_date(trade_date_value)

    @staticmethod
    def _merge_statuses(statuses: Iterable[str]) -> str:
        status_set = {normalize_text(status) for status in statuses if normalize_text(status)}
        if not status_set:
            return NO_DATA_STATUS
        if status_set == {SUCCESS_STATUS}:
            return SUCCESS_STATUS
        if FAILED_STATUS in status_set:
            return FAILED_STATUS
        if PENDING_RETRY_STATUS in status_set:
            return PENDING_RETRY_STATUS
        if SUCCESS_STATUS in status_set:
            return "partial_success"
        if NO_DATA_STATUS in status_set and len(status_set) == 1:
            return NO_DATA_STATUS
        if NOT_APPLICABLE_STATUS in status_set and len(status_set) == 1:
            return NOT_APPLICABLE_STATUS
        return "partial_success"


def _iter_csv_rows(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


def _extract_symbol_exchange(symbol: str) -> str:
    if ":" in symbol:
        return normalize_text(symbol.split(":", 1)[1]).upper()
    return "PUBLIC"
