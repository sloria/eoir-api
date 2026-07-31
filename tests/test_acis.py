from __future__ import annotations

import json
from typing import Any

import pytest

from eoir_api.exceptions import (
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    UpstreamError,
)
from eoir_api.lib.acis import AcisBrowser, _Capture

pytestmark = pytest.mark.anyio


def responded(payload: Any, *, status: int = 200) -> _Capture:
    capture = _Capture(requested=True, status=status, body=json.dumps(payload))
    capture.received.set()
    return capture


##### Failure classification #####


def test_no_request_means_no_token_was_minted(settings):
    with pytest.raises(CaptchaError) as excinfo:
        AcisBrowser(settings)._parse(_Capture(requested=False))
    assert excinfo.value.reason is CaptchaError.Reason.NO_REQUEST


def test_request_without_a_response_is_a_timeout_not_a_mint_failure(settings):
    with pytest.raises(CaptchaError) as excinfo:
        AcisBrowser(settings)._parse(_Capture(requested=True))
    assert excinfo.value.reason is CaptchaError.Reason.NO_RESPONSE
    assert str(settings.lookup_timeout) in str(excinfo.value)


def test_upstream_refusal_is_recorded_as_rejected(settings):
    capture = responded({"message": "Invalid Captcha Provided"})
    with pytest.raises(CaptchaError) as excinfo:
        AcisBrowser(settings)._parse(capture)
    assert excinfo.value.reason is CaptchaError.Reason.REJECTED


##### Non-captcha outcomes are unchanged #####


def test_successful_payload_is_returned_verbatim(settings, master_hearing):
    assert AcisBrowser(settings)._parse(responded(master_hearing)) == master_hearing


def test_missing_case_raises_not_found(settings):
    capture = responded({"message": "No case info found for A-Number"})
    with pytest.raises(CaseNotFoundError):
        AcisBrowser(settings)._parse(capture)


def test_bad_nationality_code_raises_not_found(settings):
    capture = responded({"message": "Invalid nationality code"})
    with pytest.raises(CaseNotFoundError):
        AcisBrowser(settings)._parse(capture)


def test_withheld_case_raises_unavailable(settings):
    capture = responded({"message": "Case information is unavailable"})
    with pytest.raises(CaseUnavailableError):
        AcisBrowser(settings)._parse(capture)


def test_unrecognized_message_raises_upstream_error(settings):
    with pytest.raises(UpstreamError):
        AcisBrowser(settings)._parse(responded({"message": "Something else broke"}))


def test_non_json_body_raises_upstream_error(settings):
    capture = _Capture(requested=True, status=200, body="<html>502</html>")
    capture.received.set()
    with pytest.raises(UpstreamError):
        AcisBrowser(settings)._parse(capture)


def test_unreadable_body_raises_upstream_error(settings):
    capture = _Capture(requested=True, status=500, body=None)
    capture.received.set()
    with pytest.raises(UpstreamError):
        AcisBrowser(settings)._parse(capture)


def test_error_status_without_a_message_raises_upstream_error(settings):
    with pytest.raises(UpstreamError):
        AcisBrowser(settings)._parse(responded({}, status=500))
