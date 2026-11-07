from __future__ import annotations

import datetime as dt

import anyio
import anyio.lowlevel
import pytest
from acis_browser import CaptchaError
from acis_core.nationalities import resolve

from eoir_api.exceptions import BrowserUnavailableError, QueueTimeoutError
from eoir_api.service import CaseService
from eoir_api.settings import Browser, Proxy, Secret, Tenant
from eoir_api.usage import TenantUsage

from .conftest import FakeAcisBrowser

pytestmark = pytest.mark.anyio

A_NUMBER = "999999999"
VE = resolve("VE")


@pytest.fixture
def usage(usage_service) -> TenantUsage:
    return TenantUsage(
        usage_service, Tenant(name="owner", key=Secret("owner-test-secret"))
    )


##### Cache #####


async def test_second_call_is_served_from_cache(usage, service, browser):
    first = await service.get_case(A_NUMBER, VE, usage=usage)
    second = await service.get_case(A_NUMBER, VE, usage=usage)

    assert first.cached is False
    assert second.cached is True
    # The browser was only driven once.
    assert browser.calls == [(A_NUMBER, "VE", "VENEZUELA")]


async def test_cache_hit_does_not_refresh_retrieved_at(usage, service, time_machine):
    first = await service.get_case(A_NUMBER, VE, usage=usage)
    time_machine.move_to(dt.datetime(2026, 7, 25, 12, 30, tzinfo=dt.UTC), tick=False)
    second = await service.get_case(A_NUMBER, VE, usage=usage)

    assert second.retrieved_at == first.retrieved_at
    assert second.retrieved_at == dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)


async def test_cache_expires(usage, service, browser, time_machine, settings):
    await service.get_case(A_NUMBER, VE, usage=usage)
    time_machine.move_to(
        dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
        + dt.timedelta(seconds=settings.lookup.cache_ttl + 1),
        tick=False,
    )
    result = await service.get_case(A_NUMBER, VE, usage=usage)

    assert result.cached is False
    assert len(browser.calls) == 2


async def test_refresh_bypasses_cache(usage, service, browser):
    await service.get_case(A_NUMBER, VE, usage=usage)
    result = await service.get_case(A_NUMBER, VE, usage=usage, refresh=True)

    assert result.cached is False
    assert len(browser.calls) == 2


async def test_cache_is_keyed_on_nationality(usage, service, browser):
    await service.get_case(A_NUMBER, VE, usage=usage)
    await service.get_case(A_NUMBER, resolve("MX"), usage=usage)
    assert browser.calls == [
        (A_NUMBER, "VE", "VENEZUELA"),
        (A_NUMBER, "MX", "MEXICO"),
    ]


async def test_failures_are_not_cached(usage, service, browser):
    browser.error = CaptchaError("boom", reason=CaptchaError.Reason.NO_RESPONSE)
    with pytest.raises(CaptchaError):
        await service.get_case(A_NUMBER, VE, usage=usage)

    browser.error = None
    result = await service.get_case(A_NUMBER, VE, usage=usage)
    assert result.cached is False
    assert len(browser.calls) == 2


##### Queue guard #####


async def test_queue_guard_rejects_when_wait_is_too_long(usage, service, browser):
    service.avg_lookup_seconds = 12.0
    # Simulate a deep queue
    service._pending = 20  # 20 * 12s = 240s > max_queue_wait (30s)

    with pytest.raises(QueueTimeoutError):
        await service.get_case(A_NUMBER, VE, usage=usage)
    assert browser.calls == []


async def test_queue_guard_allows_a_short_queue(usage, service):
    service.avg_lookup_seconds = 12.0
    service._pending = 2  # 24s, well under the limit

    result = await service.get_case(A_NUMBER, VE, usage=usage)
    assert result.cached is False


async def test_cache_hits_skip_the_queue_guard(usage, service):
    await service.get_case(A_NUMBER, VE, usage=usage)

    service._pending = 100
    result = await service.get_case(A_NUMBER, VE, usage=usage)
    assert result.cached is True


