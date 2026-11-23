from __future__ import annotations

from enum import StrEnum, auto
from typing import Any

from acis_core.exceptions import ACISError


class CaptchaError(ACISError):
    """Raised when an hCaptcha token can't be obtained or the token is refused."""

    class Reason(StrEnum):
        NO_REQUEST = auto()
        """Form was submitted but no case request followed."""
        CHALLENGE = auto()
        """hCaptcha showed a visible challenge instead of minting a token."""
        NO_RESPONSE = auto()
        """Case request went out but nothing came back."""
        REJECTED = auto()
        """Token was submitted and rejected."""

    def __init__(
        self, message: str, *, reason: Reason, payload: dict[str, Any] | None = None
    ) -> None:
        super().__init__(message, payload=payload)
        self.reason = reason


class CaseNotFoundError(ACISError):
    """Raised when ACIS has no case for a given A-Number."""


class InvalidNationalityError(ACISError):
    """Raised when ACIS rejects the nationality code."""


class CaseUnavailableError(ACISError):
    """Raised when the case exists but ACIS won't release information for it."""


class UpstreamError(ACISError):
    """Raised when ACIS returns an unexpected response."""


class BrowserLostError(UpstreamError):
    """Raised when Chrome dies or isn't running."""
