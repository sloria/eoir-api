from __future__ import annotations

import os
from pathlib import Path

import click
import uvicorn

from eoir_api.exceptions import ConfigurationError
from eoir_api.settings import CONFIG_ENV_VAR, Settings, find_config


@click.group()
def cli() -> None:
    """eoir-api CLI."""


@cli.command()
@click.option(
    "-c",
    "--config",
    "config_path",
    type=click.Path(dir_okay=False, path_type=Path),
    help=f"Config file. Default: ${CONFIG_ENV_VAR}, then the user config dir.",
)
@click.option("--host", help="Override [server] host.")
@click.option("--port", type=int, help="Override [server] port.")
@click.option("--reload", is_flag=True, help="Reload on code changes.")
def serve(
    config_path: Path | None, host: str | None, port: int | None, *, reload: bool
) -> None:
    """Run the API server."""
    try:
        path = find_config(config_path)
        settings = Settings.load(path)
    except ConfigurationError as exc:
        raise click.ClickException(str(exc)) from exc

    # Needed for the factory to load the config in the subprocess with --reload
    os.environ[CONFIG_ENV_VAR] = str(path.resolve())
    uvicorn.run(
        "eoir_api.asgi:app_from_env",
        factory=True,
        reload=reload,
        host=host or settings.server.host,
        port=port or settings.server.port,
        access_log=False,
    )
