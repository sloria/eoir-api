"""Classification of ACIS response payloads."""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Any


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
