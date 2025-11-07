"""Basic coverage for the JSON-backed access provider."""

from tests.maker_ui._helpers import ensure_test_env

ensure_test_env()

from maker_access_control_ui.access.provider import get_provider  # noqa: E402


def test_provider_basic_access():
    provider = get_provider()
    assert provider.check_access("01020304", "test_tool_a_activator") is True
    assert provider.check_access("A1B2C3D4", "test_tool_a_activator") is False


def test_provider_grant_revoke():
    provider = get_provider()
    assert provider.check_access("A1B2C3D4", "test_tool_b_activator") is False
    provider.grant("u.bob", "t.tool_b")
    assert provider.check_access("A1B2C3D4", "test_tool_b_activator") is True
    provider.revoke("u.bob", "t.tool_b")
    assert provider.check_access("A1B2C3D4", "test_tool_b_activator") is False
