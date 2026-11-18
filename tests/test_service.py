from __future__ import annotations

import datetime as dt

import anyio
import anyio.lowlevel
import httpx2
import pytest
from acis_core.exceptions import BrowserLostError, CaptchaError
from acis_core.nationalities import resolve

from eoir_api.exceptions import BrowserUnavailableError, QueueTimeoutError
from eoir_api.remote import RemoteBrowser
from eoir_api.service import CaseService
from eoir_api.settings import Browser, Secret, Tenant
from eoir_api.usage import TenantUsage

from .conftest import FakeAcisBrowser, mock_runner

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


##### Tenant max_concurrency #####


def hold_lookups(browser) -> tuple[anyio.Event, anyio.Event]:
    started, release = anyio.Event(), anyio.Event()
    lookup = browser.lookup

    async def held(*args):
        started.set()
        await release.wait()
        return await lookup(*args)

    browser.lookup = held  # type: ignore[method-assign]
    return started, release


@pytest.fixture
def maxed(usage_service) -> TenantUsage:
    return TenantUsage(
        usage_service,
        Tenant(name="capped", key=Secret("capped-test-secret"), max_concurrency=1),
    )


async def test_max_concurrency_is_released_after_a_lookup_fails(
    maxed, service, browser
):
    browser.error = CaptchaError("boom", reason=CaptchaError.Reason.NO_RESPONSE)
    with pytest.raises(CaptchaError):
        await service.get_case(A_NUMBER, VE, usage=maxed)

    browser.error = None
    result = await service.get_case(A_NUMBER, VE, usage=maxed)
    assert result.cached is False


async def test_cache_hit_is_served_to_a_tenant_at_max_concurrency(
    maxed, service, browser
):
    await service.get_case(A_NUMBER, VE, usage=maxed)
    started, release = hold_lookups(browser)

    async def in_flight() -> None:
        await service.get_case("100000001", VE, usage=maxed)

    async with anyio.create_task_group() as tg:
        tg.start_soon(in_flight)
        await started.wait()
        result = await service.get_case(A_NUMBER, VE, usage=maxed)
        release.set()

    assert result.cached is True


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
    browser.error = CAPTCHA
    started, release = hold_lookups(browser)
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


def configure_browsers(settings, **groups: str) -> None:
    settings.browsers = [
        Browser(name=name, runner="mac", group=group) for name, group in groups.items()
    ]


async def test_retry_prefers_a_browser_in_another_group(
    usage, master_hearing, settings, clock
):
    configure_browsers(
        settings,
        a="provider-a",
        b="provider-a",
        c="provider-b",
    )
    a, b, c = (FakeAcisBrowser(payload=master_hearing) for _ in "abc")
    service = CaseService({"a": a, "b": b, "c": c}, settings, clock=clock)
    a.error = CAPTCHA
    await service.get_case(A_NUMBER, VE, usage=usage)
    assert len(b.calls) == 0
    assert len(c.calls) == 1


async def test_retry_prefers_the_group_challenged_longest_ago(
    usage, master_hearing, settings, clock
):
    configure_browsers(
        settings,
        a="provider-a",
        b="provider-b",
        d="provider-c",
        c="provider-b",
        e="provider-d",
    )
    a, b, c, d, e = (FakeAcisBrowser(payload=master_hearing) for _ in "abcde")
    service = CaseService(  # ties break on dict order: d before c
        {"a": a, "b": b, "d": d, "c": c, "e": e}, settings, clock=clock
    )
    a.error = b.error = d.error = CAPTCHA
    with pytest.raises(CaptchaError):  # a, then b: provider-b is now challenged
        await service.get_case(A_NUMBER, VE, usage=usage)

    await service.get_case("100000001", VE, usage=usage)  # d, then a retry

    assert len(c.calls) == 0
    assert len(e.calls) == 1


async def test_retry_falls_back_to_the_same_group(
    usage, master_hearing, settings, clock
):
    configure_browsers(
        settings,
        a="provider-a",
        b="provider-a",
    )
    a, b = (FakeAcisBrowser(payload=master_hearing) for _ in "ab")
    service = CaseService({"a": a, "b": b}, settings, clock=clock)
    a.error = CAPTCHA
    await service.get_case(A_NUMBER, VE, usage=usage)
    assert len(b.calls) == 1


