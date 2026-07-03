"""Configuration for the Yandex Music MCP server, loaded from environment variables.

Settings are read from ``YANDEX_MUSIC_*`` environment variables via
pydantic-settings, which validates and coerces them (e.g.
``YANDEX_MUSIC_TIMEOUT`` must parse as a float). A ``.env`` file in the
working directory is honored.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

YANDEX_MUSIC_API_BASE = "https://api.music.yandex.net"

DEFAULT_DOWNLOAD_DIR = Path.home() / ".yandexmusic-mcp" / "downloads"


class Settings(BaseSettings):
    """Server settings, sourced from ``YANDEX_MUSIC_*`` env vars (or a ``.env`` file)."""

    model_config = SettingsConfigDict(
        env_prefix="YANDEX_MUSIC_", env_file=".env", extra="ignore", case_sensitive=False
    )

    token: str = Field(default="", description="OAuth token; required for every API call.")
    # 0 means "resolve automatically from /account/status on first use".
    user_id: int = Field(default=0, ge=0)
    base_url: str = YANDEX_MUSIC_API_BASE
    timeout: float = Field(default=30.0, gt=0)
    # YM rate-limits aggressively on both reads and writes; keep a floor delay.
    rate_limit_delay: float = Field(default=1.5, ge=0.0, le=30.0)
    retry_backoff: float = Field(default=2.0, ge=1.0, le=10.0)
    retry_attempts: int = Field(default=3, ge=0, le=10)
    download_dir: Path = DEFAULT_DOWNLOAD_DIR
    # When true, the mutating tools (playlists, likes, downloads) are hidden —
    # a safe, read-only deployment for untrusted contexts.
    read_only: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        """Construct from the environment (kept for call-site readability)."""
        return cls()
