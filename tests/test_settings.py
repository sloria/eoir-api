from __future__ import annotations

import re
import tomllib
from pathlib import Path

import msgspec
import pytest

from eoir_api.exceptions import ConfigurationError
from eoir_api.settings import (
    CONFIG_ENV_VAR,
    RunnerSettings,
    Settings,
    find_config,
)

EXAMPLE_CONFIG = Path(__file__).parent.parent / "hub.example.toml"
EXAMPLE_RUNNER_CONFIG = Path(__file__).parent.parent / "runner.example.toml"
PORTAL = 'portal = { secret = "p" }'
TENANT = 'tenants = [{ name = "owner", key = "owner-test-secret" }]'
RUNNERS = (
    'runners = [{ name = "mac", url = "http://mac:8002", token = "runner-test-token" }]'
)
RUNNER_TABLE = 'name = "mac"\nurl = "http://mac:8002"\ntoken = "runner-test-token"'
BROWSER = '[[browsers]]\nname = "a"\nrunner = "mac"'


def hub(
    extra: str = "",
    *,
    tenants: str = TENANT,
    runners: str = RUNNERS,
    browsers: str = BROWSER,
) -> str:
    return f"{tenants}\n{runners}\n{extra}\n{browsers}"


@pytest.fixture
def write_config(tmp_path):
    def write(text: str, *, portal: bool = True) -> Path:
        path = tmp_path / "hub.toml"
        path.write_text(f"{PORTAL}\n{text}" if portal else text)
        return path

    return write


def test_load_minimal_config_uses_defaults(write_config):
    settings = Settings.load(write_config(hub()))
    [tenant] = settings.tenants
    assert tenant.name == "owner"
    assert tenant.key == "owner-test-secret"
    assert tenant.quota_per_day is None
    assert settings.server.port == 8001
    assert settings.lookup.attempts == 1
    [runner] = settings.runners
    assert (runner.name, runner.url, runner.token) == (
        "mac",
        "http://mac:8002",
        "runner-test-token",
    )
    [browser] = settings.browsers
    assert (browser.name, browser.runner, browser.group) == ("a", "mac", None)


def test_load_resolves_env_ref(write_config, monkeypatch):
    monkeypatch.setenv("TEST_API_KEY", "env-test-secret-key")
    settings = Settings.load(
        write_config(
            hub(tenants='tenants = [{ name = "a", key = { env = "TEST_API_KEY" } }]')
        )
    )
    assert settings.tenants[0].key == "env-test-secret-key"


def test_load_resolves_file_ref_and_strips_trailing_newline(write_config, tmp_path):
    secret_file = tmp_path / "secret"
    secret_file.write_text("file-test-secret-key\n")
    settings = Settings.load(
        write_config(
            hub(
                tenants=f'tenants = [{{ name = "a", key = {{ file = "{secret_file}" }} }}]'
            )
        )
    )
    assert settings.tenants[0].key == "file-test-secret-key"


def test_load_env_ref_coerces_to_field_type(write_config, monkeypatch):
    monkeypatch.setenv("TEST_PORT", "9000")
    settings = Settings.load(
        write_config(hub('[server]\nport = { env = "TEST_PORT" }'))
    )
    assert settings.server.port == 9000


def test_load_unset_env_var_names_key_not_value(write_config, monkeypatch):
    monkeypatch.delenv("TEST_UNSET", raising=False)
    with pytest.raises(ConfigurationError, match=r"\$\.sentry\.dsn.*TEST_UNSET"):
        Settings.load(write_config(hub('[sentry]\ndsn = { env = "TEST_UNSET" }')))


def test_load_missing_secret_file_names_key(write_config, tmp_path):
    missing = tmp_path / "nope"
    with pytest.raises(ConfigurationError, match=r"\$\.tenants\[0\]\.key"):
        Settings.load(
            write_config(
                hub(
                    tenants=f'tenants = [{{ name = "a", key = {{ file = "{missing}" }} }}]'
                )
            )
        )


