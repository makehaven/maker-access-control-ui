"""Tests for the LAN-served lobby presence board.

The board replaces screens polling Pantheon, so it has to match what the
website's access_display feed showed: one card per visit, service accounts
hidden, guests counted on their host's card, nothing older than a day.
"""

from __future__ import annotations

from typing import Any

import pytest

from ._helpers import ensure_test_env

ensure_test_env()

from maker_access_control_ui import presence  # noqa: E402
from maker_access_control_ui import sync as sync_service  # noqa: E402
from maker_access_control_ui.ui import app as application  # noqa: E402

ALICE = {"id": "u.alice", "uuid": "alice-uuid", "first_name": "Alice", "last_name": "Anderson", "photo": "/p/alice.jpg?itok=1"}
BOB = {"id": "u.bob", "uuid": "bob-uuid", "first_name": "Bob", "last_name": "Baker"}
RIG = {"id": "u.rig", "uuid": "rig-uuid", "first_name": "Card", "last_name": "Rig", "presence_hidden": True}


@pytest.fixture()
def client() -> Any:
    return application.test_client()


@pytest.fixture(autouse=True)
def _clean_presence() -> Any:
    presence.reset()
    yield
    presence.reset()


def test_repeat_taps_within_five_minutes_are_one_visit() -> None:
    presence.record_grant(ALICE, "Door", now=1000)
    presence.record_grant(ALICE, "Laser", now=1100)
    items = presence.feed(now=1200)["items"]
    assert len(items) == 1
    assert items[0]["count"] == 2
    assert items[0]["door"] == "Door"
    assert items[0]["first"] == 1000 and items[0]["last"] == 1100


def test_a_tap_after_the_debounce_starts_a_new_count_but_keeps_the_arrival() -> None:
    presence.record_grant(ALICE, "Door", now=1000)
    presence.record_grant(ALICE, "Laser", now=2000)
    item = presence.feed(now=2100)["items"][0]
    assert (item["count"], item["door"], item["first"]) == (1, "Laser", 1000)


def test_service_accounts_never_appear() -> None:
    presence.record_grant(RIG, "Door", now=1000)
    assert presence.feed(now=1001)["items"] == []


def test_entries_older_than_a_day_drop_off() -> None:
    presence.record_grant(BOB, "Door", now=1000)
    assert presence.feed(now=1000 + presence.WINDOW_SECONDS + 1)["items"] == []


def test_feed_is_incremental_and_oldest_first() -> None:
    presence.record_grant(ALICE, "Door", now=1000)
    presence.record_grant(BOB, "Door", now=1500)
    items = presence.feed(now=1600)["items"]
    assert [i["name"] for i in items] == ["Alice Anderson", "Bob Baker"]
    assert [i["name"] for i in presence.feed(after=1000, now=1600)["items"]] == ["Bob Baker"]


def test_photos_are_served_from_the_box_not_the_website() -> None:
    presence.record_grant(ALICE, "Door", now=1000)
    presence.record_grant(BOB, "Door", now=1000)
    by_name = {i["name"]: i for i in presence.feed(now=1001)["items"]}
    assert by_name["Alice Anderson"]["photo"] == "/display/photo/alice-uuid"
    assert by_name["Bob Baker"]["photo"] is None
    assert presence.photo_source("alice-uuid") == "/p/alice.jpg?itok=1"


def test_guests_get_a_card_and_count_on_their_hosts_card() -> None:
    presence.record_grant(ALICE, "Door", now=1000)
    presence.set_guest_checkins(
        [
            {"id": "guest-1", "name": "Gina Guest", "checked_in": 1100, "host_id": "alice-uuid"},
            {"id": "guest-2", "name": "Earlier Guest", "checked_in": 900, "host_id": "alice-uuid"},
        ]
    )
    by_name = {i["name"]: i for i in presence.feed(now=1200)["items"]}
    assert by_name["Alice Anderson"]["guest_count"] == 1  # only since she arrived
    assert by_name["Gina Guest"]["door"] == presence.GUEST_DOOR_LABEL


@pytest.mark.asyncio
async def test_a_granted_tap_reaches_the_board(client: Any) -> None:
    res = await client.get("/api/v0/serial/01020304/permission/tool_a")
    assert res.status_code == 200
    feed = await (await client.get("/api/presence")).get_json()
    assert [(i["name"], i["door"]) for i in feed["items"]] == [("Alice Anderson", "Tool A")]


@pytest.mark.asyncio
async def test_a_denied_tap_does_not(client: Any) -> None:
    res = await client.get("/api/v0/serial/A1B2C3D4/permission/tool_a")
    assert res.status_code == 403
    feed = await (await client.get("/api/presence")).get_json()
    assert feed["items"] == []


@pytest.mark.asyncio
async def test_the_board_page_carries_the_kiosk_runtime(client: Any) -> None:
    res = await client.get("/display/presence")
    assert res.status_code == 200
    body = await res.get_data(as_text=True)
    assert "MakerspaceKiosk.start(" in body
    assert "window.MakerspaceKiosk" in body  # runtime inlined, not just called


@pytest.mark.asyncio
async def test_sync_installs_guest_checkins(monkeypatch: pytest.MonkeyPatch) -> None:
    export = {
        "users": [{"id": f"u{n}", "card_serial": f"S{n}", "uuid": f"uuid-{n}"} for n in range(50)],
        "tools": [],
        "assignments": [],
        "guest_checkins": [{"id": "g1", "name": "Gina", "checked_in": 10**10, "host_id": ""}],
    }

    async def fake_fetch(*_args: Any, **_kwargs: Any) -> Any:
        return export, '"e1"'

    monkeypatch.setattr(sync_service, "fetch_fallback_store", fake_fetch)
    await sync_service.run_sync_once(force=True)
    assert [i["name"] for i in presence.feed(now=10**10)["items"]] == ["Gina"]
