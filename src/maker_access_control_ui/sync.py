"""Unattended fallback-store synchronisation and health reporting.

When this box is authoritative for badge decisions, the most dangerous failure
is a silent one: the sync loop stops while the API keeps answering from a
frozen store.  Revoked members would still be admitted and nothing would say
so.  Every choice in this module follows from that:

* a fetch failure never clears or narrows the store -- stale data still opens
  doors for legitimate members, so we keep serving it and shout in ``/health``;
* a *successful* fetch that returns implausibly few users is rejected, because
  a half-broken export is how you revoke the whole membership by accident;
* sync state is persisted next to the store, so a restarted box reports the
  true age of its data instead of pretending it just woke up fresh.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from dataclasses import field
from http import HTTPStatus
from pathlib import Path
from threading import Lock
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple
from urllib.error import HTTPError
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.parse import urlunparse
from urllib.request import Request
from urllib.request import urlopen

from maker_access_control_ui.config import CONFIG


logger = logging.getLogger(__name__)

#: Sentinel returned by :func:`fetch_fallback_store` when the source replied 304.
UNCHANGED = object()


# ----------------------------------------------------------------------
# Fetching
# ----------------------------------------------------------------------
def build_fallback_url(source_url: str, download_code: str) -> str:
    """Return ``source_url`` with the shared download code applied as a query arg."""
    parsed = urlparse(source_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Fallback export URL must include a scheme and host.")
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if download_code:
        query["code"] = download_code
    parts = list(parsed)
    parts[4] = urlencode(query)
    return urlunparse(parts)


def fetch_fallback_store_sync(
    source_url: str,
    download_code: str,
    timeout: float = 60.0,
    etag: Optional[str] = None,
) -> Tuple[Any, Optional[str]]:
    """Download the fallback export, honouring ``ETag`` when the source offers one.

    Returns ``(payload, etag)``, or ``(UNCHANGED, etag)`` when the source
    answered ``304 Not Modified``.  Conditional requests matter here because the
    export is expensive to build; polling often is only affordable if most polls
    cost nothing.
    """
    final_url = build_fallback_url(source_url, download_code)
    request = Request(final_url, headers={"Accept": "application/json"})
    if download_code:
        request.add_header("X-Access-Control-Code", download_code)
    if etag:
        request.add_header("If-None-Match", etag)

    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read()
            new_etag = response.headers.get("ETag")
    except HTTPError as error:
        if error.code == HTTPStatus.NOT_MODIFIED:
            return UNCHANGED, etag
        raise

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise ValueError("Fallback export response was not valid JSON.") from error
    if not isinstance(payload, dict):
        raise ValueError("Fallback export must be a JSON object.")
    return payload, new_etag


async def fetch_fallback_store(
    source_url: str,
    download_code: str,
    timeout: float = 60.0,
    etag: Optional[str] = None,
) -> Tuple[Any, Optional[str]]:
    """Async wrapper around :func:`fetch_fallback_store_sync`."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: fetch_fallback_store_sync(source_url, download_code, timeout, etag),
    )


# ----------------------------------------------------------------------
# Payload sanity checks
# ----------------------------------------------------------------------
class PayloadRejected(ValueError):
    """Raised when an export downloaded cleanly but is not safe to install."""


def validate_payload(
    payload: Dict[str, Any],
    current_user_count: int,
    min_users: int = 10,
    max_shrink_ratio: float = 0.5,
) -> None:
    """Reject exports that would revoke the membership by accident.

    A Drupal query that half-fails still returns HTTP 200 with well-formed JSON.
    Installing it would silently deny hundreds of members, and because the box
    is authoritative there is nothing downstream to catch the mistake.  So an
    export must clear two floors before it is allowed to replace a working one.
    """
    users = payload.get("users")
    if not isinstance(users, list):
        raise PayloadRejected("Export contains no 'users' list.")

    incoming = len(users)
    if incoming < min_users:
        raise PayloadRejected(
            f"Export contains only {incoming} users (floor is {min_users}); "
            "refusing to install it."
        )
    if current_user_count > 0:
        floor = current_user_count * max_shrink_ratio
        if incoming < floor:
            raise PayloadRejected(
                f"Export shrank from {current_user_count} to {incoming} users "
                f"(more than the {1 - max_shrink_ratio:.0%} drop allowed); "
                "refusing to install it."
            )


