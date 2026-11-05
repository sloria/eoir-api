from __future__ import annotations

from typing import Any

import pytest
from click.testing import CliRunner
from litestar import Litestar

from eoir_api.asgi import app_from_env
from eoir_api.cli import cli
from eoir_api.settings import CONFIG_ENV_VAR


@pytest.fixture
def uvicorn_calls(monkeypatch) -> list[tuple[Any, dict[str, Any]]]:
    calls: list[tuple[Any, dict[str, Any]]] = []
    monkeypatch.setattr(
        "eoir_api.cli.uvicorn.run", lambda app, **kwargs: calls.append((app, kwargs))
    )
    return calls


@pytest.fixture
def config_path(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        f'api_secret = "s"\n[server]\nport = 9001\n[chrome]\nprofiles_dir = "{tmp_path}"'
    )
    return path


def test_serve_uses_server_settings_and_disables_access_log(
    config_path, uvicorn_calls, monkeypatch
):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    result = CliRunner().invoke(cli, ["serve", "-c", str(config_path)])
    assert result.exit_code == 0, result.output
    [(_, kwargs)] = uvicorn_calls
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 9001
    assert kwargs["access_log"] is False


def test_serve_host_and_port_flags_override_config(
    config_path, uvicorn_calls, monkeypatch
):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)
    result = CliRunner().invoke(
        cli, ["serve", "-c", str(config_path), "--host", "0.0.0.0", "--port", "8123"]
    )
    assert result.exit_code == 0, result.output
    [(_, kwargs)] = uvicorn_calls
    assert kwargs["host"] == "0.0.0.0"
    assert kwargs["port"] == 8123


def test_serve_invalid_config_fails_before_starting_server(tmp_path, uvicorn_calls):
    path = tmp_path / "config.toml"
    path.write_text('api_secret = "s"\nbogus = 1')
    result = CliRunner().invoke(cli, ["serve", "-c", str(path)])
    assert result.exit_code != 0
    assert "unknown field" in result.output
    assert not uvicorn_calls


def test_app_from_env_builds_app_from_config(config_path, monkeypatch):
    monkeypatch.setenv(CONFIG_ENV_VAR, str(config_path))
    assert isinstance(app_from_env(), Litestar)
