from __future__ import annotations

import json
from typing import Any

import pytest
from patchright.async_api import Error as PlaywrightError

from acis_browser import (
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidNationalityError,
    Outcome,
    UpstreamError,
    raise_for_outcome,
)
from acis_browser.browser import _Capture, option_label

pytestmark = pytest.mark.anyio

_UNSET = object()


def responded(
    payload: Any = _UNSET, *, status: int = 200, body: str | None = None
) -> _Capture:
    capture = _Capture(
        requested=True,
        status=status,
        body=json.dumps(payload) if payload is not _UNSET else body,
    )
    capture.received.set()
    return capture


async def fake_start() -> None:
    pass


async def lookup_with(browser, fake_once, a_number: str = "012345678"):
    """Run ``lookup`` against a stubbed ``_lookup_once``."""
    browser.start = fake_start
    browser._lookup_once = fake_once
    return await browser.lookup(a_number, "MX", "MEXICO")


def test_option_label_matches_only_the_exact_country():
    pattern = option_label("GUINEA", "GV")

    assert pattern.pattern == r"^GUINEA\ \(GV\)$"
    assert pattern.match("GUINEA (GV)")
    assert not pattern.match("EQUATORIAL GUINEA (EK)")
    assert not pattern.match("GUINEA BISSAU (PU)")


##### Captcha failures #####


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
    with pytest.raises(CaptchaError) as excinfo:
        acis_browser._parse(responded({"message": "Invalid Captcha Provided"}))
    assert excinfo.value.reason is CaptchaError.Reason.REJECTED


##### Payloads are returned, not raised #####


def test_successful_payload_is_returned_verbatim(acis_browser, master_hearing):
    assert acis_browser._parse(responded(master_hearing)) == master_hearing


@pytest.mark.parametrize(
    ("message", "outcome"),
    [
        ("No case info found for A-Number", Outcome.NOT_FOUND),
        ("Invalid nationality code", Outcome.INVALID_NATIONALITY),
        ("Case information is unavailable", Outcome.UNAVAILABLE),
        ("Something else broke", Outcome.OTHER),
    ],
)
def test_message_payloads_are_returned_and_classified(acis_browser, message, outcome):
    payload = {"message": message}

    assert acis_browser._parse(responded(payload)) == payload
    assert Outcome.from_payload(payload) is outcome


def test_a_non_dict_data_section_is_not_a_success():
    assert Outcome.from_payload({"Data": None}) is Outcome.OTHER
    assert Outcome.from_payload({}) is Outcome.OTHER


def test_non_json_body_raises_upstream_error(acis_browser):
    with pytest.raises(UpstreamError):
        acis_browser._parse(responded(body="<html>502</html>"))


def test_unreadable_body_raises_upstream_error(acis_browser):
    with pytest.raises(UpstreamError):
        acis_browser._parse(responded(status=500))


def test_non_object_payload_raises_upstream_error(acis_browser):
    with pytest.raises(UpstreamError):
        acis_browser._parse(responded([1, 2]))


def test_error_status_on_a_success_payload_raises_upstream_error(acis_browser):
    with pytest.raises(UpstreamError):
        acis_browser._parse(responded({"Data": {}}, status=500))


##### raise_for_outcome #####


def test_raise_for_outcome_is_a_no_op_for_a_success(master_hearing):
    assert raise_for_outcome(master_hearing) is None


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("No case info found for A-Number", CaseNotFoundError),
        ("Invalid nationality code", InvalidNationalityError),
        ("Case information is unavailable", CaseUnavailableError),
        ("Something else broke", UpstreamError),
    ],
)
def test_raise_for_outcome_raises_the_matching_error(message, expected):
    payload = {"message": message}

    with pytest.raises(expected) as excinfo:
        raise_for_outcome(payload)
    assert excinfo.value.payload == payload
    assert str(excinfo.value) == message


def test_raise_for_outcome_reports_a_rejected_captcha():
    with pytest.raises(CaptchaError) as excinfo:
        raise_for_outcome({"message": "Invalid Captcha Provided"})
    assert excinfo.value.reason is CaptchaError.Reason.REJECTED


def test_raise_for_outcome_describes_a_payload_with_no_message():
    with pytest.raises(UpstreamError) as excinfo:
        raise_for_outcome({})
    assert str(excinfo.value)


##### Lookup #####


async def test_lookup_returns_message_payload_verbatim(acis_browser):
    payload = {"message": "No case info found"}

    async def fake_once(a_number, nat_code, nat_name):
        return dict(payload)

    assert await lookup_with(acis_browser, fake_once) == payload


async def test_lookup_returns_success_payload_untouched(acis_browser, master_hearing):
    async def fake_once(a_number, nat_code, nat_name):
        return dict(master_hearing)

    assert await lookup_with(acis_browser, fake_once, "999999999") == master_hearing


async def test_lookup_retries_captcha_then_raises(acis_browser, monkeypatch):
    calls = []

    async def fake_once(a_number, nat_code, nat_name):
        calls.append(a_number)
        raise CaptchaError("rejected", reason=CaptchaError.Reason.REJECTED)

    async def no_sleep(seconds):
        pass

    monkeypatch.setattr("acis_browser.browser.asyncio.sleep", no_sleep)

    with pytest.raises(CaptchaError):
        await lookup_with(acis_browser, fake_once)
    assert len(calls) == acis_browser.lookup_attempts


async def test_lookup_propagates_upstream_error(acis_browser):
    async def fake_once(a_number, nat_code, nat_name):
        raise UpstreamError("non-JSON")

    with pytest.raises(UpstreamError):
        await lookup_with(acis_browser, fake_once)


##### Browser lifecycle #####


async def test_browser_lost_mid_lookup_is_converted_and_discards_the_context(
    acis_browser,
):
    closed = []

    async def fake_once(a_number, nat_code, nat_name):
        raise PlaywrightError("Target page, context or browser has been closed")

    async def fake_close() -> None:
        closed.append(True)

    acis_browser.close = fake_close

    with pytest.raises(UpstreamError):
        await lookup_with(acis_browser, fake_once)
    assert closed == [True]


async def test_browser_lost_is_not_retried_as_a_captcha(acis_browser):
    calls = []

    async def fake_once(a_number, nat_code, nat_name):
        calls.append(a_number)
        raise PlaywrightError("Browser closed")

    async def fake_close() -> None:
        pass

    acis_browser.close = fake_close

    with pytest.raises(UpstreamError):
        await lookup_with(acis_browser, fake_once)
    assert len(calls) == 1


async def test_browser_lost_is_discarded_even_when_closing_it_fails(acis_browser):
    async def fake_once(a_number, nat_code, nat_name):
        raise PlaywrightError("Browser closed")

    async def fake_close() -> None:
        raise PlaywrightError("Connection closed")

    acis_browser.close = fake_close

    with pytest.raises(UpstreamError):
        await lookup_with(acis_browser, fake_once)