# ----------------------------------------------------------------------
# Sync state
# ----------------------------------------------------------------------
@dataclass
class SyncState:
    """Thread-safe record of what the sync loop has managed to do."""

    last_attempt_at: Optional[float] = None
    last_success_at: Optional[float] = None
    last_change_at: Optional[float] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    total_successes: int = 0
    etag: Optional[str] = None
    generated_at: Optional[str] = None
    counts: Dict[str, int] = field(default_factory=dict)
    source_url: str = ""
    _lock: Lock = field(default_factory=Lock, repr=False, compare=False)

    def record_success(
        self,
        counts: Dict[str, int],
        etag: Optional[str],
        generated_at: Optional[str],
        changed: bool,
        now: float,
    ) -> None:
        """Record a completed sync, whether or not the data actually moved."""
        with self._lock:
            self.last_attempt_at = now
            self.last_success_at = now
            self.last_error = None
            self.consecutive_failures = 0
            self.total_successes += 1
            self.etag = etag
            if generated_at:
                self.generated_at = generated_at
            if counts:
                self.counts = dict(counts)
            if changed:
                self.last_change_at = now

    def record_failure(self, error: str, now: float) -> None:
        """Record a failed sync without disturbing the data we still hold."""
        with self._lock:
            self.last_attempt_at = now
            self.last_error = error
            self.consecutive_failures += 1

    def snapshot(self) -> Dict[str, Any]:
        """Return a plain dict copy safe to serialise."""
        with self._lock:
            return {
                "last_attempt_at": self.last_attempt_at,
                "last_success_at": self.last_success_at,
                "last_change_at": self.last_change_at,
                "last_error": self.last_error,
                "consecutive_failures": self.consecutive_failures,
                "total_successes": self.total_successes,
                "etag": self.etag,
                "generated_at": self.generated_at,
                "counts": dict(self.counts),
                "source_url": self.source_url,
            }

    def restore(self, data: Dict[str, Any]) -> None:
        """Reload persisted state so a restart reports true data age."""
        with self._lock:
            self.last_attempt_at = data.get("last_attempt_at")
            self.last_success_at = data.get("last_success_at")
            self.last_change_at = data.get("last_change_at")
            self.last_error = data.get("last_error")
            self.consecutive_failures = int(data.get("consecutive_failures") or 0)
            self.total_successes = int(data.get("total_successes") or 0)
            self.etag = data.get("etag")
            self.generated_at = data.get("generated_at")
            counts = data.get("counts")
            self.counts = dict(counts) if isinstance(counts, dict) else {}
            self.source_url = data.get("source_url") or ""


STATE = SyncState()


def _state_path() -> Optional[Path]:
    """Return the sidecar path used to persist sync state across restarts.

    Read from the environment rather than the frozen config so this tracks the
    same store the provider actually opened, even if it was pointed elsewhere
    after import.
    """
    store = os.getenv("CARDSYS_TEST_STORE") or CONFIG.STORE_PATH
    if not store:
        return None
    return Path(f"{store}.sync-state.json")


def load_state() -> None:
    """Restore persisted sync state, ignoring anything unreadable."""
    path = _state_path()
    if not path or not path.exists():
        return
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not read sync state from %s: %s", path, exc)
        return
    if isinstance(data, dict):
        STATE.restore(data)
        logger.info("Restored sync state from %s", path)


