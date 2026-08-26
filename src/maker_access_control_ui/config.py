"""Minimal configuration helpers for the Maker Access Control UI."""

from __future__ import annotations

import os
from dataclasses import dataclass
from dataclasses import field
from urllib.parse import urlparse


TEST_MODE = os.getenv(
    "MAKER_ACCESS_CONTROL_UI_TEST_MODE", os.getenv("CARDSYS_TEST_MODE", "0")
) == "1"


def _origin_of(url: str) -> str:
    """Return just the scheme and host of ``url``.

    The store already names the Drupal the box trusts, so the proxy defaults to
    that same origin. Pointing the two at different sites is possible but has
    to be deliberate.
    """
    parsed = urlparse(url or "")
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _env_flag(*keys: str, default: bool) -> bool:
    """Return the first environment variable in ``keys`` parsed as a boolean."""
    for key in keys:
        value = os.getenv(key)
        if value is not None and value != "":
            return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _env_number(*keys: str, default: float) -> float:
    """Return the first environment variable in ``keys`` parsed as a number."""
    for key in keys:
        value = os.getenv(key)
        if value is not None and value != "":
            try:
                return float(value)
            except ValueError:
                continue
    return default


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
    STORE_PATH: str = field(default="")

    # Unattended synchronisation.  Off by default so that adding this module
    # changes nothing for an existing manually-loaded box; the Proxmox unit
    # turns it on explicitly.
    SYNC_ENABLED: bool = field(default=False)
    SYNC_INTERVAL_SECONDS: float = field(default=300.0)
    SYNC_JITTER_SECONDS: float = field(default=15.0)
    SYNC_TIMEOUT_SECONDS: float = field(default=60.0)
    #: Floors that stop a half-broken export from revoking the membership.
    SYNC_MIN_USERS: int = field(default=10)
    SYNC_MAX_SHRINK_RATIO: float = field(default=0.5)

    HEALTH_WARN_SECONDS: float = field(default=900.0)
    HEALTH_CRITICAL_SECONDS: float = field(default=3600.0)

    # Proxy-on-miss.  Off by default; turning it on trades a little latency on
    # the miss path for correctness about members the snapshot has not heard of
    # yet.
    PROXY_ENABLED: bool = field(default=False)
    PROXY_BASE_URL: str = field(default="")
    PROXY_TIMEOUT_SECONDS: float = field(default=2.5)
    PROXY_CACHE_SECONDS: float = field(default=30.0)

    # Log-forward.  Nine Drupal modules read the access log; once this box
    # answers taps, this is the only thing keeping them fed.
    LOG_FORWARD_ENABLED: bool = field(default=False)
    LOG_FORWARD_URL: str = field(default="")
    LOG_FORWARD_CODE: str = field(default="")
    LOG_FORWARD_QUEUE_PATH: str = field(default="")
    LOG_FORWARD_INTERVAL: float = field(default=15.0)
    LOG_FORWARD_BATCH_SIZE: int = field(default=200)
    LOG_FORWARD_TIMEOUT: float = field(default=15.0)
    LOG_FORWARD_MAX_QUEUE: int = field(default=50_000)


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
        STORE_PATH=_env_or_default("CARDSYS_TEST_STORE", default=""),
        SYNC_ENABLED=_env_flag(
            "MAKER_ACCESS_CONTROL_SYNC_ENABLED",
            "CARDSYS_SYNC_ENABLED",
            default=False,
        ),
        SYNC_INTERVAL_SECONDS=_env_number(
            "MAKER_ACCESS_CONTROL_SYNC_INTERVAL", default=300.0
        ),
        SYNC_JITTER_SECONDS=_env_number(
            "MAKER_ACCESS_CONTROL_SYNC_JITTER", default=15.0
        ),
        SYNC_TIMEOUT_SECONDS=_env_number(
            "MAKER_ACCESS_CONTROL_SYNC_TIMEOUT", default=60.0
        ),
        SYNC_MIN_USERS=int(
            _env_number("MAKER_ACCESS_CONTROL_SYNC_MIN_USERS", default=10)
        ),
        SYNC_MAX_SHRINK_RATIO=_env_number(
            "MAKER_ACCESS_CONTROL_SYNC_MAX_SHRINK_RATIO", default=0.5
        ),
        HEALTH_WARN_SECONDS=_env_number(
            "MAKER_ACCESS_CONTROL_HEALTH_WARN_SECONDS", default=900.0
        ),
        HEALTH_CRITICAL_SECONDS=_env_number(
            "MAKER_ACCESS_CONTROL_HEALTH_CRITICAL_SECONDS", default=3600.0
        ),
        PROXY_ENABLED=_env_flag(
            "MAKER_ACCESS_CONTROL_PROXY_ENABLED", default=False
        ),
        PROXY_BASE_URL=_env_or_default(
            "MAKER_ACCESS_CONTROL_PROXY_BASE_URL",
            default=_origin_of(fallback_url),
        ),
        PROXY_TIMEOUT_SECONDS=_env_number(
            "MAKER_ACCESS_CONTROL_PROXY_TIMEOUT", default=2.5
        ),
        PROXY_CACHE_SECONDS=_env_number(
            "MAKER_ACCESS_CONTROL_PROXY_CACHE_SECONDS", default=30.0
        ),
        LOG_FORWARD_ENABLED=_env_flag(
            "MAKER_ACCESS_CONTROL_LOG_FORWARD_ENABLED", default=False
        ),
        LOG_FORWARD_URL=_env_or_default(
            "MAKER_ACCESS_CONTROL_LOG_FORWARD_URL",
            default=(
                f"{_origin_of(fallback_url)}/api/v0/access-control/log"
                if _origin_of(fallback_url)
                else ""
            ),
        ),
        LOG_FORWARD_CODE=_env_or_default(
            "MAKER_ACCESS_CONTROL_LOG_FORWARD_CODE", default=""
        ),
        LOG_FORWARD_QUEUE_PATH=_env_or_default(
            "MAKER_ACCESS_CONTROL_LOG_FORWARD_QUEUE", default=""
        ),
        LOG_FORWARD_INTERVAL=_env_number(
            "MAKER_ACCESS_CONTROL_LOG_FORWARD_INTERVAL", default=15.0
        ),
        LOG_FORWARD_BATCH_SIZE=int(
            _env_number("MAKER_ACCESS_CONTROL_LOG_FORWARD_BATCH_SIZE", default=200)
        ),
        LOG_FORWARD_TIMEOUT=_env_number(
            "MAKER_ACCESS_CONTROL_LOG_FORWARD_TIMEOUT", default=15.0
        ),
        LOG_FORWARD_MAX_QUEUE=int(
            _env_number("MAKER_ACCESS_CONTROL_LOG_FORWARD_MAX_QUEUE", default=50_000)
        ),
        PERMISSION_ENDPOINT_TEMPLATE=permission_template or permission_default,
        PERMISSION_ENDPOINT_EMAIL_TEMPLATE=permission_email_template
        or permission_email_default,
        FALLBACK_SOURCE_URL=fallback_url,
        FALLBACK_DOWNLOAD_CODE=fallback_code,
    )


CONFIG = load_config()
