from __future__ import annotations

import re
import tomllib
from pathlib import Path

import msgspec
import pytest

from eoir_api.exceptions import ConfigurationError
from eoir_api.settings import (
    CONFIG_ENV_VAR,
    Settings,
    find_config,
)

EXAMPLE_CONFIG = Path(__file__).parent.parent / "config.example.toml"


@pytest.fixture
def write_config(tmp_path):
    def write(text: str) -> Path:
        path = tmp_path / "config.toml"
        path.write_text(text)
        return path

    return write


def test_load_minimal_config_uses_defaults(write_config):
    settings = Settings.load(write_config('api_secret = "s3cret"'))
    assert settings.api_secret == "s3cret"
    assert settings.server.port == 8001
    assert settings.lookup.attempts == 1
    assert [b.name for b in settings.browsers] == ["default"]
    assert settings.browsers[0].proxy is None


def test_load_nested_sections_and_browsers(write_config):
    settings = Settings.load(
        write_config("""
api_secret = "s3cret"

[lookup]
interval = 5

[[browsers]]
name = "direct"

[[browsers]]
name = "araw-1"
proxy = { server = "socks5://araw:1081", username = "u", password = "p" }
""")
    )
    assert settings.lookup.interval == 5
    araw = settings.browsers[1]
    assert araw.name == "araw-1"
    assert araw.proxy is not None
    assert araw.proxy.server == "socks5://araw:1081"
    assert araw.proxy.password == "p"


def test_load_resolves_env_ref(write_config, monkeypatch):
    monkeypatch.setenv("TEST_API_SECRET", "from-env")
    settings = Settings.load(write_config('api_secret = { env = "TEST_API_SECRET" }'))
    assert settings.api_secret == "from-env"


def test_load_resolves_file_ref_and_strips_trailing_newline(write_config, tmp_path):
    secret_file = tmp_path / "secret"
    secret_file.write_text("from-file\n")
    settings = Settings.load(write_config(f'api_secret = {{ file = "{secret_file}" }}'))
    assert settings.api_secret == "from-file"


def test_load_resolves_refs_inside_browser_proxy(write_config, monkeypatch):
    monkeypatch.setenv("TEST_PROXY_PASS", "hunter2")
    settings = Settings.load(
        write_config("""
api_secret = "s3cret"
[[browsers]]
name = "a"
proxy = { server = "socks5://a:1", password = { env = "TEST_PROXY_PASS" } }
""")
    )
    proxy = settings.browsers[0].proxy
    assert proxy is not None
    assert proxy.password == "hunter2"


def test_load_env_ref_coerces_to_field_type(write_config, monkeypatch):
    monkeypatch.setenv("TEST_PORT", "9000")
    settings = Settings.load(
        write_config('api_secret = "s"\n[server]\nport = { env = "TEST_PORT" }')
    )
    assert settings.server.port == 9000


def test_load_unset_env_var_names_key_not_value(write_config, monkeypatch):
    monkeypatch.delenv("TEST_UNSET", raising=False)
    with pytest.raises(ConfigurationError, match=r"\$\.sentry\.dsn.*TEST_UNSET"):
        Settings.load(
            write_config('api_secret = "s"\n[sentry]\ndsn = { env = "TEST_UNSET" }')
        )


