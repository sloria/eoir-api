from __future__ import annotations

import datetime as dt
from html.parser import HTMLParser

import msgspec
import pytest
from litestar.testing import AsyncTestClient

from eoir_api.app import build_app

from .conftest import NOW, lookup, seed

pytestmark = pytest.mark.anyio


async def csrf_token(client) -> str:
    await client.get("/portal/login")
    return client.cookies["csrftoken"]


async def login(client, key="metered-test-secret"):
    data = {"key": key, "_csrf_token": await csrf_token(client)}
    return await client.post("/portal/login", data=data, follow_redirects=False)


class Page(HTMLParser):
    """The parts of a portal page the tests read, free of markup."""

    def __init__(self, html: str) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self.options: list[str] = []
        self.selected: str | None = None
        self.links: dict[str, str] = {}
        self.fields: dict[str, str | None] = {}
        self._chunks: list[str] = []
        self._open: dict[str, tuple[int, dict[str, str | None]]] = {}
        self._script = False
        self.feed(html)
        self.text = " ".join(self._chunks)

    @property
    def statuses(self) -> list[str]:
        return [row[0] for row in self.rows]

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("li", "option", "a"):
            self._open[tag] = (len(self._chunks), attrs)
        elif tag == "input":
            self.fields[attrs["name"]] = attrs.get("value")
        self._script = tag == "script"

    def handle_data(self, data):
        if not self._script and data.strip():
            self._chunks.append(" ".join(data.split()))

    def handle_endtag(self, tag):
        self._script = False
        if tag not in self._open:
            return
        start, attrs = self._open.pop(tag)
        chunks = self._chunks[start:]
        if tag == "li":
            self.rows.append(chunks)
        elif tag == "a":
            self.links[" ".join(chunks)] = attrs["href"] or ""
        else:
            self.options.append(" ".join(chunks))
            if "selected" in attrs:
                self.selected = self.options[-1]


async def portal(client, **params):
    return await client.get("/portal", params=params, follow_redirects=False)


async def portal_page(client, **params) -> Page:
    return Page((await portal(client, **params)).text)


##### Login #####


