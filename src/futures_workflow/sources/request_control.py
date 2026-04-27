import random
from threading import Lock
from time import monotonic, sleep
from typing import Dict, Mapping, Optional
from urllib.parse import urlparse

from requests import Response

from ..exceptions import PendingRetryError


_DEFAULT_BEHAVIOR = {
    "min_interval_seconds": 0.15,
    "jitter_seconds": 0.05,
    "blocked_backoff_seconds": 15.0,
}

_HOST_SCHEDULES: Dict[str, float] = {}
_HOST_BLOCKED_UNTIL: Dict[str, float] = {}
_LOCK = Lock()

_BLOCKED_STATUS_CODES = {403, 429, 456}
_BLOCKED_TEXT_MARKERS = (
    "拒绝访问",
    "已被新浪安全部门封禁",
    "IP 存在异常访问",
    "停止异常访问一段时间后",
    "finproduct@staff.sina.com.cn",
)


def pace_request(url: str, settings: Optional[Mapping[str, object]] = None) -> None:
    host = _host_key(url)
    behavior = _behavior_for_host(settings, host)
    min_interval = float(behavior.get("min_interval_seconds", _DEFAULT_BEHAVIOR["min_interval_seconds"]) or 0.0)
    jitter = float(behavior.get("jitter_seconds", _DEFAULT_BEHAVIOR["jitter_seconds"]) or 0.0)
    now = monotonic()
    with _LOCK:
        scheduled = max(now, _HOST_SCHEDULES.get(host, 0.0), _HOST_BLOCKED_UNTIL.get(host, 0.0))
        if jitter > 0:
            scheduled += random.uniform(0.0, jitter)
        _HOST_SCHEDULES[host] = scheduled + max(min_interval, 0.0)
    wait_seconds = max(0.0, scheduled - now)
    if wait_seconds > 0:
        sleep(wait_seconds)


def raise_for_protective_block(url: str, response: Response, settings: Optional[Mapping[str, object]] = None) -> None:
    text = response.text[:4096]
    if response.status_code in _BLOCKED_STATUS_CODES or any(marker in text for marker in _BLOCKED_TEXT_MARKERS):
        host = _host_key(url)
        behavior = _behavior_for_host(settings, host)
        blocked_backoff = float(behavior.get("blocked_backoff_seconds", _DEFAULT_BEHAVIOR["blocked_backoff_seconds"]) or 0.0)
        if blocked_backoff > 0:
            with _LOCK:
                _HOST_BLOCKED_UNTIL[host] = max(_HOST_BLOCKED_UNTIL.get(host, 0.0), monotonic() + blocked_backoff)
        raise PendingRetryError(f"{host} returned a protective block for {url}")


def _host_key(url: str) -> str:
    return urlparse(url).netloc.lower()


def _behavior_for_host(settings: Optional[Mapping[str, object]], host: str) -> Dict[str, object]:
    if not settings:
        return dict(_DEFAULT_BEHAVIOR)
    request_behavior = settings.get("request_behavior", {})
    if not isinstance(request_behavior, Mapping):
        return dict(_DEFAULT_BEHAVIOR)
    default_behavior = request_behavior.get("default", {})
    host_behavior = request_behavior.get("hosts", {}).get(host, {})
    merged = dict(_DEFAULT_BEHAVIOR)
    if isinstance(default_behavior, Mapping):
        merged.update(default_behavior)
    if isinstance(host_behavior, Mapping):
        merged.update(host_behavior)
    return merged
