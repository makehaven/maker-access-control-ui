"""Minimal configuration helpers for the Maker Access Control UI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import field


TEST_MODE = os.getenv(
    "MAKER_ACCESS_CONTROL_UI_TEST_MODE", os.getenv("CARDSYS_TEST_MODE", "0")
) == "1"


def _env_or_default(*keys: str, default: str) -> str:
    """Return the first populated environment variable in ``keys``."""
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return default


@dataclass(frozen=True)
class Config:
    """Configuration block used by the Maker Access Control UI."""

    ACCESS_PROVIDER: str = field(default="local")
    PERMISSION_ENDPOINT_TEMPLATE: str = field(
        default="/api/v0/serial/{card_serial}/permission/{permission_id}"
    )


def load_config() -> Config:
    """Load configuration from the environment."""

    provider_default = "local"
    permission_default = "/api/v0/serial/{card_serial}/permission/{permission_id}"
    provider = _env_or_default(
        "MAKER_ACCESS_CONTROL_UI_ACCESS_PROVIDER",
        "CARDSYS_ACCESS_PROVIDER",
        default=provider_default,
    ).lower()

    permission_template = _env_or_default(
        "MAKER_ACCESS_CONTROL_PERMISSION_ENDPOINT",
        "BADGE_PERMISSION_FETCH_URL",
        default=permission_default,
    )

    return Config(
        ACCESS_PROVIDER=provider,
        PERMISSION_ENDPOINT_TEMPLATE=permission_template or permission_default,
    )


CONFIG = load_config()
