"""Access provider protocol and factory helpers."""

from __future__ import annotations

from typing import Any
from typing import Protocol

from maker_access_control_ui.config import CONFIG
from maker_access_control_ui.config import TEST_MODE

from .local_provider import LocalProvider


class AccessProvider(Protocol):
    """Protocol describing the operations available on an access provider."""

    def check_access(self, rfid: str, device_id: str) -> bool:  # noqa: D102
        ...

    def grant(self, user_id: str, tool_id: str) -> None:  # noqa: D102
        ...

    def revoke(self, user_id: str, tool_id: str) -> None:  # noqa: D102
        ...

    def delete_assignment(self, user_id: str, tool_id: str) -> None:  # noqa: D102
        ...

    def list_tools(self) -> list[dict[str, Any]]:  # noqa: D102
        """Return all tools known to the provider."""
        ...

    def list_people(self) -> list[dict[str, Any]]:  # noqa: D102
        """Return all people known to the provider."""
        ...

    def list_assignments(self) -> list[tuple[str, str]]:  # noqa: D102
        """Return all user/tool assignment pairs."""
        ...

    def get_person(self, user_id: str) -> dict[str, Any] | None:  # noqa: D102
        """Return a person by identifier when available."""
        ...

    def get_tool(self, tool_id: str) -> dict[str, Any] | None:  # noqa: D102
        """Return a tool by identifier when available."""
        ...

    def as_state(self) -> dict[str, Any]:  # noqa: D102
        """Return the provider state suitable for serialisation."""
        ...

    def find_user_by_card(
        self, card_serial: str
    ) -> dict[str, Any] | None:  # noqa: D102
        """Return a person matched by card serial."""
        ...

    def find_user_by_uuid(self, user_uuid: str) -> dict[str, Any] | None:  # noqa: D102
        """Return a person matched by UUID."""
        ...

    def list_permissions(self) -> list[str]:  # noqa: D102
        """Return known permission identifiers."""
        ...

    def has_permission(self, user_id: str, permission_id: str) -> bool:  # noqa: D102
        """Return True if ``user_id`` has ``permission_id``."""
        ...

    def find_tools_for_reader(
        self, reader_name: str
    ) -> list[dict[str, Any]]:  # noqa: D102
        """Return tools mapped to a given reader device."""
        ...

    def find_tool_by_badge(
        self, permission_id: str
    ) -> dict[str, Any] | None:  # noqa: D102
        """Return a tool identified by a badge/permission id."""
        ...

    def upsert_person(  # noqa: D102
        self,
        user_id: str,
        rfid: str,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        user_uuid: str | None = None,
        email: str | None = None,
    ) -> None:
        """Create or update a person record."""
        ...

    def upsert_tool(  # noqa: D102
        self,
        tool_id: str,
        device_id: str,
        name: str | None = None,
        *,
        reader_device_id: str | None = None,
        activator_device_id: str | None = None,
        badge_name: str | None = None,
    ) -> None:
        """Create or update a tool record."""
        ...

    def delete_person(self, user_id: str) -> None:  # noqa: D102
        ...

    def delete_tool(self, tool_id: str) -> None:  # noqa: D102
        ...


_local_provider_instance: LocalProvider | None = None


def get_provider() -> AccessProvider:
    """Factory returning the active access provider."""
    global _local_provider_instance
    provider_mode = (CONFIG.ACCESS_PROVIDER or "").lower()

    if TEST_MODE and provider_mode not in {"local", "test"}:
        # When running the Maker UI/tests we always fall back to the JSON store
        # even if a developer forgot to flip the env var.
        provider_mode = "local"

    if provider_mode in {"local", "test"}:
        if _local_provider_instance is None:
            _local_provider_instance = LocalProvider()
        return _local_provider_instance
    raise RuntimeError(
        "AccessProvider mode '%s' is not wired. Set CARDSYS_ACCESS_PROVIDER=local"
        " to use the JSON-backed provider." % provider_mode
    )
