"""Response parsing."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING, Any

from acis_core.nationalities import Nationality

from eoir_api_client.exceptions import (
    APIError,
    AuthenticationError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidRequestError,
    QuotaExceededError,
    RetryLaterError,
    ServerError,
)
from eoir_api_client.models import LookupResult, Quota

if TYPE_CHECKING:
    import httpx2

# Used when a 429 or 503 has no usable Retry-After
DEFAULT_RETRY_AFTER = 5.0

_CLIENT_ERRORS: dict[int, type[APIError]] = {
    400: InvalidRequestError,
    401: AuthenticationError,
    404: CaseNotFoundError,
    422: CaseUnavailableError,
}


def parse_response(response: httpx2.Response) -> LookupResult:
    """Return the lookup result, or raise the error the response stands for."""
    quota = _quota(response.headers)
    request_id = response.headers.get("x-request-id")
    status_code = response.status_code
    if status_code == 200:
        data = response.json()
        return LookupResult(
            a_number=data["a_number"],
            nationality=Nationality(**data["nationality"]),
            retrieved_at=dt.datetime.fromisoformat(data["retrieved_at"]),
            cached=data["cached"],
            acis=data["acis"],
            quota=quota,
            request_id=request_id,
        )

    body = _error_body(response)
    extra: dict[str, Any] = {}
    if body.get("code") == "quota_exceeded":
        error_class = QuotaExceededError if quota else APIError
    elif status_code in {429, 503}:
        error_class = RetryLaterError
        extra["retry_after"] = _retry_after(response.headers)
    elif status_code >= 500:
        error_class = ServerError
    else:
        error_class = _CLIENT_ERRORS.get(status_code, APIError)
    raise error_class(
        body.get("detail") or response.reason_phrase,
        status_code=status_code,
        quota=quota,
        request_id=request_id,
        **extra,
    )


def _error_body(response: httpx2.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _retry_after(headers: httpx2.Headers) -> float:
    try:
        return max(0.0, float(headers["Retry-After"]))
    except (KeyError, ValueError):
        return DEFAULT_RETRY_AFTER


def _quota(headers: httpx2.Headers) -> Quota | None:
    try:
        return Quota(
            limit=int(headers["X-RateLimit-Limit"]),
            remaining=int(headers["X-RateLimit-Remaining"]),
            reset_at=dt.datetime.fromtimestamp(
                int(headers["X-RateLimit-Reset"]), tz=dt.UTC
            ),
        )
    except (KeyError, ValueError):
        return None
