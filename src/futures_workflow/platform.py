import json
import shutil
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from .config import NORMALIZED_DIR, NORMALIZED_ROOT, PROJECT_ROOT, QUERY_NORMALIZED_DIR
from .constants import (
    CONTRACTS_DATASET,
    CONTRACTS_STANDARD_FIELDS,
    DERIVATIVES_DATASET,
    DERIVATIVES_STANDARD_FIELDS,
    FUTURES_DATASET,
    FUTURES_RESULTS_DATASET,
    FUTURES_RESULTS_STANDARD_FIELDS,
    OPTION_RESULTS_DATASET,
    OPTION_RESULTS_STANDARD_FIELDS,
    OPTIONS_CHAIN_MATRIX_FIELDS,
    OPTIONS_CHAIN_VIEW,
    OPTIONS_DATASET,
    OPTIONS_STANDARD_FIELDS,
    UNDERLYING_SUMMARY_FIELDS,
    UNDERLYING_SUMMARY_VIEW,
)
from .models import OptionQuoteRow, QuoteRow
from .normalize.csv_utils import write_dict_rows_csv, write_typed_rows_csv
from .utils import ensure_directory, relative_to_project


CANONICAL_DATASET_ORDER = [
    FUTURES_DATASET,
    OPTIONS_DATASET,
    DERIVATIVES_DATASET,
    CONTRACTS_DATASET,
    OPTION_RESULTS_DATASET,
    FUTURES_RESULTS_DATASET,
    OPTIONS_CHAIN_VIEW,
    UNDERLYING_SUMMARY_VIEW,
]


def write_options_daily_quotes(path: Path, rows: Iterable[OptionQuoteRow]) -> Path:
    return write_typed_rows_csv(
        path=path,
        rows=list(rows),
        fieldnames=OPTIONS_STANDARD_FIELDS,
        sort_keys=["trade_date", "exchange", "product_code", "contract"],
    )


def futures_to_derivatives_rows(rows: Iterable[QuoteRow]) -> List[Dict[str, str]]:
    mapped: List[Dict[str, str]] = []
    for row in rows:
        mapped.append(
            {
                "trade_date": row.trade_date,
                "instrument_type": "future",
                "exchange": row.exchange,
                "product_code": row.variety_code,
                "product_name": row.variety_name,
                "contract": row.contract,
                "underlying_exchange": row.exchange,
                "underlying_kind": _future_underlying_kind(row),
                "underlying_product_code": row.variety_code,
                "underlying_contract": row.contract,
                "delivery_month": row.delivery_month,
                "expire_date": "",
                "option_type": "",
                "strike_price": "",
                "exercise_type": "",
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "prev_settlement": row.prev_settlement,
                "settlement": row.settlement,
                "change_close": row.change_close,
                "change_settlement": row.change_settlement,
                "volume": row.volume,
                "open_interest": row.open_interest,
                "open_interest_change": row.open_interest_change,
                "turnover": row.turnover,
                "delta": "",
                "implied_volatility": "",
                "exercise_volume": "",
                "source_url": row.source_url,
                "source_type": row.source_type,
                "retrieved_at": row.retrieved_at,
                "raw_path": row.raw_path,
            }
        )
    return mapped


def options_to_derivatives_rows(rows: Iterable[OptionQuoteRow]) -> List[Dict[str, str]]:
    mapped: List[Dict[str, str]] = []
    for row in rows:
        mapped.append(
            {
                "trade_date": row.trade_date,
                "instrument_type": "option",
                "exchange": row.exchange,
                "product_code": row.product_code,
                "product_name": row.product_name,
                "contract": row.contract,
                "underlying_exchange": row.underlying_exchange,
                "underlying_kind": row.underlying_kind,
                "underlying_product_code": row.underlying_product_code,
                "underlying_contract": row.underlying_contract,
                "delivery_month": "",
                "expire_date": row.expire_date,
                "option_type": row.option_type,
                "strike_price": row.strike_price,
                "exercise_type": row.exercise_type,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "prev_settlement": row.prev_settlement,
                "settlement": row.settlement,
                "change_close": row.change_close,
                "change_settlement": row.change_settlement,
                "volume": row.volume,
                "open_interest": row.open_interest,
                "open_interest_change": row.open_interest_change,
                "turnover": row.turnover,
                "delta": row.delta,
                "implied_volatility": row.implied_volatility,
                "exercise_volume": row.exercise_volume,
                "source_url": row.source_url,
                "source_type": row.source_type,
                "retrieved_at": row.retrieved_at,
                "raw_path": row.raw_path,
            }
        )
    return mapped


