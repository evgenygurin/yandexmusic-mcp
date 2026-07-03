"""Settings tests — env prefix, defaults, validation."""

import pytest
from pydantic import ValidationError

from yandexmusic_mcp.config import Settings


def test_defaults(monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("YANDEX_MUSIC_"):
            monkeypatch.delenv(key)
    settings = Settings(_env_file=None)
    assert settings.token == ""
    assert settings.user_id == 0
    assert settings.base_url == "https://api.music.yandex.net"
    assert settings.rate_limit_delay == 1.5
    assert settings.retry_attempts == 3
    assert settings.read_only is False


def test_env_prefix(monkeypatch):
    monkeypatch.setenv("YANDEX_MUSIC_TOKEN", "secret")
    monkeypatch.setenv("YANDEX_MUSIC_USER_ID", "1234")
    monkeypatch.setenv("YANDEX_MUSIC_READ_ONLY", "1")
    settings = Settings(_env_file=None)
    assert settings.token == "secret"
    assert settings.user_id == 1234
    assert settings.read_only is True


def test_invalid_values_rejected(monkeypatch):
    monkeypatch.setenv("YANDEX_MUSIC_RATE_LIMIT_DELAY", "99")  # > 30s cap
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
