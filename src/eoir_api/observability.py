"""Logging and Sentry setup shared by the hub and the runner."""

from __future__ import annotations

import logging
import sys
from typing import TYPE_CHECKING, Any

import sentry_sdk
import structlog
from acis_core.exceptions import CaptchaError
from litestar.logging.config import (
    LoggingConfig,
    StructLoggingConfig,
    default_structlog_processors,
    default_structlog_standard_lib_processors,
)
from litestar.middleware.logging import LoggingMiddlewareConfig
from litestar.plugins.structlog import StructlogConfig, StructlogPlugin
from sentry_sdk.integrations.litestar import LitestarIntegration

from eoir_api.exceptions import BrowserUnavailableError

if TYPE_CHECKING:
    from eoir_api.settings import Sentry


def is_expected_error(hint: Any) -> bool:
    exc_info = (hint or {}).get("exc_info")
    exc = exc_info[1] if exc_info else None
    while exc is not None:
        if isinstance(exc, (CaptchaError, BrowserUnavailableError)):
            return True
        exc = exc.__cause__
    return False


def scrub_sentry_event(event: Any, hint: Any) -> Any:
    # Captcha errors and cooldowns are expected, so don't send them to Sentry
    if is_expected_error(hint):
        return None
    request = event.get("request")
    if request:
        request.pop("data", None)
    return event


def init_sentry(sentry: Sentry) -> None:
    if sentry.dsn:
        sentry_sdk.init(
            sentry.dsn,
            include_local_variables=False,
            send_default_pii=False,
            before_send=scrub_sentry_event,
            environment=sentry.environment or None,
            integrations=[LitestarIntegration()],
        )


def create_structlog_plugin() -> StructlogPlugin:
    logging.getLogger("uvicorn.access").addFilter(lambda _record: False)
    return StructlogPlugin(
        config=StructlogConfig(
            structlog_logging_config=StructLoggingConfig(
                processors=default_structlog_processors(as_json=not is_tty()),
                standard_lib_logging_config=LoggingConfig(
                    formatters={
                        "standard": {
                            "()": structlog.stdlib.ProcessorFormatter,
                            "processors": [
                                structlog.stdlib.add_logger_name,
                                *default_structlog_standard_lib_processors(
                                    as_json=not is_tty()
                                ),
                            ],
                        }
                    }
                ),
            ),
            middleware_logging_config=LoggingMiddlewareConfig(
                request_log_fields=["path", "method"],
                response_log_fields=["status_code"],
            ),
        )
    )


def is_tty() -> bool:
    return bool(sys.stderr.isatty() or sys.stdout.isatty())
