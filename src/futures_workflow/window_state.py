import json
from pathlib import Path
from typing import Dict, Mapping

from .config import WINDOW_RUNS_STATE_PATH
from .utils import ensure_directory, iso_timestamp


def summarize_window_run(result: Mapping[str, object]) -> Dict[str, object]:
    return {
        "run_id": str(result.get("run_id", "") or ""),
        "action_name": str(result.get("action_name", "") or ""),
        "scope": str(result.get("scope", "") or ""),
        "mode": str(result.get("mode", "") or ""),
        "target": str(result.get("target", "") or ""),
        "window_start": str(result.get("window_start", "") or ""),
        "window_end": str(result.get("window_end", "") or ""),
        "status": str(result.get("status", "") or ""),
        "engineering_status": str(result.get("engineering_status", "") or ""),
        "elapsed_seconds": float(result.get("elapsed_seconds", 0.0) or 0.0),
        "date_counts": dict(result.get("date_counts", {}) or {}),
        "issue_category_counts": dict(result.get("issue_category_counts", {}) or {}),
        "blocked_issues": list(result.get("blocked_issues", []) or []),
        "updated_at": str(result.get("updated_at", "") or ""),
        "details": dict(result.get("details", {}) or {}),
    }


def append_window_run(
    result: Mapping[str, object],
    *,
    state_path: Path = WINDOW_RUNS_STATE_PATH,
    limit: int = 40,
) -> Dict[str, object]:
    ensure_directory(state_path.parent)
    payload = read_window_state(state_path=state_path)
    runs = list(payload.get("runs", []) or [])
    runs.append(summarize_window_run(result))
    runs = runs[-limit:]
    payload = {
        "updated_at": iso_timestamp(),
        "runs": runs,
    }
    state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def read_window_state(*, state_path: Path = WINDOW_RUNS_STATE_PATH) -> Dict[str, object]:
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
