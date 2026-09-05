from __future__ import annotations

from enum import StrEnum, auto
from typing import Any


class AcisError(Exception):
    """Base class for failures talking to ACIS."""

    def __init__(self, *args: object, payload: dict[str, Any] | None = None) -> None:
        super().__init__(*args)
        self.payload = payload


class InvalidANumberError(AcisError):
    """Raised when an A-Number isn't valid."""


class UnknownNationalityError(AcisError):
    """Raised when a nationality code or name can't be resolved."""


class CaptchaError(AcisError):
    """Raised when an hCaptcha token can't be obtained or the token is refused."""

    class Reason(StrEnum):
        NO_REQUEST = auto()
        """Form was submitted but no case request followed."""
        NO_RESPONSE = auto()
        """Case request went out but nothing came back."""
        REJECTED = auto()
        """Token was submitted and rejected."""

    def __init__(
        self, message: str, *, reason: Reason, payload: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, payload=payload)
        self.reason = reason


class CaseNotFoundError(AcisError):
    """Raised when ACIS has no case for a given A-Number."""


class InvalidNationalityError(AcisError):
    """Raised when ACIS rejects the nationality code."""


class CaseUnavailableError(AcisError):
    """Raised when the case exists but ACIS won't release information for it."""


class UpstreamError(AcisError):
    """Raised when ACIS returns an unexpected response."""