def build_contract_snapshot_rows(
    futures_rows: Iterable[QuoteRow],
    options_rows: Iterable[OptionQuoteRow],
    master_metadata: Optional[Dict[Tuple[str, str, str], Dict[str, str]]] = None,
) -> List[Dict[str, str]]:
    master_metadata = master_metadata or {}
    rows: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    for item in futures_rows:
        key = ("future", item.exchange, item.contract)
        rows[key] = {
            "trade_date": item.trade_date,
            "instrument_type": "future",
            "exchange": item.exchange,
            "product_code": item.variety_code,
            "product_name": item.variety_name,
            "contract": item.contract,
            "contract_status": "trading",
            "list_date": "",
            "expire_date": "",
            "last_trade_date": "",
            "contract_multiplier": "",
            "quote_unit": "",
            "price_tick": "",
            "delivery_type": "",
            "exercise_type": "",
            "option_type": "",
            "strike_price": "",
            "underlying_exchange": item.exchange,
            "underlying_kind": "",
            "underlying_product_code": item.variety_code,
            "underlying_contract": item.contract,
            "source_url": item.source_url,
            "source_type": item.source_type,
            "retrieved_at": item.retrieved_at,
            "raw_path": item.raw_path,
        }
        _merge_master_metadata(rows[key], master_metadata.get(key, {}))
    for item in options_rows:
        key = ("option", item.exchange, item.contract)
        rows[key] = {
            "trade_date": item.trade_date,
            "instrument_type": "option",
            "exchange": item.exchange,
            "product_code": item.product_code,
            "product_name": item.product_name,
            "contract": item.contract,
            "contract_status": "",
            "list_date": "",
            "expire_date": "",
            "last_trade_date": "",
            "contract_multiplier": "",
            "quote_unit": "",
            "price_tick": "",
            "delivery_type": "",
            "exercise_type": "",
            "option_type": "",
            "strike_price": "",
            "underlying_exchange": "",
            "underlying_kind": "",
            "underlying_product_code": "",
            "underlying_contract": "",
            "source_url": item.source_url,
            "source_type": item.source_type,
            "retrieved_at": item.retrieved_at,
            "raw_path": item.raw_path,
        }
        _merge_master_metadata(rows[key], master_metadata.get(key, {}))
    return list(rows.values())


def build_options_chain_matrix(rows: Iterable[OptionQuoteRow]) -> List[Dict[str, str]]:
    buckets: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}
    for row in rows:
        key = (row.exchange, row.underlying_contract, row.expire_date, row.strike_price or row.contract)
        current = buckets.setdefault(
            key,
            {
                "trade_date": row.trade_date,
                "exchange": row.exchange,
                "underlying_contract": row.underlying_contract,
                "expire_date": row.expire_date,
                "strike_price": row.strike_price,
                "call_contract": "",
                "call_close": "",
                "call_settlement": "",
                "call_volume": "",
                "call_open_interest": "",
                "call_delta": "",
                "call_implied_volatility": "",
                "put_contract": "",
                "put_close": "",
                "put_settlement": "",
                "put_volume": "",
                "put_open_interest": "",
                "put_delta": "",
                "put_implied_volatility": "",
            },
        )
        prefix = "call" if row.option_type == "call" else "put"
        current[f"{prefix}_contract"] = row.contract
        current[f"{prefix}_close"] = row.close
        current[f"{prefix}_settlement"] = row.settlement
        current[f"{prefix}_volume"] = row.volume
        current[f"{prefix}_open_interest"] = row.open_interest
        current[f"{prefix}_delta"] = row.delta
        current[f"{prefix}_implied_volatility"] = row.implied_volatility
    return list(buckets.values())


