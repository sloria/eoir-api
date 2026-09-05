"""Wrapper around patchright to drive headed Chrome to do ACIS lookups."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import TYPE_CHECKING, Any, Literal, Self

import structlog
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import TimeoutError as PlaywrightTimeoutError
from patchright.async_api import async_playwright

from acis_browser.a_number import redact
from acis_browser.exceptions import (
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidNationalityError,
    UpstreamError,
)

if TYPE_CHECKING:
    from pathlib import Path
    from types import TracebackType

    from patchright.async_api import (
        BrowserContext,
        Page,
        Playwright,
        Request,
        Response,
    )

logger = structlog.get_logger()

ACIS_URL = "https://acis.eoir.justice.gov/en/"


def option_label(nat_name: str, nat_code: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(f'{nat_name} ({nat_code})')}$", re.IGNORECASE)


##### Outcomes #####


class Outcome(StrEnum):
    """Classification of an ACIS payload by its pinned ``message`` fragments."""

    OK = auto()
    CAPTCHA_REJECTED = auto()
    UNAVAILABLE = auto()
    NOT_FOUND = auto()
    INVALID_NATIONALITY = auto()
    OTHER = auto()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Outcome:
        if isinstance(payload.get("Data"), dict):
            return cls.OK
        message = payload.get("message") or ""
        for fragment, outcome in _MESSAGES:
            if fragment in message:
                return outcome
        return cls.OTHER


_MESSAGES = (
    ("Invalid Captcha Provided", Outcome.CAPTCHA_REJECTED),
    ("Case information is unavailable", Outcome.UNAVAILABLE),
    ("No case info found", Outcome.NOT_FOUND),
    ("Invalid nationality code", Outcome.INVALID_NATIONALITY),
)


def raise_for_outcome(payload: dict[str, Any]) -> None:
    """Raise the exception matching the payload's outcome; return for a success."""
    outcome = Outcome.from_payload(payload)
    if outcome is Outcome.OK:
        return
    message = payload.get("message") or ""
    if outcome is Outcome.CAPTCHA_REJECTED:
        raise CaptchaError(
            message, reason=CaptchaError.Reason.REJECTED, payload=payload
        )
    if outcome is Outcome.NOT_FOUND:
        raise CaseNotFoundError(message, payload=payload)
    if outcome is Outcome.INVALID_NATIONALITY:
        raise InvalidNationalityError(message, payload=payload)
    if outcome is Outcome.UNAVAILABLE:
        raise CaseUnavailableError(message, payload=payload)
    raise UpstreamError(
        message or "ACIS returned an unexpected payload", payload=payload
    )


##### Browser #####


@dataclass
class _Capture:
    requested: bool = False
    status: int = 0
    body: str | None = None
    received: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass(kw_only=True)
