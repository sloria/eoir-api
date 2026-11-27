from __future__ import annotations

import datetime as dt
import inspect
import json
from importlib.metadata import version

import httpx2
import pytest

from eoir_api_client import (
    AsyncClient,
    AuthenticationError,
    CaseNotFoundError,
    CaseUnavailableError,
    Client,
    InvalidRequestError,
    NetworkError,
    Quota,
    QuotaExceededError,
    RetryLaterError,
    ServerError,
)

pytestmark = pytest.mark.anyio

CASE = {
    "a_number": "999999999",
    "nationality": {"code": "VE", "name": "VENEZUELA"},
    "retrieved_at": "2026-07-25T12:00:00Z",
    "cached": False,
    "acis": {"Data": {"AlienName": "DOE, JANE"}},
}
QUOTA_HEADERS = {
    "X-RateLimit-Limit": "100",
    "X-RateLimit-Remaining": "42",
    "X-RateLimit-Reset": "1785067200",
}
QUOTA = Quota(
    limit=100, remaining=42, reset_at=dt.datetime(2026, 7, 26, 12, 0, tzinfo=dt.UTC)
)


def ok() -> httpx2.Response:
    return httpx2.Response(200, json=CASE)


def error(status_code: int, **kwargs) -> httpx2.Response:
    return httpx2.Response(status_code, json={"detail": "nope"}, **kwargs)


@pytest.fixture(
    params=[(Client, httpx2.Client), (AsyncClient, httpx2.AsyncClient)],
    ids=["sync", "async"],
)
def make_lookup(request):
    """Build a `lookup` coroutine for either client, answered by `handler`."""
    client_class, http_client_class = request.param

    def make(handler):
        client = client_class(
            "http://eoir.test",
            "fake-key",
            http_client=http_client_class(transport=httpx2.MockTransport(handler)),
        )

        async def lookup(*args, **kwargs):
            result = client.lookup(*args, **kwargs)
            return await result if inspect.isawaitable(result) else result

        return lookup

    return make


class sequence:  # noqa: N801
    """Answer successive requests with `responses`; record the requests."""

    def __init__(self, *responses: httpx2.Response | Exception) -> None:
        self.remaining = list(responses)
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        response = self.remaining.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


async def test_returns_the_case(make_lookup):
    result = await make_lookup(sequence(ok()))("999999999", "VE")

    assert result.case.name == "DOE, JANE"
    assert result.acis == CASE["acis"]
    assert result.nationality.code == "VE"
    assert result.retrieved_at == dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
    assert result.cached is False
    assert result.quota is None


async def test_sends_api_key_user_agent_and_case_details(make_lookup):
    handler = sequence(ok())

    await make_lookup(handler)("999999999", "venezuela", refresh=True)

    (request,) = handler.requests
    assert request.headers["x-api-key"] == "fake-key"
    assert request.headers["user-agent"] == (
        f"eoir-api-client/{version('eoir-api-client')}"
    )
    assert (request.method, str(request.url)) == (
        "POST",
        "http://eoir.test/cases/lookup",
    )
    assert json.loads(request.content) == {
        "a_number": "999999999",
        "nationality": "venezuela",
        "refresh": True,
    }


async def test_result_carries_quota_and_request_id(make_lookup):
    response = httpx2.Response(
        200, json=CASE, headers={**QUOTA_HEADERS, "x-request-id": "abc123"}
    )

    result = await make_lookup(sequence(response))("999999999", "VE")

    assert result.quota == QUOTA
    assert result.request_id == "abc123"


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (400, InvalidRequestError),
        (401, AuthenticationError),
        (404, CaseNotFoundError),
        (422, CaseUnavailableError),
        (502, ServerError),
    ],
)
async def test_error_mapping(make_lookup, status_code, expected):
    handler = sequence(error(status_code, headers=QUOTA_HEADERS))

    with pytest.raises(expected) as excinfo:
        await make_lookup(handler)("999999999", "VE")

    assert excinfo.value.status_code == status_code
    assert excinfo.value.detail == "nope"
    assert excinfo.value.quota == QUOTA
    assert len(handler.requests) == 1


@pytest.mark.parametrize("status_code", [429, 503])
async def test_retry_later(make_lookup, status_code):
    handler = sequence(error(status_code, headers={"Retry-After": "12"}))

    with pytest.raises(RetryLaterError) as excinfo:
        await make_lookup(handler)("999999999", "VE")

    assert not isinstance(excinfo.value, QuotaExceededError)
    assert excinfo.value.retry_after == 12
    assert excinfo.value.status_code == status_code
    assert len(handler.requests) == 1


async def test_quota_exceeded(make_lookup):
    response = httpx2.Response(
        429,
        json={"detail": "Daily quota exceeded", "code": "quota_exceeded"},
        headers={"Retry-After": "7200", **QUOTA_HEADERS},
    )

    with pytest.raises(QuotaExceededError) as excinfo:
        await make_lookup(sequence(response))("999999999", "VE")

    assert not isinstance(excinfo.value, RetryLaterError)
    assert excinfo.value.quota == QUOTA
    assert excinfo.value.code == "quota_exceeded"


async def test_quota_exceeded_without_quota_headers_says_when_to_retry(make_lookup):
    response = httpx2.Response(
        429,
        json={"detail": "Daily quota exceeded", "code": "quota_exceeded"},
        headers={"Retry-After": "7200"},
    )

    with pytest.raises(RetryLaterError) as excinfo:
        await make_lookup(sequence(response))("999999999", "VE")

    assert excinfo.value.retry_after == 7200


async def test_non_json_error_still_maps_by_status(make_lookup):
    response = httpx2.Response(502, text="<html>bad gateway</html>")

    with pytest.raises(ServerError) as excinfo:
        await make_lookup(sequence(response))("999999999", "VE")

    assert excinfo.value.detail
    assert excinfo.value.code is None


async def test_timeout_has_a_message(make_lookup):
    with pytest.raises(NetworkError) as excinfo:
        await make_lookup(sequence(httpx2.ReadTimeout("")))("999999999", "VE")

    assert str(excinfo.value) == "ReadTimeout"


async def test_network_error(make_lookup):
    with pytest.raises(NetworkError) as excinfo:
        await make_lookup(sequence(httpx2.ConnectError("boom")))("999999999", "VE")

    assert isinstance(excinfo.value.__cause__, httpx2.ConnectError)
    assert excinfo.value.status_code is None
