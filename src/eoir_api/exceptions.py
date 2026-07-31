from __future__ import annotations

from enum import StrEnum, auto


class EoirApiError(Exception):
    """Base class for all application errors."""


class ConfigurationError(EoirApiError):
    """Raised when settings are missing or invalid."""


class UnknownNationalityError(EoirApiError):
    """Raised when a nationality code or name can't be resolved."""


class InvalidANumberError(EoirApiError):
    """Raised when an A-Number isn't valid."""


class AcisError(EoirApiError):
    """Base class for failures talking to ACIS."""


class CaptchaError(AcisError):
    """Raised when an hCaptcha token can't be obtained or the token is refused."""

    class Reason(StrEnum):
        NO_REQUEST = auto()
        """Form was submitted but no case request followed."""
        NO_RESPONSE = auto()
        """Case request went out but nothing came back."""
        REJECTED = auto()
        """Token was submitted and rejected."""

    def __init__(self, message: str, *, reason: Reason) -> None:
        super().__init__(message)
        self.reason = reason


class CaseNotFoundError(AcisError):
    """Raised when ACIS has no case for a given A-Number and nationality."""


class CaseUnavailableError(AcisError):
    """Raised when the case exists but ACIS won't release information for it."""


class UpstreamError(AcisError):
    """Raised when ACIS returns an unexpected response."""


class QueueTimeoutError(EoirApiError):
    """Raised when a request would wait too long behind the browser lock."""
