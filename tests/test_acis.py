from __future__ import annotations

import json
from typing import Any

import pytest
from patchright.async_api import Error as PlaywrightError

from eoir_api.lib.acis import (
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidNationalityError,
    UpstreamError,
    _Capture,
    option_label,
)

pytestmark = pytest.mark.anyio


def responded(payload: Any, *, status: int = 200) -> _Capture:
    capture = _Capture(requested=True, status=status, body=json.dumps(payload))
    capture.received.set()
    return capture


def test_option_label_matches_only_the_exact_country():
    pattern = option_label("GUINEA", "GV")

    assert pattern.pattern == r"^GUINEA\ \(GV\)$"
    assert pattern.match("GUINEA (GV)")
    assert not pattern.match("EQUATORIAL GUINEA (EK)")
    assert not pattern.match("GUINEA BISSAU (PU)")


##### Failure classification #####


def test_no_request_means_no_token_was_minted(acis_browser):
    with pytest.raises(CaptchaError) as excinfo:
        acis_browser._parse(_Capture(requested=False))
    assert excinfo.value.reason is CaptchaError.Reason.NO_REQUEST


def test_request_without_a_response_is_a_timeout_not_a_mint_failure(acis_browser):
    with pytest.raises(CaptchaError) as excinfo:
        acis_browser._parse(_Capture(requested=True))
    assert excinfo.value.reason is CaptchaError.Reason.NO_RESPONSE
    assert str(acis_browser.lookup_timeout) in str(excinfo.value)


def test_upstream_refusal_is_recorded_as_rejected(acis_browser):
    capture = responded({"message": "Invalid Captcha Provided"})
    with pytest.raises(CaptchaError) as excinfo:
        acis_browser._parse(capture)
    assert excinfo.value.reason is CaptchaError.Reason.REJECTED


##### Non-captcha outcomes are unchanged #####


def test_successful_payload_is_returned_verbatim(acis_browser, master_hearing):
    assert acis_browser._parse(responded(master_hearing)) == master_hearing


def test_missing_case_raises_not_found(acis_browser):
    capture = responded({"message": "No case info found for A-Number"})
    with pytest.raises(CaseNotFoundError):
        acis_browser._parse(capture)


def test_bad_nationality_code_raises_invalid_nationality(acis_browser):
    capture = responded({"message": "Invalid nationality code"})
    with pytest.raises(InvalidNationalityError):
        acis_browser._parse(capture)


def test_withheld_case_raises_unavailable(acis_browser):
    capture = responded({"message": "Case information is unavailable"})
    with pytest.raises(CaseUnavailableError):
        acis_browser._parse(capture)


def test_unrecognized_message_raises_upstream_error(acis_browser):
    with pytest.raises(UpstreamError):
        acis_browser._parse(responded({"message": "Something else broke"}))


def test_non_json_body_raises_upstream_error(acis_browser):
    capture = _Capture(requested=True, status=200, body="<html>502</html>")
    capture.received.set()
    with pytest.raises(UpstreamError):
        acis_browser._parse(capture)


def test_unreadable_body_raises_upstream_error(acis_browser):
    capture = _Capture(requested=True, status=500, body=None)
    capture.received.set()
    with pytest.raises(UpstreamError):
        acis_browser._parse(capture)


def test_error_status_without_a_message_raises_upstream_error(acis_browser):
    with pytest.raises(UpstreamError):
        acis_browser._parse(responded({}, status=500))


##### Browser lifecycle #####


async def _lookup(browser, fake_once):
    async def fake_start() -> None:
        pass

    browser.start = fake_start
    browser._lookup_once = fake_once
    return await browser.lookup("012345678", "MX", "MEXICO")


async def test_a_lost_browser_is_reported_as_an_upstream_error(acis_browser):
    async def fake_once(a_number, nat_code, nat_name):
        raise PlaywrightError("Target page, context or browser has been closed")

    closed = []

    async def fake_close() -> None:
        closed.append(True)

    acis_browser.close = fake_close

    with pytest.raises(UpstreamError):
        await _lookup(acis_browser, fake_once)
    assert closed == [True]


async def test_a_lost_browser_is_discarded_even_when_closing_it_fails(acis_browser):
    async def fake_once(a_number, nat_code, nat_name):
        raise PlaywrightError("Browser closed")

    async def fake_close() -> None:
        raise PlaywrightError("Connection closed")

    acis_browser.close = fake_close

    with pytest.raises(UpstreamError):
        await _lookup(acis_browser, fake_once)


async def test_a_lost_browser_is_not_retried_as_a_captcha(acis_browser):
    calls = []

    async def fake_once(a_number, nat_code, nat_name):
        calls.append(a_number)
        raise PlaywrightError("Browser closed")

    async def fake_close() -> None:
        pass

    acis_browser.close = fake_close

    with pytest.raises(UpstreamError):
        await _lookup(acis_browser, fake_once)
    assert len(calls) == 1
