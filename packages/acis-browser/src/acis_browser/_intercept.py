"""Utilities for the case request interception and rewriting."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import parse_qsl, urlencode, urlsplit

import structlog
from patchright.async_api import Error as PlaywrightError

if TYPE_CHECKING:
    import re

    from patchright.async_api import Page, Route

    from acis_browser.browser import Capture

logger = structlog.get_logger()

PLACEHOLDER = ("123456789", "MX", "MEXICO")


@dataclass(frozen=True)
class CaseQuery:
    a_number: str = field(repr=False)
    nat_code: str = field(repr=False)


def with_case(url: str, case: CaseQuery) -> str | None:
    """Return the case request URL rewritten to the given case."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if not {"alienNumber", "natCode"} <= query.keys():
        return None
    query |= {"alienNumber": case.a_number, "natCode": case.nat_code}
    return parts._replace(query=urlencode(query)).geturl()


def case_of(url: str) -> CaseQuery:
    """Return the case for the given case request URL."""
    query = dict(parse_qsl(urlsplit(url).query))
    return CaseQuery(query.get("alienNumber", ""), query.get("natCode", ""))


@dataclass
class WarmPage:
    """A page with the form filled with the placeholder, awaiting one real case."""

    page: Page
    ready_at: float = 0.0
    case: CaseQuery | None = None
    capture: Capture | None = None

    @property
    def age(self) -> float:
        return round(time.monotonic() - self.ready_at, 1)

    async def install_route(self, url: re.Pattern[str]) -> None:
        await self.page.route(url, self._on_case_request)

    async def _on_case_request(self, route: Route) -> None:
        case, self.case = self.case, None
        # Send the request for the pending real case
        url = with_case(route.request.url, case) if case else None
        try:
            if url:
                await route.continue_(url=url)
                return
            await route.abort()
        except PlaywrightError:
            logger.warning("lookup.route_failed")
        if case and self.capture:
            # Fail the lookup now rather than at its timeout
            self.capture.received.set()
