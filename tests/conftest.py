from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from litestar.datastructures import State
from litestar.di import Provide
from litestar.testing import AsyncTestClient, create_async_test_client

from eoir_api.app import ROUTE_HANDLERS, create_openapi_config
from eoir_api.lib.acis import AcisBrowser, CaseNotFoundError
from eoir_api.service import CaseService
from eoir_api.settings import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar

pytestmark = pytest.mark.anyio

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"


# Required for pytest-anyio
@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


# Freeze time so retrieved_at and cache behaviour are deterministic.
@pytest.fixture(autouse=True)
def set_time(time_machine):
    time_machine.move_to(dt.datetime(2026, 7, 25, 12, 0, 0, tzinfo=dt.UTC), tick=False)


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def master_hearing() -> dict[str, Any]:
    return load_fixture("master_hearing_scheduled.json")


class FakeAcisBrowser:
    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        self.payload = payload
        self.error: Exception | None = None
        self.calls: list[tuple[str, str, str]] = []

    async def lookup(
        self, a_number: str, nat_code: str, nat_name: str
    ) -> dict[str, Any]:
        self.calls.append((a_number, nat_code, nat_name))
        if self.error is not None:
            raise self.error
        if self.payload is None:
            raise CaseNotFoundError(f"No case info found for A-Number {a_number}")
        return self.payload


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        debug=True,
        api_secret="test-secret",
        chrome_profile_dir=tmp_path / "profile",
        sentry_dsn="",
    )


@pytest.fixture
def acis_browser(settings) -> AcisBrowser:
    return AcisBrowser(
        profile_dir=settings.chrome_profile_dir,
        lookup_timeout=settings.lookup_timeout,
        lookup_attempts=settings.lookup_attempts,
        idle_timeout=settings.browser_idle_timeout,
    )


@pytest.fixture
def browser(master_hearing) -> FakeAcisBrowser:
    return FakeAcisBrowser(payload=master_hearing)


@pytest.fixture
def service(browser, settings) -> CaseService:
    return CaseService(browser, settings)


@pytest.fixture
async def client(settings, service) -> AsyncIterator[AsyncTestClient[Litestar]]:
    async def provide_settings() -> Settings:
        return settings

    async def provide_service() -> CaseService:
        return service

    async with create_async_test_client(
        route_handlers=ROUTE_HANDLERS,
        openapi_config=create_openapi_config(),
        state=State({"settings": settings}),
        dependencies={
            "settings": Provide(provide_settings),
            "service": Provide(provide_service),
        },
    ) as test_client:
        yield test_client
