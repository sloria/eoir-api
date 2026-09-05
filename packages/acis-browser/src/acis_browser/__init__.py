"""Automated browser to perform ACIS lookups."""

from acis_core.exceptions import AcisError
from acis_core.outcome import Outcome

from acis_browser.browser import AcisBrowser, raise_for_outcome
from acis_browser.exceptions import (
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidNationalityError,
    UpstreamError,
)

__all__ = [
    "AcisBrowser",
    "AcisError",
    "CaptchaError",
    "CaseNotFoundError",
    "CaseUnavailableError",
    "InvalidNationalityError",
    "Outcome",
    "UpstreamError",
    "raise_for_outcome",
]
