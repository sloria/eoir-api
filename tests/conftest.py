from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx2
import msgspec
import pytest
import structlog
from acis_core.exceptions import CaseNotFoundError
from litestar.testing import AsyncTestClient
from sqlspec import SQLSpec

from eoir_api.app import build_app
from eoir_api.remote import RunnerClient
from eoir_api.service import CaseService
from eoir_api.settings import (
    Browser,
    Lookup,
    Portal,
    Runner,
    Secret,
    Settings,
    Tenant,
    Usage,
)
from eoir_api.usage import LookupOutcome, UsageService, create_config

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar

pytestmark = pytest.mark.anyio

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"

NOW = dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
OWNER = {"x-api-key": "owner-test-secret"}
METERED = {"x-api-key": "metered-test-secret"}
BODY = {"a_number": "123456789", "nationality": "VE"}
RUNNER_TOKEN = "runner-test-token"


# Required for pytest-anyio
@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


# Freeze time so retrieved_at and cache behaviour are deterministic.
@pytest.fixture(autouse=True)
def set_time(time_machine):
    time_machine.move_to(NOW, tick=False)


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def master_hearing() -> dict[str, Any]:
    return load_fixture("master_hearing_scheduled.json")


class FakeAcisBrowser:
    is_available = True

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
        tenants=[
            Tenant(name="owner", key=Secret("owner-test-secret")),
            Tenant(name="metered", key=Secret("metered-test-secret"), quota_per_day=5),
        ],
        portal=Portal(secret=Secret("portal-secret")),
        runners=[Runner(name="mac", url="http://mac:8002", token=Secret(RUNNER_TOKEN))],
        browsers=[Browser(name="direct", runner="mac")],
        lookup=Lookup(interval=0),
        usage=Usage(db_path=tmp_path / "usage.sqlite"),
    )


@pytest.fixture
def browser(master_hearing) -> FakeAcisBrowser:
    return FakeAcisBrowser(payload=master_hearing)


@pytest.fixture
def logs():
    with structlog.testing.capture_logs(
        processors=[structlog.contextvars.merge_contextvars]
    ) as captured:
        yield captured


@pytest.fixture
def runner_browser(master_hearing) -> FakeAcisBrowser:
    return FakeAcisBrowser(payload=master_hearing)


def mock_runner(handler, name: str = "mac") -> RunnerClient:
    client = httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler), base_url=f"http://{name}"
    )
    return RunnerClient(name, client)


@dataclass
class FakeClock:
    now: float = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def service(browser, settings, clock) -> CaseService:
    return CaseService({"direct": browser}, settings, clock=clock)


@pytest.fixture
async def client(settings, service) -> AsyncIterator[AsyncTestClient[Litestar]]:
    async with AsyncTestClient(app=build_app(settings, service)) as test_client:
        yield test_client


@pytest.fixture
async def usage_service(settings) -> AsyncIterator[UsageService]:
    spec = SQLSpec()
    config = spec.add_config(create_config(settings.usage.db_path))
    await config.migrate_up(use_logger=True, summary_only=True)
    yield UsageService(config, settings.usage.retention_days)
    await spec.close_all_pools()


class LookupRow(msgspec.Struct):
    id: int
    tenant: str
    ts: dt.datetime
    outcome: LookupOutcome
    cached: int
    duration_ms: int | None


async def lookup_rows(service: UsageService) -> list[LookupRow]:
    async with service.provide_session() as db:
        return await db.select(
            "SELECT * FROM lookups ORDER BY id", schema_type=LookupRow
        )


async def lookup(client, headers=METERED, body=BODY):
    return await client.post("/cases/lookup", json=body, headers=headers)


async def seed(service, *ages, tenant="metered", outcome="ok", cached=False):
    for age in ages:
        await service.record(
            tenant=tenant,
            ts=NOW - age,
            outcome=outcome,
            cached=cached,
            duration_ms=None if cached else 1000,
        )
