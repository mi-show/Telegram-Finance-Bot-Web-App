"""Tests for config module."""
import pytest
from app.config import Settings


SETTINGS_ENV_KEYS = (
    "BOT_TOKEN",
    "DATABASE_URL",
    "LOG_LEVEL",
    "DATE_FORMAT",
    "MAX_LIST_RECORDS",
    "CACHE_TTL",
    "WEBAPP_URL",
    "WEBAPP_HOST",
    "WEBAPP_PORT",
    "WEBAPP_INITDATA_TTL",
    "WEBAPP_DEV_TELEGRAM_ID",
)


@pytest.fixture(autouse=True)
def isolate_settings_env(monkeypatch):
    """Prevent host environment variables from affecting config defaults tests."""
    for key in SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_settings_defaults():
    """Test settings with default values."""
    # Ignore local .env so the test validates class defaults only.
    settings = Settings(_env_file=None, BOT_TOKEN="test-token")
    assert settings.log_level == "INFO"
    assert settings.date_format == "%Y-%m-%d"
    assert settings.max_list_records == 100
    assert settings.cache_ttl_seconds == 300


def test_settings_database_url_default():
    """Test default database URL."""
    settings = Settings(_env_file=None, BOT_TOKEN="test-token")
    assert "sqlite" in settings.database_url


def test_settings_cache_ttl():
    """Test cache TTL setting."""
    settings = Settings(_env_file=None, BOT_TOKEN="test-token")
    assert isinstance(settings.cache_ttl_seconds, int)
    assert settings.cache_ttl_seconds > 0
