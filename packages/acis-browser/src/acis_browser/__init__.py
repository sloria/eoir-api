"""Automated browser to perform ACIS lookups."""

from acis_browser.a_number import normalize_a_number, redact
from acis_browser.browser import AcisBrowser, Outcome, raise_for_outcome
from acis_browser.exceptions import (
    AcisError,
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidANumberError,
    InvalidNationalityError,
    UnknownNationalityError,
    UpstreamError,
)
from acis_browser.nationalities import Nationality, get_by_code, resolve

__all__ = [
    "AcisBrowser",
    "AcisError",
    "CaptchaError",
    "CaseNotFoundError",
    "CaseUnavailableError",
    "InvalidANumberError",
    "InvalidNationalityError",
    "Nationality",
    "Outcome",
    "UnknownNationalityError",
    "UpstreamError",
    "get_by_code",
    "normalize_a_number",
    "raise_for_outcome",
    "redact",
    "resolve",
]
