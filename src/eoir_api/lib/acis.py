"""Wrapper around patchright to drive headed Chrome to do ACIS lookups."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Self

import anyio
import structlog
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import TimeoutError as PlaywrightTimeoutError
from patchright.async_api import async_playwright

from eoir_api.exceptions import (
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    UpstreamError,
)
from eoir_api.nationalities import get_by_code

if TYPE_CHECKING:
    from types import TracebackType

    from patchright.async_api import (
        BrowserContext,
        Page,
        Playwright,
        Request,
        Response,
    )

    from eoir_api.settings import Settings

logger = structlog.get_logger()

ACIS_URL = "https://acis.eoir.justice.gov/en/"
CASE_INFO_PATH = "/api/Case/GetCaseInfo"
WAIT_UNTIL = "domcontentloaded"

MODAL_OVERLAY_SELECTOR = ".ReactModal__Overlay"
MODAL_BUTTON_SELECTOR = ".ReactModalPortal button"
DIGIT_INPUT_SELECTOR = 'input[inputmode="numeric"]'
NATIONALITY_INPUT_SELECTOR = "#react-select-3-input"
NATIONALITY_OPTION_SELECTOR = '[role="option"]'
APP_READY_SELECTOR = f"{MODAL_OVERLAY_SELECTOR}, {DIGIT_INPUT_SELECTOR}"

SUBMIT_SELECTOR = "#btn_submit"
TYPE_DELAY = 70

CAPTCHA_ERROR_FRAGMENT = "Invalid Captcha Provided"
NOT_FOUND_FRAGMENTS = ("No case info found", "Invalid nationality code")
UNAVAILABLE_FRAGMENT = "Case information is unavailable"

##### Browser #####


@dataclass
class _Capture:
    requested: bool = False
    status: int = 0
    body: str | None = None
    received: anyio.Event = field(default_factory=anyio.Event)


class AcisBrowser:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Lock to ensure only one lookup at a time
        self._lock = anyio.Lock()
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._last_used: float = 0.0

    ##### Lifecycle #####

    async def start(self) -> None:
        """Launch Chrome. Safe to call repeatedly."""
        if self._context is not None:
            return
        settings = self._settings
        settings.chrome_profile_dir.mkdir(parents=True, exist_ok=True)
        logger.info("browser starting", profile=str(settings.chrome_profile_dir))
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(settings.chrome_profile_dir),
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
        if idle < self._settings.browser_idle_timeout:
            return False
        async with self._lock:
            # Re-check under the lock: a lookup may have started meanwhile.
            if self._context is None:
                return False
            if time.monotonic() - self._last_used < self._settings.browser_idle_timeout:
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

    async def lookup(self, a_number: str, nat_code: str) -> dict[str, Any]:
        """Return the raw ACIS JSON payload for a case. Retries transient captcha failures."""
        attempts = self._settings.lookup_attempts
        async with self._lock:
            await self.start()
            self._last_used = time.monotonic()
            try:
                attempt = 0
                while True:
                    attempt += 1
                    try:
                        payload = await self._lookup_once(a_number, nat_code)
                    except CaptchaError as exc:
                        logger.warning(
                            "lookup.captcha_failed",
                            attempt=attempt,
                            attempts=attempts,
                            nat_code=nat_code,
                            reason=exc.reason,
                            error=str(exc),
                        )
                        if attempt >= attempts:
                            raise
                        await anyio.sleep(2**attempt)
                    else:
                        return payload
            finally:
                self._last_used = time.monotonic()

    async def _lookup_once(self, a_number: str, nat_code: str) -> dict[str, Any]:
        """Drive the form and return the parsed backend response."""
        if self._context is None:  # pragma: no cover
            raise UpstreamError("Browser is not running")
        page = await self._context.new_page()
        captured = _Capture()

        async def on_request(request: Request) -> None:
            if CASE_INFO_PATH in request.url:
                captured.requested = True

        async def on_response(response: Response) -> None:
            if CASE_INFO_PATH not in response.url:
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
            await page.goto(ACIS_URL, wait_until=WAIT_UNTIL, timeout=60_000)
            await self._wait_for(page, APP_READY_SELECTOR, "app", timeout_ms=30_000)
            await self._dismiss_modal(page)
            await self._fill_form(page, a_number, nat_code)
            await page.locator(SUBMIT_SELECTOR).click()
            with anyio.move_on_after(self._settings.lookup_timeout):
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
            await page.wait_for_selector(MODAL_OVERLAY_SELECTOR, timeout=500)
        except PlaywrightTimeoutError:
            return
        await page.locator(MODAL_BUTTON_SELECTOR).last.click()
        await self._wait_for(
            page, MODAL_OVERLAY_SELECTOR, "consent modal to close", state="detached"
        )

    async def _fill_form(self, page: Page, a_number: str, nat_code: str) -> None:
        await page.locator(DIGIT_INPUT_SELECTOR).first.click()
        await page.keyboard.type(a_number, delay=TYPE_DELAY)

        await page.locator(NATIONALITY_INPUT_SELECTOR).click()
        await page.keyboard.type(get_by_code(nat_code).name, delay=TYPE_DELAY)
        await self._wait_for(page, NATIONALITY_OPTION_SELECTOR, "nationality options")
        await page.keyboard.press("Enter")
        await self._wait_for(
            page,
            NATIONALITY_OPTION_SELECTOR,
            "nationality menu to close",
            state="detached",
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
                "No response to the case request within "
                f"{self._settings.lookup_timeout}s",
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

        message = payload.get("message") if isinstance(payload, dict) else None
        if message:
            if CAPTCHA_ERROR_FRAGMENT in message:
                raise CaptchaError(message, reason=CaptchaError.Reason.REJECTED)
            if UNAVAILABLE_FRAGMENT in message:
                raise CaseUnavailableError(message)
            if any(fragment in message for fragment in NOT_FOUND_FRAGMENTS):
                raise CaseNotFoundError(message)
            raise UpstreamError(message)

        if status != 200:
            raise UpstreamError(f"ACIS returned HTTP {status}")
        if not isinstance(payload, dict):
            raise UpstreamError("ACIS returned an unexpected payload shape")
        return payload
