from __future__ import annotations

import datetime as dt
import time
from typing import Annotated, Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import msgspec
from litestar import Controller, Request, get, post
from litestar.datastructures import State
from litestar.di import NamedDependency
from litestar.exceptions import NotAuthorizedException, ValidationException
from litestar.params import CookieParameter, QueryParameter, URLEncodedBody
from litestar.plugins.jinja import JinjaTemplateEngine
from litestar.response import Redirect, Template
from litestar.status_codes import HTTP_303_SEE_OTHER, HTTP_401_UNAUTHORIZED

from eoir_api.auth import SESSION_MAX_AGE, resolve_tenant
from eoir_api.settings import Tenant
from eoir_api.usage import UNCOUNTED, LookupOutcome, TenantUsage

FAILED: set[LookupOutcome] = UNCOUNTED | {"unavailable"}
LABELS: dict[LookupOutcome, str] = {
    "ok": "OK",
    "not_found": "Not found",
    "invalid_nationality": "Invalid nationality",
    "unavailable": "Case unavailable",
    "captcha": "Temporarily unavailable",
    "upstream_error": "Upstream error",
    "quota_exceeded": "Quota exceeded",
    "concurrency_limited": "Too many concurrent lookups",
    "queue_full": "Too many pending lookups",
}
OUTCOME_FILTERS: dict[str, tuple[str, set[LookupOutcome]]] = {
    "failed": ("Failed", FAILED),
    **{outcome: (label, {outcome}) for outcome, label in LABELS.items()},
}
PAGE_SIZE = 10


class Login(msgspec.Struct):
    key: str


def failed(value: LookupOutcome) -> bool:
    return value in FAILED


def duration(ms: int | None) -> str:
    if ms is None:
        return ""
    return f"{ms}ms" if ms < 1000 else f"{ms / 1000:.1f}s"


def register_filters(engine: JinjaTemplateEngine) -> None:
    engine.engine.filters.update(
        outcome_label=LABELS.__getitem__, duration=duration, number="{:,}".format
    )
    engine.engine.tests["failed"] = failed


def login_redirect(request: Request[Any, Any, State], exc: Exception) -> Redirect:
    return Redirect("/portal/login")


def portal_redirect(request: Request[Any, Any, State], exc: Exception) -> Redirect:
    return Redirect("/portal")


def zone(name: str | None) -> dt.tzinfo:
    """Resolve an IANA zone name, falling back to UTC."""
    try:
        return ZoneInfo(name) if name else dt.UTC
    except ZoneInfoNotFoundError, ValueError:
        return dt.UTC


def parse_day(value: str | None) -> dt.date | None:
    """Parse an ISO date, treating a blank form field as no date."""
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationException(f"Invalid date: {value}") from exc


def parse_outcome(value: str | None) -> str | None:
    """Validate an outcome filter, treating a blank form field as no filter."""
    if not value:
        return None
    if value not in OUTCOME_FILTERS:
        raise ValidationException(f"Invalid outcome: {value}")
    return value


def midnight(day: dt.date | None, tz: dt.tzinfo, days: int = 0) -> dt.datetime | None:
    if day is None:
        return None
    return dt.datetime.combine(day + dt.timedelta(days=days), dt.time(), tzinfo=tz)


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
        *,
        before: Annotated[dt.datetime | None, QueryParameter()] = None,
        after: Annotated[dt.datetime | None, QueryParameter()] = None,
        from_param: Annotated[str | None, QueryParameter(name="from")] = None,
        to_param: Annotated[str | None, QueryParameter(name="to")] = None,
        status_param: Annotated[str | None, QueryParameter(name="status")] = None,
        tz: Annotated[str | None, CookieParameter(name="tz")] = None,
    ) -> Template:
        from_, to = parse_day(from_param), parse_day(to_param)
        outcome = parse_outcome(status_param)
        outcomes = OUTCOME_FILTERS[outcome][1] if outcome else None
        tzinfo = zone(tz)
        start, end = midnight(from_, tzinfo), midnight(to, tzinfo, days=1)
        if after:
            newer = await usage.lookups_after(
                after, limit=PAGE_SIZE + 1, before=end, outcomes=outcomes
            )
            has_prev, has_next = len(newer) > PAGE_SIZE, True
            items = newer[:PAGE_SIZE][::-1]
        else:
            older = await usage.lookups(
                limit=PAGE_SIZE + 1,
                before=before or end,
                after=start,
                outcomes=outcomes,
            )
            has_prev, has_next = before is not None, len(older) > PAGE_SIZE
            items = older[:PAGE_SIZE]
        newest, oldest = (items[0].ts, items[-1].ts) if items else (None, None)
        counts = await usage.count(before=end, after=start, newer_than=newest)
        totals = {c.outcome: c.total for c in counts}
        shown = [c for c in counts if outcomes is None or c.outcome in outcomes]
        offset = sum(c.newer for c in shown)
        filters = {"from": from_, "to": to, "status": outcome}
        filters = {k: v for k, v in filters.items() if v}

        def page_url(**params: str) -> str:
            return f"/portal?{urlencode({**filters, **params})}"

        return Template(
            "portal.html",
            context={
                "tenant": request.user,
                "usage": await usage.summary(),
                "items": items,
                "prev_after": newest if has_prev else None,
                "next_before": oldest if has_next else None,
                "position": (
                    offset + 1,
                    offset + len(items),
                    sum(c.total for c in shown),
                ),
                "from": from_,
                "to": to,
                "outcome": outcome,
                "outcome_options": [
                    ("", "All", sum(totals.values())),
                    *(
                        (value, label, sum(totals.get(o, 0) for o in of))
                        for value, (label, of) in OUTCOME_FILTERS.items()
                    ),
                ],
                "filtered": bool(filters),
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
