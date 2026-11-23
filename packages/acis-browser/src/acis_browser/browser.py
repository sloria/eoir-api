"""Wrapper around patchright to drive headed Chrome to do ACIS lookups."""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import shutil
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Self

import structlog
from acis_core.outcome import Outcome
from patchright._impl._errors import TargetClosedError  # not re-exported publicly
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import TimeoutError as PlaywrightTimeoutError
from patchright.async_api import async_playwright

from acis_browser._intercept import (
    PLACEHOLDER,
    CaseQuery,
    WarmPage,
    case_of,
)
from acis_browser.exceptions import (
    BrowserLostError,
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
        ProxySettings,
        Request,
        Response,
    )

logger = structlog.get_logger()

ACIS_ORIGIN = "https://acis.eoir.justice.gov"
ACIS_URL = f"{ACIS_ORIGIN}/en/"
HCAPTCHA_IFRAME = 'iframe[src*="hcaptcha.com"]'
CHALLENGE_IFRAME = f'{HCAPTCHA_IFRAME}[src*="frame=challenge"]'
CASE_INFO_PATH = "/api/Case/GetCaseInfo"
CASE_INFO_URL = re.compile(rf"{re.escape(CASE_INFO_PATH)}\?")

BROWSER_LOST_ERRORS = (PlaywrightError, RuntimeError)


def purge_site_storage(profile_dir: Path) -> None:
    """Remove on-disk storage that could hold case data."""
    for name in (
        "Cache",
        "IndexedDB",
        "Local Storage",
        "Service Worker",
        "Session Storage",
        "Sessions",
        "Sessions_Encrypted",
        "WebStorage",
    ):
        shutil.rmtree(profile_dir / "Default" / name, ignore_errors=True)


def option_label(nat_name: str, nat_code: str) -> re.Pattern[str]:
    return re.compile(rf"^{re.escape(f'{nat_name} ({nat_code})')}$", re.IGNORECASE)


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
    raise UpstreamError("ACIS returned an unexpected payload", payload=payload)


##### Browser #####


@dataclass
class Capture:
    requested: bool = False
    challenged: bool = False
    status: int = 0
    url: str = ""
    body: str | None = None
    received: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass(kw_only=True)
