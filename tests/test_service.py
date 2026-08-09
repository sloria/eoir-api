from __future__ import annotations

import datetime as dt

import pytest

from eoir_api.exceptions import QueueTimeoutError
from eoir_api.lib.acis import CaptchaError
from eoir_api.nationalities import resolve
from eoir_api.service import CaseService

pytestmark = pytest.mark.anyio

A_NUMBER = "999999999"
VE = resolve("VE")


##### Cache #####


async def test_second_call_is_served_from_cache(service, browser):
    first = await service.get_case(A_NUMBER, VE)
    second = await service.get_case(A_NUMBER, VE)

    assert first.cached is False
    assert second.cached is True
    # The browser was only driven once.
    assert browser.calls == [(A_NUMBER, "VE", "VENEZUELA")]


async def test_cache_hit_does_not_refresh_retrieved_at(service, time_machine):
    first = await service.get_case(A_NUMBER, VE)
    time_machine.move_to(dt.datetime(2026, 7, 25, 12, 30, tzinfo=dt.UTC), tick=False)
    second = await service.get_case(A_NUMBER, VE)

    assert second.retrieved_at == first.retrieved_at
    assert second.retrieved_at == dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)


async def test_cache_expires(service, browser, time_machine, settings):
    await service.get_case(A_NUMBER, VE)
    time_machine.move_to(
        dt.datetime(2026, 7, 25, 12, 0, tzinfo=dt.UTC)
        + dt.timedelta(seconds=settings.cache_ttl + 1),
        tick=False,
    )
    result = await service.get_case(A_NUMBER, VE)

    assert result.cached is False
    assert len(browser.calls) == 2


async def test_refresh_bypasses_cache(service, browser):
    await service.get_case(A_NUMBER, VE)
    result = await service.get_case(A_NUMBER, VE, refresh=True)

    assert result.cached is False
    assert len(browser.calls) == 2


async def test_cache_is_keyed_on_nationality(service, browser):
    await service.get_case(A_NUMBER, VE)
    await service.get_case(A_NUMBER, resolve("MX"))
    assert browser.calls == [
        (A_NUMBER, "VE", "VENEZUELA"),
        (A_NUMBER, "MX", "MEXICO"),
    ]


async def test_failures_are_not_cached(service, browser):
    browser.error = CaptchaError("boom", reason=CaptchaError.Reason.NO_REQUEST)
    with pytest.raises(CaptchaError):
        await service.get_case(A_NUMBER, VE)

    browser.error = None
    result = await service.get_case(A_NUMBER, VE)
    assert result.cached is False
    assert len(browser.calls) == 2


##### Queue guard #####


async def test_queue_guard_rejects_when_wait_is_too_long(settings, browser):
    service = CaseService(browser, settings)
    service.avg_lookup_seconds = 12.0
    # Simulate a deep queue
    service._pending = 20  # 20 * 12s = 240s > max_queue_wait (120s)

    with pytest.raises(QueueTimeoutError):
        await service.get_case(A_NUMBER, VE)
    assert browser.calls == []


async def test_queue_guard_allows_a_short_queue(settings, browser):
    service = CaseService(browser, settings)
    service.avg_lookup_seconds = 12.0
    service._pending = 2  # 24s, well under the limit

    result = await service.get_case(A_NUMBER, VE)
    assert result.cached is False


async def test_cache_hits_skip_the_queue_guard(settings, browser):
    service = CaseService(browser, settings)
    await service.get_case(A_NUMBER, VE)

    service._pending = 100
    result = await service.get_case(A_NUMBER, VE)
    assert result.cached is True


async def test_pending_is_released_after_a_failure(service, browser):
    browser.error = CaptchaError("boom", reason=CaptchaError.Reason.NO_REQUEST)
    with pytest.raises(CaptchaError):
        await service.get_case(A_NUMBER, VE)
    assert service.pending == 0
