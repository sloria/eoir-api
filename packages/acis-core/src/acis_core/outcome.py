"""Classification of ACIS response payloads."""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Any

from acis_core.exceptions import (
    CaptchaError,
    CaseNotFoundError,
    CaseUnavailableError,
    InvalidNationalityError,
    UpstreamError,
)


class Outcome(StrEnum):
    """Classification of an ACIS payload by its pinned ``message`` fragments."""

    OK = auto()
    CAPTCHA_REJECTED = auto()
    UNAVAILABLE = auto()
    NOT_FOUND = auto()
    INVALID_NATIONALITY = auto()
    OTHER = auto()

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Outcome:
        data = payload.get("Data")
        if isinstance(data, dict):
            if data.get("AlienName") and data.get("CaseID"):
                return cls.OK
            return cls.OTHER
        message = payload.get("message") or ""
        for fragment, outcome in MESSAGES:
            if fragment in message:
                return outcome
        return cls.OTHER


MESSAGES = (
    ("Invalid Captcha Provided", Outcome.CAPTCHA_REJECTED),
    ("Case information is unavailable", Outcome.UNAVAILABLE),
    ("No case info found", Outcome.NOT_FOUND),
    ("Invalid nationality code", Outcome.INVALID_NATIONALITY),
)


def raise_for_outcome(payload: dict[str, Any]) -> None:
    """Raise the exception matching the payload's outcome; return for a success."""
    outcome = Outcome.from_payload(payload)
    if outcome is Outcome.OK:
        return
    message = payload.get("message") or ""
    if outcome is Outcome.CAPTCHA_REJECTED:
        raise CaptchaError(
            message, reason=CaptchaError.Reason.REJECTED, payload=payload
        )
    if outcome is Outcome.NOT_FOUND:
        raise CaseNotFoundError(message, payload=payload)
    if outcome is Outcome.INVALID_NATIONALITY:
        raise InvalidNationalityError(message, payload=payload)
    if outcome is Outcome.UNAVAILABLE:
        raise CaseUnavailableError(message, payload=payload)
    raise UpstreamError("ACIS returned an unexpected payload", payload=payload)
