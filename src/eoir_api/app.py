from __future__ import annotations

import importlib.metadata
import logging
import sys
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import anyio
import sentry_sdk
import structlog
from acis_browser import AcisBrowser, CaptchaError
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

from eoir_api.paths import redact_path
from eoir_api.routes import ROUTE_HANDLERS
from eoir_api.service import CaseService
from eoir_api.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

logger = structlog.get_logger()


##### Lifecycle hooks #####


def make_browser_lifespan(browser: AcisBrowser) -> Callable[[Litestar], Any]:
    check_interval = 60

    @asynccontextmanager
    async def browser_lifespan(_app: Litestar) -> AsyncGenerator[None]:
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

    return browser_lifespan


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
                    name="x-api-key",
                    security_scheme_in="header",
                )
            }
        ),
        security=[{"apiKey": []}],
    )


def _caused_by_captcha_error(hint: Any) -> bool:
    exc_info = (hint or {}).get("exc_info")
    exc = exc_info[1] if exc_info else None
    while exc is not None:
        if isinstance(exc, CaptchaError):
            return True
        exc = exc.__cause__
    return False


def _scrub_sentry_event(event: Any, hint: Any) -> Any:
    # Captcha errors are expected, so don't send them to Sentry
    if _caused_by_captcha_error(hint):
        return None

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
    browser = AcisBrowser(
        profile_dir=settings.chrome_profile_dir,
        lookup_timeout=settings.lookup_timeout,
        lookup_attempts=settings.lookup_attempts,
        idle_timeout=settings.browser_idle_timeout,
    )
    service = CaseService(browser, settings)

    async def provide_settings() -> Settings:
        return settings

    async def provide_service() -> CaseService:
        return service

    return Litestar(
        route_handlers=ROUTE_HANDLERS,
        state=State({"settings": settings}),
        openapi_config=create_openapi_config(),
        plugins=[structlog_plugin],
        lifespan=[make_browser_lifespan(browser)],
        dependencies={
            "settings": Provide(provide_settings),
            "service": Provide(provide_service),
        },
        debug=settings.debug,
    )


def _is_tty() -> bool:
    return bool(sys.stderr.isatty() or sys.stdout.isatty())
