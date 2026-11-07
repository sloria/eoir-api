from __future__ import annotations

import importlib.metadata
import logging
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import anyio
import msgspec
import sentry_sdk
import structlog
from acis_browser import AcisBrowser, CaptchaError
from litestar import Litestar, Request
from litestar.config.csrf import CSRFConfig
from litestar.datastructures import State
from litestar.di import Provide
from litestar.logging.config import (
    LoggingConfig,
    StructLoggingConfig,
    default_structlog_processors,
    default_structlog_standard_lib_processors,
)
from litestar.middleware.logging import LoggingMiddlewareConfig
from litestar.middleware.rate_limit import RateLimitConfig
from litestar.middleware.session.client_side import CookieBackendConfig
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin
from litestar.openapi.spec import Components, SecurityScheme
from litestar.plugins.jinja import JinjaTemplateEngine
from litestar.plugins.structlog import StructlogConfig, StructlogPlugin
from litestar.template import TemplateConfig
from sentry_sdk.integrations.litestar import LitestarIntegration
from sqlspec import SQLSpec
from sqlspec.adapters.aiosqlite import AiosqliteConfig
from sqlspec.extensions.litestar import SQLSpecPlugin

from eoir_api.auth import SESSION_MAX_AGE, TenantAuthMiddleware
from eoir_api.exceptions import BrowserUnavailableError
from eoir_api.portal import PortalController, register_filters
from eoir_api.routes import ROUTE_HANDLERS
from eoir_api.service import CaseService
from eoir_api.settings import Proxy, Settings, Tenant
from eoir_api.usage import TenantUsage, UsageService, create_config

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Iterable, Mapping

    from litestar.plugins import PluginProtocol
    from patchright.async_api import ProxySettings

logger = structlog.get_logger()

HERE = Path(__file__).parent


##### Lifecycle hooks #####


def make_browser_lifespan(
    browsers: Mapping[str, AcisBrowser], idle_timeout: float
) -> Callable[[Litestar], Any]:
    check_interval = 60

    async def close_browser(name: str, browser: AcisBrowser) -> None:
        try:
            await browser.close()
        except Exception:
            logger.exception("browser close failed", browser=name)

    @asynccontextmanager
    async def browser_lifespan(_app: Litestar) -> AsyncGenerator[None]:
        async def reap_idle_browsers() -> None:
            while True:
                await anyio.sleep(check_interval)
                for name, browser in browsers.items():
                    idle = time.monotonic() - browser.last_used
                    if not browser.is_running or idle < idle_timeout:
                        continue
                    logger.info(
                        "browser idle, closing", browser=name, idle_seconds=round(idle)
                    )
                    await close_browser(name, browser)

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(reap_idle_browsers)
                try:
                    yield
                finally:
                    tg.cancel_scope.cancel()
        finally:
            async with anyio.create_task_group() as tg:
                for name, browser in browsers.items():
                    tg.start_soon(close_browser, name, browser)

    return browser_lifespan


def make_usage_lifespan(
    usage: UsageService, config: AiosqliteConfig
) -> Callable[[Litestar], Any]:
    prune_interval = 24 * 60 * 60

    @asynccontextmanager
    async def usage_lifespan(_app: Litestar) -> AsyncGenerator[None]:
        async def prune_daily() -> None:
            while True:
                try:
                    logger.info("usage.pruned", deleted=await usage.prune())
                except Exception:
                    logger.exception("usage prune failed")
                await anyio.sleep(prune_interval)

        await config.migrate_up(use_logger=True, summary_only=True)
        async with anyio.create_task_group() as tg:
            tg.start_soon(prune_daily)
            yield
            tg.cancel_scope.cancel()

    return usage_lifespan


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


def is_expected_error(hint: Any) -> bool:
    exc_info = (hint or {}).get("exc_info")
    exc = exc_info[1] if exc_info else None
    while exc is not None:
        if isinstance(exc, (CaptchaError, BrowserUnavailableError)):
            return True
        exc = exc.__cause__
    return False


def scrub_sentry_event(event: Any, hint: Any) -> Any:
    # Captcha errors and cooldowns are expected, so don't send them to Sentry
    if is_expected_error(hint):
        return None
    request = event.get("request")
    if request:
        request.pop("data", None)
    return event


