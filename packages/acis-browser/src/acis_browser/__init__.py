"""Automated browser to perform ACIS lookups."""

from acis_core.exceptions import AcisError
from acis_core.outcome import Outcome, raise_for_outcome

from acis_browser.browser import AcisBrowser
from acis_browser.exceptions import (
    BrowserLostError,
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidNationalityError,
    UpstreamError,
)

__all__ = [
    "AcisBrowser",
    "AcisError",
    "BrowserLostError",
    "CaptchaError",
    "CaseNotFoundError",
    "CaseUnavailableError",
    "InvalidNationalityError",
    "Outcome",
    "UpstreamError",
    "raise_for_outcome",
]
