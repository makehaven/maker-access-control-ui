"""Fixtures for Maker Access Control UI tests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Generator

import pytest

from ._helpers import ensure_test_env

ensure_test_env()

from maker_access_control_ui.access import provider as provider_module  # noqa: E402


DEFAULT_STATE = {
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
    ],
    "assignments": [["u.alice", "t.tool_a"]],
}

DEFAULT_READER_MAP = {
    "readers": {
        "test_tool_a_reader": {
            "device_name": "test_tool_a_reader",
            "associated_tool_names": ["t.tool_a"],
        },
        "test_tool_b_reader": {
            "device_name": "test_tool_b_reader",
            "associated_tool_names": ["t.tool_b"],
        },
    },
    "tools": {
        "t.tool_a": {
            "device_name": "test_tool_a_activator",
            "badge_name": "tool_a",
        },
        "t.tool_b": {
            "device_name": "test_tool_b_activator",
            "badge_name": "tool_b",
        },
    },
}


@pytest.fixture(autouse=True)
def configure_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Configure the JSON store used by the local access provider."""
    store_path = tmp_path / "store.json"
    store_path.write_text(json.dumps(DEFAULT_STATE))
    monkeypatch.setenv("CARDSYS_TEST_STORE", str(store_path))

    reader_path = tmp_path / "reader_to_tool_config.test.json"
    reader_path.write_text(json.dumps(DEFAULT_READER_MAP))
    monkeypatch.setenv("READER_TO_TOOL_CONFIG_PATH", str(reader_path))

    provider_module._local_provider_instance = None
    yield
    provider_module._local_provider_instance = None


@pytest.fixture()
def provider() -> provider_module.AccessProvider:
    """Return a configured access provider instance for tests."""
    return provider_module.get_provider()
