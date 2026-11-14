from __future__ import annotations

import os
from pathlib import Path

import click
import uvicorn

from eoir_api.exceptions import ConfigurationError
from eoir_api.settings import (
    CONFIG_ENV_VAR,
    DEBUG_ENV_VAR,
    RunnerSettings,
    Settings,
    find_config,
)


@click.group()
def cli() -> None:
    """eoir-api CLI."""


def config_option(filename: str):
    return click.option(
        "-c",
        "--config",
        "config_path",
        type=click.Path(dir_okay=False, path_type=Path),
        help=f"Config file. Default: ${CONFIG_ENV_VAR}, then {filename} in the user config dir.",
    )


@cli.command()
@config_option("hub.toml")
@click.option("--host", help="Override [server] host.")
@click.option("--port", type=int, help="Override [server] port.")
@click.option("--reload", is_flag=True, help="Reload on code changes.")
@click.option("--debug", is_flag=True, help="Litestar debug mode; overrides config.")
def hub(
    config_path: Path | None,
    host: str | None,
    port: int | None,
    *,
    reload: bool,
    debug: bool,
) -> None:
    """Start the hub server."""
    try:
        path = find_config(config_path)
        settings = Settings.load(path)
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    # The factory reads these in the subprocess started by --reload
    os.environ[CONFIG_ENV_VAR] = str(path.resolve())
    if debug:
        os.environ[DEBUG_ENV_VAR] = "1"
    uvicorn.run(
        "eoir_api.asgi:app_from_env",
        factory=True,
        reload=reload,
        host=host or settings.server.host,
        port=port or settings.server.port,
        access_log=False,
    )


@cli.command()
@config_option("runner.toml")
@click.option("--host", help="Override [runner] host.")
@click.option("--port", type=int, help="Override [runner] port.")
def runner(config_path: Path | None, host: str | None, port: int | None) -> None:
    """Start a runner server."""
    from eoir_api.runner import create_runner_app  # noqa: PLC0415

    try:
        settings = RunnerSettings.load(find_config(config_path, "runner.toml"))
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc
    uvicorn.run(
        create_runner_app(settings),
        host=host or settings.runner.host,
        port=port or settings.runner.port,
        access_log=False,
    )
