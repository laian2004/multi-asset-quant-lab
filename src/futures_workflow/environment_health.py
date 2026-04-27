import socket
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional

from .config import CHECKPOINT_PATH, DATA_DIR, DUCKDB_PATH, PROJECT_ROOT, STATE_DIR
from .utils import ensure_directory, iso_timestamp


DEFAULT_NETWORK_HOSTS = (
    "www.dce.com.cn",
    "query.sse.com.cn",
    "www.szse.cn",
    "fund.eastmoney.com",
    "api.coingecko.com",
)


def run_environment_health_check(
    *,
    project_root: Path = PROJECT_ROOT,
    data_dir: Path = DATA_DIR,
    state_dir: Path = STATE_DIR,
    checkpoint_path: Path = CHECKPOINT_PATH,
    duckdb_path: Path = DUCKDB_PATH,
    network_hosts: Iterable[str] = DEFAULT_NETWORK_HOSTS,
    subprocess_runner=subprocess.run,
) -> Dict[str, object]:
    checks = {
        "project_root_exists": project_root.exists(),
        "data_dir_exists": data_dir.exists(),
        "state_dir_exists": state_dir.exists(),
        "checkpoint_exists": checkpoint_path.exists(),
        "duckdb_parent_writable": _check_duckdb_parent(duckdb_path),
        "playwright_runtime": _check_playwright_runtime(subprocess_runner=subprocess_runner),
        "dns": _check_dns_hosts(network_hosts),
    }
    failed_checks = []
    issue_category_counts: Dict[str, int] = {}
    blocked_issues = []

    if not checks["project_root_exists"]:
        failed_checks.append("project_root_missing")
        issue_category_counts["path_missing"] = issue_category_counts.get("path_missing", 0) + 1
        blocked_issues.append("project_root: 工作目录不存在")
    if not checks["data_dir_exists"]:
        failed_checks.append("data_dir_missing")
        issue_category_counts["path_missing"] = issue_category_counts.get("path_missing", 0) + 1
        blocked_issues.append("data_dir: data 目录不存在")
    if not checks["state_dir_exists"]:
        failed_checks.append("state_dir_missing")
        issue_category_counts["path_missing"] = issue_category_counts.get("path_missing", 0) + 1
        blocked_issues.append("state_dir: state 目录不存在")
    if not checks["duckdb_parent_writable"]:
        failed_checks.append("duckdb_parent_unwritable")
        issue_category_counts["storage_unwritable"] = issue_category_counts.get("storage_unwritable", 0) + 1
        blocked_issues.append("duckdb: DuckDB 目录不可写")

    playwright_status = str((checks["playwright_runtime"] or {}).get("status", "") or "")
    if playwright_status != "success":
        failed_checks.append("playwright_runtime_missing")
        issue_category_counts["browser_runtime_missing"] = issue_category_counts.get("browser_runtime_missing", 0) + 1
        blocked_issues.append(str((checks["playwright_runtime"] or {}).get("message", "") or "playwright runtime unavailable"))

    dns_failures = [host for host, payload in (checks["dns"] or {}).items() if not bool((payload or {}).get("ok", False))]
    if dns_failures:
        failed_checks.append("dns_failure")
        issue_category_counts["dns_failure"] = len(dns_failures)
        blocked_issues.extend(f"dns: {host}" for host in dns_failures)

    status = "success" if not failed_checks else "partial_success"
    return {
        "status": status,
        "engineering_status": "success" if not failed_checks else "partial",
        "action_name": "environment_check",
        "scope": "environment",
        "mode": "inspect",
        "target": "local_runtime",
        "window_start": "",
        "window_end": "",
        "elapsed_seconds": 0.0,
        "date_counts": {"checked": len(checks)},
        "issue_category_counts": issue_category_counts,
        "blocked_issues": blocked_issues,
        "checks": checks,
        "updated_at": iso_timestamp(),
    }


def _check_duckdb_parent(duckdb_path: Path) -> bool:
    try:
        ensure_directory(duckdb_path.parent)
        probe = duckdb_path.parent / ".duckdb-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _check_playwright_runtime(*, subprocess_runner=subprocess.run) -> Dict[str, object]:
    try:
        version_completed = subprocess_runner(
            [sys.executable, "-m", "playwright", "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:  # pragma: no cover
        return {"status": "failed", "message": str(exc)}
    if int(getattr(version_completed, "returncode", 1)) != 0:
        stderr = str(getattr(version_completed, "stderr", "") or "").strip()
        stdout = str(getattr(version_completed, "stdout", "") or "").strip()
        return {
            "status": "failed",
            "message": stderr or stdout or "playwright runtime unavailable",
        }

    version = str(getattr(version_completed, "stdout", "") or "").strip() or "playwright runtime available"
    probe_code = (
        "from playwright.sync_api import sync_playwright; "
        "p = sync_playwright().start(); "
        "b = p.chromium.launch(headless=True); "
        "b.close(); "
        "p.stop(); "
        "print('chromium_launch_ok')"
    )
    try:
        launch_completed = subprocess_runner(
            [sys.executable, "-c", probe_code],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:  # pragma: no cover
        return {"status": "failed", "message": f"{version}; chromium launch probe failed: {exc}"}

    if int(getattr(launch_completed, "returncode", 1)) == 0:
        return {
            "status": "success",
            "message": version,
            "browser_launch": True,
        }

    stderr = str(getattr(launch_completed, "stderr", "") or "").strip()
    stdout = str(getattr(launch_completed, "stdout", "") or "").strip()
    detail = stderr or stdout or "chromium launch probe failed"
    return {
        "status": "failed",
        "message": f"{version}; {detail}",
        "browser_launch": False,
    }


def _check_dns_hosts(hosts: Iterable[str]) -> Dict[str, Dict[str, object]]:
    results: Dict[str, Dict[str, object]] = {}
    for host in hosts:
        text = str(host or "").strip()
        if not text:
            continue
        try:
            answer = socket.getaddrinfo(text, 443)
            results[text] = {
                "ok": bool(answer),
                "address_count": len(answer),
            }
        except OSError as exc:
            results[text] = {
                "ok": False,
                "message": str(exc),
            }
    return results
