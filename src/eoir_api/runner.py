"""Runner app that runs browsers and performs lookups for a hub over HTTP."""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING, Any

import structlog
from acis_core.exceptions import AcisError, BrowserLostError, CaptchaError
from litestar import Litestar, Response, get, post
from litestar.connection import ASGIConnection
from litestar.datastructures import State
from litestar.exceptions import NotAuthorizedException
from litestar.handlers import BaseRouteHandler
from litestar.params import JSONBody
from litestar.status_codes import (
    HTTP_404_NOT_FOUND,
    HTTP_502_BAD_GATEWAY,
    HTTP_503_SERVICE_UNAVAILABLE,
)

from eoir_api.browsers import create_browsers, make_browser_lifespan
from eoir_api.observability import create_structlog_plugin, init_sentry
from eoir_api.remote import ErrorCode, LookupRequest, RunnerError
from eoir_api.request_id import RequestIdMiddleware

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from litestar.plugins import PluginProtocol

    from eoir_api.service import SupportsLookup
    from eoir_api.settings import RunnerSettings

logger = structlog.get_logger()


def error_response(
    status: int,
    error: ErrorCode,
    message: str,
    *,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Response[RunnerError]:
    return Response(
        RunnerError(error, reason=reason, payload=payload, message=message),
        status_code=status,
    )


def require_token(connection: ASGIConnection, _: BaseRouteHandler) -> None:
    scheme, _sep, token = connection.headers.get("authorization", "").partition(" ")
    expected: str = connection.app.state.token
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        token.encode(), expected.encode()
    ):
        logger.warning("runner.unauthorized")
        raise NotAuthorizedException


@get("/healthz", sync_to_thread=False)
def health(state: State) -> dict[str, Any]:
    return {"status": "ok", "browsers": list(state.browsers)}


@post("/lookup", status_code=200, guards=[require_token])
async def lookup(data: JSONBody[LookupRequest], state: State) -> Response[Any]:
    browser: SupportsLookup | None = state.browsers.get(data.browser)
    if browser is None:
        logger.warning("runner.unknown_browser", browser=data.browser)
        return error_response(
            HTTP_404_NOT_FOUND, "unknown_browser", f"No browser {data.browser}"
        )
    with structlog.contextvars.bound_contextvars(browser=data.browser):
        try:
            payload = await browser.lookup(data.a_number, data.nat_code, data.nat_name)
        except CaptchaError as exc:
            return error_response(
                HTTP_503_SERVICE_UNAVAILABLE,
                "captcha",
                str(exc),
                reason=exc.reason,
                payload=exc.payload,
            )
        except BrowserLostError as exc:
            return error_response(
                HTTP_503_SERVICE_UNAVAILABLE, "browser_lost", str(exc)
            )
        except AcisError as exc:
            logger.warning("runner.upstream_error", error=str(exc))
            return error_response(
                HTTP_502_BAD_GATEWAY, "upstream", str(exc), payload=exc.payload
            )
        except Exception:
            logger.exception("runner.lookup_failed")
            raise
    return Response(payload)


def build_runner_app(
    token: str,
    browsers: Mapping[str, SupportsLookup],
    *,
    plugins: Iterable[PluginProtocol] = (),
    lifespan: Iterable[Callable[[Litestar], Any]] = (),
) -> Litestar:
    return Litestar(
        route_handlers=[health, lookup],
        middleware=[RequestIdMiddleware(trust_header=True)],
        plugins=list(plugins),
        lifespan=list(lifespan),
        state=State({"token": token, "browsers": browsers}),
        openapi_config=None,
    )


def create_runner_app(settings: RunnerSettings) -> Litestar:
    init_sentry(settings.sentry)
    browsers = create_browsers(settings.browsers, settings.chrome, settings.lookup)
    return build_runner_app(
        settings.runner.token,
        browsers,
        plugins=[create_structlog_plugin()],
        lifespan=[make_browser_lifespan(browsers, settings.chrome.idle_timeout)],
    )