def test_load_missing_secret_file_names_key(write_config, tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(ConfigurationError, match=r"\$\.api_secret"):
        Settings.load(write_config(f'api_secret = {{ file = "{missing}" }}'))


@pytest.mark.parametrize(
    "text",
    [
        'api_secret = "s"\nbogus = 1',
        'api_secret = "s"\n[lookup]\nretries = 3',
        'api_secret = "s"\n[[browsers]]\nname = "a"\nport = 1',
    ],
)
def test_load_rejects_unknown_keys(write_config, text):
    with pytest.raises(ConfigurationError, match="unknown field"):
        Settings.load(write_config(text))


def test_load_rejects_duplicate_browser_names(write_config):
    with pytest.raises(ConfigurationError, match="duplicate browser names: a"):
        Settings.load(
            write_config(
                'api_secret = "s"\n[[browsers]]\nname = "a"\n[[browsers]]\nname = "a"'
            )
        )


@pytest.mark.parametrize("name", ["", "..", ".hidden", "a/b", "a b"])
def test_load_rejects_names_unsafe_as_directory(write_config, name):
    with pytest.raises(ConfigurationError, match=r"browsers\[0\]\.name"):
        Settings.load(write_config(f'api_secret = "s"\n[[browsers]]\nname = "{name}"'))


@pytest.mark.parametrize(
    "text",
    [
        'api_secret = ""',
        "debug = true",
        'api_secret = "s"\n[lookup]\nattempts = 0',
        'api_secret = "s"\n[lookup]\nmax_browsers = 0',
        'api_secret = "s"\nbrowsers = []',
    ],
)
def test_load_rejects_invalid_values(write_config, text):
    with pytest.raises(ConfigurationError):
        Settings.load(write_config(text))


def test_load_invalid_toml_raises_configuration_error(write_config):
    with pytest.raises(ConfigurationError, match="Invalid TOML"):
        Settings.load(write_config("api_secret = "))


def test_load_expands_user_in_profiles_dir(write_config):
    settings = Settings.load(
        write_config('api_secret = "s"\n[chrome]\nprofiles_dir = "~/profiles"')
    )
    assert settings.chrome.profiles_dir == Path.home() / "profiles"


def test_secrets_are_redacted_in_repr(write_config):
    settings = Settings.load(
        write_config("""
api_secret = "top-secret"
[sentry]
dsn = "https://key@sentry.example/1"
[[browsers]]
name = "a"
proxy = { server = "socks5://a:1", username = "proxy-user", password = "proxy-pass" }
""")
    )
    text = repr(settings)
    for secret in ("top-secret", "key@sentry", "proxy-user", "proxy-pass"):
        assert secret not in text


def test_find_config_prefers_explicit_path(tmp_path, monkeypatch):
    explicit = tmp_path / "explicit.toml"
    explicit.touch()
    from_env = tmp_path / "env.toml"
    from_env.touch()
    monkeypatch.setenv(CONFIG_ENV_VAR, str(from_env))
    assert find_config(explicit) == explicit


def test_find_config_falls_back_to_env_var(tmp_path, monkeypatch):
    from_env = tmp_path / "env.toml"
    from_env.touch()
    monkeypatch.setenv(CONFIG_ENV_VAR, str(from_env))
    assert find_config() == from_env


def test_find_config_missing_file_names_path(tmp_path, monkeypatch):
    missing = tmp_path / "missing.toml"
    monkeypatch.setenv(CONFIG_ENV_VAR, str(missing))
    with pytest.raises(ConfigurationError, match=r"missing\.toml"):
        find_config()


def _field_paths(struct_type: type[msgspec.Struct], prefix: str = "") -> set[str]:
    paths = set()
    for f in msgspec.structs.fields(struct_type):
        paths.add(prefix + f.name)
        if isinstance(f.type, type) and issubclass(f.type, msgspec.Struct):
            paths |= _field_paths(f.type, f"{prefix}{f.name}.")
    return paths


def _key_paths(table: dict[str, object], prefix: str = "") -> set[str]:
    paths = set()
    for key, value in table.items():
        paths.add(prefix + key)
        if isinstance(value, dict):
            paths |= _key_paths(value, f"{prefix}{key}.")
    return paths


def test_example_config_loads(monkeypatch):
    monkeypatch.setenv("API_SECRET", "example")
    Settings.load(EXAMPLE_CONFIG)


def test_example_config_documents_every_settings_field():
    # Commented-out `# key = value` lines count as documented
    text = re.sub(r"^# (\w+ = )", r"\1", EXAMPLE_CONFIG.read_text(), flags=re.MULTILINE)
    assert _field_paths(Settings) <= _key_paths(tomllib.loads(text))
