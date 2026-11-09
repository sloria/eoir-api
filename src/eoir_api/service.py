"""Service class for looking up cases. Composes the browser, the cache, and queue mgmt."""

from __future__ import annotations

import datetime as dt  # noqa: TC003
import math
import time
from collections import Counter
from collections.abc import Callable, Mapping  # noqa: TC003
from dataclasses import dataclass, field
from typing import Any, Protocol

import anyio
import msgspec
import structlog
from acis_browser import (
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidNationalityError,
    Outcome,
    raise_for_outcome,
)
from acis_core.nationalities import Nationality

from eoir_api.exceptions import (
    BrowserUnavailableError,
    QueueTimeoutError,
    QuotaExceededError,
)
from eoir_api.lib.cache import TTLCache
from eoir_api.settings import Settings
from eoir_api.usage import LookupOutcome, TenantUsage

logger = structlog.get_logger()

# Weight for the exponential moving average of lookup duration.
EWMA_ALPHA = 0.3


class SupportsLookup(Protocol):
    async def lookup(
        self, a_number: str, nat_code: str, nat_name: str
    ) -> dict[str, Any]: ...


@dataclass(eq=False)  # eq=False to make slots hashable (usable in a set)
class BrowserSlot:
    """Container for a browser and its pacing state."""

    name: str
    browser: SupportsLookup
    group: str | None
    lock: anyio.Lock = field(default_factory=anyio.Lock)
    last_started: float = -math.inf
    cooldown_until: float = -math.inf

    def in_cooldown(self, now: float) -> bool:
        return now < self.cooldown_until


OUTCOMES: dict[type[Exception], LookupOutcome] = {
    CaseNotFoundError: "not_found",
    InvalidNationalityError: "invalid_nationality",
    CaseUnavailableError: "unavailable",
    CaptchaError: "captcha",
    # Every browser left is cooling down after a captcha failure
    BrowserUnavailableError: "captcha",
}


def outcome_of(exc: Exception) -> LookupOutcome:
    return OUTCOMES.get(type(exc), "upstream_error")


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
    _tenant_pending: Counter[str] = field(default_factory=Counter, init=False)

    def __post_init__(self) -> None:
        # Not a dataclass field: msgspec resolves field annotations when Litestar
        # builds the signature model, and it cannot evaluate TTLCache's PEP 695 type
        # parameter.
        self._cache: TTLCache[dict[str, Any]] = TTLCache(
            ttl=self.settings.lookup.cache_ttl
        )
        groups = {b.name: b.group for b in self.settings.browsers}
        self._slots = [
            BrowserSlot(name, b, groups.get(name)) for name, b in self.browsers.items()
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

    def _pick_browser(self, exclude: set[BrowserSlot]) -> BrowserSlot:
        now = self.clock()
        tried_groups = {slot.group for slot in exclude} - {None}
        candidates = [
            slot
            for slot in self._slots
            if slot not in exclude and not slot.in_cooldown(now)
        ]
        if not candidates:
            raise self._unavailable()
        return min(
            candidates,
            key=lambda slot: (
                # On a retry, pick a browser from the following, in order:
                # An untried group
                slot.group in tried_groups,
                # the group challenged longest ago
                self._last_challenged(slot) if exclude else -math.inf,
                # unlocked
                slot.lock.locked(),
                # least recently used
                slot.last_started,
            ),
        )

    def _last_challenged(self, slot: BrowserSlot) -> float:
        if slot.group is None:
            return slot.cooldown_until
        return max(s.cooldown_until for s in self._slots if s.group == slot.group)

    async def _lookup(
        self, a_number: str, nationality: Nationality
    ) -> tuple[dict[str, Any], BrowserSlot, float]:
        tried: set[BrowserSlot] = set()
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
                        EWMA_ALPHA * duration
                        + (1 - EWMA_ALPHA) * self.avg_lookup_seconds
                    )
                return payload, slot, duration

    async def _check_quota(self, usage: TenantUsage) -> None:
        quota = await usage.quota()
        if quota is None or quota.remaining > 0:
            return
        retry_after = quota.reset_in()
        logger.info("lookup.quota_exceeded", retry_after=retry_after)
        raise QuotaExceededError("Daily quota exceeded", retry_after=retry_after)

    async def get_case(
        self,
        a_number: str,
        nationality: Nationality,
        *,
        usage: TenantUsage,
        refresh: bool = False,
    ) -> Case:
        """Return the case for an A-Number and nationality, recording the lookup.

        Raises ``QuotaExceededError`` if the tenant is out of quota,
        ``QueueTimeoutError`` if the tenant is at its concurrency cap or the request
        would wait too long and
        ``BrowserUnavailableError`` if every browser is in a captcha cooldown.
        """
        key = (a_number, nationality.code)
        if not refresh:
            entry = self._cache.get(key)
            if entry is not None:
                logger.debug("lookup.cache_hit", nat_code=nationality.code)
                await usage.record(outcome="ok", cached=True)
                return Case(
                    a_number=a_number,
                    nationality=nationality,
                    retrieved_at=entry.stored_at,
                    cached=True,
                    acis=entry.value,
                )

        await self._check_quota(usage)
        tenant = usage.tenant
        max_concurrency = tenant.max_concurrency
        if (
            max_concurrency is not None
            and self._tenant_pending[tenant.name] >= max_concurrency
        ):
            raise QueueTimeoutError(
                f"Tenant max_concurrency of {max_concurrency} reached",
                max_concurrency=max_concurrency,
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
        self._tenant_pending[tenant.name] += 1
        started = self.clock()
        outcome: LookupOutcome = "ok"
        logger.info("lookup.start", nat_code=nationality.code, pending=self._pending)
        try:
            payload, slot, duration = await self._lookup(a_number, nationality)
            upstream = Outcome.from_payload(payload)
            if upstream is not Outcome.OK:
                logger.info(
                    "lookup.no_case",
                    nat_code=nationality.code,
                    browser=slot.name,
                    group=slot.group,
                    outcome=upstream,
                )
            raise_for_outcome(payload)
        except Exception as exc:
            outcome = outcome_of(exc)
            logger.warning(
                "lookup.failed",
                nat_code=nationality.code,
                error=type(exc).__name__,
                outcome=outcome,
                elapsed=round(self.clock() - started, 1),
            )
            raise
        finally:
            self._pending -= 1
            self._tenant_pending[tenant.name] -= 1
            await usage.record(
                outcome=outcome,
                cached=False,
                duration_ms=round((self.clock() - started) * 1000),
            )

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