class AcisBrowser:
    """A Playwright/Patchright wrapper to do ACIS lookups."""

    profile_dir: Path
    lookup_timeout: float = 20
    lookup_attempts: int = 1
    proxy: ProxySettings | None = None
    intercept: bool = False

    last_used: float = field(default=0.0, init=False)
    # Lock to ensure only one lookup or close at a time
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)
    _playwright: Playwright | None = field(default=None, init=False, repr=False)
    _context: BrowserContext | None = field(default=None, init=False, repr=False)
    _warm_task: asyncio.Task[WarmPage | None] | None = field(
        default=None, init=False, repr=False
    )

    ##### Lifecycle #####

    @property
    def is_running(self) -> bool:
        return self._context is not None

    async def start(self) -> None:
        """Launch Chrome. Safe to call repeatedly."""
        if self._context is not None:
            return
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        purge_site_storage(self.profile_dir)
        # XXX: A file where Chrome expects its cache dir makes the cache
        # backend fail to start, so Chrome runs with no HTTP disk cache and
        # case responses (keyed by a URL holding the A-number) never touch disk
        cache_blocker = self.profile_dir / "disk-cache-disabled"
        cache_blocker.touch()
        logger.info("browser starting", profile=str(self.profile_dir))
        self._playwright = await async_playwright().start()
        self._context = await self._playwright.chromium.launch_persistent_context(
            str(self.profile_dir),
            channel="chrome",
            headless=False,
            no_viewport=True,
            proxy=self.proxy,
            args=[f"--disk-cache-dir={cache_blocker}"],
        )

    async def close(self) -> None:
        async with self._lock:
            await self._close()

    async def _close(self) -> None:
        if self._warm_task is not None:
            self._warm_task.cancel()
            await asyncio.gather(self._warm_task, return_exceptions=True)
            self._warm_task = None
        if self._context is not None:
            logger.info("browser stopping")
            try:
                await self._context.close()
                purge_site_storage(self.profile_dir)
            except BROWSER_LOST_ERRORS as exc:
                logger.warning("browser.close_failed", error=str(exc))
            finally:
                self._context = None
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            finally:
                self._playwright = None

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
            self.last_used = time.monotonic()
            await self.start()
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
                            reason=exc.reason,
                            error=str(exc),
                        )
                        if attempt >= attempts:
                            raise
                        await asyncio.sleep(2**attempt)
                    except BROWSER_LOST_ERRORS as exc:
                        logger.warning("lookup.browser_lost", error=str(exc))
                        with contextlib.suppress(*BROWSER_LOST_ERRORS):
                            await self._close()
                        raise BrowserLostError("Chrome is no longer available") from exc
                    else:
                        if self.intercept and self._warm_task is None:
                            self._warm_task = asyncio.create_task(self._warm())
                        return payload
            finally:
                self.last_used = time.monotonic()

    async def _warm(self) -> WarmPage | None:
        """Open a new page with the form filled with the placeholder."""
        if self._context is None:  # pragma: no cover
            return None
        try:
            warm = WarmPage(await self._context.new_page())
            try:
                await self._open_form(warm.page)
                await self._fill_form(warm.page, *PLACEHOLDER)
                await warm.install_route(CASE_INFO_URL)
                await self._wait_for_captcha(warm.page)
            except BaseException:
                await self._close_page(warm.page)
                raise
        except Exception as exc:  # noqa: BLE001 Not BaseException because CancelledError shouldn't be swallowed
            logger.warning("lookup.warm_failed", error=str(exc))
            return None
        warm.ready_at = time.monotonic()
        return warm

    async def _take_warm_page(
        self, case: CaseQuery, capture: Capture
    ) -> WarmPage | None:
        """Return the warm page set to send the case if still valid, else discard it."""
        if not re.fullmatch(r"\d{9}", case.a_number):
            return None
        task, self._warm_task = self._warm_task, None
        try:
            warm = await asyncio.wait_for(task, self.lookup_timeout) if task else None
        except TimeoutError:
            logger.warning("lookup.warm_timeout")
            return None
        if warm is None:
            return None
        is_fresh = False
        try:
            is_fresh = (
                not warm.page.is_closed()
                # Warm page was loaded with the modal accepted; it may have expired
                and await self._modal_was_accepted(warm.page.context)
            )
            if is_fresh:
                warm.case, warm.capture = case, capture
                return warm
            logger.info("lookup.warm_page_stale", age=warm.age)
        except BROWSER_LOST_ERRORS as exc:
            logger.warning("lookup.warm_failed", error=str(exc))
        finally:
            if not is_fresh:
                await self._close_page(warm.page)
        return None

    async def _lookup_once(
        self, a_number: str, nat_code: str, nat_name: str
    ) -> dict[str, Any]:
        """Fill the form, or submit a warm one, and return the parsed response."""
        if self._context is None:  # pragma: no cover
            raise BrowserLostError("Browser is not running")
        case = CaseQuery(a_number, nat_code.upper())
        capture = Capture()
        warm = await self._take_warm_page(case, capture)
        structlog.contextvars.bind_contextvars(is_warm=warm is not None)
        logger.debug("lookup.page", age=warm.age if warm else None)
        page = warm.page if warm else await self._context.new_page()

        async def on_request(request: Request) -> None:
            if CASE_INFO_PATH in request.url:
                capture.requested = True

        async def on_response(response: Response) -> None:
            if CASE_INFO_PATH not in response.url:
                return
            capture.status = response.status
            capture.url = response.url
            try:
                capture.body = await response.text()
            except Exception as exc:  # noqa: BLE001
                logger.warning("could not read ACIS response body", error=str(exc))
            finally:
                capture.received.set()

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            if warm is None:
                await self._open_form(page)
                await self._fill_form(page, a_number, nat_code, nat_name)
                await self._wait_for_captcha(page)
            await page.locator("#btn_submit").click()
            await self._wait_for_response(page, capture)
        except TargetClosedError:
            raise
        except PlaywrightError as exc:
            raise UpstreamError("Could not lookup case") from exc
        finally:
            try:
                await self._clear_site_storage(page)
            except BROWSER_LOST_ERRORS as exc:
                logger.warning("could not clear site storage", error=str(exc))
            await self._close_page(page)

        if warm and capture.received.is_set() and case_of(capture.url) != case:
            raise UpstreamError("Case request was not rewritten")
        return self._parse(capture)

    async def _close_page(self, page: Page) -> None:
        try:
            await page.close()
        except BROWSER_LOST_ERRORS:
            logger.warning("could not close page")

    async def _open_form(self, page: Page) -> None:
        await page.goto(ACIS_URL, wait_until="domcontentloaded", timeout=60_000)
        app_hydrated = await self._wait_for(
            page,
            "html[data-react-helmet]",
            "app to hydrate",
            state="attached",
            timeout_ms=30_000,
        )
        if not app_hydrated:
            raise UpstreamError("ACIS did not finish loading")
        await self._dismiss_modal(page)

    async def _clear_site_storage(self, page: Page) -> None:
        # Unload the app first, or it could write after the clear
        with contextlib.suppress(PlaywrightTimeoutError):
            await page.goto("about:blank", timeout=5_000)
        cdp = await page.context.new_cdp_session(page)
        await cdp.send(
            "Storage.clearDataForOrigin",
            {
                "origin": ACIS_ORIGIN,
                "storageTypes": (
                    "local_storage,indexeddb,cache_storage,service_workers"
                ),
            },
        )

    async def _wait_for_response(self, page: Page, capture: Capture) -> None:
        """Wait for the case response, giving up early on a visible challenge."""

        async def watch_challenge() -> None:
            await self._wait_for(
                page,
                f"{CHALLENGE_IFRAME} >> visible=true",
                "visible challenge",
                state="attached",
                timeout_ms=0,
            )
            if capture.requested:
                await capture.received.wait()
            else:
                capture.challenged = True

        tasks = {
            asyncio.create_task(watch_challenge()),
            asyncio.create_task(capture.received.wait()),
        }
        try:
            done, _ = await asyncio.wait(
                tasks, timeout=self.lookup_timeout, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        for task in done:
            task.result()

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
        overlay = ".ReactModal__Overlay"
        if (
            await self._modal_was_accepted(page.context)
            and not await page.locator(overlay).count()
        ):
            return
        if not await self._wait_for(page, overlay, "consent modal", timeout_ms=500):
            return
        await page.locator(".ReactModalPortal button").last.click()
        await self._wait_for(page, overlay, "consent modal to close", state="detached")

    async def _modal_was_accepted(self, context: BrowserContext) -> bool:
        cookies = await context.cookies(ACIS_URL)
        return any(c["name"] == "disclaimer" and c["value"] == "true" for c in cookies)

    async def _wait_for_captcha(self, page: Page) -> None:
        if not await self._wait_for(
            page,
            HCAPTCHA_IFRAME,
            "captcha widget",
            state="attached",
            timeout_ms=15_000,
        ):
            return
        for frame in page.frames:
            if "hcaptcha.com" in frame.url:
                with contextlib.suppress(PlaywrightTimeoutError):
                    await frame.wait_for_load_state("load", timeout=15_000)

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

    def _parse(self, capture: Capture) -> dict[str, Any]:
        if not capture.received.is_set():
            if capture.challenged:
                raise CaptchaError(
                    "No captcha token obtained: hCaptcha showed a visible challenge",
                    reason=CaptchaError.Reason.CHALLENGE,
                )
            if not capture.requested:
                raise CaptchaError(
                    "No captcha token obtained: the form was submitted but no case "
                    "request followed",
                    reason=CaptchaError.Reason.NO_REQUEST,
                )
            raise CaptchaError(
                f"No response to the case request within {self.lookup_timeout}s",
                reason=CaptchaError.Reason.NO_RESPONSE,
            )
        if capture.body is None:
            raise UpstreamError(
                f"Could not read ACIS response body (HTTP {capture.status})"
            )
        status, body = capture.status, capture.body
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
