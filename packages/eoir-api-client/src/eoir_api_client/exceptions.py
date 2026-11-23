from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from eoir_api_client.models import Quota


class APIError(Exception):
    """Base class for all client errors."""

    def __init__(
        self,
        detail: str,
        *,
        status_code: int | None = None,
        quota: Quota | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.quota = quota
        self.request_id = request_id


class InvalidRequestError(APIError):
    """Invalid A-Number, unknown nationality, or malformed body."""


class AuthenticationError(APIError):
    """Invalid or missing API key."""


class CaseNotFoundError(APIError):
    """No case found for that A-Number and nationality."""


class CaseUnavailableError(APIError):
    """The case exists but ACIS won't release information for it."""


class RetryLaterError(APIError):
    """Lookups are temporarily unavailable; retry after ``retry_after`` seconds.

    ``status_code`` is 429 when too many lookups are pending and 503 when
    lookups are paused, e.g. after a captcha.
    """

    def __init__(self, detail: str, *, retry_after: float, **kwargs: Any) -> None:
        super().__init__(detail, **kwargs)
        self.retry_after = retry_after


class QuotaExceededError(RetryLaterError):
    """The daily quota is used up."""


class ServerError(APIError):
    """The API failed or ACIS returned an unexpected response."""


class NetworkError(APIError):
    """The request never got a response."""
