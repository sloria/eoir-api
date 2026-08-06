from __future__ import annotations

import pytest

from eoir_api.exceptions import (
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    UpstreamError,
)

pytestmark = pytest.mark.anyio

A_NUMBER = "999999999"
HEADERS = {"x-api-key": "test-secret"}


##### Health #####


async def test_health_check(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.text == "ok"


async def test_health_check_does_not_start_the_browser(client, browser):
    await client.get("/healthz")
    assert browser.started is False
    assert browser.calls == []


##### Auth #####


async def test_missing_secret_is_rejected(client):
    response = await client.get(f"/cases/{A_NUMBER}?nationality=VE")
    assert response.status_code == 401


async def test_wrong_secret_is_rejected(client):
    response = await client.get(
        f"/cases/{A_NUMBER}?nationality=VE", headers={"x-api-key": "nope"}
    )
    assert response.status_code == 401


async def test_auth_is_checked_before_any_lookup(client, browser):
    await client.get(f"/cases/{A_NUMBER}?nationality=VE")
    assert browser.calls == []


async def test_auth_is_checked_before_parameter_validation(client):
    response = await client.get(f"/cases/{A_NUMBER}?nationality=VE&refresh=maybe")
    assert response.status_code == 401


##### Happy path #####


async def test_lookup_returns_acis_payload(client, master_hearing):
    response = await client.get(f"/cases/{A_NUMBER}?nationality=VE", headers=HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert body["a_number"] == A_NUMBER
    assert body["nationality"] == {"code": "VE", "name": "VENEZUELA"}
    assert body["cached"] is False
    assert body["retrieved_at"] == "2026-07-25T12:00:00Z"
    assert body["acis"] == master_hearing


async def test_lookup_accepts_nationality_name(client, browser):
    response = await client.get(
        f"/cases/{A_NUMBER}?nationality=venezuela", headers=HEADERS
    )
    assert response.status_code == 200
    assert browser.calls == [(A_NUMBER, "VE")]


async def test_lookup_normalizes_a_number_before_calling_acis(client, browser):
    response = await client.get("/cases/999-999-999?nationality=VE", headers=HEADERS)
    assert response.status_code == 200
    assert browser.calls == [(A_NUMBER, "VE")]


##### Input errors #####


async def test_bad_a_number_returns_400(client):
    response = await client.get("/cases/12345?nationality=VE", headers=HEADERS)
    assert response.status_code == 400


async def test_missing_nationality_returns_400(client):
    response = await client.get(f"/cases/{A_NUMBER}", headers=HEADERS)
    assert response.status_code == 400


async def test_unknown_nationality_returns_400(client):
    response = await client.get(
        f"/cases/{A_NUMBER}?nationality=ATLANTIS", headers=HEADERS
    )
    assert response.status_code == 400


async def test_iso_only_code_returns_400(client):
    response = await client.get(f"/cases/{A_NUMBER}?nationality=DZ", headers=HEADERS)
    assert response.status_code == 400


##### Upstream errors #####


async def test_case_not_found_returns_404(client, browser):
    browser.error = CaseNotFoundError("No case info found")
    response = await client.get(f"/cases/{A_NUMBER}?nationality=VE", headers=HEADERS)
    assert response.status_code == 404
    assert "nationality" in response.json()["detail"].lower()


async def test_case_unavailable_returns_422(client, browser):
    browser.error = CaseUnavailableError("Case information is unavailable")
    response = await client.get(f"/cases/{A_NUMBER}?nationality=VE", headers=HEADERS)
    assert response.status_code == 422


async def test_captcha_exhausted_returns_503(client, browser):
    browser.error = CaptchaError(
        "No captcha token obtained", reason=CaptchaError.Reason.NO_REQUEST
    )
    response = await client.get(f"/cases/{A_NUMBER}?nationality=VE", headers=HEADERS)
    assert response.status_code == 503
    assert "Retry-After" in response.headers


async def test_upstream_error_returns_502(client, browser):
    browser.error = UpstreamError("ACIS returned HTTP 500")
    response = await client.get(f"/cases/{A_NUMBER}?nationality=VE", headers=HEADERS)
    assert response.status_code == 502


async def test_failures_are_never_served_from_cache(client, browser):
    ok = await client.get(f"/cases/{A_NUMBER}?nationality=VE", headers=HEADERS)
    assert ok.status_code == 200

    browser.error = CaptchaError("boom", reason=CaptchaError.Reason.NO_REQUEST)
    failed = await client.get(
        f"/cases/{A_NUMBER}?nationality=VE&refresh=true", headers=HEADERS
    )
    assert failed.status_code == 503
    assert "acis" not in failed.json()
