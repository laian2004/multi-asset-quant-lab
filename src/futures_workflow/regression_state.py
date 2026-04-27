import json
from pathlib import Path
from typing import Dict, Mapping

from .config import REGRESSION_SMOKE_STATE_PATH
from .utils import ensure_directory, iso_timestamp

_EXTERNAL_REGRESSION_ISSUE_CATEGORIES = {
    "result_chain_publication_lag",
    "result_chain_source_gap",
    "historical_public_contract_gap",
    "blocked_public_source_gap",
}


def _infer_engineering_status(result: Mapping[str, object]) -> str:
    existing = str(result.get("engineering_status", "")).strip()
    if existing:
        return existing
    status = str(result.get("status", "")).strip()
    audit = result.get("audit", {}) or {}
    if list(audit.get("needs_repair_dates", []) or []):
        return "partial"
    platform_sync_status = str(result.get("platform_sync_status", "")).strip()
    platform_validation_status = str(result.get("platform_validation_status", "")).strip()
    build_db_status = str(result.get("build_db_status", "")).strip()
    if platform_sync_status and platform_sync_status != "success":
        return "partial"
    if platform_validation_status and platform_validation_status != "success":
        return "partial"
    if build_db_status and build_db_status != "success":
        return "partial"
    gui_smoke = result.get("gui_smoke", {}) or {}
    if gui_smoke and not bool(gui_smoke.get("has_yield_curves")):
        return "partial"
    issue_categories = {str(key) for key in (audit.get("issue_category_counts", {}) or {})}
    if issue_categories - _EXTERNAL_REGRESSION_ISSUE_CATEGORIES:
        return "partial"
    if status == "success":
        return "success"
    if issue_categories and issue_categories <= _EXTERNAL_REGRESSION_ISSUE_CATEGORIES:
        return "success"
    return ""


def summarize_regression_smoke(result: Mapping[str, object]) -> Dict[str, object]:
    date_results = result.get("date_results", {}) or {}
    window_results = result.get("window_results", {}) or {}
    audit = result.get("audit", {}) or {}
    platform_sync = result.get("platform_sync", {}) or {}
    platform_validation = result.get("platform_validation", {}) or {}
    build_db = result.get("build_db", {}) or {}
    gui_smoke = result.get("gui_smoke", {}) or {}
    return {
        "status": str(result.get("status", "")),
        "engineering_status": _infer_engineering_status(result),
        "dates": list(result.get("dates", []) or []),
        "date_statuses": {
            str(trade_date): str((payload or {}).get("checkpoint_status") or (payload or {}).get("status") or "")
            for trade_date, payload in date_results.items()
        },
        "window_results": {
            str(window_name): {
                "status": str((payload or {}).get("status", "")),
                "sample_count": int((payload or {}).get("sample_count", 0) or 0),
                "sampled_dates": list((payload or {}).get("sampled_dates", []) or []),
                "status_counts": dict((payload or {}).get("status_counts", {}) or {}),
            }
            for window_name, payload in window_results.items()
        },
        "audit": {
            "needs_repair_dates": list(audit.get("needs_repair_dates", []) or []),
            "issue_category_counts": dict(audit.get("issue_category_counts", {}) or {}),
            "issues": list(audit.get("issues", []) or []),
            "blocked_issues": list(audit.get("blocked_issues", []) or []),
        },
        "platform_sync_status": str(platform_sync.get("status", "")),
        "platform_validation_status": str(platform_validation.get("status", "")),
        "build_db_status": str(build_db.get("status", "")) if build_db else "",
        "gui_smoke": dict(gui_smoke or {}),
        "hydrated_dates": list(result.get("hydrated_dates", []) or []),
    }


def write_regression_smoke_state(
    result: Mapping[str, object],
    *,
    state_path: Path = REGRESSION_SMOKE_STATE_PATH,
) -> Dict[str, object]:
    ensure_directory(state_path.parent)
    payload = {
        "updated_at": iso_timestamp(),
        "result": summarize_regression_smoke(result),
    }
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_regression_smoke_state(*, state_path: Path = REGRESSION_SMOKE_STATE_PATH) -> Dict[str, object]:
    if not state_path.exists():
        return {}
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    result = payload.get("result", {}) or {}
    if isinstance(result, dict) and not str(result.get("engineering_status", "")).strip():
        result["engineering_status"] = _infer_engineering_status(result)
        payload["result"] = result
    return payload
