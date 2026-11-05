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
from acis_browser import CaptchaError, Outcome, raise_for_outcome
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
    group: str | None
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
        self._cache: TTLCache[dict[str, Any]] = TTLCache(
            ttl=self.settings.lookup.cache_ttl
        )
        groups = {b.name: b.group for b in self.settings.browsers}
        self._slots = [
            _BrowserSlot(name, b, groups.get(name)) for name, b in self.browsers.items()
        ]

    @property
    def pending(self) -> int:
        return self._pending

    @property
    def estimated_wait(self) -> float:
        """Projected seconds before a newly-arriving request would start."""
        now = self.clock()
        available = sum(not slot.in_cooldown(now) for slot in self._slots)
        per_lookup = max(self.avg_lookup_seconds, self.settings.lookup.interval)
        return self._pending * per_lookup / max(1, available)

    @property
    def retry_after(self) -> float:
        """Seconds until a browser is out of captcha cooldown; 0 if one is now."""
        cooldown_ends = min(slot.cooldown_until for slot in self._slots)
        return max(0, cooldown_ends - self.clock())

    def _unavailable(self) -> BrowserUnavailableError:
        return BrowserUnavailableError(
            "No browser available for lookup.", retry_after=self.retry_after
        )

    def _pick_browser(self, exclude: set[_BrowserSlot]) -> _BrowserSlot:
        now = self.clock()
        tried_groups = {slot.group for slot in exclude} - {None}
        candidates = [
            slot
            for slot in self._slots
            if slot not in exclude and not slot.in_cooldown(now)
        ]
        if not candidates:
            raise self._unavailable()
        # untried group first, then unlocked, then least recently used
        return min(
            candidates,
            key=lambda slot: (
                slot.group in tried_groups,
                slot.lock.locked(),
                slot.last_started,
            ),
        )

    async def _lookup(
        self, a_number: str, nationality: Nationality
    ) -> tuple[dict[str, Any], _BrowserSlot, float]:
        tried: set[_BrowserSlot] = set()
        max_browsers = min(self.settings.lookup.max_browsers, len(self._slots))
        while True:
            slot = self._pick_browser(tried)
            async with slot.lock:
                now = self.clock()
                if slot.in_cooldown(now):  # cooled down while waiting for the lock
                    continue
                tried.add(slot)
                delay = self.settings.lookup.interval - (now - slot.last_started)
                if delay > 0:
                    if delay >= 1:
                        logger.info(
                            "lookup.pacing",
                            browser=slot.name,
                            group=slot.group,
                            delay=round(delay),
                        )
                    await anyio.sleep(delay)
                slot.last_started = self.clock()
                try:
                    with structlog.contextvars.bound_contextvars(
                        browser=slot.name, group=slot.group
                    ):
                        payload = await slot.browser.lookup(
                            a_number, nationality.code, nationality.name
                        )
                except CaptchaError as exc:
                    if exc.reason is not CaptchaError.Reason.NO_RESPONSE:
                        slot.cooldown_until = (
                            self.clock() + self.settings.lookup.captcha_cooldown
                        )
                        logger.warning(
                            "lookup.cooldown",
                            browser=slot.name,
                            group=slot.group,
                            seconds=self.settings.lookup.captcha_cooldown,
                        )
                    if len(tried) >= max_browsers:
                        logger.warning("lookup.capped", browsers=len(tried))
                        raise
                    continue
                finally:
                    duration = self.clock() - slot.last_started
                    self.avg_lookup_seconds = (
                        _EWMA_ALPHA * duration
                        + (1 - _EWMA_ALPHA) * self.avg_lookup_seconds
                    )
                return payload, slot, duration

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
            raise self._unavailable()
        wait = self.estimated_wait
        if wait > self.settings.lookup.max_queue_wait:
            raise QueueTimeoutError(
                f"Estimated wait {wait:.0f}s exceeds "
                f"{self.settings.lookup.max_queue_wait}s; retry shortly"
            )

        self._pending += 1
        started = self.clock()
        logger.info("lookup.start", nat_code=nationality.code, pending=self._pending)
        try:
            payload, slot, duration = await self._lookup(a_number, nationality)
        except Exception as exc:
            logger.warning(
                "lookup.failed",
                nat_code=nationality.code,
                error=type(exc).__name__,
                elapsed=round(self.clock() - started, 1),
            )
            raise
        finally:
            self._pending -= 1

        outcome = Outcome.from_payload(payload)
        if outcome is not Outcome.OK:
            logger.info(
                "lookup.no_case",
                nat_code=nationality.code,
                browser=slot.name,
                group=slot.group,
                outcome=outcome,
            )
        raise_for_outcome(payload)
        entry = self._cache.set(key, payload)
        logger.info(
            "lookup.success",
            nat_code=nationality.code,
            browser=slot.name,
            group=slot.group,
            duration=round(duration, 1),
            elapsed=round(self.clock() - started, 1),
        )
        return Case(
            a_number=a_number,
            nationality=nationality,
            retrieved_at=entry.stored_at,
            cached=False,
            acis=payload,
        )
