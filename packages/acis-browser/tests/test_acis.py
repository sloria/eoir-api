from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any

import pytest
from patchright._impl._errors import TargetClosedError
from patchright.async_api import Error as PlaywrightError

import acis_browser as acis_browser_module
from acis_browser import (
    BrowserLostError,
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidNationalityError,
    Outcome,
    UpstreamError,
    raise_for_outcome,
)
from acis_browser._intercept import PLACEHOLDER
from acis_browser.browser import (
    Capture,
    option_label,
    purge_site_storage,
)

pytestmark = pytest.mark.anyio

_UNSET = object()


def responded(
    payload: Any = _UNSET, *, status: int = 200, body: str | None = None
) -> Capture:
    capture = Capture(
        requested=True,
        status=status,
        body=json.dumps(payload) if payload is not _UNSET else body,
    )
    capture.received.set()
    return capture


async def noop(*args):
    pass


async def lookup_with(browser, fake_once, a_number: str = "012345678"):
    """Run ``lookup`` against a stubbed ``_lookup_once``."""
    browser.start = noop
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
        acis_browser._parse(Capture(requested=False))
    assert excinfo.value.reason is CaptchaError.Reason.NO_REQUEST


def test_request_without_a_response_is_a_timeout_not_a_mint_failure(acis_browser):
    with pytest.raises(CaptchaError) as excinfo:
        acis_browser._parse(Capture(requested=True))
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
    ],
)
def test_raise_for_outcome_raises_the_matching_error(message, expected):
    payload = {"message": message}

    with pytest.raises(expected) as excinfo:
        raise_for_outcome(payload)
    assert excinfo.value.payload == payload
    assert str(excinfo.value) == message


def test_raise_for_outcome_omits_unrecognized_upstream_text():
    payload = {"message": "Lookup broke for 123456789"}

    with pytest.raises(UpstreamError) as excinfo:
        raise_for_outcome(payload)
    assert excinfo.value.payload == payload
    assert "123456789" not in str(excinfo.value)


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

    monkeypatch.setattr("acis_browser.browser.asyncio.sleep", noop)
    acis_browser.lookup_attempts = 2

    with pytest.raises(CaptchaError):
        await lookup_with(acis_browser, fake_once)
    assert len(calls) == 2


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

    acis_browser._close = fake_close

    with pytest.raises(BrowserLostError):
        await lookup_with(acis_browser, fake_once)
    assert closed == [True]


async def test_dead_driver_transport_is_treated_as_browser_lost(acis_browser):
    closed = []

    async def fake_once(a_number, nat_code, nat_name):
        raise RuntimeError(
            "BrowserContext.new_page: unable to perform operation on "
            "<WriteUnixTransport closed=True>; the handler is closed"
        )

    async def fake_close() -> None:
        closed.append(True)

    acis_browser._close = fake_close

    with pytest.raises(BrowserLostError):
        await lookup_with(acis_browser, fake_once)
    assert closed == [True]


async def test_browser_closing_mid_page_load_is_browser_lost(acis_browser):
    class Page:
        def on(self, event, handler):
            pass

        async def goto(self, *args, **kwargs):
            raise TargetClosedError

        async def close(self):
            raise TargetClosedError

    class Context:
        async def new_page(self):
            return Page()

    async def fake_close() -> None:
        pass

    acis_browser.start = noop
    acis_browser._context = Context()
    acis_browser._close = fake_close

    with pytest.raises(BrowserLostError):
        await acis_browser.lookup("012345678", "MX", "MEXICO")


async def test_close_stops_playwright_when_context_close_fails(acis_browser):
    class Context:
        async def close(self):
            raise RuntimeError("the handler is closed")

    class Playwright:
        stopped = False

        async def stop(self):
            self.stopped = True

    acis_browser._context = Context()
    acis_browser._playwright = Playwright()

    await acis_browser.close()

    assert acis_browser._context is None
    assert acis_browser._playwright is None


async def test_browser_lost_is_not_retried_as_a_captcha(acis_browser):
    calls = []

    async def fake_once(a_number, nat_code, nat_name):
        calls.append(a_number)
        raise PlaywrightError("Browser closed")

    async def fake_close() -> None:
        pass

    acis_browser._close = fake_close

    with pytest.raises(BrowserLostError):
        await lookup_with(acis_browser, fake_once)
    assert len(calls) == 1


async def test_browser_lost_is_discarded_even_when_closing_it_fails(acis_browser):
    async def fake_once(a_number, nat_code, nat_name):
        raise PlaywrightError("Browser closed")

    async def fake_close() -> None:
        raise PlaywrightError("Connection closed")

    acis_browser._close = fake_close

    with pytest.raises(BrowserLostError):
        await lookup_with(acis_browser, fake_once)


async def test_close_waits_for_an_in_flight_lookup(acis_browser):
    started = asyncio.Event()
    finish = asyncio.Event()
    events = []

    async def fake_once(a_number, nat_code, nat_name):
        started.set()
        await finish.wait()
        events.append("lookup")
        return {"Data": {}}

    async def fake_close() -> None:
        events.append("close")

    acis_browser._close = fake_close
    lookup = asyncio.create_task(lookup_with(acis_browser, fake_once))
    await started.wait()

    close = asyncio.create_task(acis_browser.close())
    await asyncio.sleep(0)
    assert events == []

    finish.set()
    await asyncio.gather(lookup, close)
    assert events == ["lookup", "close"]


##### Interception #####

CASE_URL = (
    "https://eoir-ws.eoir.justice.gov/api/Case/GetCaseInfo"
    "?alienNumber={}&languageCode=EN&natCode={}"
)
CASE = ("987654321", "GT")
NOT_FOUND = {"message": "No case info found for A-Number"}