def build_underlying_summary(
    futures_rows: Iterable[QuoteRow],
    options_rows: Iterable[OptionQuoteRow],
) -> List[Dict[str, str]]:
    futures_map = {row.contract: row for row in futures_rows}
    buckets: Dict[Tuple[str, str, str], Dict[str, str]] = {}
    for row in options_rows:
        key = (row.trade_date, row.exchange, row.underlying_contract)
        current = buckets.setdefault(
            key,
            {
                "trade_date": row.trade_date,
                "exchange": row.exchange,
                "underlying_contract": row.underlying_contract,
                "underlying_kind": row.underlying_kind,
                "futures_contract": row.underlying_contract,
                "futures_close": "",
                "futures_settlement": "",
                "futures_volume": "",
                "futures_open_interest": "",
                "options_contract_count": "0",
                "options_total_volume": "0",
                "options_total_open_interest": "0",
                "call_volume": "0",
                "put_volume": "0",
                "call_open_interest": "0",
                "put_open_interest": "0",
            },
        )
        current["options_contract_count"] = str(int(current["options_contract_count"]) + 1)
        current["options_total_volume"] = _sum_text(current["options_total_volume"], row.volume)
        current["options_total_open_interest"] = _sum_text(current["options_total_open_interest"], row.open_interest)
        if row.option_type == "call":
            current["call_volume"] = _sum_text(current["call_volume"], row.volume)
            current["call_open_interest"] = _sum_text(current["call_open_interest"], row.open_interest)
        else:
            current["put_volume"] = _sum_text(current["put_volume"], row.volume)
            current["put_open_interest"] = _sum_text(current["put_open_interest"], row.open_interest)
        future_row = futures_map.get(row.underlying_contract)
        if future_row is not None:
            current["futures_close"] = future_row.close
            current["futures_settlement"] = future_row.settlement
            current["futures_volume"] = future_row.volume
            current["futures_open_interest"] = future_row.open_interest
    return list(buckets.values())


def build_platform_rows(
    *,
    futures_rows: List[QuoteRow],
    options_rows: List[OptionQuoteRow],
    option_result_rows: Optional[List[Dict[str, str]]] = None,
    futures_result_rows: Optional[List[Dict[str, str]]] = None,
    master_metadata: Optional[Dict[Tuple[str, str, str], Dict[str, str]]] = None,
) -> Dict[str, List[object]]:
    option_result_rows = list(option_result_rows or [])
    futures_result_rows = list(futures_result_rows or [])
    return {
        FUTURES_DATASET: list(futures_rows),
        OPTIONS_DATASET: list(options_rows),
        DERIVATIVES_DATASET: futures_to_derivatives_rows(futures_rows) + options_to_derivatives_rows(options_rows),
        CONTRACTS_DATASET: build_contract_snapshot_rows(futures_rows, options_rows, master_metadata=master_metadata),
        OPTION_RESULTS_DATASET: option_result_rows,
        FUTURES_RESULTS_DATASET: futures_result_rows,
        OPTIONS_CHAIN_VIEW: build_options_chain_matrix(options_rows),
        UNDERLYING_SUMMARY_VIEW: build_underlying_summary(futures_rows, options_rows),
    }


