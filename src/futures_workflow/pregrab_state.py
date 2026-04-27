import json
from pathlib import Path
from typing import Dict, Mapping

from .config import PREGRAB_STATE_PATH
from .utils import ensure_directory, iso_timestamp


def summarize_pregrab_run(result: Mapping[str, object]) -> Dict[str, object]:
    exchange_results = result.get("exchange_results", {}) or {}
    return {
        "run_id": str(result.get("run_id", "") or ""),
        "mode": str(result.get("mode", "") or ""),
        "exchanges": list(result.get("exchanges", []) or []),
        "window_start": str(result.get("window_start", "") or ""),
        "window_end": str(result.get("window_end", "") or ""),
        "status": str(result.get("status", "") or ""),
        "engineering_status": str(result.get("engineering_status", "") or ""),
        "elapsed_seconds": float(result.get("elapsed_seconds", 0.0) or 0.0),
        "date_counts": dict(result.get("date_counts", {}) or {}),
        "issue_category_counts": dict(result.get("issue_category_counts", {}) or {}),
        "blocked_issues": list(result.get("blocked_issues", []) or []),
        "cleanup_status": str(result.get("cleanup_status", "") or ""),
        "exchange_results": {
            str(exchange): {
                "exchange": str((payload or {}).get("exchange", "") or exchange),
                "status": str((payload or {}).get("status", "") or ""),
                "engineering_status": str((payload or {}).get("engineering_status", "") or ""),
                "elapsed_seconds": float((payload or {}).get("elapsed_seconds", 0.0) or 0.0),
                "day_count": int((payload or {}).get("day_count", 0) or 0),
                "success_count": int((payload or {}).get("success_count", 0) or 0),
                "no_data_count": int((payload or {}).get("no_data_count", 0) or 0),
                "not_applicable_count": int((payload or {}).get("not_applicable_count", 0) or 0),
                "blocked_external_count": int((payload or {}).get("blocked_external_count", 0) or 0),
                "failed_count": int((payload or {}).get("failed_count", 0) or 0),
                "passed": bool((payload or {}).get("passed", False)),
                "engineering_passed": bool((payload or {}).get("engineering_passed", False)),
                "issue_category_counts": dict((payload or {}).get("issue_category_counts", {}) or {}),
                "blocked_issues": list((payload or {}).get("blocked_issues", []) or []),
                "failed_days": list((payload or {}).get("failed_days", []) or []),
                "blocked_days": list((payload or {}).get("blocked_days", []) or []),
            }
            for exchange, payload in exchange_results.items()
        },
    }


def append_pregrab_run(
    result: Mapping[str, object],
    *,
    state_path: Path = PREGRAB_STATE_PATH,
    limit: int = 20,
) -> Dict[str, object]:
    ensure_directory(state_path.parent)
    payload = read_pregrab_state(state_path=state_path)
    runs = list(payload.get("runs", []) or [])
    runs.append(summarize_pregrab_run(result))
    runs = runs[-limit:]
    payload = {
        "updated_at": iso_timestamp(),
        "runs": runs,
    }
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_pregrab_state(*, state_path: Path = PREGRAB_STATE_PATH) -> Dict[str, object]:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