@pytest.mark.parametrize(
    "text",
    [
        hub("bogus = 1"),
        hub('api_secret = "s"'),
        hub(tenants='tenants = [{ name = "a", key = "owner-test-secret", quota = 1 }]'),
        hub("[lookup]\nretries = 3"),
        hub('[chrome]\nprofiles_dir = "~/profiles"'),
        hub(browsers=BROWSER + "\nport = 1"),
        hub(browsers=BROWSER + '\nproxy = { server = "socks5://x:1" }'),
    ],
)
def test_load_rejects_unknown_keys(write_config, text):
    with pytest.raises(ConfigurationError, match="unknown field"):
        Settings.load(write_config(text))


def test_load_rejects_duplicate_browser_names(write_config):
    with pytest.raises(ConfigurationError, match="duplicate browser names: a"):
        Settings.load(write_config(hub(browsers=f"{BROWSER}\n{BROWSER}")))


@pytest.mark.parametrize("name", ["", "..", ".hidden", "a/b", "a b"])
def test_load_rejects_names_unsafe_as_directory(write_config, name):
    with pytest.raises(ConfigurationError, match=r"browsers\[0\]\.name"):
        Settings.load(
            write_config(hub(browsers=f'[[browsers]]\nname = "{name}"\nrunner = "mac"'))
        )


@pytest.mark.parametrize(
    "text",
    [
        "debug = true",
        hub(tenants="tenants = []"),
        hub(
            tenants='tenants = [{ name = "a", key = "owner-test-secret", quota_per_day = 0 }]'
        ),
        hub(
            tenants='tenants = [{ name = "a", key = "owner-test-secret", max_concurrency = 0 }]'
        ),
        hub(tenants='tenants = [{ name = "a/b", key = "owner-test-secret" }]'),
        hub("[lookup]\nattempts = 0"),
        hub("[lookup]\nmax_browsers = 0"),
        hub(browsers=""),
        hub("browsers = []", browsers=""),
        hub(runners=""),
        hub(runners="runners = []"),
        hub(browsers='[[browsers]]\nname = "a"'),
    ],
)
def test_load_rejects_invalid_values(write_config, text):
    with pytest.raises(ConfigurationError):
        Settings.load(write_config(text))


@pytest.mark.parametrize(
    ("text", "match"),
    [
        (
            hub(browsers='[[browsers]]\nname = "a"\nrunner = "nope"'),
            "unknown runner nope",
        ),
        (
            hub(
                runners="",
                browsers=f"[[runners]]\n{RUNNER_TABLE}\n[[runners]]\n{RUNNER_TABLE}\n{BROWSER}",
            ),
            "duplicate runner names: mac",
        ),
        (
            hub(runners='runners = [{ name = "mac", url = "http://x", token = " " }]'),
            "runner token must not be blank",
        ),
        (
            hub(
                runners='runners = [{ name = "a/b", url = "http://x", token = "runner-test-token" }]'
            ),
            "name",
        ),
    ],
)
def test_load_rejects_invalid_runner_config(write_config, text, match):
    with pytest.raises(ConfigurationError, match=match):
        Settings.load(write_config(text))


@pytest.mark.parametrize("key", ["", " "])
def test_load_rejects_blank_tenant_key(write_config, key):
    with pytest.raises(ConfigurationError, match="tenant key must not be blank"):
        Settings.load(
            write_config(hub(tenants=f'tenants = [{{ name = "a", key = "{key}" }}]'))
        )


def test_load_rejects_empty_portal_secret(write_config):
    with pytest.raises(ConfigurationError, match="portal secret must not be blank"):
        Settings.load(
            write_config(f'portal = {{ secret = "" }}\n{hub()}', portal=False)
        )


def test_portal_is_optional(write_config):
    assert Settings.load(write_config(hub(), portal=False)).portal is None


def test_load_invalid_toml_raises_configuration_error(write_config):
    with pytest.raises(ConfigurationError, match="Invalid TOML"):
        Settings.load(write_config("debug = "))


