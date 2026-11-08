from __future__ import annotations

import hmac
import time
from typing import TYPE_CHECKING

import structlog
from litestar.connection import ASGIConnection
from litestar.exceptions import NotAuthorizedException
from litestar.middleware import ASGIMiddleware

if TYPE_CHECKING:
    from collections.abc import Iterable

    from litestar.types import ASGIApp, Receive, Scope, Send

    from eoir_api.settings import Tenant

SESSION_MAX_AGE = 12 * 60 * 60  # seconds

logger = structlog.get_logger()


def resolve_tenant(tenants: Iterable[Tenant], key: str) -> Tenant | None:
    given = key.encode()
    match = None
    for tenant in tenants:
        if hmac.compare_digest(given, tenant.key.encode()):
            match = tenant
    return match


class TenantAuthMiddleware(ASGIMiddleware):
    """Authenticate the tenant for ``x-api-key``, setting``request.user``."""

    exclude_opt_key = "exclude_from_auth"
    should_bypass_for_scope = staticmethod(
        lambda scope: scope["path"].startswith(("/healthz", "/schema"))
    )

    def __init__(self, tenants: Iterable[Tenant]) -> None:
        self.tenants = list(tenants)
        self.by_name = {t.name: t for t in self.tenants}

    async def handle(
        self, scope: Scope, receive: Receive, send: Send, next_app: ASGIApp
    ) -> None:
        connection = ASGIConnection(scope)
        key = connection.headers.get("x-api-key")
        tenant, auth = None, "header"
        if key is not None:
            tenant = resolve_tenant(self.tenants, key)
        elif scope["route_handler"].opt.get("session_auth"):
            session = connection.session
            if session.get("exp", 0) > time.time():
                tenant = self.by_name.get(session.get("tenant"))
            auth = "cookie"
        if tenant is None:
            logger.warning(
                "auth.rejected",
                path=scope["path"],
                method=scope.get("method"),
                auth=auth,
            )
            raise NotAuthorizedException("Invalid or missing x-api-key header")
        scope["user"] = tenant
        scope["auth"] = auth
        with structlog.contextvars.bound_contextvars(tenant=tenant.name):
            await next_app(scope, receive, send)