def write_platform_outputs(
    *,
    trade_date: str,
    dataset_rows: Dict[str, List[object]],
    include_datasets: Iterable[str],
    selection_id: Optional[str] = None,
    selection_summary: Optional[Dict[str, object]] = None,
    update_contracts_latest: bool = False,
) -> Tuple[Dict[str, str], Dict[str, int]]:
    include = [dataset for dataset in CANONICAL_DATASET_ORDER if dataset in set(include_datasets)]
    query_mode = bool(selection_id)
    output_root = (QUERY_NORMALIZED_DIR / selection_id) if query_mode else NORMALIZED_ROOT
    outputs: Dict[str, str] = {}
    row_counts: Dict[str, int] = {}

    for dataset_name in include:
        rows = dataset_rows.get(dataset_name, [])
        if not _should_write_dataset(dataset_name, rows, dataset_rows):
            continue
        output_path = _dataset_output_path(trade_date=trade_date, dataset_name=dataset_name, output_root=output_root, query_mode=query_mode)
        _write_dataset(output_path, dataset_name, rows)
        outputs[dataset_name] = relative_to_project(output_path, PROJECT_ROOT)
        row_counts[dataset_name] = len(rows)

    if query_mode:
        _write_query_manifest(
            output_root=output_root,
            selection_id=selection_id or "",
            selection_summary=selection_summary or {},
            trade_date=trade_date,
            outputs=outputs,
            row_counts=row_counts,
            datasets=include,
        )

    return outputs, row_counts


def write_contracts_latest(rows: List[Dict[str, str]], *, snapshot_path: Optional[Path] = None) -> Path:
    latest_path = NORMALIZED_ROOT / "master" / "contracts_latest.csv"
    if snapshot_path and snapshot_path.exists():
        ensure_directory(latest_path.parent)
        shutil.copyfile(snapshot_path, latest_path)
        return latest_path
    write_dict_rows_csv(
        latest_path,
        rows,
        CONTRACTS_STANDARD_FIELDS,
        ["instrument_type", "exchange", "contract"],
    )
    return latest_path


def collect_dataset_observed_exchanges(dataset_rows: Dict[str, List[object]]) -> Dict[str, List[str]]:
    observed: Dict[str, List[str]] = {}
    for dataset_name, rows in dataset_rows.items():
        exchanges = set()
        for row in rows:
            if isinstance(row, dict):
                exchange = str(row.get("exchange", "")).strip()
            else:
                exchange = str(getattr(row, "exchange", "")).strip()
            if exchange:
                exchanges.add(exchange)
        observed[dataset_name] = sorted(exchanges)
    return observed


def write_legacy_futures_output(path: Path, rows: Iterable[QuoteRow]) -> Path:
    from .normalize.daily_quotes import write_daily_quotes_csv

    return write_daily_quotes_csv(path, rows)


def _should_write_dataset(dataset_name: str, rows: List[object], dataset_rows: Dict[str, List[object]]) -> bool:
    if dataset_name in {FUTURES_DATASET, OPTIONS_DATASET, DERIVATIVES_DATASET, CONTRACTS_DATASET}:
        return bool(rows)
    if dataset_name in {OPTION_RESULTS_DATASET, OPTIONS_CHAIN_VIEW}:
        return bool(dataset_rows.get(OPTIONS_DATASET))
    if dataset_name == FUTURES_RESULTS_DATASET:
        return bool(dataset_rows.get(FUTURES_DATASET)) or bool(rows)
    if dataset_name == UNDERLYING_SUMMARY_VIEW:
        return bool(dataset_rows.get(FUTURES_DATASET) or dataset_rows.get(OPTIONS_DATASET))
    return bool(rows)