def test_secrets_are_redacted_in_repr(write_config):
    settings = Settings.load(
        write_config(
            hub(
                '[sentry]\ndsn = "https://key@sentry.example/1"',
                tenants='tenants = [{ name = "owner", key = "top-secret-tenant-key" }]',
                runners='runners = [{ name = "mac", url = "http://mac:8002", token = "top-secret-runner-token" }]',
            )
        )
    )
    text = repr(settings)
    for secret in (
        "top-secret-tenant-key",
        "top-secret-runner-token",
        "key@sentry",
    ):
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


##### Runners #####


@pytest.fixture
def write_runner_config(tmp_path):
    def write(text: str, token: str = "runner-test-token") -> Path:
        path = tmp_path / "runner.toml"
        path.write_text(f'[runner]\ntoken = "{token}"\n{text}')
        return path

    return write


def test_load_runner_config_uses_defaults(write_runner_config):
    settings = RunnerSettings.load(write_runner_config(""))
    assert (settings.runner.host, settings.runner.port) == ("127.0.0.1", 8002)
    assert settings.runner.token == "runner-test-token"
    assert (settings.lookup.timeout, settings.lookup.attempts) == (20, 1)
    assert [b.name for b in settings.browsers] == ["default"]


def test_runner_config_expands_user_in_profiles_dir(write_runner_config):
    settings = RunnerSettings.load(
        write_runner_config('[chrome]\nprofiles_dir = "~/profiles"')
    )
    assert settings.chrome.profiles_dir == Path.home() / "profiles"


def test_runner_secrets_are_redacted_in_repr(write_runner_config, monkeypatch):
    monkeypatch.setenv("TEST_PROXY_PASS", "proxy-pass")
    settings = RunnerSettings.load(
        write_runner_config(
            '[[browsers]]\nname = "a"\nproxy = { server = "socks5://a:1", '
            'username = "proxy-user", password = { env = "TEST_PROXY_PASS" } }'
        )
    )
    proxy = settings.browsers[0].proxy
    assert proxy is not None
    assert proxy.password == "proxy-pass"
    text = repr(settings)
    for secret in ("runner-test-token", "proxy-user", "proxy-pass"):
        assert secret not in text


@pytest.mark.parametrize(
    "text",
    [
        '[[tenants]]\nname = "a"\nkey = "owner-test-secret"',
        "[lookup]\ninterval = 5",
        "[usage]\nretention_days = 1",
        '[[browsers]]\nname = "a"\ngroup = "g"',
        '[[browsers]]\nname = "a"\nrunner = "r"',
    ],
)
def test_runner_config_rejects_hub_only_fields(write_runner_config, text):
    with pytest.raises(ConfigurationError, match="unknown field"):
        RunnerSettings.load(write_runner_config(text))


def test_runner_config_rejects_blank_token(write_runner_config):
    with pytest.raises(ConfigurationError, match="runner token must not be blank"):
        RunnerSettings.load(write_runner_config("", token=""))


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
    monkeypatch.setenv("API_KEY", "example-test-secret")
    monkeypatch.setenv("PORTAL_SECRET", "example")
    monkeypatch.setenv("RUNNER_TOKEN", "example-runner-token")
    Settings.load(EXAMPLE_CONFIG)


def test_example_runner_config_loads(monkeypatch):
    monkeypatch.setenv("RUNNER_TOKEN", "example-runner-token")
    RunnerSettings.load(EXAMPLE_RUNNER_CONFIG)


@pytest.mark.parametrize(
    ("path", "settings_type"),
    [(EXAMPLE_CONFIG, Settings), (EXAMPLE_RUNNER_CONFIG, RunnerSettings)],
)
def test_example_config_documents_every_settings_field(path, settings_type):
    # Commented-out `# key = value` lines count as documented
    text = re.sub(r"^# (\w+ = )", r"\1", path.read_text(), flags=re.MULTILINE)
    assert _field_paths(settings_type) <= _key_paths(tomllib.loads(text))
