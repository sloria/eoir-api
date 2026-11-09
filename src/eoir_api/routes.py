from __future__ import annotations

import math
from typing import Annotated

import msgspec
import structlog
from acis_browser import (
    BrowserLostError,
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidNationalityError,
    UpstreamError,
)
from acis_core.a_numbers import InvalidANumberError, normalize_a_number
from acis_core.nationalities import UnknownNationalityError, resolve
from litestar import Response, get, post
from litestar.di import NamedDependency
from litestar.exceptions import (
    ClientException,
    HTTPException,
    NotFoundException,
    ServiceUnavailableException,
    TooManyRequestsException,
)
from litestar.params import JSONBody
from litestar.status_codes import (
    HTTP_200_OK,
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_502_BAD_GATEWAY,
)

from eoir_api.exceptions import (
    BrowserUnavailableError,
    QueueTimeoutError,
    QuotaExceededError,
)
from eoir_api.service import Case, CaseService
from eoir_api.usage import Quota, TenantUsage

logger = structlog.get_logger()


##### Errors and response models #####


class UnprocessableContentException(ClientException):
    status_code = HTTP_422_UNPROCESSABLE_ENTITY


class BadGatewayException(HTTPException):
    status_code = HTTP_502_BAD_GATEWAY


class CaseLookup(msgspec.Struct, forbid_unknown_fields=True):
    a_number: str
    nationality: Annotated[
        str,
        msgspec.Meta(
            description="EOIR nationality code or country name. See the Nationality dropdown on https://acis.eoir.justice.gov/ for the full list.",
        ),
    ]
    refresh: Annotated[
        bool, msgspec.Meta(description="Bypass the cache and force a fresh lookup.")
    ] = False


##### Route handlers #####


UNAVAILABLE_DETAIL = "Lookup temporarily unavailable. Retry later."


def retry_after_header(seconds: float) -> dict[str, str]:
    return {"Retry-After": str(max(1, round(seconds)))}


def rate_limit_headers(quota: Quota | None) -> dict[str, str]:
    if quota is None:
        return {}
    return {
        "X-RateLimit-Limit": str(quota.limit),
        "X-RateLimit-Remaining": str(quota.remaining),
        "X-RateLimit-Reset": str(math.ceil(quota.reset_at.timestamp())),
    }


@get("/", exclude_from_auth=True, include_in_schema=False, sync_to_thread=False)
def index() -> dict[str, str]:
    return {"docs": "/schema", "openapi": "/schema/openapi.json"}


@get(
    "/healthz",
    media_type="text/plain",
    exclude_from_auth=True,
    include_in_schema=False,
    sync_to_thread=False,
)
def health() -> Response:
    return Response("ok", status_code=200)


@post(
    "/cases/lookup",
    status_code=HTTP_200_OK,
    raises=[
        NotFoundException,
        UnprocessableContentException,
        TooManyRequestsException,
        BadGatewayException,
        ServiceUnavailableException,
        BadGatewayException,
    ],
)
async def lookup_case(
    *,
    data: JSONBody[CaseLookup],
    service: NamedDependency[CaseService],
    usage: NamedDependency[TenantUsage],
) -> Response[Case]:
    """Look up current case information for an A-Number and nationality."""
    try:
        case = await fetch_case(service, usage, data)
    except HTTPException as exc:
        exc.headers = {
            **(exc.headers or {}),
            **rate_limit_headers(await usage.quota()),
        }
        raise
    return Response(case, headers=rate_limit_headers(await usage.quota()))


async def fetch_case(
    service: CaseService, usage: TenantUsage, data: CaseLookup
) -> Case:
    try:
        cleaned = normalize_a_number(data.a_number)
    except InvalidANumberError as exc:
        raise ClientException(str(exc)) from exc

    try:
        resolved = resolve(data.nationality)
    except UnknownNationalityError as exc:
        raise ClientException(str(exc)) from exc

    log = logger.bind(nat_code=resolved.code)
    try:
        return await service.get_case(
            cleaned, resolved, usage=usage, refresh=data.refresh
        )
    except CaseNotFoundError as exc:
        log.info("case.not_found")
        raise NotFoundException("No case found for that A-Number.") from exc
    except InvalidNationalityError as exc:
        log.info("case.invalid_nationality")
        raise NotFoundException(
            "No case found for that A-Number with that nationality code."
        ) from exc
    except CaseUnavailableError as exc:
        log.info("case.unavailable")
        raise UnprocessableContentException(str(exc)) from exc
    except QuotaExceededError as exc:
        raise TooManyRequestsException(
            "Daily quota exceeded",
            headers=retry_after_header(exc.retry_after),
            extra={"reason": "quota_exceeded"},
        ) from exc
    except QueueTimeoutError as exc:
        if exc.max_concurrency is not None:
            log.info("case.tenant_capped", max_concurrency=exc.max_concurrency)
        else:
            log.info("case.queue_full", error=str(exc))
        raise TooManyRequestsException(
            "Too many pending lookups. Retry later.",
            headers=retry_after_header(service.avg_lookup_seconds),
        ) from exc
    except CaptchaError as exc:
        log.warning("case.captcha_error", reason=exc.reason)
        raise ServiceUnavailableException(
            UNAVAILABLE_DETAIL, headers=retry_after_header(service.retry_after)
        ) from exc
    except BrowserUnavailableError as exc:
        log.info("case.browsers_unavailable", retry_after=round(exc.retry_after))
        raise ServiceUnavailableException(
            UNAVAILABLE_DETAIL, headers=retry_after_header(exc.retry_after)
        ) from exc
    except BrowserLostError as exc:
        log.warning("case.browser_lost", error=str(exc))
        raise ServiceUnavailableException(
            UNAVAILABLE_DETAIL, headers=retry_after_header(1)
        ) from exc
    except UpstreamError as exc:
        log.warning("case.upstream_error", error=str(exc))
        raise BadGatewayException("EOIR lookup failed.") from exc


ROUTE_HANDLERS = [index, health, lookup_case]