async def test_pending_is_released_after_a_failure(usage, service, browser):
    browser.error = CaptchaError("boom", reason=CaptchaError.Reason.NO_RESPONSE)
    with pytest.raises(CaptchaError):
        await service.get_case(A_NUMBER, VE, usage=usage)
    assert service.pending == 0


##### Browser dispatch #####


CAPTCHA = CaptchaError("boom", reason=CaptchaError.Reason.REJECTED)


@pytest.fixture
def browsers(master_hearing):
    return {
        "a": FakeAcisBrowser(payload=master_hearing),
        "b": FakeAcisBrowser(payload=master_hearing),
    }


@pytest.fixture
def multi_browser_service(browsers, settings, clock):
    return CaseService(browsers, settings, clock=clock)


async def test_lookups_alternate_between_idle_browsers(
    usage, multi_browser_service, browsers, clock
):
    a, b = browsers.values()
    for i in range(4):
        await multi_browser_service.get_case(f"10000000{i}", VE, usage=usage)
        clock.now += 15
    assert len(a.calls) == 2
    assert len(b.calls) == 2


async def test_captcha_retries_on_another_browser(
    usage, multi_browser_service, browsers
):
    a, b = browsers.values()
    a.error = CAPTCHA
    result = await multi_browser_service.get_case(A_NUMBER, VE, usage=usage)
    assert result.cached is False
    assert len(a.calls) == 1
    assert len(b.calls) == 1

    await multi_browser_service.get_case("100000001", VE, usage=usage)
    assert len(a.calls) == 1
    assert len(b.calls) == 2


async def test_browser_is_used_again_after_cooldown(
    usage, multi_browser_service, browsers, settings, clock
):
    a = browsers["a"]
    a.error = CAPTCHA
    await multi_browser_service.get_case(A_NUMBER, VE, usage=usage)
    a.error = None

    clock.now += settings.lookup.captcha_cooldown + 1
    await multi_browser_service.get_case("100000001", VE, usage=usage)
    assert len(a.calls) == 2


async def test_all_browsers_unavailable_raises_with_retry_after(
    usage, multi_browser_service, browsers
):
    a, b = browsers.values()
    a.error = b.error = CAPTCHA
    with pytest.raises(CaptchaError):
        await multi_browser_service.get_case(A_NUMBER, VE, usage=usage)
    assert len(a.calls) == len(b.calls) == 1

    with pytest.raises(BrowserUnavailableError) as excinfo:
        await multi_browser_service.get_case("100000001", VE, usage=usage)
    assert 0 < excinfo.value.retry_after <= 300
    assert len(a.calls) == len(b.calls) == 1


async def test_lookup_interval_applies_per_browser(
    usage, multi_browser_service, settings, clock, monkeypatch
):
    service = multi_browser_service
    settings.lookup.interval = 30
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)
        clock.now += delay

    monkeypatch.setattr("eoir_api.service.anyio.sleep", fake_sleep)

    await service.get_case("100000000", VE, usage=usage)
    clock.now += 10
    await service.get_case("100000001", VE, usage=usage)
    assert sleeps == []

    clock.now += 10
    await service.get_case("100000002", VE, usage=usage)
    assert sleeps == [10]


async def test_estimated_wait_shrinks_with_more_browsers(
    multi_browser_service, browsers, settings
):
    one = CaseService({"a": browsers["a"]}, settings)
    two = multi_browser_service
    one.avg_lookup_seconds = two.avg_lookup_seconds = 10.0
    one._pending = two._pending = 4
    assert one.estimated_wait == 40
    assert two.estimated_wait == 20


@pytest.mark.parametrize(
    "reason", [CaptchaError.Reason.NO_REQUEST, CaptchaError.Reason.CHALLENGE]
)
async def test_challenge_without_token_starts_a_cooldown(
    usage, multi_browser_service, browsers, reason
):
    a, b = browsers.values()
    a.error = CaptchaError("no token", reason=reason)
    await multi_browser_service.get_case(A_NUMBER, VE, usage=usage)
    assert len(b.calls) == 1

    a.error = None
    await multi_browser_service.get_case("100000001", VE, usage=usage)
    assert len(a.calls) == 1
    assert len(b.calls) == 2