def save_state() -> None:
    """Persist sync state next to the store, atomically."""
    path = _state_path()
    if not path:
        return
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(STATE.snapshot(), handle, indent=2)
        tmp_path.replace(path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not persist sync state to %s: %s", path, exc)


# ----------------------------------------------------------------------
# The sync itself
# ----------------------------------------------------------------------
def _provider() -> Any:
    from maker_access_control_ui.access.provider import get_provider

    return get_provider()


def _current_user_count() -> int:
    try:
        return len(_provider().list_people())
    except Exception:  # noqa: BLE001
        return 0


async def run_sync_once(force: bool = False) -> Dict[str, Any]:
    """Fetch the export once and install it if it passes the sanity floors.

    ``force`` bypasses the ``ETag`` short-circuit; the sanity floors always
    apply, since they exist precisely for the cases an operator cannot foresee.
    """
    now = time.time()
    source_url = (CONFIG.FALLBACK_SOURCE_URL or "").strip()
    download_code = (CONFIG.FALLBACK_DOWNLOAD_CODE or "").strip()
    STATE.source_url = source_url

    if not source_url:
        message = "No fallback source URL configured."
        STATE.record_failure(message, now)
        save_state()
        return {"status": "error", "error": message}

    try:
        payload, etag = await fetch_fallback_store(
            source_url,
            download_code,
            timeout=CONFIG.SYNC_TIMEOUT_SECONDS,
            etag=None if force else STATE.etag,
        )
    except Exception as exc:  # noqa: BLE001
        message = f"{type(exc).__name__}: {exc}"
        STATE.record_failure(message, now)
        save_state()
        logger.warning("Fallback sync failed: %s", message)
        return {"status": "error", "error": message}

    if payload is UNCHANGED:
        STATE.record_success({}, etag, None, changed=False, now=now)
        save_state()
        logger.debug("Fallback sync: source unchanged (304).")
        return {"status": "unchanged"}

    try:
        validate_payload(
            payload,
            _current_user_count(),
            min_users=CONFIG.SYNC_MIN_USERS,
            max_shrink_ratio=CONFIG.SYNC_MAX_SHRINK_RATIO,
        )
    except PayloadRejected as exc:
        message = f"Rejected export: {exc}"
        STATE.record_failure(message, now)
        save_state()
        logger.error("Fallback sync %s", message)
        return {"status": "rejected", "error": str(exc)}

    provider = _provider()
    importer = getattr(provider, "import_store_payload", None)
    if not callable(importer):
        message = "Active provider does not support remote imports."
        STATE.record_failure(message, now)
        save_state()
        return {"status": "error", "error": message}

    try:
        summary = importer(payload)
    except Exception as exc:  # noqa: BLE001
        message = f"Import failed: {type(exc).__name__}: {exc}"
        STATE.record_failure(message, now)
        save_state()
        logger.exception("Fallback sync import failed")
        return {"status": "error", "error": message}

    generated_at = payload.get("generated_at")
    STATE.record_success(
        summary,
        etag,
        generated_at if isinstance(generated_at, str) else None,
        changed=True,
        now=now,
    )
    save_state()
    logger.info(
        "Fallback sync installed %s users, %s tools, %s assignments.",
        summary.get("users"),
        summary.get("tools"),
        summary.get("assignments"),
    )
    return {"status": "ok", **summary}


async def sync_loop() -> None:
    """Run :func:`run_sync_once` forever, on an interval, never dying.

    The loop swallows every exception on purpose.  A background task that
    crashes leaves the API serving a store that will never be refreshed again
    -- exactly the silent failure ``/health`` exists to make loud, so the loop
    must survive to keep reporting.
    """
    interval = max(30.0, float(CONFIG.SYNC_INTERVAL_SECONDS))
    jitter = max(0.0, float(CONFIG.SYNC_JITTER_SECONDS))
    logger.info("Fallback sync loop starting (every %ss).", interval)
    while True:
        try:
            await run_sync_once()
        except asyncio.CancelledError:
            logger.info("Fallback sync loop cancelled.")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Fallback sync loop iteration failed unexpectedly.")
        delay = interval + (random.uniform(0, jitter) if jitter else 0.0)
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.info("Fallback sync loop cancelled.")
            raise


# ----------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------
def health_report(now: Optional[float] = None) -> Tuple[Dict[str, Any], int]:
    """Return ``(body, http_status)`` describing whether the box is trustworthy.

    ``ok`` and ``degraded`` both answer 200 so a single missed poll does not
    page anyone at 3am; ``stale`` and ``empty`` answer 503 because at that point
    the box is making access decisions nobody should trust.
    """
    now = time.time() if now is None else now
    snapshot = STATE.snapshot()

    try:
        provider = _provider()
        users = len(provider.list_people())
        tools = len(provider.list_tools())
        assignments = len(provider.list_assignments())
    except Exception as exc:  # noqa: BLE001
        return (
            {
                "status": "error",
                "reason": f"Provider unavailable: {type(exc).__name__}: {exc}",
                "sync": snapshot,
            },
            HTTPStatus.SERVICE_UNAVAILABLE,
        )

    last_success = snapshot["last_success_at"]
    age = None if last_success is None else max(0.0, now - last_success)

    if users == 0:
        status, reason = "empty", "Store holds no users; every badge would be denied."
    elif age is None:
        status, reason = (
            "unknown",
            "No successful sync recorded; store age cannot be established.",
        )
    elif age > CONFIG.HEALTH_CRITICAL_SECONDS:
        status, reason = (
            "stale",
            f"Last successful sync was {int(age)}s ago "
            f"(critical after {CONFIG.HEALTH_CRITICAL_SECONDS}s).",
        )
    elif age > CONFIG.HEALTH_WARN_SECONDS:
        status, reason = (
            "degraded",
            f"Last successful sync was {int(age)}s ago "
            f"(warn after {CONFIG.HEALTH_WARN_SECONDS}s).",
        )
    else:
        status, reason = "ok", None

    body: Dict[str, Any] = {
        "status": status,
        "store": {"users": users, "tools": tools, "assignments": assignments},
        "sync": {
            **snapshot,
            "age_seconds": None if age is None else round(age, 1),
            "enabled": CONFIG.SYNC_ENABLED,
            "interval_seconds": CONFIG.SYNC_INTERVAL_SECONDS,
        },
        "thresholds": {
            "warn_seconds": CONFIG.HEALTH_WARN_SECONDS,
            "critical_seconds": CONFIG.HEALTH_CRITICAL_SECONDS,
        },
    }

    # Imported lazily: proxy policy asks health_report() whether the store is
    # fresh, so a module-level import would be circular.
    from maker_access_control_ui import logforward as logforward_service
    from maker_access_control_ui import proxy as proxy_service

    body["proxy"] = proxy_service.counters()
    body["log_forward"] = logforward_service.status()
    if reason:
        body["reason"] = reason

    unhealthy = status in {"stale", "empty", "unknown", "error"}
    return body, (
        HTTPStatus.SERVICE_UNAVAILABLE if unhealthy else HTTPStatus.OK
    )
