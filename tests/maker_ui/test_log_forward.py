"""Tests for forwarding locally-made decisions back to Drupal.

Nine Drupal modules read the access log. Once this box answers taps, this queue
is the only thing keeping them fed, so the properties that matter are about
what survives: a decision must reach the queue before the door opens, an outage
must not lose it, a retry must not double-count it, and a request the proxy
handed upstream must never be forwarded at all.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from ._helpers import ensure_test_env

ensure_test_env()

from maker_access_control_ui import logforward as logforward_service  # noqa: E402
from maker_access_control_ui import proxy as proxy_service  # noqa: E402
from maker_access_control_ui import sync as sync_service  # noqa: E402
from maker_access_control_ui.ui import app as application  # noqa: E402


@pytest.fixture(autouse=True)
def enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Turn log-forward on, pointed at a host no test actually contacts."""
    patched = replace(
        logforward_service.CONFIG,
        LOG_FORWARD_ENABLED=True,
        LOG_FORWARD_URL="https://drupal.test/api/v0/access-control/log",
        LOG_FORWARD_CODE="test-code",
        LOG_FORWARD_QUEUE_PATH=str(tmp_path / "logqueue.jsonl"),
        LOG_FORWARD_BATCH_SIZE=200,
        LOG_FORWARD_MAX_QUEUE=50_000,
    )
    monkeypatch.setattr(logforward_service, "CONFIG", patched)
    logforward_service.reset()
    proxy_service.reset()
    sync_service.STATE.restore({})
    yield patched
    logforward_service.reset()
    proxy_service.reset()
    sync_service.STATE.restore({})


@pytest.fixture()
def client() -> Any:
    """Return a Quart test client."""
    return application.test_client()


def _queued() -> list:
    """Return the events the module would actually drain."""
    path = logforward_service.queue_path()
    assert path is not None
    if not path.exists():
        return []
    return logforward_service._read_queue(path)


# ----------------------------------------------------------------------
# Enqueue
# ----------------------------------------------------------------------
def test_enqueue_writes_a_complete_event() -> None:
    """Everything Drupal needs to rebuild the entry travels with the event."""
    event_id = logforward_service.enqueue(
        member_uuid="abc", permission="laser_cutter", result=True, method="card"
    )
    assert event_id
    (event,) = _queued()
    assert event["event_id"] == event_id
    assert event["uuid"] == "abc"
    assert event["permission"] == "laser_cutter"
    assert event["result"] is True
    assert event["source"] == "local_authority"
    assert event["method"] == "card"
    assert event["timestamp"] > 0


def test_enqueue_is_a_no_op_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing is written until an operator turns forwarding on."""
    monkeypatch.setattr(
        logforward_service,
        "CONFIG",
        replace(logforward_service.CONFIG, LOG_FORWARD_ENABLED=False),
    )
    assert logforward_service.enqueue(member_uuid="a", permission="p", result=True) is None


def test_a_full_disk_costs_visibility_not_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A door must still open when the queue cannot be written."""

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("No space left on device")

    monkeypatch.setattr(Path, "open", boom)
    assert logforward_service.enqueue(member_uuid="a", permission="p", result=True) is None


def test_a_torn_line_does_not_poison_the_queue() -> None:
    """Append-only writing can leave a partial final line after a power cut."""
    logforward_service.enqueue(member_uuid="a", permission="p", result=True)
    path = logforward_service.queue_path()
    assert path is not None
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"event_id": "trunc')
    assert len(_queued()) == 1
    # The torn line must not show up as backlog that can never clear.
    assert logforward_service.queue_depth() == 1


# ----------------------------------------------------------------------
# Draining
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_successful_drain_clears_only_what_drupal_settled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Accepted, duplicate and permanently-rejected events all leave the queue."""
    for index in range(3):
        logforward_service.enqueue(
            member_uuid=f"member-{index}", permission="door", result=True
        )
    queued = _queued()

    def fake_post(events: list) -> dict:
        assert len(events) == 3
        return {
            "accepted": 2,
            "duplicates": 0,
            "rejected": [{"event_id": queued[2]["event_id"], "reason": "No user."}],
        }

    monkeypatch.setattr(logforward_service, "_post_batch_sync", fake_post)
    result = await logforward_service.drain_once()

    assert result["status"] == "ok"
    assert _queued() == []
    status = logforward_service.status()
    assert status["forwarded"] == 2
    assert status["dropped_rejected"] == 1


@pytest.mark.asyncio
async def test_an_outage_keeps_every_event_queued(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An evening of taps during a WAN outage is what this exists to preserve."""
    for index in range(5):
        logforward_service.enqueue(
            member_uuid=f"member-{index}", permission="door", result=True
        )

    def boom(_events: list) -> Any:
        raise OSError("connection refused")

    monkeypatch.setattr(logforward_service, "_post_batch_sync", boom)
    result = await logforward_service.drain_once()

    assert result["status"] == "error"
    assert len(_queued()) == 5
    assert logforward_service.status()["consecutive_failures"] == 1