def proxy_settings(proxy: Proxy | None) -> ProxySettings | None:
    if proxy is None:
        return None
    fields = msgspec.structs.asdict(proxy)
    return cast("ProxySettings", {k: v for k, v in fields.items() if v is not None})


def create_app(settings: Settings) -> Litestar:
    if settings.sentry.dsn:
        sentry_sdk.init(
            settings.sentry.dsn,
            include_local_variables=False,
            send_default_pii=False,
            before_send=scrub_sentry_event,
            environment=settings.sentry.environment or None,
            integrations=[LitestarIntegration()],
        )

    logging.getLogger("uvicorn.access").addFilter(lambda _record: False)
    structlog_plugin = StructlogPlugin(
        config=StructlogConfig(
            structlog_logging_config=StructLoggingConfig(
                processors=default_structlog_processors(as_json=not is_tty()),
                standard_lib_logging_config=LoggingConfig(
                    formatters={
                        "standard": {
                            "()": structlog.stdlib.ProcessorFormatter,
                            "processors": [
                                structlog.stdlib.add_logger_name,
                                *default_structlog_standard_lib_processors(
                                    as_json=not is_tty()
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

    browsers = {
        b.name: AcisBrowser(
            profile_dir=settings.chrome.profiles_dir / b.name,
            proxy=proxy_settings(b.proxy),
            lookup_timeout=settings.lookup.timeout,
            lookup_attempts=settings.lookup.attempts,
        )
        for b in settings.browsers
    }
    service = CaseService(browsers, settings)
    plugins: list[PluginProtocol] = [structlog_plugin]
    lifespan = [make_browser_lifespan(browsers, settings.chrome.idle_timeout)]
    return build_app(settings, service, plugins=plugins, lifespan=lifespan)


def build_app(
    settings: Settings,
    service: CaseService,
    *,
    plugins: Iterable[PluginProtocol] = (),
    lifespan: Iterable[Callable[[Litestar], Any]] = (),
) -> Litestar:
    """Wire routes, auth and dependencies."""

    spec = SQLSpec()
    usage_config = spec.add_config(create_config(settings.usage.db_path))
    usage_service = UsageService(usage_config, settings.usage.retention_days)

    async def provide_service() -> CaseService:
        return service

    async def provide_tenants() -> list[Tenant]:
        return settings.tenants

    async def provide_usage(request: Request[Tenant, Any, State]) -> TenantUsage:
        return TenantUsage(usage_service, request.user)

    route_handlers: list[Any] = [*ROUTE_HANDLERS]
    middleware: list[Any] = []
    template_config = csrf = None
    if settings.portal is not None:
        api_paths = ["^/cases", "^/healthz", "^/schema"]
        session = CookieBackendConfig(
            secret=settings.portal.session_key,
            key="session",
            httponly=True,
            samesite="lax",
            secure=not settings.debug,
            max_age=SESSION_MAX_AGE,
            exclude=api_paths,
        )
        csrf = CSRFConfig(
            secret=settings.portal.secret,
            cookie_httponly=True,
            cookie_secure=not settings.debug,
            exclude=api_paths,
        )
        login_limit = RateLimitConfig(
            rate_limit=("minute", 10),
            check_throttle_handler=lambda request: (
                request.method == "POST" and request.url.path == "/portal/login"
            ),
            set_rate_limit_headers=False,
        )
        route_handlers.append(PortalController)
        # Session must go before TenantAuthMiddleware
        middleware += [login_limit.middleware, session.middleware]
        template_config = TemplateConfig(
            directory=HERE / "templates",
            engine=JinjaTemplateEngine,
            engine_callback=register_filters,
        )

    return Litestar(
        route_handlers=route_handlers,
        template_config=template_config,
        openapi_config=create_openapi_config(),
        middleware=[*middleware, TenantAuthMiddleware(settings.tenants)],
        csrf_config=csrf,
        plugins=[SQLSpecPlugin(sqlspec=spec), *plugins],
        lifespan=[
            make_usage_lifespan(usage_service, usage_config),
            *lifespan,
        ],
        dependencies={
            "service": Provide(provide_service),
            "tenants": Provide(provide_tenants),
            "usage": Provide(provide_usage),
        },
        debug=settings.debug,
    )


def is_tty() -> bool:
    return bool(sys.stderr.isatty() or sys.stdout.isatty())
