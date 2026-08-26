"""Forward locally-made access decisions back to Drupal.

Nine Drupal modules read `access_control_log` entities. Today every badge tap
creates one *because Drupal answered the request*. The moment this box answers
instead, Drupal stops seeing taps and all nine go quiet -- most visibly the
lobby presence display, which simply goes blank for door entries. This module
is the way back.

Three decisions shape everything here:

* **The queue is on disk, written before the door opens.** An evening of taps
  during a WAN outage is exactly what this exists to preserve; an in-memory
  queue would lose it to a power cut.
* **Forwarding never blocks a decision.** Enqueue is an append; the network
  lives entirely in a background drainer. A door must never wait on logging.
* **Only decisions *this box* made are forwarded.** A request the proxy handed
  upstream was already logged by Drupal as it answered; forwarding it again
  would double-count it in every report built on those entities.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from pathlib import Path
from threading import Lock
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from urllib.error import HTTPError
from urllib.request import Request
from urllib.request import urlopen

from maker_access_control_ui.config import CONFIG


logger = logging.getLogger(__name__)

_QUEUE_LOCK = Lock()

_STATE: Dict[str, Any] = {
    "last_drain_at": None,
    "last_success_at": None,
    "last_error": None,
    "consecutive_failures": 0,
    "forwarded": 0,
    "duplicates": 0,
    "dropped_rejected": 0,
    "dropped_overflow": 0,
}
_STATE_LOCK = Lock()


def _bump(key: str, amount: int = 1) -> None:
    with _STATE_LOCK:
        _STATE[key] = (_STATE.get(key) or 0) + amount


def queue_path() -> Optional[Path]:
    """Return the queue file path, derived from the store location."""
    if CONFIG.LOG_FORWARD_QUEUE_PATH:
        return Path(CONFIG.LOG_FORWARD_QUEUE_PATH)
    store = os.getenv("CARDSYS_TEST_STORE") or CONFIG.STORE_PATH
    if not store:
        return None
    return Path(f"{store}.logqueue.jsonl")


# ----------------------------------------------------------------------
# Queue
# ----------------------------------------------------------------------
def _read_queue(path: Path) -> List[Dict[str, Any]]:
    """Read the queue, skipping any line that did not survive a crash."""
    if not path.exists():
        return []
    events: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                # A torn final line is the normal cost of append-only writing.
                logger.warning("Discarding unreadable log-forward queue line.")
                continue
            if isinstance(event, dict):
                events.append(event)
    return events


def _write_queue(path: Path, events: List[Dict[str, Any]]) -> None:
    """Replace the queue file atomically."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    tmp_path.replace(path)


def enqueue(
    *,
    member_uuid: str,
    permission: str,
    result: bool,
    note: str = "",
    method: str = "unknown",
    source: str = "local_authority",
) -> Optional[str]:
    """Record one decision for later forwarding. Returns its event id.

    Appends and returns; the caller is on the path that opens a door and must
    not wait for anything. A failure to enqueue is logged and swallowed for the
    same reason -- a full disk should cost visibility, not access.
    """
    if not CONFIG.LOG_FORWARD_ENABLED:
        return None
    path = queue_path()
    if not path:
        return None

    event = {
        "event_id": str(uuid.uuid4()),
        "uuid": member_uuid,
        "permission": permission,
        "result": bool(result),
        "note": note,
        "source": source,
        "method": method,
        "timestamp": int(time.time()),
    }

    try:
        with _QUEUE_LOCK:
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, separators=(",", ":")) + "\n")
    except Exception as exc:  # noqa: BLE001
        logger.error("Could not enqueue access log event: %s", exc)
        return None
    return event["event_id"]


def queue_depth() -> int:
    """Return how many events are waiting to be forwarded.

    Counts parseable events rather than lines: a line torn by a power cut will
    never drain, and reporting it as backlog would show a queue that never
    clears.
    """
    path = queue_path()
    if not path or not path.exists():
        return 0
    try:
        with _QUEUE_LOCK:
            return len(_read_queue(path))
    except Exception:  # noqa: BLE001
        return 0


def _trim_overflow(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop the oldest events once the queue exceeds its cap.

    An unbounded queue turns a long Drupal outage into a full disk, which takes
    the door down too. Losing the oldest history is the cheaper failure, but it
    is a real loss, so it is counted and logged rather than done quietly.
    """
    cap = int(CONFIG.LOG_FORWARD_MAX_QUEUE)
    if cap <= 0 or len(events) <= cap:
        return events
    overflow = len(events) - cap
    _bump("dropped_overflow", overflow)
    logger.error(
        "Log-forward queue exceeded %s events; dropped the %s oldest.", cap, overflow
    )
    return events[overflow:]


# ----------------------------------------------------------------------
# Draining
# ----------------------------------------------------------------------
def _post_batch_sync(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """POST one batch, raising on anything that deserves a retry."""
    url = CONFIG.LOG_FORWARD_URL
    body = json.dumps({"events": events}).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    code = CONFIG.LOG_FORWARD_CODE
    if code:
        request.add_header("X-Access-Control-Code", code)

    try:
        with urlopen(request, timeout=CONFIG.LOG_FORWARD_TIMEOUT) as response:
            raw = response.read()
    except HTTPError as error:
        raw = error.read()
        # 4xx other than 413 means this batch will never be accepted as-is;
        # surface it so the drainer can decide, rather than retrying forever.
        raise LogForwardRejected(int(error.code), raw.decode("utf-8", "replace"))

    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Ingest response was not a JSON object.")
    return payload


class LogForwardRejected(Exception):
    """Raised when the ingest endpoint refused a batch outright."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail[:200]}")
        self.status = status
        self.detail = detail


