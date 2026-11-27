from __future__ import annotations

from typing import TYPE_CHECKING, Self

import httpx2

from eoir_api_client._protocol import parse_response
from eoir_api_client.exceptions import NetworkError

if TYPE_CHECKING:
    from eoir_api_client.models import LookupResult

DEFAULT_TIMEOUT = 120.0


class _BaseClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"x-api-key": api_key}

    def _url(self, path: str) -> str:
        return self._base_url + path


class Client(_BaseClient):
    """Synchronous client for eoir-api.

    ``timeout`` is ignored when ``http_client`` is given.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx2.Client | None = None,
    ) -> None:
        super().__init__(base_url, api_key)
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx2.Client(timeout=timeout)

    def lookup(
        self,
        a_number: str,
        nationality: str,
        *,
        refresh: bool = False,
    ) -> LookupResult:
        """Look up a case by A-Number and nationality code or country name.

        Makes one request; retrying is the caller's to schedule.
        """
        body = {"a_number": a_number, "nationality": nationality, "refresh": refresh}
        try:
            response = self._http_client.post(
                self._url("/cases/lookup"), json=body, headers=self._headers
            )
        except httpx2.HTTPError as error:
            raise NetworkError(str(error) or type(error).__name__) from error
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

    ``timeout`` is ignored when ``http_client`` is given.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        http_client: httpx2.AsyncClient | None = None,
    ) -> None:
        super().__init__(base_url, api_key)
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx2.AsyncClient(timeout=timeout)

    async def lookup(
        self,
        a_number: str,
        nationality: str,
        *,
        refresh: bool = False,
    ) -> LookupResult:
        """Look up a case by A-Number and nationality code or country name.

        Makes one request; retrying is the caller's to schedule.
        """
        body = {"a_number": a_number, "nationality": nationality, "refresh": refresh}
        try:
            response = await self._http_client.post(
                self._url("/cases/lookup"), json=body, headers=self._headers
            )
        except httpx2.HTTPError as error:
            raise NetworkError(str(error) or type(error).__name__) from error
        return parse_response(response)

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()