def _dataset_output_path(*, trade_date: str, dataset_name: str, output_root: Path, query_mode: bool) -> Path:
    if dataset_name == FUTURES_DATASET:
        if query_mode:
            return output_root / "futures" / "daily_quotes" / f"{trade_date}.csv"
        return NORMALIZED_DIR / f"{trade_date}.csv"
    mapping = {
        OPTIONS_DATASET: ("options", "daily_quotes"),
        DERIVATIVES_DATASET: ("derivatives", "daily_quotes"),
        CONTRACTS_DATASET: ("master", "contracts"),
        OPTION_RESULTS_DATASET: ("results", "options_exercise"),
        FUTURES_RESULTS_DATASET: ("results", "futures_delivery"),
        OPTIONS_CHAIN_VIEW: ("views", "options_chain_matrix"),
        UNDERLYING_SUMMARY_VIEW: ("views", "underlying_derivatives_summary"),
    }
    prefix = mapping[dataset_name]
    return output_root.joinpath(*prefix, f"{trade_date}.csv")


def _write_dataset(path: Path, dataset_name: str, rows: List[object]) -> None:
    if dataset_name == FUTURES_DATASET:
        write_legacy_futures_output(path, rows)  # type: ignore[arg-type]
        return
    if dataset_name == OPTIONS_DATASET:
        write_options_daily_quotes(path, rows)  # type: ignore[arg-type]
        return
    fieldnames_map = {
        DERIVATIVES_DATASET: (DERIVATIVES_STANDARD_FIELDS, ["trade_date", "instrument_type", "exchange", "contract"]),
        CONTRACTS_DATASET: (CONTRACTS_STANDARD_FIELDS, ["instrument_type", "exchange", "contract"]),
        OPTION_RESULTS_DATASET: (OPTION_RESULTS_STANDARD_FIELDS, ["trade_date", "exchange", "contract"]),
        FUTURES_RESULTS_DATASET: (FUTURES_RESULTS_STANDARD_FIELDS, ["trade_date", "exchange", "contract"]),
        OPTIONS_CHAIN_VIEW: (OPTIONS_CHAIN_MATRIX_FIELDS, ["trade_date", "exchange", "underlying_contract", "expire_date", "strike_price"]),
        UNDERLYING_SUMMARY_VIEW: (UNDERLYING_SUMMARY_FIELDS, ["trade_date", "exchange", "underlying_contract"]),
    }
    fieldnames, sort_keys = fieldnames_map[dataset_name]
    write_dict_rows_csv(path, rows, fieldnames, sort_keys)  # type: ignore[arg-type]


def _write_query_manifest(
    *,
    output_root: Path,
    selection_id: str,
    selection_summary: Dict[str, object],
    trade_date: str,
    outputs: Dict[str, str],
    row_counts: Dict[str, int],
    datasets: List[str],
) -> None:
    manifest_path = output_root / "manifest.json"
    if manifest_path.exists():
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    else:
        payload = {}
    payload["selection_id"] = selection_id
    payload["selection"] = selection_summary
    payload["datasets"] = datasets
    dates = payload.setdefault("dates", {})
    dates[trade_date] = {
        "outputs": outputs,
        "row_counts": row_counts,
    }
    ensure_directory(manifest_path.parent)
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sum_text(left: str, right: str) -> str:
    total = 0
    for value in (left, right):
        text = str(value or "").strip()
        if not text:
            continue
        try:
            total += int(float(text))
        except ValueError:
            continue
    return str(total)


def _future_underlying_kind(row: QuoteRow) -> str:
    if row.exchange == "CFFEX":
        if row.variety_code in {"IF", "IH", "IC", "IM"}:
            return "index"
        if row.variety_code in {"TS", "TF", "T", "TL"}:
            return "bond"
    return "futures"


def _merge_master_metadata(target: Dict[str, str], metadata: Dict[str, str]) -> None:
    for field in (
        "contract_status",
        "list_date",
        "expire_date",
        "last_trade_date",
        "contract_multiplier",
        "quote_unit",
        "price_tick",
        "delivery_type",
        "exercise_type",
        "option_type",
        "strike_price",
        "underlying_exchange",
        "underlying_kind",
        "underlying_product_code",
        "underlying_contract",
        "source_url",
        "source_type",
        "retrieved_at",
        "raw_path",
    ):
        value = metadata.get(field, "")
        text = str(value).strip()
        if text:
            target[field] = text
