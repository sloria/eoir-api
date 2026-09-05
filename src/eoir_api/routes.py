from __future__ import annotations

from typing import Annotated

import structlog
from acis_browser import (
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidANumberError,
    InvalidNationalityError,
    UnknownNationalityError,
    UpstreamError,
    normalize_a_number,
    redact,
    resolve,
)
from litestar import Response, get
from litestar.di import NamedDependency
from litestar.exceptions import (
    ClientException,
    HTTPException,
    NotFoundException,
    ServiceUnavailableException,
    TooManyRequestsException,
)
from litestar.params import FromPath, QueryParameter
from litestar.status_codes import (
    HTTP_422_UNPROCESSABLE_ENTITY,
    HTTP_502_BAD_GATEWAY,
)

from eoir_api.exceptions import QueueTimeoutError
from eoir_api.guards import require_api_key
from eoir_api.service import Case, CaseService

logger = structlog.get_logger()


##### Errors and response models #####


class UnprocessableContentException(ClientException):
    status_code = HTTP_422_UNPROCESSABLE_ENTITY


class BadGatewayException(HTTPException):
    status_code = HTTP_502_BAD_GATEWAY


##### Route handlers #####


@get("/healthz", media_type="text/plain", include_in_schema=False, sync_to_thread=False)
def health() -> Response:
    return Response("ok", status_code=200)


@get(
    "/cases/{a_number:str}",
    guards=[require_api_key],
    raises=[
        NotFoundException,
        UnprocessableContentException,
        TooManyRequestsException,
        ServiceUnavailableException,
    ],
)
async def get_case(
    *,
    a_number: FromPath[str],
    service: NamedDependency[CaseService],
    nationality: Annotated[
        str,
        QueryParameter(
            description="EOIR nationality code or country name. See the Nationality dropdown on https://acis.eoir.justice.gov/ for the full list.",
        ),
    ] = "",
    refresh: Annotated[
        bool,
        QueryParameter(description="Bypass the cache and force a fresh lookup."),
    ] = False,
) -> Case:
    """Look up current case information for an A-Number and nationality."""
    try:
        cleaned = normalize_a_number(a_number)
    except InvalidANumberError as exc:
        raise ClientException(str(exc)) from exc

    try:
        resolved = resolve(nationality)
    except UnknownNationalityError as exc:
        raise ClientException(str(exc)) from exc

    log = logger.bind(a_number=redact(cleaned), nat_code=resolved.code)
    try:
        return await service.get_case(cleaned, resolved, refresh=refresh)
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
    except QueueTimeoutError as exc:
        log.info("case.queue_full")
        retry_after = max(1, round(service.avg_lookup_seconds))
        raise TooManyRequestsException(
            str(exc), headers={"Retry-After": str(retry_after)}
        ) from exc
    except CaptchaError as exc:
        log.warning("case.captcha_error", reason=exc.reason)
        raise ServiceUnavailableException(
            "Could not obtain a captcha token after several attempts. Try again.",
            headers={"Retry-After": "300"},
        ) from exc
    except UpstreamError as exc:
        log.warning("case.upstream_error", error=str(exc))
        raise BadGatewayException(f"Upstream error: {exc}") from exc


ROUTE_HANDLERS = [health, get_case]
