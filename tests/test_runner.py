from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from litestar.testing import AsyncTestClient

from eoir_api.runner import build_runner_app

from .conftest import RUNNER_TOKEN

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from litestar import Litestar

pytestmark = pytest.mark.anyio

AUTH = {"Authorization": f"Bearer {RUNNER_TOKEN}"}
BODY = {
    "browser": "proxied-1",
    "a_number": "123456789",
    "nat_code": "VE",
    "nat_name": "VENEZUELA",
}


@pytest.fixture
async def runner_client(runner_browser) -> AsyncIterator[AsyncTestClient[Litestar]]:
    app = build_runner_app(RUNNER_TOKEN, {"proxied-1": runner_browser})
    async with AsyncTestClient(app=app) as client:
        yield client


async def test_healthz_lists_browsers_without_auth(runner_client):
    response = await runner_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "browsers": ["proxied-1"]}


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong-runner-token"},
        {"Authorization": RUNNER_TOKEN},
        {"Authorization": f"Basic {RUNNER_TOKEN}"},
    ],
)
async def test_lookup_rejects_bad_token(runner_client, runner_browser, headers):
    response = await runner_client.post("/lookup", json=BODY, headers=headers)
    assert response.status_code == 401
    assert runner_browser.calls == []
