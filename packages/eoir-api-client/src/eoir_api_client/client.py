from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Self

import anyio
import httpx2

from eoir_api_client._protocol import parse_response
from eoir_api_client.exceptions import APIError, NetworkError, ServerError

if TYPE_CHECKING:
    from collections.abc import Callable

    from eoir_api_client.models import LookupResult

    # Called with the error and the coming wait before each retry.
    OnRetry = Callable[[APIError, float], None]

DEFAULT_TIMEOUT = 120.0
DEFAULT_MAX_ATTEMPTS = 3


class _BaseClient:
    def __init__(self, base_url: str, api_key: str, *, max_attempts: int) -> None:
        self._url = base_url.rstrip("/") + "/cases/lookup"
        self._headers = {"x-api-key": api_key}
        self.max_attempts = max_attempts

    def _retry_delay(
        self, error: APIError, failures: int, on_retry: OnRetry | None
    ) -> float | None:
        """Return the seconds to wait before retrying, or None to give up.

        `RetryLaterError` is never retried here: the wait is the caller's to schedule.
        """
        if failures >= self.max_attempts or not isinstance(
            error, (ServerError, NetworkError)
        ):
            return None
        delay = 2.0 ** (failures - 1)
        if on_retry is not None:
            on_retry(error, delay)
        return delay


class Client(_BaseClient):
    """Synchronous client for eoir-api.

    Network and server errors are tried up to ``max_attempts`` times.
    ``timeout`` is ignored when ``http_client`` is given.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        http_client: httpx2.Client | None = None,
    ) -> None:
        super().__init__(base_url, api_key, max_attempts=max_attempts)
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx2.Client(timeout=timeout)

    def lookup(
        self,
        a_number: str,
        nationality: str,
        *,
        refresh: bool = False,
        on_retry: OnRetry | None = None,
    ) -> LookupResult:
        """Look up a case by A-Number and nationality code or country name.

        Raises `RetryLaterError` without waiting when the API says to retry later.
        """
        body = {"a_number": a_number, "nationality": nationality, "refresh": refresh}
        failures = 0
        while True:
            try:
                return self._send(body)
            except APIError as error:
                failures += 1
                delay = self._retry_delay(error, failures, on_retry)
                if delay is None:
                    raise
            time.sleep(delay)

    def _send(self, body: dict[str, Any]) -> LookupResult:
        try:
            response = self._http_client.post(
                self._url, json=body, headers=self._headers
            )
        except httpx2.HTTPError as error:
            raise NetworkError(str(error)) from error
        return parse_response(response)

    def close(self) -> None:
        if self._owns_http_client:
            self._http_client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


class AsyncClient(_BaseClient):
    """Asynchronous client for eoir-api.

    Network and server errors are tried up to ``max_attempts`` times.
    ``timeout`` is ignored when ``http_client`` is given.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        super().__init__(base_url, api_key, max_attempts=max_attempts)
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx2.AsyncClient(timeout=timeout)

    async def lookup(
        self,
        a_number: str,
        nationality: str,
        *,
        refresh: bool = False,
        on_retry: OnRetry | None = None,
    ) -> LookupResult:
        """Look up a case by A-Number and nationality code or country name.

        Raises `RetryLaterError` without waiting when the API says to retry later.
        """
        body = {"a_number": a_number, "nationality": nationality, "refresh": refresh}
        failures = 0
        while True:
            try:
                return await self._send(body)
            except APIError as error:
                failures += 1
                delay = self._retry_delay(error, failures, on_retry)
                if delay is None:
                    raise
            await anyio.sleep(delay)

    async def _send(self, body: dict[str, Any]) -> LookupResult:
        try:
            response = await self._http_client.post(
                self._url, json=body, headers=self._headers
            )
        except httpx2.HTTPError as error:
            raise NetworkError(str(error)) from error
        return parse_response(response)

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
