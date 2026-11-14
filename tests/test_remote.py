from __future__ import annotations

from typing import TYPE_CHECKING

import httpx2
import pytest
import structlog
from acis_core.exceptions import BrowserLostError, CaptchaError, UpstreamError

from eoir_api.remote import RemoteBrowser, RunnerClient
from eoir_api.runner import build_runner_app

from .conftest import RUNNER_TOKEN, FakeAcisBrowser, mock_runner

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = pytest.mark.anyio

ARGS = ("123456789", "VE", "VENEZUELA")


def asgi_runner(browser: FakeAcisBrowser, token: str = RUNNER_TOKEN) -> RunnerClient:
    app = build_runner_app(RUNNER_TOKEN, {"proxied-1": browser})
    client = httpx2.AsyncClient(
        transport=httpx2.ASGITransport(app=app),  # ty: ignore[invalid-argument-type]
        base_url="http://runner",
        headers={"Authorization": f"Bearer {token}"},
    )
    return RunnerClient("mac", client)


@pytest.fixture
async def runner(runner_browser) -> AsyncIterator[RunnerClient]:
    runner = asgi_runner(runner_browser)
    yield runner
    await runner.client.aclose()


async def test_lookup_returns_runner_payload(runner, runner_browser, master_hearing):
    payload = await RemoteBrowser(runner, "proxied-1").lookup(*ARGS)
    assert payload == master_hearing
    assert runner_browser.calls == [ARGS]


@pytest.mark.parametrize("reason", list(CaptchaError.Reason))
async def test_captcha_error_round_trips_with_reason_and_payload(
    runner, runner_browser, reason
):
    runner_browser.error = CaptchaError("boom", reason=reason, payload={"a": 1})
    with pytest.raises(CaptchaError) as excinfo:
        await RemoteBrowser(runner, "proxied-1").lookup(*ARGS)
    assert excinfo.value.reason is reason
    assert excinfo.value.payload == {"a": 1}
    assert str(excinfo.value) == "boom"


async def test_upstream_error_round_trips(runner, runner_browser):
    runner_browser.error = UpstreamError("bad payload", payload={"Data": None})
    with pytest.raises(UpstreamError) as excinfo:
        await RemoteBrowser(runner, "proxied-1").lookup(*ARGS)
    assert type(excinfo.value) is UpstreamError
    assert excinfo.value.payload == {"Data": None}


async def test_browser_lost_round_trips(runner, runner_browser):
    runner_browser.error = BrowserLostError("Chrome is no longer available")
    with pytest.raises(BrowserLostError, match="Chrome is no longer available"):
        await RemoteBrowser(runner, "proxied-1").lookup(*ARGS)


async def test_unknown_browser_raises_browser_lost(runner):
    with pytest.raises(BrowserLostError, match="No browser nope"):
        await RemoteBrowser(runner, "nope").lookup(*ARGS)


async def test_bad_token_raises_browser_lost(runner_browser):
    runner = asgi_runner(runner_browser, token="wrong-runner-token")
    with pytest.raises(BrowserLostError, match="401"):
        await RemoteBrowser(runner, "proxied-1").lookup(*ARGS)
    assert runner_browser.calls == []


async def test_unreachable_runner_raises_browser_lost():
    def refuse(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(BrowserLostError, match="unreachable"):
        await RemoteBrowser(mock_runner(refuse), "proxied-1").lookup(*ARGS)


async def test_5xx_without_body_raises_browser_lost():
    runner = mock_runner(lambda _request: httpx2.Response(502, text="Bad Gateway"))
    with pytest.raises(BrowserLostError, match="502"):
        await RemoteBrowser(runner, "proxied-1").lookup(*ARGS)


async def test_unknown_captcha_reason_is_treated_as_rejected():
    runner = mock_runner(
        lambda _request: httpx2.Response(
            503, json={"error": "captcha", "reason": "added_later", "extra": 1}
        )
    )
    with pytest.raises(CaptchaError) as excinfo:
        await RemoteBrowser(runner, "proxied-1").lookup(*ARGS)
    assert excinfo.value.reason is CaptchaError.Reason.REJECTED


@pytest.mark.parametrize(
    ("error", "event"),
    [
        (
            CaptchaError("boom", reason=CaptchaError.Reason.CHALLENGE),
            "lookup.captcha_failed",
        ),
        (BrowserLostError("Chrome is no longer available"), "lookup.browser_lost"),
    ],
)
async def test_runner_failure_is_logged_with_request_context(
    runner, runner_browser, logs, error, event
):
    runner_browser.error = error
    with structlog.contextvars.bound_contextvars(tenant="owner", runner="mac"):
        with pytest.raises(type(error)):
            await RemoteBrowser(runner, "proxied-1").lookup(*ARGS)
    [entry] = [e for e in logs if e["event"] == event]
    assert entry["tenant"] == "owner"
    assert entry["runner"] == "mac"


async def test_runner_logs_with_hub_request_id(runner, runner_browser, logs):
    runner_browser.error = UpstreamError("bad payload")
    with structlog.contextvars.bound_contextvars(request_id="hub-request-1"):
        with pytest.raises(UpstreamError):
            await RemoteBrowser(runner, "proxied-1").lookup(*ARGS)
    [entry] = [e for e in logs if e["event"] == "runner.upstream_error"]
    assert entry["request_id"] == "hub-request-1"
