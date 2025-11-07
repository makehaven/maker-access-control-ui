"""Test utilities for configuring Maker Access Control UI fixtures."""

from __future__ import annotations

import functools
import os


@functools.lru_cache(maxsize=1)
def ensure_test_env() -> None:
    """Populate required environment variables for test mode."""
    os.environ.setdefault("CARDSYS_TEST_MODE", "1")
    os.environ.setdefault("CARDSYS_ACCESS_PROVIDER", "local")
    os.environ.setdefault("CARDSYS_DEVICE_ADAPTER", "virtual")

    # Provide safe defaults for required config entries.
    os.environ.setdefault("BADGE_PERMISSION_LOGIN_URL", "http://localhost/login")
    os.environ.setdefault(
        "BADGE_PERMISSION_FETCH_URL",
        "http://localhost/api/v0/uuid/{uuid}/permission/{permission}",
    )
    os.environ.setdefault("BADGE_PERMISSION_USER", "test")
    os.environ.setdefault("BADGE_PERMISSION_PASS", "test")
    os.environ.setdefault("ESPHOME_API_ENCRYPTION_KEY", "test-key")
    os.environ.setdefault("ESPHOME_API_PASSWORD", "test-pass")
    os.environ.setdefault("ESPHOME_API_PORT", "6053")
    os.environ.setdefault("GRAYLOG_HOST", "localhost")
    os.environ.setdefault("GRAYLOG_PYTHON_PORT", "12201")
    os.environ.setdefault(
        "USER_INFO_URL",
        "http://localhost/api/v0/serial/{card_serial}/user",
    )
    os.environ.setdefault("HOME_ASSISTANT_ENTITY_PREFIX", "input_boolean.")
