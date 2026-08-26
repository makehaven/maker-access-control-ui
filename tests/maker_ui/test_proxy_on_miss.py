"""Tests for proxy-on-miss.

The value of the proxy is entirely in *when it declines*. A proxy that fires on
every denial hands the outage back to the network; a proxy that fails loudly
turns a slow Drupal into a locked building. These tests pin both edges.
"""

from __future__ import annotations

import time
from dataclasses import replace
from typing import Any

import pytest

from ._helpers import ensure_test_env

ensure_test_env()

from maker_access_control_ui import proxy as proxy_service  # noqa: E402
from maker_access_control_ui import sync as sync_service  # noqa: E402
from maker_access_control_ui.ui import app as application  # noqa: E402


DRUPAL_USER = [
    {
        "first_name": "Newly",
        "last_name": "Joined",
        "uuid": "99999999-9999-9999-9999-999999999999",
        "card_serial": "FEEDFACE",
        "access": "Active",
    }
]
DRUPAL_GRANT = [
    {
        "first_name": "Newly",
        "last_name": "Joined",
        "permission": "tool_b",
        "access": "true",
        "uuid": "99999999-9999-9999-9999-999999999999",
    }
]


@pytest.fixture(autouse=True)
def clean_proxy() -> Any:
    """Reset proxy cache, counters, and sync state between tests."""
    proxy_service.reset()
    sync_service.STATE.restore({})
    yield
    proxy_service.reset()
    sync_service.STATE.restore({})