##### Runners #####


LOST = BrowserLostError("Runner one unreachable")


def runner_service(settings, clock, master_hearing, **browsers: str):
    settings.browsers = [Browser(name=b, runner=r) for b, r in browsers.items()]
    fakes = {name: FakeAcisBrowser(payload=master_hearing) for name in browsers}
    return CaseService(fakes, settings, clock=clock), fakes


async def test_lost_browser_retries_on_another_browser(
    usage, settings, clock, master_hearing
):
    service, fakes = runner_service(settings, clock, master_hearing, a="one", b="two")
    fakes["a"].error = LOST
    result = await service.get_case(A_NUMBER, VE, usage=usage)
    assert result.cached is False
    assert len(fakes["b"].calls) == 1


async def test_lost_runner_without_alternative_raises_browser_lost(
    usage, settings, clock, master_hearing
):
    service, fakes = runner_service(settings, clock, master_hearing, a="one")
    fakes["a"].error = LOST
    with pytest.raises(BrowserLostError):
        await service.get_case(A_NUMBER, VE, usage=usage)


async def test_runner_failover_counts_against_max_browsers(
    usage, settings, clock, master_hearing
):
    settings.lookup.max_browsers = 1
    service, fakes = runner_service(settings, clock, master_hearing, a="one", b="two")
    fakes["a"].error = LOST
    with pytest.raises(BrowserLostError):
        await service.get_case(A_NUMBER, VE, usage=usage)
    assert len(fakes["b"].calls) == 0


class FakeRunner:
    def __init__(self, payload) -> None:
        self.payload = payload
        self.healthy = True
        self.reachable = True
        self.lookups = 0

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if not self.reachable:
            raise httpx2.ConnectError("connection refused", request=request)
        if request.url.path == "/healthz":
            return httpx2.Response(200 if self.healthy else 503)
        self.lookups += 1
        return httpx2.Response(200, json=self.payload)


@pytest.fixture
def fake_runner(master_hearing) -> FakeRunner:
    return FakeRunner(master_hearing)


def remote_service(settings, clock, fake_runner, master_hearing):
    settings.browsers = [
        Browser(name="a", runner="one"),
        Browser(name="b", runner="two"),
    ]
    remote = RemoteBrowser(mock_runner(fake_runner, "one"), "a")
    other = FakeAcisBrowser(payload=master_hearing)
    return CaseService({"a": remote, "b": other}, settings, clock=clock), remote, other


async def test_unhealthy_runner_is_skipped_until_it_answers_again(
    usage, settings, clock, fake_runner, master_hearing
):
    service, remote, other = remote_service(
        settings, clock, fake_runner, master_hearing
    )

    fake_runner.healthy = False
    await remote.runner.check_health()
    for i in range(2):
        await service.get_case(f"10000000{i}", VE, usage=usage)
    assert (fake_runner.lookups, len(other.calls)) == (0, 2)

    fake_runner.healthy = True
    await remote.runner.check_health()
    await service.get_case("100000002", VE, usage=usage)
    assert fake_runner.lookups == 1


async def test_unreachable_runner_is_skipped_before_its_next_health_check(
    usage, settings, clock, fake_runner, master_hearing
):
    service, remote, other = remote_service(
        settings, clock, fake_runner, master_hearing
    )
    fake_runner.reachable = False
    await service.get_case(A_NUMBER, VE, usage=usage)  # fails over to b
    assert len(other.calls) == 1
    assert not remote.is_available

    clock.now += 60
    await service.get_case("100000001", VE, usage=usage)
    assert len(other.calls) == 2


async def test_all_runners_down_raises_unavailable(usage, settings, clock, fake_runner):
    settings.browsers = [Browser(name="a", runner="one")]
    remote = RemoteBrowser(mock_runner(fake_runner, "one"), "a")
    service = CaseService({"a": remote}, settings, clock=clock)
    fake_runner.healthy = False
    await remote.runner.check_health()
    with pytest.raises(BrowserUnavailableError):
        await service.get_case(A_NUMBER, VE, usage=usage)
    assert fake_runner.lookups == 0
