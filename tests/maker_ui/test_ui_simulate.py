"""Integration tests around the Maker Access Control UI Flask application."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.maker_ui._helpers import ensure_test_env

ensure_test_env()

from quart.testing import QuartClient
from maker_access_control_ui.access import provider as provider_module  # noqa: E402
from maker_access_control_ui.ui.app import app  # noqa: E402

pytestmark = pytest.mark.asyncio

SEED_DATA = {
    "users": [
        {
            "id": "u.alice",
            "card_serial": "01020304",
            "first_name": "Alice",
            "last_name": "Anderson",
            "uuid": "11111111-1111-1111-1111-111111111111",
        },
        {
            "id": "u.bob",
            "card_serial": "A1B2C3D4",
            "first_name": "Bob",
            "last_name": "Baker",
            "uuid": "22222222-2222-2222-2222-222222222222",
        },
    ],
    "tools": [
        {
            "id": "t.tool_a",
            "name": "Tool A",
            "reader_device_id": "test_tool_a_reader",
            "activator_device_id": "test_tool_a_activator",
            "badge_name": "tool_a",
        },
        {
            "id": "t.tool_b",
            "name": "Tool B",
            "reader_device_id": "test_tool_b_reader",
            "activator_device_id": "test_tool_b_activator",
            "badge_name": "tool_b",
        },
        {
            "id": "t.door",
            "name": "Test Door",
            "reader_device_id": "test_door_reader",
            "activator_device_id": "test_door_activator",
            "badge_name": "door",
        },
    ],
    "assignments": [["u.alice", "t.tool_a"], ["u.alice", "t.door"]],
}


@pytest.fixture
def client() -> QuartClient:
    """Build a Flask test client for the Maker UI app."""
    return app.test_client()


async def test_state_endpoint_returns_seed_data(client: QuartClient):
    """State endpoint should reflect seeded data."""
    res = await client.get("/api/state")
    assert res.status_code == 200
    payload = await res.get_json()
    assert payload["users"][0]["id"] == "u.alice"
    assert ["u.alice", "t.tool_a"] in payload["assignments"]
    assert payload["tools"][0]["reader_device_id"] == "test_tool_a_reader"
    assert "meta" in payload
    assert "tool_a" in payload["permissions"]


async def test_create_user_tool_and_assignment_flow(client: QuartClient):
    """Creating users, tools, and assignments should persist."""
    res_user = await client.post(
        "/api/users",
        json={
            "card_serial": "0F0E0D0C",
            "first_name": "Charlie",
            "last_name": "Chaplin",
            "email": "charlie@example.com",
        },
    )
    assert res_user.status_code == 200
    user_payload = await res_user.get_json()
    user_id = user_payload["id"]
    assert user_payload["uuid"]

    res_tool = await client.post(
        "/api/tools",
        json={
            "permission_id": "laser",
            "name": "Laser Cutter",
        },
    )
    assert res_tool.status_code == 200
    tool_payload = await res_tool.get_json()
    tool_id = tool_payload["id"]
    assert tool_payload["badge_name"] == "laser"
    assert tool_payload["reader_device_id"] == tool_id

    res_assignment = await client.post(
        "/api/assignments",
        json={"user_id": user_id, "tool_id": tool_id},
    )
    assert res_assignment.status_code == 200

    state_res = await client.get("/api/state")
    state = await state_res.get_json()
    assert any(user["id"] == user_id for user in state["users"])
    assert any(tool["id"] == tool_id for tool in state["tools"])
    assert [user_id, tool_id] in state["assignments"]
    assert "laser" in state["permissions"]


async def test_assignment_validation_requires_existing_entities(client: QuartClient):
    """Assignments require existing user and tool records."""
    res_user_missing = await client.post(
        "/api/assignments",
        json={"user_id": "missing", "tool_id": "t.tool_a"},
    )
    assert res_user_missing.status_code == 404

    res_tool_missing = await client.post(
        "/api/assignments",
        json={"user_id": "u.alice", "tool_id": "missing"},
    )
    assert res_tool_missing.status_code == 404


async def test_delete_endpoints_remove_entities_and_assignments(client: QuartClient):
    """Deleting entities removes them from state."""
    res_delete_assignment = await client.delete("/api/assignments/u.alice/t.tool_a")
    assert res_delete_assignment.status_code == 204

    res_delete_user = await client.delete("/api/users/u.alice")
    assert res_delete_user.status_code == 204

    res_delete_tool = await client.delete("/api/tools/t.tool_b")
    assert res_delete_tool.status_code == 204

    state_res = await client.get("/api/state")
    state = await state_res.get_json()
    assert all(user["id"] != "u.alice" for user in state["users"])
    assert all(tool["id"] != "t.tool_b" for tool in state["tools"])
    assert ["u.alice", "t.tool_a"] not in state["assignments"]


async def test_permission_endpoint_grants_access(client: QuartClient):
    """Grant endpoint returns success when permission exists."""
    res = await client.get("/api/v0/serial/01020304/permission/tool_a")
    assert res.status_code == 200
    payload = await res.get_json()
    assert payload[0]["access"] == "true"
    assert payload[0]["permission"] == "tool_a"


async def test_permission_endpoint_denies_access(client: QuartClient):
    """Permission endpoint denies unauthorized access."""
    res = await client.get("/api/v0/serial/A1B2C3D4/permission/tool_a")
    assert res.status_code == 403
    payload = await res.get_json()
    assert "error" in payload


async def test_user_info_endpoint(client: QuartClient):
    """User info endpoint returns seeded user details."""
    res = await client.get("/api/v0/serial/01020304/user")
    assert res.status_code == 200
    payload = await res.get_json()
    assert payload["first_name"] == "Alice"
    assert payload["uuid"].startswith("1111")

    res_uuid = await client.get(
        "/api/v0/uuid/11111111-1111-1111-1111-111111111111/permission/tool_a"
    )
    assert res_uuid.status_code == 200
    payload_uuid = await res_uuid.get_json()
    assert payload_uuid[0]["permission"] == "tool_a"


async def test_user_creation_generates_uuid_when_missing_id(client: QuartClient):
    """User creation generates a UUID when absent."""
    res = await client.post(
        "/api/users",
        json={"card_serial": "ABCDEF12"},
    )
    assert res.status_code == 200
    payload = await res.get_json()
    assert payload["uuid"]
    assert payload["id"] == payload["uuid"]


async def test_tool_creation_only_permission_id(client: QuartClient):
    """Tool creation should derive ids when only a permission id is provided."""
    res = await client.post(
        "/api/tools",
        json={"permission_id": "shopbot"},
    )
    assert res.status_code == 200
    payload = await res.get_json()
    assert payload["badge_name"] == "shopbot"
    assert payload["reader_device_id"] == payload["id"]
    assert payload["activator_device_id"] == payload["reader_device_id"]


async def test_simulator_permission_flow(client: QuartClient):
    """Simulator endpoint should echo request details."""
    res = await client.post(
        "/api/simulator/permission",
        json={"card_id": "01020304", "permission_id": "tool_a"},
    )
    assert res.status_code == 200
    payload = await res.get_json()
    assert payload["request"]["url"].endswith("permission/tool_a")
    assert payload["response"]["status"] == 200
    assert payload["response"]["body"][0]["access"] == "true"
