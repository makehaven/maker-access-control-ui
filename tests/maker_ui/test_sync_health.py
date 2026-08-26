"""Tests for unattended fallback synchronisation and the health endpoint.

The properties asserted here are the ones that keep an authoritative box
honest: a failed sync must never narrow the store, a suspiciously small export
must never be installed, and ``/health`` must go red rather than quietly serve
data that stopped being refreshed.
"""

from __future__ import annotations

import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Any
from typing import Dict

import pytest

from ._helpers import ensure_test_env

ensure_test_env()

from maker_access_control_ui import sync as sync_service  # noqa: E402
from maker_access_control_ui.access import provider as provider_module  # noqa: E402
from maker_access_control_ui.ui import app as application  # noqa: E402


def _export(user_count: int, **extra: Any) -> Dict[str, Any]:
    """Build a well-formed fallback export holding ``user_count`` members."""
    payload: Dict[str, Any] = {
        "users": [
            {
                "id": f"u.member{index}",
                "card_serial": f"{index:08X}",
                "first_name": "Member",
                "last_name": str(index),
                "uuid": f"{index:08d}-0000-0000-0000-000000000000",
            }
            for index in range(user_count)
        ],
        "tools": [
            {
                "id": "t.tool_a",
                "name": "Tool A",
                "reader_device_id": "test_tool_a_reader",
                "activator_device_id": "test_tool_a_activator",
                "badge_name": "tool_a",
            }
        ],
        "assignments": [["u.member0", "t.tool_a"]] if user_count else [],
    }
    payload.update(extra)
    return payload


@pytest.fixture(autouse=True)
def fresh_sync_state() -> Any:
    """Reset the module-level sync state between tests."""
    sync_service.STATE.restore({})
    yield
    sync_service.STATE.restore({})


@pytest.fixture()
def client() -> Any:
    """Return a Quart test client."""
    return application.test_client()


# ----------------------------------------------------------------------
# Sanity floors
# ----------------------------------------------------------------------
def test_validate_payload_accepts_a_healthy_export() -> None:
    """A full export replacing a full store is fine."""
    sync_service.validate_payload(_export(800), current_user_count=807)


def test_validate_payload_rejects_an_export_below_the_floor() -> None:
    """An export with almost nobody in it is a broken query, not a purge."""
    with pytest.raises(sync_service.PayloadRejected, match="only 3 users"):
        sync_service.validate_payload(_export(3), current_user_count=0, min_users=10)


def test_validate_payload_rejects_a_sudden_shrink() -> None:
    """Losing most of the membership in one export must not be installed."""
    with pytest.raises(sync_service.PayloadRejected, match="shrank from 807 to 100"):
        sync_service.validate_payload(_export(100), current_user_count=807)


def test_validate_payload_rejects_a_payload_with_no_user_list() -> None:
    """A response shaped like an error page must not be treated as an export."""
    with pytest.raises(sync_service.PayloadRejected):
        sync_service.validate_payload({"error": "nope"}, current_user_count=807)


# ----------------------------------------------------------------------
# run_sync_once
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sync_installs_a_good_export(monkeypatch: pytest.MonkeyPatch) -> None:
    """A healthy export replaces the store and is recorded as a success."""

    async def fake_fetch(*_args: Any, **_kwargs: Any) -> Any:
        return _export(50, generated_at="2026-08-26T12:00:00+00:00"), '"abc"'

    monkeypatch.setattr(sync_service, "fetch_fallback_store", fake_fetch)
    result = await sync_service.run_sync_once()

    assert result["status"] == "ok"
    assert result["users"] == 50
    assert len(provider_module.get_provider().list_people()) == 50

    snapshot = sync_service.STATE.snapshot()
    assert snapshot["last_success_at"] is not None
    assert snapshot["last_error"] is None
    assert snapshot["etag"] == '"abc"'
    assert snapshot["generated_at"] == "2026-08-26T12:00:00+00:00"


@pytest.mark.asyncio
async def test_sync_failure_leaves_the_store_intact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable source must not cost anyone their access."""
    provider = provider_module.get_provider()
    before = len(provider.list_people())
    assert before > 0

    async def fake_fetch(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("network unreachable")

    monkeypatch.setattr(sync_service, "fetch_fallback_store", fake_fetch)
    result = await sync_service.run_sync_once()

    assert result["status"] == "error"
    assert len(provider.list_people()) == before

    snapshot = sync_service.STATE.snapshot()
    assert snapshot["consecutive_failures"] == 1
    assert "network unreachable" in snapshot["last_error"]
    assert snapshot["last_success_at"] is None


@pytest.mark.asyncio
async def test_sync_rejects_a_shrinking_export_without_touching_the_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A half-broken export downloads cleanly; it still must not be installed."""
    provider = provider_module.get_provider()
    before = len(provider.list_people())

    async def fake_fetch(*_args: Any, **_kwargs: Any) -> Any:
        return _export(0), None

    monkeypatch.setattr(sync_service, "fetch_fallback_store", fake_fetch)
    result = await sync_service.run_sync_once()

    assert result["status"] == "rejected"
    assert len(provider.list_people()) == before
    assert sync_service.STATE.snapshot()["last_success_at"] is None


