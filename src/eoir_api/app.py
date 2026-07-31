from __future__ import annotations

import importlib.metadata
import logging
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import anyio
import sentry_sdk
import structlog
from litestar import Litestar
from litestar.datastructures import State
from litestar.di import Provide
from litestar.logging.config import (
    LoggingConfig,
    StructLoggingConfig,
    default_structlog_processors,
    default_structlog_standard_lib_processors,
)
from litestar.middleware.logging import LoggingMiddlewareConfig
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin
from litestar.openapi.spec import Components, SecurityScheme
from litestar.plugins.structlog import StructlogConfig, StructlogPlugin
from sentry_sdk.integrations.litestar import LitestarIntegration

from eoir_api.a_number import redact_path
from eoir_api.lib.acis import AcisBrowser
from eoir_api.routes import ROUTE_HANDLERS
from eoir_api.service import CaseService
from eoir_api.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

logger = structlog.get_logger()


##### Lifecycle hooks #####


@asynccontextmanager
async def manage_browser(app: Litestar) -> AsyncGenerator[None]:
    browser: AcisBrowser = app.state.browser
    check_interval = 60

    async def reap_idle_browser() -> None:
        while True:
            await anyio.sleep(check_interval)
            try:
                await browser.close_if_idle()
            except Exception:
                logger.exception("browser idle check failed")

    async with anyio.create_task_group() as tg:
        tg.start_soon(reap_idle_browser)
        try:
            yield
        finally:
            tg.cancel_scope.cancel()
            await browser.close()


##### App factory #####


def create_openapi_config() -> OpenAPIConfig:
    return OpenAPIConfig(
        title="EOIR Automated Case Information (ACIS) API",
        version=importlib.metadata.version("eoir-api"),
        use_handler_docstrings=True,
        render_plugins=[
            ScalarRenderPlugin(
                options={
                    "agent": {"disabled": True},
                    "showToolbar": "never",
                    "mcp": {"disabled": True},
                    "hideClientButton": True,
                }
            )
        ],
        components=Components(
            security_schemes={
                "apiKey": SecurityScheme(
                    type="apiKey",
                    name="x-key",
                    security_scheme_in="header",
                )
            }
        ),
        security=[{"apiKey": []}],
    )


def _scrub_sentry_event(event: Any, _hint: Any) -> Any:
    # redact A-Numbers from URL and transaction names
    request = event.get("request")
    if request and request.get("url"):
        request["url"] = redact_path(request["url"])
    if event.get("transaction"):
        event["transaction"] = redact_path(event["transaction"])
    return event


def _redact_path_processor(_logger: Any, _method: Any, event_dict: Any) -> Any:
    path = event_dict.get("path")
    if isinstance(path, str):
        event_dict["path"] = redact_path(path)
    return event_dict


def create_app(settings: Settings) -> Litestar:
    if settings.sentry_dsn:
        sentry_sdk.init(
            settings.sentry_dsn,
            include_local_variables=False,
            send_default_pii=False,
            before_send=_scrub_sentry_event,
            environment=settings.sentry_env,
            integrations=[LitestarIntegration()],
        )

    # Suppress access logs to avoid logging A-Numbers
    logging.getLogger("uvicorn.access").addFilter(lambda _record: False)
    structlog_plugin = StructlogPlugin(
        config=StructlogConfig(
            structlog_logging_config=StructLoggingConfig(
                processors=[
                    _redact_path_processor,
                    *default_structlog_processors(as_json=not _is_tty()),
                ],
                standard_lib_logging_config=LoggingConfig(
                    formatters={
                        "standard": {
                            "()": structlog.stdlib.ProcessorFormatter,
                            "processors": [
                                structlog.stdlib.add_logger_name,
                                *default_structlog_standard_lib_processors(
                                    as_json=not _is_tty()
                                ),
                            ],
                        }
                    }
                ),
            ),
            middleware_logging_config=LoggingMiddlewareConfig(
                request_log_fields=["path", "method"],
                response_log_fields=["status_code"],
            ),
        )
    )

    # XXX: Single browser and service instance to reuse
    # the browser session and TTLCache across requests
    browser = AcisBrowser(settings)
    service = CaseService(browser, settings)

    async def provide_settings() -> Settings:
        return settings

    async def provide_service() -> CaseService:
        return service

    return Litestar(
        route_handlers=ROUTE_HANDLERS,
        state=State({"settings": settings, "browser": browser, "service": service}),
        openapi_config=create_openapi_config(),
        plugins=[structlog_plugin],
        lifespan=[manage_browser],
        dependencies={
            "settings": Provide(provide_settings),
            "service": Provide(provide_service),
        },
        debug=settings.debug,
    )


def _is_tty() -> bool:
    return bool(sys.stderr.isatty() or sys.stdout.isatty())
