"""Proxy-on-miss: ask Drupal when the local store cannot answer honestly.

The local store is authoritative for speed and for surviving an outage, but it
is a *snapshot*.  Two things it cannot know:

* a member who joined, or a badge earned, since the last successful sync;
* anything at all, if the store is empty or has gone stale.

Forwarding those cases to Drupal turns a wrong answer into a slow one.  The
rule that keeps this from becoming "just use Drupal" is that a **fresh** local
deny is trusted: proxying every deny would double the latency of the most
common outcome and hand the outage back to the network.

The proxy is also strictly not allowed to make things worse.  If Drupal is
slow, down, or answering with a PHP error page dressed as HTTP 200, the local
answer stands.  A door that opens for the right people on stale data beats a
door that opens for nobody because the WAN is having a bad day.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from http import HTTPStatus
from threading import Lock
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen

from maker_access_control_ui.config import CONFIG


logger = logging.getLogger(__name__)

#: Why the local store declined to answer.  Each reason has its own policy.
REASON_USER_NOT_FOUND = "user_not_found"
REASON_PERMISSION_DENIED = "permission_denied"
REASON_UNKNOWN_PERMISSION = "unknown_permission"

_CACHE: Dict[str, Tuple[float, int, Any]] = {}
_CACHE_LOCK = Lock()

_COUNTERS: Dict[str, int] = {
    "attempts": 0,
    "answered": 0,
    "declined": 0,
    "failures": 0,
    "cache_hits": 0,
}
_COUNTERS_LOCK = Lock()


def _bump(key: str) -> None:
    with _COUNTERS_LOCK:
        _COUNTERS[key] = _COUNTERS.get(key, 0) + 1


def counters() -> Dict[str, Any]:
    """Return proxy counters for ``/health``."""
    with _COUNTERS_LOCK:
        snapshot = dict(_COUNTERS)
    with _CACHE_LOCK:
        snapshot["cache_entries"] = len(_CACHE)
    snapshot["enabled"] = CONFIG.PROXY_ENABLED
    snapshot["base_url"] = CONFIG.PROXY_BASE_URL
    return snapshot


def reset() -> None:
    """Clear cache and counters (used by tests)."""
    with _CACHE_LOCK:
        _CACHE.clear()
    with _COUNTERS_LOCK:
        for key in _COUNTERS:
            _COUNTERS[key] = 0


# ----------------------------------------------------------------------
# Policy
# ----------------------------------------------------------------------
def should_try(reason: str) -> bool:
    """Decide whether ``reason`` is worth a round trip to Drupal.

    An unknown user is always worth asking about: the store genuinely has
    nothing to say, and the most likely explanation is a member who joined
    since the last sync.  A *denial* is different -- the store does have
    something to say -- so it is only re-checked when the store is too old to
    be believed.
    """
    if not CONFIG.PROXY_ENABLED or not CONFIG.PROXY_BASE_URL:
        return False
    if reason in {REASON_USER_NOT_FOUND, REASON_UNKNOWN_PERMISSION}:
        return True
    if reason == REASON_PERMISSION_DENIED:
        from maker_access_control_ui import sync as sync_service

        body, _status = sync_service.health_report()
        return body.get("status") != "ok"
    return False


# ----------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------
def _looks_like_an_answer(body: Any) -> bool:
    """Reject bodies that parsed but are not a response this API produces.

    Drupal answers HTTP 200 with a PHP fatal error page when its vendor tree is
    broken -- ``raise_for_status`` cannot see that, and neither can a bare
    ``json.loads`` if the page happens to parse.  Anything that is not a list
    of records or an object carrying ``error`` is treated as a failed proxy so
    the local answer stands.
    """
    if isinstance(body, list):
        return all(isinstance(item, dict) for item in body)
    if isinstance(body, dict):
        return "error" in body or "access" in body
    return False


def _fetch_sync(url: str, timeout: float) -> Tuple[int, Any]:
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(response.getcode() or 0)
            raw = response.read()
    except HTTPError as error:
        # 403/404 from Drupal are real answers -- a denial is information.
        status = int(error.code)
        raw = error.read()

    body = json.loads(raw)
    if not _looks_like_an_answer(body):
        raise ValueError("Proxy response did not look like an access-control answer.")
    return status, body


async def maybe_proxy(path: str, reason: str) -> Optional[Tuple[int, Any]]:
    """Return Drupal's ``(status, body)`` for ``path``, or ``None`` to stay local.

    ``None`` is the safe outcome and is returned for every failure mode: policy
    says don't ask, the request timed out, the connection failed, or the body
    was not a recognisable answer.
    """
    if not should_try(reason):
        _bump("declined")
        return None

    url = CONFIG.PROXY_BASE_URL.rstrip("/") + path
    now = time.time()

    with _CACHE_LOCK:
        cached = _CACHE.get(url)
        if cached and cached[0] > now:
            _bump("cache_hits")
            logger.debug("Proxy cache hit for %s", path)
            return cached[1], cached[2]

    _bump("attempts")
    loop = asyncio.get_running_loop()
    try:
        status, body = await loop.run_in_executor(
            None, lambda: _fetch_sync(url, CONFIG.PROXY_TIMEOUT_SECONDS)
        )
    except Exception as exc:  # noqa: BLE001
        _bump("failures")
        logger.warning(
            "Proxy to %s failed (%s: %s); keeping the local answer.",
            path,
            type(exc).__name__,
            exc,
        )
        return None

    ttl = max(0.0, float(CONFIG.PROXY_CACHE_SECONDS))
    if ttl:
        with _CACHE_LOCK:
            _CACHE[url] = (now + ttl, status, body)
            # Bounded so a flood of unknown serials cannot grow it without end.
            if len(_CACHE) > 512:
                for key in [k for k, v in _CACHE.items() if v[0] <= now]:
                    _CACHE.pop(key, None)

    _bump("answered")
    logger.info("Proxy answered %s (%s) for reason=%s", path, status, reason)
    return status, body


def status_is_success(status: int) -> bool:
    """Return whether a proxied status counts as a grant."""
    return status == HTTPStatus.OK
