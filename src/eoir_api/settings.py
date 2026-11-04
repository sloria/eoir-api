from __future__ import annotations

import os
import tomllib
from collections import Counter
from pathlib import Path
from typing import Annotated, Any

import msgspec
from platformdirs import user_config_path, user_data_path

from eoir_api.exceptions import ConfigurationError

CONFIG_ENV_VAR = "EOIR_API_CONFIG"
DEFAULT_CONFIG_PATH = user_config_path("eoir-api") / "config.toml"
DEFAULT_PROFILES_DIR = user_data_path("eoir-api") / "profiles"


class Secret(str):
    """String whose ``repr`` is redacted so it never reaches logs."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "Secret('**********')"


class _Base(msgspec.Struct, kw_only=True, forbid_unknown_fields=True):
    pass


class Server(_Base):
    host: str = "127.0.0.1"
    port: int = 8001


class Chrome(_Base):
    profiles_dir: Path = DEFAULT_PROFILES_DIR
    """Parent of one persistent Chrome profile per browser."""
    idle_timeout: int = 900
    """Seconds of inactivity before a browser is torn down."""


class Lookup(_Base):
    interval: int = 30
    """Minimum seconds between lookups on one browser."""
    timeout: int = 20
    """Seconds to wait for a single lookup attempt to produce a response."""
    attempts: Annotated[int, msgspec.Meta(ge=1)] = 1
    """Attempts per browser before giving up on a lookup."""
    max_browsers: Annotated[int, msgspec.Meta(ge=1)] = 2
    """Browsers one request tries before giving up on captcha failures."""
    captcha_cooldown: int = 300
    """Seconds a browser pauses after a captcha failure."""
    cache_ttl: int = 3 * 60 * 60
    """Seconds to cache a successful lookup result."""
    max_queue_wait: int = 30
    """Beyond this, return 429 instead of holding the connection."""


class Sentry(_Base):
    dsn: Secret = Secret("")
    environment: str = ""


class Proxy(_Base):
    server: str
    username: Secret | None = None
    password: Secret | None = None


class Browser(_Base):
    # Also the profile dir name, so it must be a safe single path segment
    name: Annotated[str, msgspec.Meta(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
    proxy: Proxy | None = None
    group: Annotated[str, msgspec.Meta(min_length=1)] | None = None


class Settings(_Base):
    api_secret: Secret
    """Secret required in the ``x-api-key`` header."""
    debug: bool = False
    server: Server = msgspec.field(default_factory=Server)
    chrome: Chrome = msgspec.field(default_factory=Chrome)
    lookup: Lookup = msgspec.field(default_factory=Lookup)
    sentry: Sentry = msgspec.field(default_factory=Sentry)
    browsers: Annotated[list[Browser], msgspec.Meta(min_length=1)] = msgspec.field(
        default_factory=lambda: [Browser(name="default")]
    )

    def __post_init__(self) -> None:
        if not self.api_secret:
            raise ValueError("api_secret must not be empty")
        counts = Counter(b.name for b in self.browsers)
        if dupes := sorted(n for n, c in counts.items() if c > 1):
            raise ValueError(f"duplicate browser names: {', '.join(dupes)}")

    @classmethod
    def load(cls, path: Path) -> Settings:
        """Load settings from a TOML file, resolving secret refs."""
        try:
            with path.open("rb") as f:
                raw = tomllib.load(f)
        except OSError as exc:
            raise ConfigurationError(f"Cannot read config {path}: {exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise ConfigurationError(f"Invalid TOML in {path}: {exc}") from exc
        try:
            return msgspec.convert(
                _resolve_refs(raw, "$"), cls, strict=False, dec_hook=_dec_hook
            )
        except msgspec.ValidationError as exc:
            raise ConfigurationError(f"Invalid config {path}: {exc}") from exc


def find_config(path: Path | None = None) -> Path:
    """Return the config path: ``path``, then ``$EOIR_API_CONFIG``, then the default."""
    if path is None:
        env = os.environ.get(CONFIG_ENV_VAR)
        path = Path(env) if env else DEFAULT_CONFIG_PATH
    if not path.is_file():
        raise ConfigurationError(
            f"Config file not found: {path} "
            f"(set with --config or {CONFIG_ENV_VAR}; default {DEFAULT_CONFIG_PATH})"
        )
    return path


def _resolve_refs(value: Any, key: str) -> Any:
    """Replace ``{ env = "X" }`` / ``{ file = "/path" }`` refs with their values."""
    if isinstance(value, list):
        return [_resolve_refs(v, f"{key}[{i}]") for i, v in enumerate(value)]
    if not isinstance(value, dict):
        return value
    if value.keys() == {"env"}:
        name = value["env"]
        if name not in os.environ:
            raise ConfigurationError(f"{key}: environment variable {name} is not set")
        return os.environ[name]
    if value.keys() == {"file"}:
        try:
            return Path(value["file"]).expanduser().read_text().rstrip("\n")
        except OSError as exc:
            raise ConfigurationError(
                f"{key}: cannot read {value['file']}: {exc.strerror}"
            ) from exc
    return {k: _resolve_refs(v, f"{key}.{k}") for k, v in value.items()}


def _dec_hook(type_: type, obj: Any) -> Any:
    if type_ is Secret and isinstance(obj, str):
        return Secret(obj)
    if type_ is Path and isinstance(obj, str):
        return Path(obj).expanduser()
    raise NotImplementedError