class AcisBrowser:
    """A Playwright/Patchright wrapper to do ACIS lookups."""

    profile_dir: Path
    lookup_timeout: float = 20
    lookup_attempts: int = 2
    idle_timeout: float = 900

    # Lock to ensure only one lookup at a time
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _playwright: Playwright | None = field(default=None, init=False, repr=False)
    _context: BrowserContext | None = field(default=None, init=False, repr=False)
    _last_used: float = field(default=0.0, init=False, repr=False)

    ##### Lifecycle #####

    async def start(self) -> None:
        """Launch Chrome. Safe to call repeatedly."""
        if self._context is not None:
            return
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        logger.info("browser starting", profile=str(self.profile_dir))
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            channel="chrome",
            headless=False,
            no_viewport=True,
        )
        self._last_used = time.monotonic()

    async def close(self) -> None:
        if self._context is not None:
            logger.info("browser stopping")
            try:
                await self._context.close()
            finally:
                self._context = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            finally:
                self._playwright = None

    async def close_if_idle(self) -> bool:
        if self._context is None:
            return False
        idle = time.monotonic() - self._last_used
        if idle < self.idle_timeout:
            return False
        async with self._lock:
            # Re-check under the lock: a lookup may have started meanwhile.
            if self._context is None:
                return False
            if time.monotonic() - self._last_used < self.idle_timeout:
                return False
            logger.info("browser idle, closing", idle_seconds=round(idle))
            await self.close()
            return True

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.close()

    ##### Lookup #####

    async def lookup(
        self, a_number: str, nat_code: str, nat_name: str
    ) -> dict[str, Any]:
        """Return the raw ACIS JSON payload for a case, whatever the outcome.

        Retries transient captcha failures. The form takes the nationality
        *name*; the code only disambiguates the option label, since names are
        substrings of one another.
        """
        attempts = self.lookup_attempts
        async with self._lock:
            await self.start()
            self._last_used = time.monotonic()
            try:
                attempt = 0
                while True:
                    attempt += 1
                    try:
                        payload = await self._lookup_once(a_number, nat_code, nat_name)
                    except CaptchaError as exc:
                        logger.warning(
                            "lookup.captcha_failed",
                            attempt=attempt,
                            attempts=attempts,
                            a_number=redact(a_number),
                            nat_code=nat_code,
                            reason=exc.reason,
                            error=str(exc),
                        )
                        if attempt >= attempts:
                            raise
                        await asyncio.sleep(2**attempt)
                    except PlaywrightError as exc:
                        logger.warning("lookup.browser_lost", error=str(exc))
                        with contextlib.suppress(PlaywrightError):
                            await self.close()
                        raise UpstreamError("Chrome is no longer available") from exc
                    else:
                        return payload
            finally:
                self._last_used = time.monotonic()

    async def _lookup_once(
        self, a_number: str, nat_code: str, nat_name: str
    ) -> dict[str, Any]:
        """Fill the form and return the parsed backend response."""
        if self._context is None:  # pragma: no cover
            raise UpstreamError("Browser is not running")
        page = await self._context.new_page()
        captured = _Capture()
        case_info_path = "/api/Case/GetCaseInfo"

        async def on_request(request: Request) -> None:
            if case_info_path in request.url:
                captured.requested = True

        async def on_response(response: Response) -> None:
            if case_info_path not in response.url:
                return
            captured.status = response.status
            try:
                captured.body = await response.text()
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not read ACIS response body", error=str(exc))
            finally:
                captured.received.set()

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            await page.goto(ACIS_URL, wait_until="domcontentloaded", timeout=60_000)
            await self._wait_for(
                page,
                '.ReactModal__Overlay, input[inputmode="numeric"]',
                "app",
                timeout_ms=30_000,
            )
            await self._dismiss_modal(page)
            await self._fill_form(page, a_number, nat_code, nat_name)
            await page.locator("#btn_submit").click()
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(self.lookup_timeout):
                    await captured.received.wait()
        except PlaywrightError as exc:
            raise UpstreamError("Could not lookup case") from exc
        finally:
            try:
                await page.close()
            except PlaywrightError:
                logger.warning("could not close page")

        return self._parse(captured)

    async def _wait_for(
        self,
        page: Page,
        selector: str,
        description: str,
        *,
        state: Literal["attached", "detached", "hidden", "visible"] = "visible",
        timeout_ms: int = 5_000,
    ) -> bool:
        try:
            await page.wait_for_selector(selector, state=state, timeout=timeout_ms)
        except PlaywrightTimeoutError:
            logger.warning("lookup.wait_timeout", condition=description, state=state)
            return False
        return True

    async def _dismiss_modal(self, page: Page) -> None:
        try:
            await page.wait_for_selector(".ReactModal__Overlay", timeout=500)
        except PlaywrightTimeoutError:
            return
        await page.locator(".ReactModalPortal button").last.click()
        await self._wait_for(
            page, ".ReactModal__Overlay", "consent modal to close", state="detached"
        )

    async def _fill_form(
        self, page: Page, a_number: str, nat_code: str, nat_name: str
    ) -> None:
        type_delay = 70  # milliseconds
        await page.locator('input[inputmode="numeric"]').first.click()
        await page.keyboard.type(a_number, delay=type_delay)

        await page.locator("#react-select-3-input").click()
        await page.keyboard.type(nat_name, delay=type_delay)
        option = page.get_by_role("option", name=option_label(nat_name, nat_code))
        await option.first.click(timeout=5000)
        await self._wait_for(
            page, '[role="option"]', "nationality menu to close", state="detached"
        )

    def _parse(self, captured: _Capture) -> dict[str, Any]:
        if not captured.received.is_set():
            if not captured.requested:
                raise CaptchaError(
                    "No captcha token obtained: the form was submitted but no case "
                    "request followed",
                    reason=CaptchaError.Reason.NO_REQUEST,
                )
            raise CaptchaError(
                f"No response to the case request within {self.lookup_timeout}s",
                reason=CaptchaError.Reason.NO_RESPONSE,
            )
        if captured.body is None:
            raise UpstreamError(
                f"Could not read ACIS response body (HTTP {captured.status})"
            )
        status, body = captured.status, captured.body
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise UpstreamError(f"ACIS returned non-JSON (HTTP {status})") from exc
        if not isinstance(payload, dict):
            raise UpstreamError("ACIS returned an unexpected payload")

        outcome = Outcome.from_payload(payload)
        if outcome is Outcome.CAPTCHA_REJECTED:
            raise CaptchaError(
                payload["message"], reason=CaptchaError.Reason.REJECTED, payload=payload
            )
        if outcome not in (Outcome.OK, Outcome.OTHER):
            return payload

        if status != 200:
            raise UpstreamError(f"ACIS returned HTTP {status}")
        return payload