class FakeRoute:
    def __init__(self, url):
        self.request = SimpleNamespace(url=url)
        self.sent = None

    async def continue_(self, url):
        self.sent = url

    async def abort(self):
        pass


class FakeResponse:
    status = 200

    def __init__(self, url, payload):
        self.url = url
        self.payload = payload

    async def text(self):
        return json.dumps(self.payload)


class FakePage:
    def __init__(self, context):
        self.context = context
        self.closed = False
        self.form = ("", "")
        self.listeners = {}
        self.rewrite = None
        self.sent = []

    def on(self, event, handler):
        self.listeners[event] = handler

    def is_closed(self):
        return self.closed

    def locator(self, selector):
        return self

    async def route(self, pattern, handler):
        self.rewrite = handler

    async def wait_for_selector(self, *args, **kwargs):
        await asyncio.Event().wait()

    async def click(self):
        url = CASE_URL.format(*self.form)
        await self.listeners["request"](SimpleNamespace(url=url))
        if self.rewrite:
            route = FakeRoute(url)
            await self.rewrite(route)
            url = route.sent
        if url:
            self.sent.append(url)
            payload = NOT_FOUND if PLACEHOLDER[0] in url else self.context.payload
            await self.listeners["response"](FakeResponse(url, payload))

    async def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, payload):
        self.payload = payload
        self.pages = []

    async def new_page(self):
        self.pages.append(FakePage(self))
        return self.pages[-1]

    async def close(self):
        pass


@pytest.fixture
def warm_browser(acis_browser, master_hearing):
    async def fill_form(page, a_number, nat_code, nat_name):
        page.form = (a_number, nat_code)

    async def modal_accepted(context):
        return True

    acis_browser.intercept = True
    acis_browser.start = noop
    acis_browser._context = FakeContext(master_hearing)
    acis_browser._open_form = noop
    acis_browser._fill_form = fill_form
    acis_browser._wait_for_captcha = noop
    acis_browser._clear_site_storage = noop
    acis_browser._modal_was_accepted = modal_accepted
    return acis_browser


async def warm_page(browser):
    await browser._warm_task
    return browser._context.pages[-1]


async def lookup_case(browser):
    return await browser.lookup(*CASE, "GUATEMALA")


async def test_lookup_after_a_lookup_submits_the_warm_form_for_the_real_case(
    warm_browser, master_hearing
):
    await lookup_case(warm_browser)
    page = await warm_page(warm_browser)
    assert page.form == PLACEHOLDER[:2]

    assert await lookup_case(warm_browser) == master_hearing
    assert page.sent == [CASE_URL.format(*CASE)]
    assert page.closed


async def test_warm_page_request_that_was_not_rewritten_is_never_returned(warm_browser):
    await lookup_case(warm_browser)
    (await warm_page(warm_browser)).rewrite = None

    with pytest.raises(UpstreamError):
        await lookup_case(warm_browser)


async def test_a_number_the_form_would_not_accept_is_not_sent_through_a_warm_page(
    warm_browser,
):
    await lookup_case(warm_browser)
    page = await warm_page(warm_browser)

    await warm_browser.lookup("A-987654321", "GT", "GUATEMALA")

    assert not page.sent


async def test_warm_page_with_an_expired_disclaimer_is_discarded_for_a_cold_load(
    warm_browser,
):
    await lookup_case(warm_browser)
    page = await warm_page(warm_browser)

    async def modal_expired(context):
        return False

    warm_browser._modal_was_accepted = modal_expired

    await lookup_case(warm_browser)

    assert page.closed
    assert not page.sent
    assert warm_browser._context.pages[2].sent == [CASE_URL.format(*CASE)]


async def test_failed_lookup_does_not_warm(warm_browser):
    warm_browser._context.payload = {"message": "Invalid Captcha Provided"}

    with pytest.raises(CaptchaError):
        await lookup_case(warm_browser)
    await asyncio.sleep(0)

    assert len(warm_browser._context.pages) == 1


async def test_failed_warm_falls_back_to_a_cold_load(warm_browser, master_hearing):
    pages = warm_browser._context.pages

    async def flaky_open_form(page):
        if len(pages) == 2:
            raise PlaywrightError("net::ERR_CONNECTION_RESET")

    warm_browser._open_form = flaky_open_form
    await lookup_case(warm_browser)
    await warm_browser._warm_task

    assert await lookup_case(warm_browser) == master_hearing
    assert pages[1].closed
    assert pages[2].sent == [CASE_URL.format(*CASE)]


async def test_close_mid_warm_closes_the_warm_page(warm_browser):
    started = asyncio.Event()
    pages = warm_browser._context.pages

    async def hanging_open_form(page):
        if len(pages) == 2:
            started.set()
            await asyncio.Event().wait()

    warm_browser._open_form = hanging_open_form
    await lookup_case(warm_browser)
    await started.wait()

    await warm_browser.close()

    assert pages[1].closed


def test_purging_site_storage_keeps_cookies(tmp_path):
    default = tmp_path / "Default"
    for name in (
        "Cache/Cache_Data",
        "Local Storage/leveldb",
        "Session Storage",
        "Sessions",
    ):
        (default / name).mkdir(parents=True)
        (default / name / "data").write_text("case")
    (default / "Cookies").write_text("hi")

    purge_site_storage(tmp_path)

    assert [p.name for p in default.iterdir()] == ["Cookies"]


@pytest.mark.parametrize(
    ("old", "new"), [("AcisBrowser", "ACISBrowser"), ("AcisError", "ACISError")]
)
def test_deprecated_names_warn_and_resolve_to_new_names(old, new):
    with pytest.warns(DeprecationWarning, match=new):
        assert getattr(acis_browser_module, old) is getattr(acis_browser_module, new)
