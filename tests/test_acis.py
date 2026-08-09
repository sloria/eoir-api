from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import pytest

from eoir_api.lib.acis import (
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    UpstreamError,
    _Capture,
    option_label,
)

if TYPE_CHECKING:
    import re

    from patchright.async_api import Page

pytestmark = pytest.mark.anyio


def responded(payload: Any, *, status: int = 200) -> _Capture:
    capture = _Capture(requested=True, status=status, body=json.dumps(payload))
    capture.received.set()
    return capture


##### Form filling #####


@dataclass
class FakeLocator:
    clicked: bool = False

    @property
    def first(self) -> FakeLocator:
        return self

    async def click(self, **_kwargs: Any) -> None:
        self.clicked = True


@dataclass
class FakeKeyboard:
    typed: list[str] = field(default_factory=list)
    pressed: list[str] = field(default_factory=list)

    async def type(self, text: str, **_kwargs: Any) -> None:
        self.typed.append(text)

    async def press(self, key: str, **_kwargs: Any) -> None:
        self.pressed.append(key)


@dataclass
class FakePage:
    keyboard: FakeKeyboard = field(default_factory=FakeKeyboard)
    roles: list[tuple[str, re.Pattern[str]]] = field(default_factory=list)
    option: FakeLocator = field(default_factory=FakeLocator)

    def locator(self, _selector: str) -> FakeLocator:
        return FakeLocator()

    def get_by_role(self, role: str, *, name: re.Pattern[str]) -> FakeLocator:
        self.roles.append((role, name))
        return self.option

    async def wait_for_selector(self, *_args: Any, **_kwargs: Any) -> None:
        return


async def test_nationality_is_chosen_by_exact_option_not_the_highlighted_one(
    acis_browser,
):
    page = FakePage()

    await acis_browser._fill_form(cast("Page", page), "245494576", "GV", "GUINEA")

    assert page.keyboard.typed == ["245494576", "GUINEA"]
    # Enter would take "EQUATORIAL GUINEA", the first substring match.
    assert page.keyboard.pressed == []
    assert page.option.clicked
    [(role, pattern)] = page.roles
    assert role == "option"
    assert pattern.match("GUINEA (GV)")
    assert not pattern.match("EQUATORIAL GUINEA (EK)")
    assert not pattern.match("GUINEA BISSAU (PU)")


# Matching the bare name finds no option at all.
def test_option_label_includes_the_code():
    assert option_label("GUINEA", "GV").pattern == r"^GUINEA\ \(GV\)$"


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


def test_bad_nationality_code_raises_not_found(acis_browser):
    capture = responded({"message": "Invalid nationality code"})
    with pytest.raises(CaseNotFoundError):
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
