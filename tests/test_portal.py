from __future__ import annotations

import datetime as dt
import re

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


def page_link(html: str, label: str) -> str | None:
    match = re.search(rf'href="([^"]*)">{label}<', html)
    return match and match[1].replace("&amp;", "&")


async def portal(client, **params):
    return await client.get("/portal", params=params, follow_redirects=False)


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
    assert "problem" not in response.headers["content-type"]
    assert (await portal(client)).status_code == 302


async def test_login_is_rate_limited_but_lookups_are_not(client):
    for _ in range(10):
        assert (await login(client, key="nope")).status_code == 401
    assert (await login(client, key="nope")).status_code == 429
    assert (await portal(client)).status_code == 302
    assert (await lookup(client)).status_code == 200


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
    assert "<strong>2 / 5</strong>" in text


async def test_portal_shows_count_for_unlimited_tenant(client, usage_service):
    await seed(usage_service, dt.timedelta(hours=1), tenant="owner")
    await login(client, key="owner-test-secret")
    text = (await portal(client)).text
    assert "<strong>1</strong>" in text


async def test_portal_lists_lookups_with_status(client):
    await lookup(client, body={"a_number": "123-456-789", "nationality": "VE"})
    await login(client)
    text = (await portal(client)).text
    assert "123456789" not in text
    assert re.search(r'<span class="ok">OK</span>', text)


async def test_portal_lookups_are_tenant_scoped(client, usage_service):
    await seed(usage_service, dt.timedelta(hours=1), tenant="owner", outcome="captcha")
    await login(client)
    text = (await portal(client)).text
    assert "Captcha failed" not in text
    assert "No lookups" in text


async def test_portal_paginates_newest_first(client, usage_service):
    await seed(usage_service, *(dt.timedelta(minutes=m) for m in range(30)))
    await login(client)
    first = (await portal(client)).text
    assert "Jul 25, 12:00" in first
    assert "Jul 25, 11:41" in first
    assert "Jul 25, 11:40" not in first
    assert page_link(first, "Previous") is None
    assert "1\N{EN DASH}20 of 30" in first
    next_url = page_link(first, "Next")

    rest = (await client.get(next_url, follow_redirects=False)).text
    assert "Jul 25, 11:40" in rest
    assert "Jul 25, 11:41" not in rest
    assert page_link(rest, "Next") is None
    assert "21\N{EN DASH}30 of 30" in rest
    prev_url = page_link(rest, "Previous")

    back = (await client.get(prev_url)).text
    assert "Jul 25, 12:00" in back
    assert "Jul 25, 11:41" in back
    assert "Jul 25, 11:40" not in back
    assert page_link(back, "Previous") is None
    assert "1\N{EN DASH}20 of 30" in back
    assert page_link(back, "Next")


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
    response = await portal(client, **{"from": "2026-07-24", "to": ""})
    assert response.status_code == 200
    assert 'value="2026-07-24"' in response.text
    assert "Jul 23" not in response.text


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


##### Disabled #####


async def test_no_portal_without_portal_section(settings, service, browser):
    settings = msgspec.structs.replace(settings, portal=None)
    async with AsyncTestClient(app=build_app(settings, service)) as client:
        assert (await client.get("/portal", follow_redirects=False)).status_code == 404
        assert (await client.get("/portal/login")).status_code == 404
        response = await lookup(client)
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
