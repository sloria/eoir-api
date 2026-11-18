from __future__ import annotations

import importlib.metadata
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

import anyio
import structlog
from litestar import Litestar, Request
from litestar.config.csrf import CSRFConfig
from litestar.datastructures import State
from litestar.di import Provide
from litestar.middleware.rate_limit import RateLimitConfig
from litestar.middleware.session.client_side import CookieBackendConfig
from litestar.openapi import OpenAPIConfig
from litestar.openapi.plugins import ScalarRenderPlugin
from litestar.openapi.spec import Components, SecurityScheme
from litestar.plugins.jinja import JinjaTemplateEngine
from litestar.static_files import create_static_files_router
from litestar.template import TemplateConfig
from sqlspec import SQLSpec
from sqlspec.adapters.aiosqlite import AiosqliteConfig
from sqlspec.extensions.litestar import SQLSpecPlugin

from eoir_api.auth import SESSION_MAX_AGE, TenantAuthMiddleware
from eoir_api.observability import create_structlog_plugin, init_sentry
from eoir_api.portal import PortalController, register_filters
from eoir_api.remote import RemoteBrowser, RunnerClient, make_runner_lifespan
from eoir_api.request_id import RequestIdMiddleware
from eoir_api.routes import ROUTE_HANDLERS
from eoir_api.service import CaseService
from eoir_api.settings import Settings, Tenant
from eoir_api.usage import TenantUsage, UsageService, create_config

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Iterable

    from litestar.plugins import PluginProtocol

logger = structlog.get_logger()

HERE = Path(__file__).parent
SCHEMA_ASSETS_PATH = "/schema/assets"


##### Lifecycle hooks #####


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


API_DESCRIPTION = """\
Look up cases in EOIR's [Automated Case Information System (ACIS)](https://acis.eoir.justice.gov/).

Authenticate by sending your API key in the `x-api-key` header.

## Retrying

Lookups run against a slow upstream. `429` and `503` responses are expected in normal operation, so clients must handle them.

**Always honor `Retry-After`.** Wait at least that long before sending the request again.

A `429` usually means too many lookups are pending, and the wait is typically seconds. If `code` is `quota_exceeded`, your daily quota is used up, and the wait can be hours. A `503` means lookups are temporarily unavailable, and the wait can be seconds to minutes.

## Quota

Your key has a quota over a rolling 24-hour window. Check your usage in the [API Portal](/portal).

## Caching

Successful lookups are cached for 3 hours. Check `cached` and `retrieved_at` in the response. Set `refresh` to `true` to force a fresh lookup, which counts against quota.
"""


def create_openapi_config() -> OpenAPIConfig:
    return OpenAPIConfig(
        title="EOIR Automated Case Information (ACIS) API",
        description=API_DESCRIPTION,
        version=importlib.metadata.version("eoir-api"),
        use_handler_docstrings=True,
        render_plugins=[
            ScalarRenderPlugin(
                css_url=f"{SCHEMA_ASSETS_PATH}/scalar.css",
                options={
                    "agent": {"disabled": True},
                    "showToolbar": "never",
                    "mcp": {"disabled": True},
                    "hideClientButton": True,
                    "withDefaultFonts": False,
                },
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


def create_app(settings: Settings) -> Litestar:
    init_sentry(settings.sentry)
    runners = {
        r.name: RunnerClient.create(r, settings.lookup) for r in settings.runners
    }
    browsers = {
        b.name: RemoteBrowser(runners[b.runner], b.name) for b in settings.browsers
    }
    return build_app(
        settings,
        CaseService(browsers, settings),
        plugins=[create_structlog_plugin()],
        lifespan=[make_runner_lifespan(runners.values())],
    )


def client_ip(header: str | None) -> Callable[[Request], str]:
    def identify(request: Request) -> str:
        if header and (ip := request.headers.get(header)):
            return ip
        return request.client.host if request.client else "anonymous"

    return identify


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

    route_handlers: list[Any] = [
        *ROUTE_HANDLERS,
        create_static_files_router(
            path=SCHEMA_ASSETS_PATH, directories=[HERE / "static"]
        ),
    ]
    middleware: list[Any] = []
    template_config = csrf = None
    if settings.portal is not None:
        api_paths = ["^/$", "^/cases", "^/healthz", "^/schema"]
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
            identifier_for_request=client_ip(settings.server.client_ip_header),
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
        middleware=[
            RequestIdMiddleware(),
            *middleware,
            TenantAuthMiddleware(settings.tenants),
        ],
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
