from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path  # noqa: TC003
from typing import Annotated

from dataclass_settings import Env, Parse, load_settings
from platformdirs import user_data_path

from eoir_api.exceptions import ConfigurationError

DEFAULT_PROFILES_DIR = user_data_path("eoir-api") / "profiles"
DIRECT = "direct"


def parse_list(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


@dataclass(kw_only=True)
class Settings:
    debug: Annotated[bool, Env("DEBUG")] = False

    api_secret: Annotated[str, Env("API_SECRET")]
    """Secret required in the ``x-api-key`` header."""

    # Browser
    chrome_profiles_dir: Annotated[Path, Env("CHROME_PROFILES_DIR")] = (
        DEFAULT_PROFILES_DIR
    )
    """Parent of one persistent Chrome profile per browser."""
    browsers: Annotated[list[str], Env("BROWSERS"), Parse(parse_list)] = field(
        default_factory=lambda: [DIRECT]
    )
    """Browsers to run: ``direct`` or a proxy URL each."""
    lookup_interval: Annotated[int, Env("LOOKUP_INTERVAL")] = 30
    """Minimum seconds between lookups on one browser."""
    captcha_cooldown: Annotated[int, Env("CAPTCHA_COOLDOWN")] = 300
    """Seconds a browser pauses after a captcha failure."""
    lookup_timeout: Annotated[int, Env("LOOKUP_TIMEOUT")] = 20
    """Seconds to wait for a single lookup attempt to produce a response."""
    lookup_attempts: Annotated[int, Env("LOOKUP_ATTEMPTS")] = 1
    """Retry attempts for lookups."""
    browser_idle_timeout: Annotated[int, Env("BROWSER_IDLE_TIMEOUT")] = 900
    """Seconds of inactivity before browser is torn down."""

    # Limits
    cache_ttl: Annotated[int, Env("CACHE_TTL")] = 3 * 60 * 60
    """Seconds to cache a successful lookup result."""
    max_queue_wait: Annotated[int, Env("MAX_QUEUE_WAIT")] = 30
    """Beyond this, return 429 instead of holding the connection."""

    # Sentry
    sentry_dsn: Annotated[str, Env("SENTRY_DSN")] = ""
    sentry_env: Annotated[str, Env("SENTRY_ENV")] = ""

    def __post_init__(self) -> None:
        if not self.api_secret:
            raise ConfigurationError("API_SECRET must be set.")
        if self.lookup_attempts < 1:
            raise ConfigurationError("LOOKUP_ATTEMPTS must be at least 1.")

    @classmethod
    def from_env(cls) -> Settings:
        """Load settings from environment variables."""
        return load_settings(cls)
