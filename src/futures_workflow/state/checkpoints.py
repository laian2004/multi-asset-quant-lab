import json
from pathlib import Path
from typing import Any, Dict, Optional

from ..constants import ERROR_STATUS, PENDING_RETRY_STATUS, SUCCESS_LIKE_STATUSES, SUCCESS_STATUS
from ..models import SourceRunResult
from ..utils import ensure_directory, iso_timestamp


class CheckpointStore:
    def __init__(self, path: Path):
        self.path = path
        ensure_directory(self.path.parent)
        if not self.path.exists():
            self.path.write_text(json.dumps({"dates": {}, "retry_queue": []}, ensure_ascii=False, indent=2), encoding="utf-8")
        self.data = self._load()

    def _load(self) -> Dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")

    def update_exchange_result(self, result: SourceRunResult) -> None:
        day_bucket = self.data.setdefault("dates", {}).setdefault(
            result.trade_date,
            {
                "last_run_at": iso_timestamp(),
                "status": "",
                "outputs": {},
                "row_counts": {},
                "selection": {},
                "datasets": {},
            },
        )
        day_bucket["last_run_at"] = iso_timestamp()
        dataset_bucket = day_bucket.setdefault("datasets", {}).setdefault(result.dataset, {"exchanges": {}})
        dataset_bucket["exchanges"][result.exchange] = result.to_summary()
        self._sync_retry_queue(result)

    def update_dataset_state(
        self,
        trade_date: str,
        dataset_name: str,
        *,
        status: str,
        expected_exchanges: Optional[list] = None,
        observed_exchanges: Optional[list] = None,
        completeness_ok: Optional[bool] = None,
        selection_match_ok: Optional[bool] = None,
    ) -> None:
        day_bucket = self.data.setdefault("dates", {}).setdefault(trade_date, {"datasets": {}})
        day_bucket["last_run_at"] = iso_timestamp()
        dataset_bucket = day_bucket.setdefault("datasets", {}).setdefault(dataset_name, {"exchanges": {}})
        dataset_bucket["status"] = status
        dataset_bucket["expected_exchanges"] = sorted(expected_exchanges or [])
        dataset_bucket["observed_exchanges"] = sorted(observed_exchanges or [])
        dataset_bucket["completeness_ok"] = bool(completeness_ok)
        dataset_bucket["selection_match_ok"] = bool(selection_match_ok) if selection_match_ok is not None else True

    def finalize_day(
        self,
        trade_date: str,
        status: str,
        outputs: Optional[Dict[str, str]] = None,
        row_counts: Optional[Dict[str, int]] = None,
        selection: Optional[Dict[str, object]] = None,
    ) -> None:
        day_bucket = self.data.setdefault("dates", {}).setdefault(trade_date, {"datasets": {}})
        day_bucket["last_run_at"] = iso_timestamp()
        day_bucket["status"] = status
        day_bucket["outputs"] = outputs or {}
        day_bucket["row_counts"] = row_counts or {}
        day_bucket["selection"] = selection or {}
        # Compatibility fields for the legacy futures workflow.
        day_bucket["csv_path"] = day_bucket["outputs"].get("futures_daily_quotes", "")
        day_bucket["row_count"] = day_bucket["row_counts"].get("futures_daily_quotes", 0)

    def get_day(self, trade_date: str) -> Dict[str, Any]:
        return self.data.get("dates", {}).get(trade_date, {})

    def get_last_successful_trade_date(self) -> Optional[str]:
        for trade_date in sorted(self.data.get("dates", {}), reverse=True):
            status = self.data["dates"][trade_date].get("status")
            if status in SUCCESS_LIKE_STATUSES:
                return trade_date
        return None

    def get_last_fully_successful_trade_date(self) -> Optional[str]:
        for trade_date in sorted(self.data.get("dates", {}), reverse=True):
            status = self.data["dates"][trade_date].get("status")
            if status == SUCCESS_STATUS:
                return trade_date
        return None

    def _sync_retry_queue(self, result: SourceRunResult) -> None:
        retry_queue = self.data.setdefault("retry_queue", [])
        retry_queue[:] = [
            item
            for item in retry_queue
            if not (
                item["trade_date"] == result.trade_date
                and item["exchange"] == result.exchange
                and item.get("dataset", "futures_daily_quotes") == result.dataset
            )
        ]
        if result.status in {ERROR_STATUS, PENDING_RETRY_STATUS}:
            retry_queue.append(
                {
                    "trade_date": result.trade_date,
                    "dataset": result.dataset,
                    "exchange": result.exchange,
                    "status": result.status,
                    "error": result.error or result.message,
                    "updated_at": iso_timestamp(),
                }
            )