@pytest.mark.asyncio
async def test_a_refused_credential_keeps_the_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrong ingest code is fixable; the queued taps must outlive the mistake."""
    logforward_service.enqueue(member_uuid="a", permission="door", result=True)

    def refuse(_events: list) -> Any:
        raise logforward_service.LogForwardRejected(403, "Invalid or missing ingest code.")

    monkeypatch.setattr(logforward_service, "_post_batch_sync", refuse)
    result = await logforward_service.drain_once()

    assert result["status"] == "rejected"
    assert len(_queued()) == 1


@pytest.mark.asyncio
async def test_draining_is_batched(monkeypatch: pytest.MonkeyPatch) -> None:
    """A long outage must not try to POST the whole backlog at once."""
    monkeypatch.setattr(
        logforward_service,
        "CONFIG",
        replace(logforward_service.CONFIG, LOG_FORWARD_BATCH_SIZE=10),
    )
    for index in range(25):
        logforward_service.enqueue(
            member_uuid=f"member-{index}", permission="door", result=True
        )

    sizes: list[int] = []

    def fake_post(events: list) -> dict:
        sizes.append(len(events))
        return {"accepted": len(events), "duplicates": 0, "rejected": []}

    monkeypatch.setattr(logforward_service, "_post_batch_sync", fake_post)
    await logforward_service.drain_once()
    await logforward_service.drain_once()

    assert sizes == [10, 10]
    assert len(_queued()) == 5


@pytest.mark.asyncio
async def test_the_queue_is_capped_and_says_so(
    monkeypatch: pytest.MonkeyPatch, caplog: Any
) -> None:
    """An unbounded queue turns a long outage into a full disk."""
    monkeypatch.setattr(
        logforward_service,
        "CONFIG",
        replace(logforward_service.CONFIG, LOG_FORWARD_MAX_QUEUE=5),
    )
    for index in range(9):
        logforward_service.enqueue(
            member_uuid=f"member-{index}", permission="door", result=True
        )

    def fake_post(events: list) -> dict:
        return {"accepted": len(events), "duplicates": 0, "rejected": []}

    monkeypatch.setattr(logforward_service, "_post_batch_sync", fake_post)
    await logforward_service.drain_once()

    status = logforward_service.status()
    assert status["dropped_overflow"] == 4
    assert status["forwarded"] == 5


# ----------------------------------------------------------------------
# Wiring: which decisions get forwarded
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_local_grant_is_forwarded(client: Any) -> None:
    """The lobby display only sees the tap if the box reports it."""
    response = await client.get("/api/v0/serial/01020304/permission/tool_a")
    assert response.status_code == 200
    (event,) = _queued()
    assert event["result"] is True
    assert event["permission"] == "tool_a"
    assert event["method"] == "card"


@pytest.mark.asyncio
async def test_a_local_deny_is_forwarded_with_its_reason(client: Any) -> None:
    """A refusal is as much a part of the audit trail as an admission."""
    sync_service.STATE.record_success({"users": 2}, None, None, changed=True, now=time.time())
    response = await client.get("/api/v0/serial/A1B2C3D4/permission/tool_b")
    assert response.status_code == 403
    (event,) = _queued()
    assert event["result"] is False
    assert "does not have" in event["note"]


@pytest.mark.asyncio
async def test_a_proxied_decision_is_not_forwarded(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drupal logged it as it answered; forwarding would double-count the tap."""
    monkeypatch.setattr(
        proxy_service,
        "CONFIG",
        replace(
            proxy_service.CONFIG, PROXY_ENABLED=True, PROXY_BASE_URL="https://drupal.test"
        ),
    )
    monkeypatch.setattr(
        proxy_service,
        "_fetch_sync",
        lambda *a, **k: (200, [{"access": "true", "permission": "tool_b"}]),
    )
    sync_service.STATE.record_success(
        {"users": 2}, None, None, changed=True, now=time.time() - 100_000
    )

    response = await client.get("/api/v0/serial/A1B2C3D4/permission/tool_b")
    assert response.status_code == 200
    assert _queued() == []


@pytest.mark.asyncio
async def test_an_unknown_member_is_not_forwarded(client: Any) -> None:
    """Drupal does not log taps it cannot attach to a user, and neither do we."""
    response = await client.get("/api/v0/serial/NOSUCHCARD/permission/tool_a")
    assert response.status_code == 404
    assert _queued() == []


@pytest.mark.asyncio
async def test_health_exposes_the_queue_depth(client: Any) -> None:
    """A queue that stopped draining is invisible from the door."""
    logforward_service.enqueue(member_uuid="a", permission="door", result=True)
    body = await (await client.get("/health")).get_json()
    assert body["log_forward"]["queue_depth"] == 1
    assert body["log_forward"]["enabled"] is True
