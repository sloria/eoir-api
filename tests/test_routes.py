from __future__ import annotations

import pytest
from acis_browser import (
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidNationalityError,
    UpstreamError,
)

pytestmark = pytest.mark.anyio

A_NUMBER = "999999999"
HEADERS = {"x-api-key": "test-secret"}


async def lookup(client, body, headers=HEADERS):
    return await client.post("/cases/lookup", json=body, headers=headers)


##### Health #####


async def test_health_check(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


##### Auth #####


async def test_missing_secret_is_rejected(client):
    response = await lookup(
        client, {"a_number": A_NUMBER, "nationality": "VE"}, headers={}
    )
    assert response.status_code == 401


async def test_wrong_secret_is_rejected(client):
    response = await lookup(
        client,
        {"a_number": A_NUMBER, "nationality": "VE"},
        headers={"x-api-key": "nope"},
    )
    assert response.status_code == 401


async def test_auth_is_checked_before_any_lookup(client, browser):
    await lookup(client, {"a_number": A_NUMBER, "nationality": "VE"}, headers={})
    assert browser.calls == []


async def test_auth_is_checked_before_parameter_validation(client):
    response = await lookup(
        client,
        {"a_number": A_NUMBER, "nationality": "VE", "refresh": "maybe"},
        headers={},
    )
    assert response.status_code == 401


##### Happy path #####


async def test_lookup_returns_acis_payload(client, master_hearing):
    response = await lookup(client, {"a_number": A_NUMBER, "nationality": "VE"})
    assert response.status_code == 200
    body = response.json()
    assert body["a_number"] == A_NUMBER
    assert body["nationality"] == {"code": "VE", "name": "VENEZUELA"}
    assert body["cached"] is False
    assert body["retrieved_at"] == "2026-07-25T12:00:00Z"
    assert body["acis"] == master_hearing


async def test_lookup_accepts_nationality_name(client, browser):
    response = await lookup(
        client,
        {"a_number": A_NUMBER, "nationality": "venezuela"},
    )
    assert response.status_code == 200
    assert browser.calls == [(A_NUMBER, "VE", "VENEZUELA")]


async def test_lookup_normalizes_a_number_before_calling_acis(client, browser):
    response = await lookup(client, {"a_number": "999-999-999", "nationality": "VE"})
    assert response.status_code == 200
    assert browser.calls == [(A_NUMBER, "VE", "VENEZUELA")]


##### Input errors #####


async def test_bad_a_number_returns_400(client):
    response = await lookup(client, {"a_number": "12345", "nationality": "VE"})
    assert response.status_code == 400


async def test_missing_nationality_returns_400(client):
    response = await lookup(client, {"a_number": A_NUMBER})
    assert response.status_code == 400


async def test_unknown_nationality_returns_400(client):
    response = await lookup(
        client,
        {"a_number": A_NUMBER, "nationality": "ATLANTIS"},
    )
    assert response.status_code == 400


async def test_missing_a_number_returns_400(client):
    response = await lookup(client, {"nationality": "VE"})
    assert response.status_code == 400


async def test_wrong_field_type_returns_400(client):
    response = await lookup(
        client, {"a_number": A_NUMBER, "nationality": "VE", "refresh": "maybe"}
    )
    assert response.status_code == 400


async def test_malformed_json_returns_400(client):
    response = await client.post(
        "/cases/lookup",
        content=b"{not json",
        headers={**HEADERS, "content-type": "application/json"},
    )
    assert response.status_code == 400


async def test_iso_only_code_returns_400(client):
    response = await lookup(client, {"a_number": A_NUMBER, "nationality": "DZ"})
    assert response.status_code == 400


async def test_a_number_in_path_is_not_routed(client, browser):
    response = await client.get(f"/cases/{A_NUMBER}", headers=HEADERS)
    assert response.status_code in (404, 405)
    assert browser.calls == []


##### Upstream errors #####


async def test_case_not_found_returns_404(client, browser):
    browser.error = CaseNotFoundError("No case info found")
    response = await lookup(client, {"a_number": A_NUMBER, "nationality": "VE"})
    assert response.status_code == 404
    assert "a-number" in response.json()["detail"].lower()


async def test_invalid_nationality_returns_404(client, browser):
    browser.error = InvalidNationalityError("Invalid nationality code")
    response = await lookup(client, {"a_number": A_NUMBER, "nationality": "VE"})
    assert response.status_code == 404
    assert "nationality" in response.json()["detail"].lower()


async def test_case_unavailable_returns_422(client, browser):
    browser.error = CaseUnavailableError("Case information is unavailable")
    response = await lookup(client, {"a_number": A_NUMBER, "nationality": "VE"})
    assert response.status_code == 422


async def test_captcha_exhausted_returns_503(client, browser):
    browser.error = CaptchaError(
        "No captcha token obtained", reason=CaptchaError.Reason.NO_REQUEST
    )
    response = await lookup(client, {"a_number": A_NUMBER, "nationality": "VE"})
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "300"


async def test_captcha_with_a_browser_still_free_returns_short_retry_after(
    client, browser
):
    browser.error = CaptchaError("timed out", reason=CaptchaError.Reason.NO_RESPONSE)
    response = await lookup(client, {"a_number": A_NUMBER, "nationality": "VE"})
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "1"


async def test_all_browsers_in_cooldown_returns_503_with_retry_after(
    client, browser, clock
):
    browser.error = CaptchaError("rejected", reason=CaptchaError.Reason.REJECTED)
    first = await lookup(client, {"a_number": A_NUMBER, "nationality": "VE"})
    assert first.status_code == 503

    browser.error = None
    clock.now += 99.6
    second = await lookup(client, {"a_number": A_NUMBER, "nationality": "VE"})
    assert second.status_code == 503
    assert second.headers["Retry-After"] == "200"
    assert len(browser.calls) == 1

    clock.now += 200.3
    third = await lookup(client, {"a_number": A_NUMBER, "nationality": "VE"})
    assert third.headers["Retry-After"] == "1"


async def test_upstream_error_returns_502(client, browser):
    browser.error = UpstreamError("ACIS returned HTTP 500")
    response = await lookup(client, {"a_number": A_NUMBER, "nationality": "VE"})
    assert response.status_code == 502


async def test_failures_are_never_served_from_cache(client, browser):
    ok = await lookup(client, {"a_number": A_NUMBER, "nationality": "VE"})
    assert ok.status_code == 200

    browser.error = CaptchaError("boom", reason=CaptchaError.Reason.NO_REQUEST)
    failed = await lookup(
        client,
        {"a_number": A_NUMBER, "nationality": "VE", "refresh": True},
    )
    assert failed.status_code == 503
    assert "acis" not in failed.json()
