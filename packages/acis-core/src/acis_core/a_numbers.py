"""Utilities for working with A-Numbers."""

from __future__ import annotations

import re

from acis_core.exceptions import AcisError


class InvalidANumberError(AcisError):
    """Raised when an A-Number isn't valid."""


_NON_DIGITS = re.compile(r"[\s\-]")


def normalize_a_number(value: str) -> str:
    candidate = _NON_DIGITS.sub("", value or "")
    candidate = candidate.removeprefix("A").removeprefix("a")
    if not candidate.isdigit() or len(candidate) != 9:
        raise InvalidANumberError(f"A-Number must be 9 digits, got {value!r}")
    return candidate


def redact(a_number: str) -> str:
    return f"***{a_number[-4:]}" if len(a_number) >= 4 else "***"
