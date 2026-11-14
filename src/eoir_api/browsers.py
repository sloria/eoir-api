"""Chrome instances hosted by a runner."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import anyio
import msgspec
import structlog
from acis_browser import AcisBrowser

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Mapping, Sequence

    from litestar import Litestar
    from patchright.async_api import ProxySettings

    from eoir_api.settings import Chrome, Proxy, RunnerBrowser, RunnerLookup

logger = structlog.get_logger()


def proxy_settings(proxy: Proxy | None) -> ProxySettings | None:
    if proxy is None:
        return None
    fields = msgspec.structs.asdict(proxy)
    return cast("ProxySettings", {k: v for k, v in fields.items() if v is not None})


def create_browsers(
    browsers: Sequence[RunnerBrowser], chrome: Chrome, lookup: RunnerLookup
) -> dict[str, AcisBrowser]:
    """Build an ``AcisBrowser`` per browser config."""
    return {
        b.name: AcisBrowser(
            profile_dir=chrome.profiles_dir / b.name,
            proxy=proxy_settings(b.proxy),
            lookup_timeout=lookup.timeout,
            lookup_attempts=lookup.attempts,
        )
        for b in browsers
    }


def make_browser_lifespan(
    browsers: Mapping[str, AcisBrowser], idle_timeout: float
) -> Callable[[Litestar], Any]:
    check_interval = 60

    async def close_browser(name: str, browser: AcisBrowser) -> None:
        try:
            await browser.close()
        except Exception:
            logger.exception("browser close failed", browser=name)

    @asynccontextmanager
    async def browser_lifespan(_app: Litestar) -> AsyncGenerator[None]:
        async def reap_idle_browsers() -> None:
            while True:
                await anyio.sleep(check_interval)
                for name, browser in browsers.items():
                    idle = time.monotonic() - browser.last_used
                    if not browser.is_running or idle < idle_timeout:
                        continue
                    logger.info(
                        "browser idle, closing", browser=name, idle_seconds=round(idle)
                    )
                    await close_browser(name, browser)

        try:
            async with anyio.create_task_group() as tg:
                tg.start_soon(reap_idle_browsers)
                try:
                    yield
                finally:
                    tg.cancel_scope.cancel()
        finally:
            async with anyio.create_task_group() as tg:
                for name, browser in browsers.items():
                    tg.start_soon(close_browser, name, browser)

    return browser_lifespan
