from __future__ import annotations

import datetime as dt
import time
from typing import Annotated, Any
from urllib.parse import urlencode

import msgspec
from litestar import Controller, Request, get, post
from litestar.datastructures import State
from litestar.di import NamedDependency
from litestar.exceptions import NotAuthorizedException, ValidationException
from litestar.params import QueryParameter, URLEncodedBody
from litestar.plugins.jinja import JinjaTemplateEngine
from litestar.response import Redirect, Template
from litestar.status_codes import HTTP_303_SEE_OTHER, HTTP_401_UNAUTHORIZED

from eoir_api.auth import SESSION_MAX_AGE, resolve_tenant
from eoir_api.settings import Tenant
from eoir_api.usage import LookupOutcome, TenantUsage

FAILED: set[LookupOutcome] = {"unavailable", "captcha", "upstream_error"}
LABELS: dict[LookupOutcome, str] = {
    "ok": "Found",
    "not_found": "Not found",
    "invalid_nationality": "Invalid nationality",
    "unavailable": "Case unavailable",
    "captcha": "Captcha failed",
    "upstream_error": "Upstream error",
}
PAGE_SIZE = 50


class Login(msgspec.Struct):
    key: str


def status_class(outcome: LookupOutcome) -> str:
    if outcome == "ok":
        return "ok"
    return "err" if outcome in FAILED else "warn"


def duration(ms: int | None) -> str:
    if ms is None:
        return ""
    return f"{ms}ms" if ms < 1000 else f"{ms / 1000:.1f}s"


def register_filters(engine: JinjaTemplateEngine) -> None:
    engine.engine.filters.update(
        status_class=status_class, outcome_label=LABELS.__getitem__, duration=duration
    )


def login_redirect(request: Request[Any, Any, State], exc: Exception) -> Redirect:
    return Redirect("/portal/login")


def portal_redirect(request: Request[Any, Any, State], exc: Exception) -> Redirect:
    return Redirect("/portal")


def midnight(day: dt.date | None, days: int = 0) -> dt.datetime | None:
    if day is None:
        return None
    return dt.datetime.combine(day + dt.timedelta(days=days), dt.time(), tzinfo=dt.UTC)


class PortalController(Controller):
    path = "/portal"
    include_in_schema = False
    opt = {"session_auth": True}
    exception_handlers = {
        NotAuthorizedException: login_redirect,
        ValidationException: portal_redirect,
    }

    @get()
    async def index(
        self,
        request: Request[Tenant, Any, State],
        usage: NamedDependency[TenantUsage],
        before: Annotated[dt.datetime | None, QueryParameter()] = None,
        from_: Annotated[dt.date | None, QueryParameter(name="from")] = None,
        to: Annotated[dt.date | None, QueryParameter()] = None,
    ) -> Template:
        items = await usage.lookups(
            limit=PAGE_SIZE + 1,
            before=before or midnight(to, days=1),
            after=midnight(from_),
        )
        next_before = items[PAGE_SIZE - 1].ts if len(items) > PAGE_SIZE else None
        range_ = {k: v for k, v in (("from", from_), ("to", to)) if v}

        def page_url(**params: str) -> str:
            return f"/portal?{urlencode({**range_, **params})}"

        return Template(
            "portal.html",
            context={
                "tenant": request.user,
                "usage": await usage.summary(),
                "items": items[:PAGE_SIZE],
                "next_before": next_before,
                "before": before,
                "from": from_,
                "to": to,
                "page_url": page_url,
            },
        )

    @get("/login", exclude_from_auth=True)
    async def login_form(self) -> Template:
        return Template("login.html")

    @post("/login", exclude_from_auth=True)
    async def login(
        self,
        request: Request[Any, Any, State],
        data: URLEncodedBody[Login],
        tenants: NamedDependency[list[Tenant]],
    ) -> Template | Redirect:
        tenant = resolve_tenant(tenants, data.key)
        if tenant is None:
            return Template(
                "login.html",
                context={"error": "Unknown key. Check it and try again."},
                status_code=HTTP_401_UNAUTHORIZED,
            )
        request.set_session(
            {"tenant": tenant.name, "exp": int(time.time()) + SESSION_MAX_AGE}
        )
        return Redirect("/portal", status_code=HTTP_303_SEE_OTHER)

    @post("/logout")
    async def logout(self, request: Request[Tenant, Any, State]) -> Redirect:
        request.clear_session()
        return Redirect("/portal/login", status_code=HTTP_303_SEE_OTHER)