async def test_missing_response_does_not_start_a_cooldown(
    usage, multi_browser_service, browsers
):
    a, b = browsers.values()
    a.error = CaptchaError("timed out", reason=CaptchaError.Reason.NO_RESPONSE)
    await multi_browser_service.get_case(A_NUMBER, VE, usage=usage)
    assert len(b.calls) == 1

    a.error = None
    await multi_browser_service.get_case("100000001", VE, usage=usage)
    assert len(a.calls) == 2


async def test_captcha_with_other_browser_in_cooldown_reports_its_retry_after(
    usage, multi_browser_service, browsers, clock
):
    a, b = browsers.values()
    a.error = CAPTCHA
    await multi_browser_service.get_case(A_NUMBER, VE, usage=usage)
    assert len(a.calls) == len(b.calls) == 1

    clock.now += 100
    b.error = CAPTCHA
    with pytest.raises(BrowserUnavailableError) as excinfo:
        await multi_browser_service.get_case("100000001", VE, usage=usage)
    assert excinfo.value.retry_after == 200


async def test_lookup_waiting_on_a_lock_skips_a_browser_that_entered_cooldown(
    usage, service, browser, settings, clock
):
    started = anyio.Event()
    release = anyio.Event()

    async def slow_captcha(*_args):
        started.set()
        await release.wait()
        raise CAPTCHA

    browser.lookup = slow_captcha  # type: ignore[method-assign]
    outcomes: list[type[Exception]] = []

    async def request(a_number: str) -> None:
        try:
            await service.get_case(a_number, VE, usage=usage)
        except (CaptchaError, BrowserUnavailableError) as exc:
            outcomes.append(type(exc))

    async with anyio.create_task_group() as tg:
        tg.start_soon(request, A_NUMBER)
        await started.wait()
        tg.start_soon(request, "100000001")  # queues on the browser's lock
        await anyio.lowlevel.checkpoint()
        release.set()

    assert outcomes == [CaptchaError, BrowserUnavailableError]


##### Browsers per lookup #####


@pytest.mark.parametrize(
    "reason", [CaptchaError.Reason.REJECTED, CaptchaError.Reason.NO_RESPONSE]
)
async def test_lookup_gives_up_after_max_browsers_fail_captcha(
    usage, master_hearing, settings, clock, reason
):
    a, b, c = (FakeAcisBrowser(payload=master_hearing) for _ in "abc")
    service = CaseService({"a": a, "b": b, "c": c}, settings, clock=clock)
    a.error = b.error = c.error = CaptchaError("boom", reason=reason)
    with pytest.raises(CaptchaError):
        await service.get_case(A_NUMBER, VE, usage=usage)
    assert [len(a.calls), len(b.calls), len(c.calls)] == [1, 1, 0]
    assert service.retry_after == 0


def configure_browsers(settings, **browsers: tuple[str, str | None]) -> None:
    settings.browsers = [
        Browser(name=name, proxy=Proxy(server=server), group=group)
        for name, (server, group) in browsers.items()
    ]


async def test_retry_prefers_a_browser_in_another_group(
    usage, master_hearing, settings, clock
):
    configure_browsers(
        settings,
        a=("socks5://host-a:1081", "provider-a"),
        b=("socks5://host-b:1081", "provider-a"),
        c=("socks5://host-c:1081", "provider-b"),
    )
    a, b, c = (FakeAcisBrowser(payload=master_hearing) for _ in "abc")
    service = CaseService({"a": a, "b": b, "c": c}, settings, clock=clock)
    a.error = CAPTCHA
    await service.get_case(A_NUMBER, VE, usage=usage)
    assert len(b.calls) == 0
    assert len(c.calls) == 1


async def test_retry_falls_back_to_the_same_group(
    usage, master_hearing, settings, clock
):
    configure_browsers(
        settings,
        a=("socks5://host-a:1081", "provider-a"),
        b=("socks5://host-b:1081", "provider-a"),
    )
    a, b = (FakeAcisBrowser(payload=master_hearing) for _ in "ab")
    service = CaseService({"a": a, "b": b}, settings, clock=clock)
    a.error = CAPTCHA
    await service.get_case(A_NUMBER, VE, usage=usage)
    assert len(b.calls) == 1
