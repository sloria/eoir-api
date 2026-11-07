from __future__ import annotations

import hashlib
import os
import tomllib
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any

import msgspec
from platformdirs import user_config_path, user_data_path

from eoir_api.exceptions import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Iterable

CONFIG_ENV_VAR = "EOIR_API_CONFIG"
DEBUG_ENV_VAR = "EOIR_API_DEBUG"
MIN_KEY_LENGTH = 16


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
    profiles_dir: Path = user_data_path("eoir-api") / "profiles"
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


class Usage(_Base):
    db_path: Path = user_data_path("eoir-api") / "usage.sqlite"
    retention_days: Annotated[int, msgspec.Meta(ge=1)] = 30


class Portal(_Base):
    secret: Secret
    """Session secret."""

    def __post_init__(self) -> None:
        if not self.secret:
            raise ValueError("portal secret must not be empty")

    @property
    def session_key(self) -> bytes:
        """Return the 32-byte AES-GCM key for the session cookie."""
        return hashlib.sha256(f"session:{self.secret}".encode()).digest()


class Sentry(_Base):
    dsn: Secret = Secret("")
    environment: str = ""


class Proxy(_Base):
    server: str
    username: Secret | None = None
    password: Secret | None = None


SafeName = Annotated[str, msgspec.Meta(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]


class Browser(_Base):
    # Also the profile dir name, so it must be a safe single path segment
    name: SafeName
    proxy: Proxy | None = None
    group: Annotated[str, msgspec.Meta(min_length=1)] | None = None


class Tenant(_Base):
    name: SafeName
    key: Secret
    """Value the tenant sends in the ``x-api-key`` header."""
    quota_per_day: Annotated[int, msgspec.Meta(ge=1)] | None = None
    """Lookups allowed per rolling 24h. Unset means unlimited."""

    def __post_init__(self) -> None:
        if len(self.key) < MIN_KEY_LENGTH:
            raise ValueError(f"tenant key must be at least {MIN_KEY_LENGTH} characters")


class Settings(_Base):
    tenants: Annotated[list[Tenant], msgspec.Meta(min_length=1)]
    portal: Portal | None = None
    debug: bool = False
    server: Server = msgspec.field(default_factory=Server)
    chrome: Chrome = msgspec.field(default_factory=Chrome)
    lookup: Lookup = msgspec.field(default_factory=Lookup)
    usage: Usage = msgspec.field(default_factory=Usage)
    sentry: Sentry = msgspec.field(default_factory=Sentry)
    browsers: Annotated[list[Browser], msgspec.Meta(min_length=1)] = msgspec.field(
        default_factory=lambda: [Browser(name="default")]
    )

    def __post_init__(self) -> None:
        if dupes := duplicates(b.name for b in self.browsers):
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
                resolve_refs(raw, "$"), cls, strict=False, dec_hook=dec_hook
            )
        except msgspec.ValidationError as exc:
            raise ConfigurationError(f"Invalid config {path}: {exc}") from exc


def duplicates(values: Iterable[str]) -> list[str]:
    return sorted(v for v, c in Counter(values).items() if c > 1)


def find_config(path: Path | None = None) -> Path:
    """Return the config path: ``path``, then ``$EOIR_API_CONFIG``, then the default."""
    default = user_config_path("eoir-api") / "config.toml"
    if path is None:
        env = os.environ.get(CONFIG_ENV_VAR)
        path = Path(env) if env else default
    if not path.is_file():
        raise ConfigurationError(
            f"Config file not found: {path} "
            f"(set with --config or {CONFIG_ENV_VAR}; default {default})"
        )
    return path


def resolve_refs(value: Any, key: str) -> Any:
    """Replace ``{ env = "X" }`` / ``{ file = "/path" }`` refs with their values."""
    if isinstance(value, list):
        return [resolve_refs(v, f"{key}[{i}]") for i, v in enumerate(value)]
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
    return {k: resolve_refs(v, f"{key}.{k}") for k, v in value.items()}


def dec_hook(type_: type, obj: Any) -> Any:
    if type_ is Secret and isinstance(obj, str):
        return Secret(obj)
    if type_ is Path and isinstance(obj, str):
        return Path(obj).expanduser()
    raise NotImplementedError
