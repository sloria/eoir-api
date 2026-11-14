from __future__ import annotations

import subprocess
import sys
from typing import Any

import pytest
from click.testing import CliRunner
from litestar import Litestar

from eoir_api.asgi import app_from_env
from eoir_api.cli import cli
from eoir_api.settings import CONFIG_ENV_VAR, DEBUG_ENV_VAR


@pytest.fixture
def uvicorn_calls(monkeypatch) -> list[tuple[Any, dict[str, Any]]]:
    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(
        "eoir_api.cli.uvicorn.run", lambda app, **kwargs: calls.append((app, kwargs))
    )
    return calls


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "hub.toml"
    path.write_text(
        'portal = { secret = "p" }\ntenants = [{ name = "owner", key = "owner-test-secret" }]\n'
        f'[server]\nport = 9001\n[usage]\ndb_path = "{tmp_path / "usage.sqlite"}"\n'
        '[[runners]]\nname = "mac"\nurl = "http://mac:8002"\ntoken = "runner-test-token"\n'
        '[[browsers]]\nname = "a"\nrunner = "mac"'
    )
    return path


def test_hub_uses_server_settings_and_disables_access_log(
    config_path, uvicorn_calls, monkeypatch
):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    result = CliRunner().invoke(cli, ["hub", "-c", str(config_path)])
    assert result.exit_code == 0, result.output
    [(_, kwargs)] = uvicorn_calls
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 9001
    assert kwargs["access_log"] is False


def test_hub_host_and_port_flags_override_config(
    config_path, uvicorn_calls, monkeypatch
):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    result = CliRunner().invoke(
        cli, ["hub", "-c", str(config_path), "--host", "0.0.0.0", "--port", "8123"]
    )
    assert result.exit_code == 0, result.output
    [(_, kwargs)] = uvicorn_calls
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8123


def test_hub_invalid_config_fails_before_starting_server(tmp_path, uvicorn_calls):
    path = tmp_path / "hub.toml"
    path.write_text(
        'tenants = [{ name = "owner", key = "owner-test-secret" }]\nbogus = 1'
    )
    result = CliRunner().invoke(cli, ["hub", "-c", str(path)])
    assert result.exit_code != 0
    assert "unknown field" in result.output
    assert not uvicorn_calls


def test_debug_flag_enables_debug_in_factory(config_path, uvicorn_calls, monkeypatch):
    monkeypatch.delenv(DEBUG_ENV_VAR, raising=False)
    CliRunner().invoke(cli, ["hub", "-c", str(config_path)])
    assert not app_from_env().debug
    CliRunner().invoke(cli, ["hub", "-c", str(config_path), "--debug"])
    assert app_from_env().debug


def test_runner_uses_runner_settings(tmp_path, uvicorn_calls, monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    path = tmp_path / "runner.toml"
    path.write_text(
        '[runner]\ntoken = "runner-test-token"\nport = 9002\n'
        f'[chrome]\nprofiles_dir = "{tmp_path}"'
    )
    result = CliRunner().invoke(cli, ["runner", "-c", str(path), "--host", "0.0.0.0"])
    assert result.exit_code == 0, result.output
    [(app, kwargs)] = uvicorn_calls
    assert isinstance(app, Litestar)
    assert (kwargs["host"], kwargs["port"]) == ("0.0.0.0", 9002)


def test_hub_starts_without_patchright(config_path):
    script = (
        "import sys\n"
        "sys.modules['patchright'] = sys.modules['acis_browser'] = None\n"
        "from eoir_api.asgi import app_from_env\n"
        "app_from_env()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={CONFIG_ENV_VAR: str(config_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
