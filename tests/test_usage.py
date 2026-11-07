from __future__ import annotations

import datetime as dt

import pytest
from acis_browser import CaptchaError, CaseNotFoundError, UpstreamError

from .conftest import NOW, OWNER, lookup, lookup_rows, seed

pytestmark = pytest.mark.anyio


def epoch(ts: dt.datetime) -> str:
    return str(int(ts.timestamp()))


##### Quota #####


async def test_lookup_under_quota_succeeds(client, usage_service):
    await seed(usage_service, *(dt.timedelta(hours=h) for h in (20, 10, 5, 1)))
    response = await lookup(client)
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "5"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert response.headers["X-RateLimit-Reset"] == epoch(NOW + dt.timedelta(hours=4))


async def test_lookup_at_quota_returns_429_until_oldest_ages_out(
    client, usage_service, browser
):
    await seed(usage_service, *(dt.timedelta(hours=h) for h in (23, 10, 5, 2, 1)))
    response = await lookup(client)
    assert response.status_code == 429
    assert response.json()["detail"] == "Daily quota exceeded"
    assert response.json()["extra"] == {"reason": "quota_exceeded"}
    assert response.headers["Retry-After"] == "3600"
    assert response.headers["X-RateLimit-Limit"] == "5"
    assert response.headers["X-RateLimit-Remaining"] == "0"
    assert response.headers["X-RateLimit-Reset"] == epoch(NOW + dt.timedelta(hours=1))
    assert browser.calls == []
    assert len(await lookup_rows(usage_service)) == 5


async def test_rows_older_than_24h_do_not_count(client, usage_service):
    await seed(usage_service, *[dt.timedelta(hours=25)] * 5)
    response = await lookup(client)
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Remaining"] == "4"


async def test_cache_hits_do_not_count(client):
    for _ in range(6):
        response = await lookup(client)
        assert response.status_code == 200
    assert response.json()["cached"] is True
    assert response.headers["X-RateLimit-Remaining"] == "4"


async def test_cache_hit_is_served_when_over_quota(client, usage_service):
    assert (await lookup(client)).status_code == 200
    await seed(usage_service, *[dt.timedelta(hours=1)] * 4)
    response = await lookup(client)
    assert response.status_code == 200
    assert response.json()["cached"] is True


async def test_captcha_failure_does_not_count(client, usage_service, browser):
    browser.error = CaptchaError("rejected", reason=CaptchaError.Reason.REJECTED)
    response = await lookup(client)
    assert response.status_code == 503
    assert response.headers["X-RateLimit-Remaining"] == "5"
    assert response.headers["X-RateLimit-Reset"] == epoch(NOW)
    assert [r.outcome for r in await lookup_rows(usage_service)] == ["captcha"]


async def test_not_found_counts(client, browser):
    browser.error = CaseNotFoundError("No case info found")
    response = await lookup(client)
    assert response.status_code == 404
    assert response.headers["X-RateLimit-Remaining"] == "4"


async def test_tenant_without_quota_is_never_limited(client, usage_service):
    await seed(usage_service, *[dt.timedelta(hours=1)] * 10, tenant="owner")
    response = await lookup(client, headers=OWNER)
    assert response.status_code == 200
    assert not any(h.lower().startswith("x-ratelimit") for h in response.headers)


async def test_quota_is_per_tenant(client, usage_service):
    await seed(usage_service, *[dt.timedelta(hours=1)] * 5, tenant="owner")
    response = await lookup(client)
    assert response.status_code == 200
    assert response.headers["X-RateLimit-Remaining"] == "4"


##### Recording #####


@pytest.mark.parametrize(
    ("error", "outcome"),
    [
        (None, "ok"),
        (CaseNotFoundError("No case info found"), "not_found"),
        (CaptchaError("boom", reason=CaptchaError.Reason.NO_REQUEST), "captcha"),
        (UpstreamError("ACIS returned HTTP 500"), "upstream_error"),
    ],
)
async def test_each_lookup_records_one_row(
    client, usage_service, browser, error, outcome
):
    browser.error = error
    await lookup(client)
    [row] = await lookup_rows(usage_service)
    assert row.tenant == "metered"
    assert row.outcome == outcome
    assert not row.cached
    assert row.ts == NOW
    assert row.duration_ms is not None


async def test_cache_hit_records_cached_row(client, usage_service):
    await lookup(client)
    await lookup(client)
    rows = await lookup_rows(usage_service)
    assert [(r.outcome, r.cached, r.duration_ms) for r in rows[1:]] == [("ok", 1, None)]


async def test_only_last_four_digits_are_stored(client, usage_service):
    await lookup(client, body={"a_number": "123-456-789", "nationality": "VE"})
    [row] = await lookup_rows(usage_service)
    assert row.a_number_last_4 == "6789"


##### Prune #####


async def test_prune_deletes_rows_past_retention(usage_service):
    await seed(usage_service, dt.timedelta(days=31), dt.timedelta(days=29))
    deleted = await usage_service.prune()
    assert deleted == 1
    assert [r.ts for r in await lookup_rows(usage_service)] == [
        NOW - dt.timedelta(days=29)
    ]
