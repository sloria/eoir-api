"""Automated browser to perform ACIS lookups."""

import warnings

from acis_core.exceptions import ACISError
from acis_core.outcome import Outcome

from acis_browser.browser import ACISBrowser, raise_for_outcome
from acis_browser.exceptions import (
    BrowserLostError,
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidNationalityError,
    UpstreamError,
)

__all__ = [
    "ACISBrowser",
    "ACISError",
    "BrowserLostError",
    "CaptchaError",
    "CaseNotFoundError",
    "CaseUnavailableError",
    "InvalidNationalityError",
    "Outcome",
    "UpstreamError",
    "raise_for_outcome",
]

_DEPRECATED_ALIASES = {"AcisBrowser": ACISBrowser, "AcisError": ACISError}


def __getattr__(name: str) -> object:
    if name in _DEPRECATED_ALIASES:
        new = _DEPRECATED_ALIASES[name]
        warnings.warn(
            f"{name} is deprecated; use {new.__name__}",
            DeprecationWarning,
            stacklevel=2,
        )
        return new
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
