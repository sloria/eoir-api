from __future__ import annotations

import json

import pytest
import sentry_sdk
from acis_browser import CaptchaError
from sentry_sdk.integrations.litestar import LitestarIntegration
from sentry_sdk.transport import Transport

from eoir_api.app import _scrub_sentry_event

A_NUMBER = "999999999"


class CaptureTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    def capture_envelope(self, envelope) -> None:
        self.events.extend(
            item.payload.json for item in envelope.items if item.payload.json
        )


@pytest.fixture
def sentry_events():
    transport = CaptureTransport()
    sentry_sdk.init(
        dsn="https://key@sentry.invalid/1",
        transport=transport,
        include_local_variables=False,
        before_send=_scrub_sentry_event,
        integrations=[LitestarIntegration()],
    )
    yield transport.events
    sentry_sdk.get_client().close()
    sentry_sdk.get_global_scope().set_client(None)


@pytest.mark.anyio
async def test_sentry_events_omit_a_number_from_request_body(
    sentry_events, client, browser
):
    browser.error = RuntimeError("boom")
    response = await client.post(
        "/cases/lookup",
        json={"a_number": A_NUMBER, "nationality": "VE"},
        headers={"x-api-key": "test-secret"},
    )
    assert response.status_code == 500
    sentry_sdk.flush()
    assert sentry_events
    assert A_NUMBER not in json.dumps(sentry_events)


def test_sentry_drops_expected_captcha_errors():
    exc = CaptchaError("boom", reason=CaptchaError.Reason.NO_REQUEST)
    assert _scrub_sentry_event({}, {"exc_info": (type(exc), exc, None)}) is None