@pytest.mark.asyncio
async def test_sync_treats_not_modified_as_a_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 304 means the data we hold is current, so the clock must reset."""

    async def fake_fetch(*_args: Any, **_kwargs: Any) -> Any:
        return sync_service.UNCHANGED, '"abc"'

    monkeypatch.setattr(sync_service, "fetch_fallback_store", fake_fetch)
    result = await sync_service.run_sync_once()

    assert result["status"] == "unchanged"
    snapshot = sync_service.STATE.snapshot()
    assert snapshot["last_success_at"] is not None
    assert snapshot["last_change_at"] is None


@pytest.mark.asyncio
async def test_sync_sends_the_stored_etag_and_force_omits_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Conditional requests are what make frequent polling affordable."""
    seen: list[Any] = []

    async def fake_fetch(*_args: Any, **kwargs: Any) -> Any:
        seen.append(kwargs.get("etag"))
        return _export(50), '"etag-1"'

    monkeypatch.setattr(sync_service, "fetch_fallback_store", fake_fetch)
    await sync_service.run_sync_once()
    await sync_service.run_sync_once()
    await sync_service.run_sync_once(force=True)

    assert seen == [None, '"etag-1"', None]


# ----------------------------------------------------------------------
# State persistence
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sync_state_survives_a_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    """A restarted box must report the real age of its data, not a fresh one."""

    async def fake_fetch(*_args: Any, **_kwargs: Any) -> Any:
        return _export(50), None

    monkeypatch.setattr(sync_service, "fetch_fallback_store", fake_fetch)
    await sync_service.run_sync_once()
    recorded = sync_service.STATE.snapshot()["last_success_at"]

    sidecar = Path(f'{os.environ["CARDSYS_TEST_STORE"]}.sync-state.json')
    assert sidecar.exists()

    sync_service.STATE.restore({})
    assert sync_service.STATE.snapshot()["last_success_at"] is None

    sync_service.load_state()
    assert sync_service.STATE.snapshot()["last_success_at"] == recorded


# ----------------------------------------------------------------------
# /health
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_health_is_unavailable_before_any_sync(client: Any) -> None:
    """A box that cannot establish its data age is not one to trust."""
    response = await client.get("/health")
    assert response.status_code == 503
    body = await response.get_json()
    assert body["status"] == "unknown"


@pytest.mark.asyncio
async def test_health_is_ok_after_a_fresh_sync(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A recently synced box reports 200 and the counts it is serving."""

    async def fake_fetch(*_args: Any, **_kwargs: Any) -> Any:
        return _export(50), None

    monkeypatch.setattr(sync_service, "fetch_fallback_store", fake_fetch)
    await sync_service.run_sync_once()

    response = await client.get("/health")
    assert response.status_code == 200
    body = await response.get_json()
    assert body["status"] == "ok"
    assert body["store"]["users"] == 50
    assert body["sync"]["age_seconds"] < 5


@pytest.mark.asyncio
async def test_health_degrades_then_goes_stale_with_age(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Age alone must move the box from ok to degraded to stale."""
    sync_service.STATE.record_success(
        {"users": 2, "tools": 2, "assignments": 1},
        None,
        None,
        changed=True,
        now=time.time(),
    )

    monkeypatch.setattr(
        sync_service,
        "CONFIG",
        replace(
            sync_service.CONFIG,
            HEALTH_WARN_SECONDS=0.0,
            HEALTH_CRITICAL_SECONDS=10_000.0,
        ),
    )
    body, status = sync_service.health_report(now=time.time() + 60)
    assert (body["status"], status) == ("degraded", 200)

    body, status = sync_service.health_report(now=time.time() + 20_000)
    assert (body["status"], status) == ("stale", 503)
    assert "critical" in body["reason"]


@pytest.mark.asyncio
async def test_health_is_unavailable_when_the_store_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty store denies everyone, so it must never report healthy."""
    sync_service.STATE.record_success({}, None, None, changed=True, now=time.time())

    class _EmptyProvider:
        def list_people(self) -> list:
            return []

        def list_tools(self) -> list:
            return []

        def list_assignments(self) -> list:
            return []

    monkeypatch.setattr(sync_service, "_provider", lambda: _EmptyProvider())
    body, status = sync_service.health_report()
    assert (body["status"], status) == ("empty", 503)


# ----------------------------------------------------------------------
# Manual import path
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_manual_import_refuses_a_shrinking_export_unless_forced(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The button and the timer enforce the same floors."""
    provider = provider_module.get_provider()
    before = len(provider.list_people())

    monkeypatch.setattr(
        sync_service,
        "fetch_fallback_store_sync",
        lambda *a, **k: (_export(0), None),
    )

    response = await client.post(
        "/api/store/import",
        json={"url": "https://example.test/api/v0/access-control/fallback-store"},
    )
    assert response.status_code == 409
    body = await response.get_json()
    assert "force" in body["error"]
    assert len(provider.list_people()) == before


@pytest.mark.asyncio
async def test_manual_import_records_state_so_health_goes_green(
    client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A hand-loaded store is a synced store; /health should say so."""
    monkeypatch.setattr(
        sync_service,
        "fetch_fallback_store_sync",
        lambda *a, **k: (_export(50), None),
    )

    response = await client.post(
        "/api/store/import",
        json={"url": "https://example.test/api/v0/access-control/fallback-store"},
    )
    assert response.status_code == 200

    health = await client.get("/health")
    assert health.status_code == 200
    assert (await health.get_json())["status"] == "ok"
