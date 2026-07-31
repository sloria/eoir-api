from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from dataclass_settings import Env, load_settings

from eoir_api.exceptions import ConfigurationError

HERE = Path(__file__).parent
PROJECT_ROOT = HERE.parent.parent
DEFAULT_PROFILE_DIR = PROJECT_ROOT / "profile"


@dataclass(kw_only=True)
class Settings:
    debug: Annotated[bool, Env("DEBUG")] = False

    api_secret: Annotated[str, Env("API_SECRET")]
    """Secret required in the ``x-key`` header."""

    # Browser
    chrome_profile_dir: Annotated[Path, Env("CHROME_PROFILE_DIR")] = DEFAULT_PROFILE_DIR
    lookup_timeout: Annotated[int, Env("LOOKUP_TIMEOUT")] = 20
    """Seconds to wait for a single lookup attempt to produce a response."""
    lookup_attempts: Annotated[int, Env("LOOKUP_ATTEMPTS")] = 2
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