async def drain_once() -> Dict[str, Any]:
    """Forward one batch, removing from the queue only what Drupal settled.

    An event is removed when Drupal accepted it, said it already had it, or
    rejected it as permanently unusable. Everything else stays queued -- the
    default on any uncertainty is to keep the record.
    """
    path = queue_path()
    if not path or not CONFIG.LOG_FORWARD_ENABLED or not CONFIG.LOG_FORWARD_URL:
        return {"status": "disabled"}

    with _QUEUE_LOCK:
        raw = _read_queue(path)
        events = _trim_overflow(raw)
        if len(events) != len(raw):
            # Persist the trim immediately. Doing it here and nowhere else is
            # what keeps the dropped-event counter honest: it counts events
            # lost, not times the check ran.
            _write_queue(path, events)
        if not events:
            return {"status": "empty"}
        batch = events[: int(CONFIG.LOG_FORWARD_BATCH_SIZE)]

    now = time.time()
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(None, lambda: _post_batch_sync(batch))
    except LogForwardRejected as exc:
        with _STATE_LOCK:
            _STATE["last_drain_at"] = now
            _STATE["last_error"] = str(exc)
            _STATE["consecutive_failures"] += 1
        if exc.status == 403 or exc.status == 503:
            # Misconfigured credential or ingest switched off: keep the events,
            # this is fixable and the history is worth more than the retries.
            logger.error("Log-forward refused (%s); keeping %s events queued.", exc.status, len(batch))
        else:
            logger.error("Log-forward rejected batch: %s", exc)
        return {"status": "rejected", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        with _STATE_LOCK:
            _STATE["last_drain_at"] = now
            _STATE["last_error"] = f"{type(exc).__name__}: {exc}"
            _STATE["consecutive_failures"] += 1
        logger.warning("Log-forward drain failed: %s: %s", type(exc).__name__, exc)
        return {"status": "error", "error": str(exc)}

    accepted = int(result.get("accepted") or 0)
    duplicates = int(result.get("duplicates") or 0)
    rejected = result.get("rejected") or []
    rejected_ids = {
        str(item.get("event_id"))
        for item in rejected
        if isinstance(item, dict) and item.get("event_id")
    }
    if rejected:
        logger.warning(
            "Log-forward: Drupal permanently rejected %s of %s events; dropping them.",
            len(rejected),
            len(batch),
        )

    settled = {str(event.get("event_id")) for event in batch}
    with _QUEUE_LOCK:
        remaining = [
            event
            for event in _read_queue(path)
            if str(event.get("event_id")) not in settled
        ]
        _write_queue(path, remaining)

    with _STATE_LOCK:
        _STATE["last_drain_at"] = now
        _STATE["last_success_at"] = now
        _STATE["last_error"] = None
        _STATE["consecutive_failures"] = 0
        _STATE["forwarded"] += accepted
        _STATE["duplicates"] += duplicates
        _STATE["dropped_rejected"] += len(rejected_ids)

    logger.info(
        "Log-forward drained %s events (%s accepted, %s duplicate, %s rejected).",
        len(batch),
        accepted,
        duplicates,
        len(rejected),
    )
    return {
        "status": "ok",
        "sent": len(batch),
        "accepted": accepted,
        "duplicates": duplicates,
        "rejected": len(rejected),
    }


async def drain_loop() -> None:
    """Drain forever, backing off while Drupal is unreachable.

    Like the sync loop, this swallows everything: a drainer that dies leaves a
    queue growing silently behind a door that still works, which is precisely
    the failure the queue depth in ``/health`` exists to expose.
    """
    base = max(1.0, float(CONFIG.LOG_FORWARD_INTERVAL))
    logger.info("Log-forward drain loop starting (every %ss).", base)
    while True:
        delay = base
        try:
            result = await drain_once()
            if result.get("status") in {"error", "rejected"}:
                with _STATE_LOCK:
                    failures = _STATE["consecutive_failures"]
                # Back off to at most ~10 minutes; the queue is durable, so
                # there is no hurry and no reason to hammer a struggling site.
                delay = min(base * (2 ** min(failures, 6)), 600.0)
            elif result.get("status") == "ok":
                # More may be waiting; come straight back for the next batch.
                delay = 0.5 if queue_depth() else base
        except asyncio.CancelledError:
            logger.info("Log-forward drain loop cancelled.")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Log-forward drain loop iteration failed unexpectedly.")
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            logger.info("Log-forward drain loop cancelled.")
            raise


def status() -> Dict[str, Any]:
    """Return log-forward state for ``/health``."""
    with _STATE_LOCK:
        snapshot = dict(_STATE)
    snapshot["enabled"] = CONFIG.LOG_FORWARD_ENABLED
    snapshot["url"] = CONFIG.LOG_FORWARD_URL
    snapshot["queue_depth"] = queue_depth()
    snapshot["max_queue"] = CONFIG.LOG_FORWARD_MAX_QUEUE
    return snapshot


def reset() -> None:
    """Clear queue and counters (used by tests)."""
    path = queue_path()
    if path and path.exists():
        path.unlink()
    with _STATE_LOCK:
        for key in _STATE:
            _STATE[key] = None if key.endswith("_at") or key == "last_error" else 0
