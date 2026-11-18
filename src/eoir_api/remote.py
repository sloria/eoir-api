"""Runner protocol, and the hub's client for browsers hosted by runners."""

from __future__ import annotations

from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import anyio
import httpx2
import msgspec
import structlog
from acis_core.exceptions import (
    AcisError,
    BrowserLostError,
    CaptchaError,
    UpstreamError,
)

from eoir_api.request_id import HEADER as REQUEST_ID_HEADER

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Collection

    from litestar import Litestar

    from eoir_api.settings import Runner, RunnerLookup

logger = structlog.get_logger()

HEALTH_INTERVAL = 5
HEALTH_TIMEOUT = 3
CONNECT_TIMEOUT = 5
# Upper bounds of AcisBrowser's Chrome launch and its per-attempt page load,
# form and captcha waits, excluding the lookup timeout
START_SECONDS = 30
PAGE_SECONDS = 120


##### Wire format #####


class LookupRequest(msgspec.Struct):
    browser: str
    a_number: str
    nat_code: str
    nat_name: str


ErrorCode = Literal["captcha", "browser_lost", "upstream", "unknown_browser"]


class RunnerError(msgspec.Struct):
    # XXX: str instead of ErrorCode/CaptchaError.Reason to avoid breakages
    # when runner and hub versions differ
    error: str | None = None
    reason: str | None = None
    payload: dict[str, Any] | None = None
    message: str | None = None


##### Hub client #####


def request_timeout(lookup: RunnerLookup) -> float:
    """Return the seconds a runner may take for one lookup, with margin."""
    backoff = sum(2**i for i in range(1, lookup.attempts))
    return START_SECONDS + lookup.attempts * (lookup.timeout + PAGE_SECONDS) + backoff


def error_from(runner: str, status: int, body: RunnerError) -> AcisError:
    """Return the exception a runner's error response stands for."""
    message = body.message or f"Runner {runner} returned HTTP {status}"
    if body.error == "captcha":
        try:
            reason = CaptchaError.Reason(body.reason)
        except ValueError:  # unknown to this version; assume the worst
            reason = CaptchaError.Reason.REJECTED
        return CaptchaError(message, reason=reason, payload=body.payload)
    if body.error == "upstream":
        return UpstreamError(message, payload=body.payload)
    # browser_lost, unknown_browser, or a broken runner
    return BrowserLostError(f"Runner {runner}: {message}", payload=body.payload)


def log_failure(error: AcisError) -> None:
    """Log a runner's failure with the request's log context."""
    if isinstance(error, CaptchaError):
        logger.warning("lookup.captcha_failed", reason=error.reason, error=str(error))
    elif isinstance(error, BrowserLostError):
        logger.warning("lookup.browser_lost", error=str(error))


@dataclass(eq=False)
class RunnerClient:
    name: str
    client: httpx2.AsyncClient
    is_up: bool = True

    @classmethod
    def create(cls, runner: Runner, lookup: RunnerLookup) -> RunnerClient:
        client = httpx2.AsyncClient(
            base_url=runner.url,
            headers={"Authorization": f"Bearer {runner.token}"},
            timeout=httpx2.Timeout(request_timeout(lookup), connect=CONNECT_TIMEOUT),
        )
        return cls(runner.name, client)

    def _mark_down(self, error: Exception) -> None:
        if self.is_up:
            logger.warning("runner.down", runner=self.name, error=repr(error))
        self.is_up = False

    def _mark_up(self) -> None:
        if not self.is_up:
            logger.info("runner.up", runner=self.name)
        self.is_up = True

    async def lookup(
        self, browser: str, a_number: str, nat_code: str, nat_name: str
    ) -> dict[str, Any]:
        try:
            return await self._lookup(browser, a_number, nat_code, nat_name)
        except AcisError as exc:
            log_failure(exc)
            raise

    async def _lookup(
        self, browser: str, a_number: str, nat_code: str, nat_name: str
    ) -> dict[str, Any]:
        request = LookupRequest(browser, a_number, nat_code, nat_name)
        request_id = structlog.contextvars.get_contextvars().get("request_id")
        headers = {REQUEST_ID_HEADER: request_id} if request_id else None
        try:
            response = await self.client.post(
                "/lookup", json=msgspec.to_builtins(request), headers=headers
            )
        except httpx2.HTTPError as exc:
            # Skip this runner until its health check passes
            self._mark_down(exc)
            raise BrowserLostError(f"Runner {self.name} unreachable: {exc!r}") from exc
        if response.is_success:
            try:
                return msgspec.json.decode(response.content, type=dict[str, Any])
            except msgspec.DecodeError:
                pass
        try:
            body = msgspec.json.decode(response.content, type=RunnerError)
        except msgspec.DecodeError:
            body = RunnerError()
        raise error_from(self.name, response.status_code, body)

    async def check_health(self) -> None:
        """Request the runner's health and mark it up or down."""
        try:
            response = await self.client.get("/healthz", timeout=HEALTH_TIMEOUT)
            response.raise_for_status()
        except httpx2.HTTPError as exc:
            self._mark_down(exc)
        else:
            self._mark_up()


@dataclass
class RemoteBrowser:
    """A browser hosted by a runner."""

    runner: RunnerClient
    name: str

    @property
    def is_available(self) -> bool:
        return self.runner.is_up

    async def lookup(
        self, a_number: str, nat_code: str, nat_name: str
    ) -> dict[str, Any]:
        return await self.runner.lookup(self.name, a_number, nat_code, nat_name)


def make_runner_lifespan(
    runners: Collection[RunnerClient],
) -> Callable[[Litestar], Any]:
    @asynccontextmanager
    async def runner_lifespan(_app: Litestar) -> AsyncGenerator[None]:
        async def poll(runner: RunnerClient) -> None:
            while True:
                await runner.check_health()
                await anyio.sleep(HEALTH_INTERVAL)

        async with AsyncExitStack() as stack:
            for runner in runners:
                await stack.enter_async_context(runner.client)
            async with anyio.create_task_group() as tg:
                for runner in runners:
                    tg.start_soon(poll, runner)
                try:
                    yield
                finally:
                    tg.cancel_scope.cancel()

    return runner_lifespan