async def test_login_redirects_to_portal(client):
    response = await login(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/portal"
    page = await portal(client)
    assert page.status_code == 200
    assert "metered" in page.text


async def test_login_with_unknown_key_is_401(client):
    response = await login(client, key="nope")
    assert response.status_code == 401
    assert "Unknown key" in response.text


async def test_login_without_csrf_token_is_403(client):
    response = await client.post(
        "/portal/login", data={"key": "metered-test-secret"}, follow_redirects=False
    )
    assert response.status_code == 403
    assert (await portal(client)).status_code == 302


async def test_login_is_rate_limited_but_lookups_are_not(client):
    for _ in range(10):
        assert (await login(client, key="nope")).status_code == 401
    assert (await login(client, key="nope")).status_code == 429
    assert (await portal(client)).status_code == 302
    assert (await lookup(client)).status_code == 200


async def test_login_rate_limit_is_per_client_ip_header(settings, service):
    server = msgspec.structs.replace(
        settings.server, client_ip_header="CF-Connecting-IP"
    )
    settings = msgspec.structs.replace(settings, server=server)
    app = build_app(settings, service)
    async with AsyncTestClient(app=app) as attacker, AsyncTestClient(app=app) as user:
        attacker.headers["CF-Connecting-IP"] = "203.0.113.1"
        user.headers["CF-Connecting-IP"] = "203.0.113.2"
        for _ in range(11):
            await login(attacker, key="nope")
        assert (await login(attacker, key="nope")).status_code == 429
        assert (await login(user)).status_code == 303


async def test_portal_without_session_redirects_to_login(client):
    response = await portal(client)
    assert response.status_code == 302
    assert response.headers["location"] == "/portal/login"
    assert (await client.get("/portal/login")).status_code == 200


async def test_session_cookie_is_httponly(client):
    response = await login(client)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


async def test_session_cookie_is_rejected_for_lookups(client, browser):
    await login(client)
    response = await client.post(
        "/cases/lookup", json={"a_number": "123456789", "nationality": "VE"}
    )
    assert response.status_code == 401
    assert browser.calls == []


async def test_session_for_removed_tenant_redirects_to_login(client, settings, service):
    await login(client)
    settings = msgspec.structs.replace(settings, tenants=settings.tenants[:1])
    async with AsyncTestClient(
        app=build_app(settings, service), cookies=client.cookies
    ) as other:
        assert (await portal(other)).status_code == 302


async def test_session_expires_after_max_age_despite_activity(client, time_machine):
    await login(client)
    time_machine.move_to(NOW + dt.timedelta(hours=11))
    assert (await portal(client)).status_code == 200
    time_machine.move_to(NOW + dt.timedelta(hours=12, seconds=1))
    assert (await portal(client)).status_code == 302


async def test_logout_clears_session(client):
    await login(client)
    data = {"_csrf_token": client.cookies["csrftoken"]}
    response = await client.post("/portal/logout", data=data, follow_redirects=False)
    assert response.status_code == 303
    assert (await portal(client)).status_code == 302


async def test_portal_with_invalid_query_redirects_to_portal(client):
    await login(client)
    response = await portal(client, before="yesterday")
    assert response.status_code == 302
    assert response.headers["location"] == "/portal"


##### Portal page #####


async def test_portal_shows_usage_against_quota(client, usage_service):
    await seed(usage_service, dt.timedelta(hours=20), dt.timedelta(hours=1))
    await seed(usage_service, dt.timedelta(hours=3), outcome="captcha")
    await seed(usage_service, dt.timedelta(days=2))
    await login(client)
    text = (await portal(client)).text
    assert "of 5 lookups" in text
    assert "3 left" in text


async def test_portal_shows_count_for_unlimited_tenant(client, usage_service):
    await seed(usage_service, dt.timedelta(hours=1), tenant="owner")
    await login(client, key="owner-test-secret")
    page = await portal_page(client)
    assert "1 lookup in the past 24 hours" in page.text
    assert "left" not in page.text


async def test_portal_lists_lookups_with_status(client):
    await lookup(client, body={"a_number": "123-456-789", "nationality": "VE"})
    await login(client)
    page = await portal_page(client)
    assert "123456789" not in page.text
    assert page.statuses == ["OK"]


async def test_portal_shows_request_id_of_each_lookup(client, usage_service):
    await seed(usage_service, dt.timedelta(hours=1))  # recorded without an id
    response = await lookup(client)
    await login(client)
    page = await portal_page(client)
    assert [response.headers["x-request-id"] in row for row in page.rows] == [
        True,
        False,
    ]


async def test_portal_lists_rejected_lookups(client, usage_service):
    await seed(usage_service, *[dt.timedelta(hours=1)] * 5)
    assert (await lookup(client)).status_code == 429
    await login(client)
    page = await portal_page(client)
    assert page.statuses[0] == "Quota exceeded"
    assert "0 left" in page.text


async def test_portal_lookups_are_tenant_scoped(client, usage_service):
    await seed(usage_service, dt.timedelta(hours=1), tenant="owner", outcome="captcha")
    await login(client)
    page = await portal_page(client)
    assert page.statuses == ["No lookups"]


async def test_portal_paginates_newest_first(client, usage_service):
    await seed(usage_service, *(dt.timedelta(minutes=m) for m in range(15)))
    await login(client)
    first = await portal_page(client)
    assert "Jul 25, 12:00" in first.text
    assert "Jul 25, 11:51" in first.text
    assert "Jul 25, 11:50" not in first.text
    assert "Previous" not in first.links
    assert "1\N{EN DASH}10 of 15" in first.text

    rest = Page((await client.get(first.links["Next"])).text)
    assert "Jul 25, 11:50" in rest.text
    assert "Jul 25, 11:51" not in rest.text
    assert "Next" not in rest.links
    assert "11\N{EN DASH}15 of 15" in rest.text

    back = Page((await client.get(rest.links["Previous"])).text)
    assert "Jul 25, 12:00" in back.text
    assert "Jul 25, 11:51" in back.text
    assert "Jul 25, 11:50" not in back.text
    assert "Previous" not in back.links
    assert "1\N{EN DASH}10 of 15" in back.text
    assert "Next" in back.links


async def test_portal_filters_by_date_range(client, usage_service):
    await seed(usage_service, *(dt.timedelta(days=d) for d in range(4)))
    await login(client)
    text = (await portal(client, **{"from": "2026-07-23", "to": "2026-07-24"})).text
    assert "Jul 24" in text
    assert "Jul 23" in text
    assert "Jul 25" not in text
    assert "Jul 22" not in text


async def test_portal_ignores_blank_date_field(client, usage_service):
    await seed(usage_service, *(dt.timedelta(days=d) for d in range(3)))
    await login(client)
    page = await portal_page(client, **{"from": "2026-07-24", "to": ""})
    assert page.fields["from"] == "2026-07-24"
    assert "Jul 23" not in page.text


async def test_portal_redirects_on_invalid_date(client):
    await login(client)
    response = await portal(client, **{"from": "nope"})
    assert response.status_code == 302
    assert response.headers["location"] == "/portal"


async def test_portal_date_range_uses_client_timezone(client, usage_service):
    # 2026-07-25 02:00 UTC is Jul 24 evening in New York
    await seed(usage_service, dt.timedelta(hours=10))
    await login(client)
    day = {"from": "2026-07-24", "to": "2026-07-24"}
    assert "No lookups" in (await portal(client, **day)).text
    client.cookies["tz"] = "America/New_York"
    assert "Jul 25, 02:00" in (await portal(client, **day)).text


async def seed_outcomes(usage_service):
    await seed(usage_service, dt.timedelta(minutes=1), dt.timedelta(minutes=2))
    await seed(usage_service, dt.timedelta(minutes=3), outcome="not_found")
    await seed(usage_service, dt.timedelta(minutes=4), outcome="captcha")
    await seed(usage_service, dt.timedelta(minutes=5), outcome="quota_exceeded")


async def test_portal_filters_by_status(client, usage_service):
    await seed_outcomes(usage_service)
    await login(client)
    page = await portal_page(client, status="not_found")
    assert page.statuses == ["Not found"]
    assert "1\N{EN DASH}1 of 1" in page.text
    assert page.selected == "Not found (1)"
    assert "All (5)" in page.options


async def test_portal_failed_filter_matches_every_failed_outcome(client, usage_service):
    await seed_outcomes(usage_service)
    await login(client)
    page = await portal_page(client, status="failed")
    assert page.statuses == ["Temporarily unavailable", "Quota exceeded"]


async def test_portal_counts_outcomes_in_date_range(client, usage_service):
    await seed_outcomes(usage_service)
    await seed(usage_service, dt.timedelta(days=3), outcome="upstream_error")
    await login(client)
    page = await portal_page(client, **{"from": "2026-07-25"})
    assert {"All (5)", "Failed (2)", "Upstream error (0)"} <= set(page.options)


async def test_portal_paging_keeps_status_filter(client, usage_service):
    await seed(usage_service, *(dt.timedelta(minutes=m) for m in range(12)))
    await seed(usage_service, dt.timedelta(seconds=30), outcome="captcha")
    await login(client)
    first = await portal_page(client, status="ok")
    assert "1\N{EN DASH}10 of 12" in first.text

    rest = Page((await client.get(first.links["Next"])).text)
    assert "11\N{EN DASH}12 of 12" in rest.text

    back = Page((await client.get(rest.links["Previous"])).text)
    assert "1\N{EN DASH}10 of 12" in back.text
    assert set(back.statuses) == {"OK"}


async def test_portal_ignores_blank_status_field(client, usage_service):
    await seed_outcomes(usage_service)
    await login(client)
    response = await portal(client, status="")
    assert response.status_code == 200
    assert "1\N{EN DASH}5 of 5" in response.text


async def test_portal_redirects_on_invalid_status(client):
    await login(client)
    response = await portal(client, status="nope")
    assert response.status_code == 302
    assert response.headers["location"] == "/portal"


##### Disabled #####


async def test_no_portal_without_portal_section(settings, service, browser):
    settings = msgspec.structs.replace(settings, portal=None)
    async with AsyncTestClient(app=build_app(settings, service)) as client:
        assert (await client.get("/portal", follow_redirects=False)).status_code == 404
        assert (await client.get("/portal/login")).status_code == 404
        response = await lookup(client)
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
