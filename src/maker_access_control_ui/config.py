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
    PERMISSION_ENDPOINT_EMAIL_TEMPLATE: str = field(
        default="/api/v0/email/{email}/permission/{permission_id}"
    )
    FALLBACK_SOURCE_URL: str = field(
        default="https://makehaven-website.lndo.site/api/v0/access-control/fallback-store"
    )
    FALLBACK_DOWNLOAD_CODE: str = field(default="")


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

    permission_email_default = "/api/v0/email/{email}/permission/{permission_id}"
    permission_email_template = _env_or_default(
        "MAKER_ACCESS_CONTROL_PERMISSION_ENDPOINT_EMAIL",
        default=permission_email_default,
    )

    fallback_url = _env_or_default(
        "MAKER_ACCESS_CONTROL_FALLBACK_URL",
        "CARDSYS_FALLBACK_URL",
        default="https://makehaven-website.lndo.site/api/v0/access-control/fallback-store",
    )
    fallback_code = _env_or_default(
        "MAKER_ACCESS_CONTROL_FALLBACK_CODE",
        "CARDSYS_FALLBACK_CODE",
        default="",
    )

    return Config(
        ACCESS_PROVIDER=provider,
        PERMISSION_ENDPOINT_TEMPLATE=permission_template or permission_default,
        PERMISSION_ENDPOINT_EMAIL_TEMPLATE=permission_email_template
        or permission_email_default,
        FALLBACK_SOURCE_URL=fallback_url,
        FALLBACK_DOWNLOAD_CODE=fallback_code,
    )


CONFIG = load_config()
