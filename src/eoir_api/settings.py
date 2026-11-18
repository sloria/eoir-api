from __future__ import annotations

import hashlib
import os
import tomllib
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Self

import msgspec
from platformdirs import user_config_path, user_data_path

from eoir_api.exceptions import ConfigurationError

if TYPE_CHECKING:
    from collections.abc import Iterable

CONFIG_ENV_VAR = "EOIR_API_CONFIG"
DEBUG_ENV_VAR = "EOIR_API_DEBUG"


class Secret(str):
    """String whose ``repr`` is redacted so it never reaches logs."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "Secret('**********')"


class _Base(msgspec.Struct, kw_only=True, forbid_unknown_fields=True):
    pass


def check_not_blank(what: str, secret: str) -> None:
    # A set-but-empty env var would otherwise match an empty credential
    if not secret.strip():
        raise ValueError(f"{what} must not be blank")


class Server(_Base):
    host: str = "127.0.0.1"
    port: int = 8001
    client_ip_header: str | None = None


class Chrome(_Base):
    profiles_dir: Path = user_data_path("eoir-api") / "profiles"
    """Parent of one persistent Chrome profile per browser."""
    idle_timeout: int = 900
    """Seconds of inactivity before a browser is torn down."""


class RunnerLookup(_Base):
    timeout: int = 20
    """Seconds to wait for a single lookup attempt to produce a response."""
    attempts: Annotated[int, msgspec.Meta(ge=1)] = 1
    """Attempts per browser before giving up on a lookup."""


class Lookup(RunnerLookup):
    interval: int = 30
    """Minimum seconds between lookups on one browser."""
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
    retention_days: Annotated[int, msgspec.Meta(ge=1)] = 180


class Portal(_Base):
    secret: Secret
    """Session secret."""

    def __post_init__(self) -> None:
        check_not_blank("portal secret", self.secret)

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


class RunnerBrowser(_Base):
    # Also the profile dir name, so it must be a safe single path segment
    name: SafeName
    proxy: Proxy | None = None


class Browser(_Base):
    name: SafeName
    runner: SafeName
    group: Annotated[str, msgspec.Meta(min_length=1)] | None = None


class Runner(_Base):
    name: SafeName
    url: str
    """Base URL, e.g. ``http://runner-1:8002``."""
    token: Secret

    def __post_init__(self) -> None:
        check_not_blank("runner token", self.token)


class Tenant(_Base):
    name: SafeName
    key: Secret
    """Value the tenant sends in the ``x-api-key`` header."""
    quota_per_day: Annotated[int, msgspec.Meta(ge=1)] | None = None
    """Lookups allowed per rolling 24h. Unset means unlimited."""
    max_concurrency: Annotated[int, msgspec.Meta(ge=1)] | None = None
    """Concurrent lookups allowed before 429. Unset means no cap."""

    def __post_init__(self) -> None:
        check_not_blank("tenant key", self.key)


class _Config(_Base):
    @classmethod
    def load(cls, path: Path) -> Self:
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


class Settings(_Config):
    tenants: Annotated[list[Tenant], msgspec.Meta(min_length=1)]
    runners: Annotated[list[Runner], msgspec.Meta(min_length=1)]
    browsers: Annotated[list[Browser], msgspec.Meta(min_length=1)]
    portal: Portal | None = None
    debug: bool = False
    server: Server = msgspec.field(default_factory=Server)
    lookup: Lookup = msgspec.field(default_factory=Lookup)
    usage: Usage = msgspec.field(default_factory=Usage)
    sentry: Sentry = msgspec.field(default_factory=Sentry)

    def __post_init__(self) -> None:
        check_unique("browser", self.browsers)
        check_unique("runner", self.runners)
        runners = {r.name for r in self.runners}
        for b in self.browsers:
            if b.runner not in runners:
                raise ValueError(f"browser {b.name}: unknown runner {b.runner}")


class RunnerServer(_Base):
    token: Secret
    """Value the hub sends as a bearer token."""
    host: str = "127.0.0.1"
    port: int = 8002

    def __post_init__(self) -> None:
        check_not_blank("runner token", self.token)


class RunnerSettings(_Config):
    """Settings for ``eoir-api runner``."""

    runner: RunnerServer
    chrome: Chrome = msgspec.field(default_factory=Chrome)
    lookup: RunnerLookup = msgspec.field(default_factory=RunnerLookup)
    sentry: Sentry = msgspec.field(default_factory=Sentry)
    browsers: Annotated[list[RunnerBrowser], msgspec.Meta(min_length=1)] = (
        msgspec.field(default_factory=lambda: [RunnerBrowser(name="default")])
    )

    def __post_init__(self) -> None:
        check_unique("browser", self.browsers)


def check_unique(kind: str, items: Iterable[Browser | RunnerBrowser | Runner]) -> None:
    counts = Counter(item.name for item in items)
    if dupes := sorted(name for name, count in counts.items() if count > 1):
        raise ValueError(f"duplicate {kind} names: {', '.join(dupes)}")


def find_config(path: Path | None = None, filename: str = "hub.toml") -> Path:
    """Return the config path: ``path``, then ``$EOIR_API_CONFIG``, then the default."""
    default = user_config_path("eoir-api") / filename
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
