"""Service class for looking up cases. Composes the browser, the cache, and queue mgmt."""

from __future__ import annotations

import datetime as dt  # noqa: TC003
import math
import time
from collections.abc import Callable, Mapping  # noqa: TC003
from dataclasses import dataclass, field
from typing import Any, Protocol

import anyio
import msgspec
import structlog
from acis_browser import CaptchaError, raise_for_outcome
from acis_core.nationalities import Nationality

from eoir_api.exceptions import BrowserUnavailableError, QueueTimeoutError
from eoir_api.lib.cache import TTLCache
from eoir_api.settings import Settings

logger = structlog.get_logger()

# Weight for the exponential moving average of lookup duration.
_EWMA_ALPHA = 0.3


class SupportsLookup(Protocol):
    async def lookup(
        self, a_number: str, nat_code: str, nat_name: str
    ) -> dict[str, Any]: ...


@dataclass(eq=False)  # eq=False to make slots hashable (usable in a set)
class _BrowserSlot:
    """Container for a browser and its pacing state."""

    name: str
    browser: SupportsLookup
    lock: anyio.Lock = field(default_factory=anyio.Lock)
    last_started: float = -math.inf
    cooldown_until: float = -math.inf

    def in_cooldown(self, now: float) -> bool:
        return now < self.cooldown_until


class Case(msgspec.Struct):
    a_number: str
    nationality: Nationality
    retrieved_at: dt.datetime
    cached: bool
    acis: dict[str, Any]


@dataclass
class CaseService:
    """Looks up cases on one or more browsers. Handles caching and pacing."""

    browsers: Mapping[str, SupportsLookup]
    settings: Settings
    clock: Callable[[], float] = time.monotonic

    avg_lookup_seconds: float = field(default=10.0, init=False)
    _pending: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        # Not a dataclass field: msgspec resolves field annotations when Litestar
        # builds the signature model, and it cannot evaluate TTLCache's PEP 695 type
        # parameter.
        self._cache: TTLCache[dict[str, Any]] = TTLCache(ttl=self.settings.cache_ttl)
        self._slots = [_BrowserSlot(name, b) for name, b in self.browsers.items()]

    @property
    def pending(self) -> int:
        return self._pending

    @property
    def estimated_wait(self) -> float:
        """Projected seconds before a newly-arriving request would start."""
        now = self.clock()
        available = sum(not slot.in_cooldown(now) for slot in self._slots)
        per_lookup = max(self.avg_lookup_seconds, self.settings.lookup_interval)
        return self._pending * per_lookup / max(1, available)

    def _unavailable(self, now: float) -> BrowserUnavailableError:
        cooldown_ends = min(s.cooldown_until for s in self._slots if s.in_cooldown(now))
        return BrowserUnavailableError(
            "No browser available for lookup.", retry_after=cooldown_ends - now
        )

    def _pick_browser(self, exclude: set[_BrowserSlot]) -> _BrowserSlot:
        now = self.clock()
        candidates = [
            slot
            for slot in self._slots
            if slot not in exclude and not slot.in_cooldown(now)
        ]
        if not candidates:
            raise self._unavailable(now)
        # unlocked first, then least recently used
        return min(candidates, key=lambda slot: (slot.lock.locked(), slot.last_started))

    async def _lookup(
        self, a_number: str, nationality: Nationality
    ) -> tuple[dict[str, Any], str, float]:
        tried: set[_BrowserSlot] = set()
        while True:
            slot = self._pick_browser(tried)
            tried.add(slot)
            async with slot.lock:
                now = self.clock()
                if slot.in_cooldown(now):  # cooled down while waiting for the lock
                    continue
                delay = self.settings.lookup_interval - (now - slot.last_started)
                if delay > 0:
                    if delay >= 1:
                        logger.info(
                            "lookup.pacing", browser=slot.name, delay=round(delay)
                        )
                    await anyio.sleep(delay)
                slot.last_started = self.clock()
                try:
                    with structlog.contextvars.bound_contextvars(browser=slot.name):
                        payload = await slot.browser.lookup(
                            a_number, nationality.code, nationality.name
                        )
                except CaptchaError as exc:
                    if exc.reason is CaptchaError.Reason.REJECTED:
                        slot.cooldown_until = (
                            self.clock() + self.settings.captcha_cooldown
                        )
                        logger.warning(
                            "lookup.cooldown",
                            browser=slot.name,
                            seconds=self.settings.captcha_cooldown,
                        )
                    if len(tried) == len(self._slots):
                        raise
                    continue
                finally:
                    duration = self.clock() - slot.last_started
                    self.avg_lookup_seconds = (
                        _EWMA_ALPHA * duration
                        + (1 - _EWMA_ALPHA) * self.avg_lookup_seconds
                    )
                return payload, slot.name, duration

    async def get_case(
        self, a_number: str, nationality: Nationality, *, refresh: bool = False
    ) -> Case:
        """Return the case for an A-Number and nationality.

        Raises ``QueueTimeoutError`` if the request would wait too long and
        ``BrowserUnavailableError`` if every browser is in a captcha cooldown.
        """
        key = (a_number, nationality.code)
        if not refresh:
            entry = self._cache.get(key)
            if entry is not None:
                logger.debug("lookup.cache_hit", nat_code=nationality.code)
                return Case(
                    a_number=a_number,
                    nationality=nationality,
                    retrieved_at=entry.stored_at,
                    cached=True,
                    acis=entry.value,
                )

        now = self.clock()
        if all(slot.in_cooldown(now) for slot in self._slots):
            raise self._unavailable(now)
        wait = self.estimated_wait
        if wait > self.settings.max_queue_wait:
            raise QueueTimeoutError(
                f"Estimated wait {wait:.0f}s exceeds "
                f"{self.settings.max_queue_wait}s; retry shortly"
            )

        self._pending += 1
        logger.info("lookup.start", nat_code=nationality.code, pending=self._pending)
        try:
            payload, browser_name, duration = await self._lookup(a_number, nationality)
        except Exception as exc:
            logger.warning(
                "lookup.failed", nat_code=nationality.code, error=type(exc).__name__
            )
            raise
        finally:
            self._pending -= 1

        raise_for_outcome(payload)
        entry = self._cache.set(key, payload)
        logger.info(
            "lookup.success",
            nat_code=nationality.code,
            browser=browser_name,
            duration=round(duration, 1),
        )
        return Case(
            a_number=a_number,
            nationality=nationality,
            retrieved_at=entry.stored_at,
            cached=False,
            acis=payload,
        )
