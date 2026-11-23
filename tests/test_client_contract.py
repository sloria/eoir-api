"""Test eoir-api-client against the real app."""

from __future__ import annotations

import httpx2
import pytest
from acis_browser import CaptchaError, CaseUnavailableError, UpstreamError
from eoir_api_client import (
    AsyncClient,
    AuthenticationError,
    CaseNotFoundError,
    InvalidRequestError,
    QuotaExceededError,
    RetryLaterError,
    ServerError,
)
from eoir_api_client import CaseUnavailableError as ClientCaseUnavailableError

from .conftest import METERED, NOW

pytestmark = pytest.mark.anyio

A_NUMBER = "999999999"


@pytest.fixture
async def http_client(client):
    transport = httpx2.ASGITransport(app=client.app)
    async with httpx2.AsyncClient(transport=transport) as http_client:
        yield http_client


@pytest.fixture
def make_client(http_client):
    def make(api_key: str = METERED["x-api-key"], **kwargs) -> AsyncClient:
        return AsyncClient(
            "http://testserver", api_key, http_client=http_client, **kwargs
        )

    return make


async def test_lookup_returns_the_case(make_client, master_hearing):
    result = await make_client().lookup(A_NUMBER, "venezuela")

    assert result.a_number == A_NUMBER
    assert result.nationality.code == "VE"
    assert result.retrieved_at == NOW
    assert result.cached is False
    assert result.acis == master_hearing
    assert result.case.name == master_hearing["Data"]["AlienName"]
    assert result.request_id
    assert result.quota is not None
    assert (result.quota.limit, result.quota.remaining) == (5, 4)
    assert result.quota.reset_at > NOW


async def test_invalid_a_number(make_client):
    with pytest.raises(InvalidRequestError):
        await make_client().lookup("12345", "VE")


async def test_bad_api_key(make_client):
    with pytest.raises(AuthenticationError):
        await make_client("wrong").lookup(A_NUMBER, "VE")


async def test_case_not_found(make_client, browser):
    browser.payload = None

    with pytest.raises(CaseNotFoundError):
        await make_client().lookup(A_NUMBER, "VE")


async def test_case_unavailable(make_client, browser):
    browser.error = CaseUnavailableError("Case information is unavailable")

    with pytest.raises(ClientCaseUnavailableError):
        await make_client().lookup(A_NUMBER, "VE")


async def test_captcha_says_when_to_retry(make_client, browser):
    browser.error = CaptchaError(
        "No captcha token obtained", reason=CaptchaError.Reason.NO_REQUEST
    )

    with pytest.raises(RetryLaterError) as excinfo:
        await make_client().lookup(A_NUMBER, "VE")

    assert excinfo.value.status_code == 503
    assert excinfo.value.retry_after == 300


async def test_quota_exceeded(make_client):
    client = make_client()
    for _ in range(5):
        await client.lookup(A_NUMBER, "VE", refresh=True)

    with pytest.raises(QuotaExceededError) as excinfo:
        await client.lookup(A_NUMBER, "VE", refresh=True)

    assert excinfo.value.retry_after > 0
    assert excinfo.value.quota is not None
    assert excinfo.value.quota.remaining == 0


async def test_upstream_error(make_client, browser):
    browser.error = UpstreamError("ACIS returned HTTP 500")

    with pytest.raises(ServerError):
        await make_client().lookup(A_NUMBER, "VE")