@pytest.fixture()
def enabled(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Turn the proxy on, pointed at a host no test actually contacts."""
    patched = replace(
        proxy_service.CONFIG,
        PROXY_ENABLED=True,
        PROXY_BASE_URL="https://drupal.test",
        PROXY_CACHE_SECONDS=30.0,
    )
    monkeypatch.setattr(proxy_service, "CONFIG", patched)
    return patched


@pytest.fixture()
def client() -> Any:
    """Return a Quart test client."""
    return application.test_client()


def _fresh_store() -> None:
    """Mark the store as just-synced so health reports ``ok``."""
    sync_service.STATE.record_success(
        {"users": 2, "tools": 2, "assignments": 1},
        None,
        None,
        changed=True,
        now=time.time(),
    )


# ----------------------------------------------------------------------
# Policy
# ----------------------------------------------------------------------
def test_proxy_is_off_unless_explicitly_enabled() -> None:
    """Nothing is forwarded until an operator turns the proxy on."""
    assert proxy_service.should_try(proxy_service.REASON_USER_NOT_FOUND) is False


def test_unknown_user_is_always_worth_asking_about(enabled: Any) -> None:
    """The store having nothing to say is the clearest case for a round trip."""
    _fresh_store()
    assert proxy_service.should_try(proxy_service.REASON_USER_NOT_FOUND) is True


def test_a_fresh_denial_is_trusted_locally(enabled: Any) -> None:
    """Proxying every deny would double the latency of the common outcome."""
    _fresh_store()
    assert proxy_service.should_try(proxy_service.REASON_PERMISSION_DENIED) is False


def test_a_denial_on_a_stale_store_is_re_checked(
    enabled: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Once the snapshot is too old to believe, a deny deserves a second look."""
    sync_service.STATE.record_success(
        {"users": 2}, None, None, changed=True, now=time.time() - 100_000
    )
    assert proxy_service.should_try(proxy_service.REASON_PERMISSION_DENIED) is True


# ----------------------------------------------------------------------
# Failure handling
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_a_slow_or_dead_drupal_leaves_the_local_answer_standing(
    enabled: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The proxy must never turn a working box into a locked building."""

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise TimeoutError("timed out")

    monkeypatch.setattr(proxy_service, "_fetch_sync", boom)
    result = await proxy_service.maybe_proxy(
        "/api/v0/serial/FEEDFACE/user", proxy_service.REASON_USER_NOT_FOUND
    )
    assert result is None
    assert proxy_service.counters()["failures"] == 1


@pytest.mark.asyncio
async def test_a_php_error_page_dressed_as_json_is_not_an_answer(
    enabled: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drupal answers 200 with a fatal-error body when its vendor tree breaks."""
    monkeypatch.setattr(
        proxy_service, "_fetch_sync", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
    )
    assert (
        await proxy_service.maybe_proxy(
            "/api/v0/serial/FEEDFACE/user", proxy_service.REASON_USER_NOT_FOUND
        )
        is None
    )


def test_shape_check_rejects_html_and_scalars() -> None:
    """Only records or an error object count as an access-control answer."""
    assert proxy_service._looks_like_an_answer([{"access": "true"}]) is True
    assert proxy_service._looks_like_an_answer({"error": "nope"}) is True
    assert proxy_service._looks_like_an_answer("<html>Fatal error</html>") is False
    assert proxy_service._looks_like_an_answer({"unrelated": 1}) is False
    assert proxy_service._looks_like_an_answer(None) is False


# ----------------------------------------------------------------------
# Caching
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_repeat_taps_are_served_from_cache(
    enabled: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A member tapping twice must not cost two round trips."""
    calls: list[str] = []

    def fake(url: str, _timeout: float) -> Any:
        calls.append(url)
        return 200, DRUPAL_USER

    monkeypatch.setattr(proxy_service, "_fetch_sync", fake)
    path = "/api/v0/serial/FEEDFACE/user"
    first = await proxy_service.maybe_proxy(path, proxy_service.REASON_USER_NOT_FOUND)
    second = await proxy_service.maybe_proxy(path, proxy_service.REASON_USER_NOT_FOUND)

    assert first == second == (200, DRUPAL_USER)
    assert len(calls) == 1
    assert proxy_service.counters()["cache_hits"] == 1


# ----------------------------------------------------------------------
# End to end through the API
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unknown_serial_is_answered_by_drupal(
    client: Any, enabled: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A member who joined since the last sync still gets in."""
    _fresh_store()
    monkeypatch.setattr(proxy_service, "_fetch_sync", lambda *a, **k: (200, DRUPAL_USER))

    response = await client.get("/api/v0/serial/FEEDFACE/user")
    assert response.status_code == 200
    assert (await response.get_json())[0]["first_name"] == "Newly"


@pytest.mark.asyncio
async def test_unknown_serial_falls_back_to_404_when_drupal_is_down(
    client: Any, enabled: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With no upstream, the local not-found answer is still returned."""
    _fresh_store()

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("connection refused")

    monkeypatch.setattr(proxy_service, "_fetch_sync", boom)
    response = await client.get("/api/v0/serial/FEEDFACE/user")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_a_locally_known_member_never_touches_the_network(
    client: Any, enabled: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The hot path stays local; that is the whole point of the box."""
    _fresh_store()

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("proxy must not be called for a local hit")

    monkeypatch.setattr(proxy_service, "_fetch_sync", boom)
    response = await client.get("/api/v0/serial/01020304/permission/tool_a")
    assert response.status_code == 200
    assert proxy_service.counters()["attempts"] == 0


@pytest.mark.asyncio
async def test_a_fresh_local_deny_is_returned_without_asking_drupal(
    client: Any, enabled: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bob has no tool_b badge and the store is current, so 403 stands."""
    _fresh_store()

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("a fresh deny must not be proxied")

    monkeypatch.setattr(proxy_service, "_fetch_sync", boom)
    response = await client.get("/api/v0/serial/A1B2C3D4/permission/tool_b")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_stale_local_deny_is_re_checked_upstream(
    client: Any, enabled: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A badge earned during a long sync outage still opens the tool."""
    sync_service.STATE.record_success(
        {"users": 2}, None, None, changed=True, now=time.time() - 100_000
    )
    monkeypatch.setattr(proxy_service, "_fetch_sync", lambda *a, **k: (200, DRUPAL_GRANT))

    response = await client.get("/api/v0/serial/A1B2C3D4/permission/tool_b")
    assert response.status_code == 200
    assert (await response.get_json())[0]["access"] == "true"


@pytest.mark.asyncio
async def test_health_reports_proxy_activity(
    client: Any, enabled: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Which path answered has to be visible, not inferred from latency."""
    _fresh_store()
    monkeypatch.setattr(proxy_service, "_fetch_sync", lambda *a, **k: (200, DRUPAL_USER))
    await client.get("/api/v0/serial/FEEDFACE/user")

    body = await (await client.get("/health")).get_json()
    assert body["proxy"]["answered"] == 1
    assert body["proxy"]["enabled"] is True
