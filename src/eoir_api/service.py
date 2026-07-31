"""Service class for looking up cases. Composes the browser, the cache, and queue mgmt."""

from __future__ import annotations

import datetime as dt  # noqa: TC003
import time
from typing import TYPE_CHECKING, Any, Protocol

import msgspec
import structlog

from eoir_api.exceptions import QueueTimeoutError
from eoir_api.lib.cache import TTLCache
from eoir_api.nationalities import Nationality

if TYPE_CHECKING:
    from eoir_api.settings import Settings

logger = structlog.get_logger()

# Weight for the exponential moving average of lookup duration.
_EWMA_ALPHA = 0.3


class SupportsLookup(Protocol):
    async def lookup(self, a_number: str, nat_code: str) -> dict[str, Any]: ...


class CaseResponse(msgspec.Struct):
    a_number: str
    nationality: Nationality
    retrieved_at: dt.datetime
    cached: bool
    acis: dict[str, Any]


class CaseService:
    def __init__(self, browser: SupportsLookup, settings: Settings) -> None:
        self._browser = browser
        self._settings = settings
        self._cache: TTLCache[dict[str, Any]] = TTLCache(ttl=settings.cache_ttl)
        self._pending = 0
        self.avg_lookup_seconds = 10.0

    @property
    def pending(self) -> int:
        return self._pending

    @property
    def estimated_wait(self) -> float:
        """Projected seconds before a newly-arriving request would start."""
        return self._pending * self.avg_lookup_seconds

    async def get_case(
        self, a_number: str, nationality: Nationality, *, refresh: bool = False
    ) -> CaseResponse:
        """Return the API response body for a case.

        Raises ``QueueTimeoutError`` if the request would wait too long.
        """
        key = (a_number, nationality.code)
        if not refresh:
            entry = self._cache.get(key)
            if entry is not None:
                logger.debug("lookup.cache_hit", nat_code=nationality.code)
                return CaseResponse(
                    a_number=a_number,
                    nationality=nationality,
                    retrieved_at=entry.stored_at,
                    cached=True,
                    acis=entry.value,
                )

        if self.estimated_wait > self._settings.max_queue_wait:
            raise QueueTimeoutError(
                f"Estimated wait {self.estimated_wait:.0f}s exceeds "
                f"{self._settings.max_queue_wait}s; retry shortly"
            )

        self._pending += 1
        started = time.monotonic()
        logger.info("lookup.start", nat_code=nationality.code, pending=self._pending)
        try:
            payload = await self._browser.lookup(a_number, nationality.code)
        except Exception as exc:
            logger.warning(
                "lookup.failed", nat_code=nationality.code, error=type(exc).__name__
            )
            raise
        finally:
            self._pending -= 1
            duration = time.monotonic() - started
            self.avg_lookup_seconds = (
                _EWMA_ALPHA * duration + (1 - _EWMA_ALPHA) * self.avg_lookup_seconds
            )

        entry = self._cache.set(key, payload)
        logger.info(
            "lookup.success",
            nat_code=nationality.code,
            duration=round(duration, 1),
        )
        return CaseResponse(
            a_number=a_number,
            nationality=nationality,
            retrieved_at=entry.stored_at,
            cached=False,
            acis=payload,
        )
