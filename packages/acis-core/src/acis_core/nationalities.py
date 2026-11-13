"""Utilities for working with EOIR nationality codes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from acis_core.exceptions import AcisError

HERE = Path(__file__).parent
REFERENCE_FILE = HERE / "reference" / "nationality-codes.json"


class UnknownNationalityError(AcisError):
    """Raised when a nationality code or name can't be resolved."""


PLACEHOLDER_CODES = frozenset({"??", "XX"})


@dataclass(frozen=True, kw_only=True)
class Nationality:
    code: str
    name: str


@cache
def _tables() -> tuple[dict[str, Nationality], dict[str, list[Nationality]]]:
    """Return (by_code, by_name) lookup tables; names may map to several codes."""
    raw = json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))
    by_code: dict[str, Nationality] = {}
    by_name: dict[str, list[Nationality]] = {}
    for entry in raw:
        code = entry["Code"].strip().upper()
        if code in PLACEHOLDER_CODES:
            continue
        nationality = Nationality(code=code, name=entry["Name"].strip().upper())
        by_code[nationality.code] = nationality
        by_name.setdefault(nationality.name, []).append(nationality)
    return by_code, by_name


def all_nationalities() -> tuple[Nationality, ...]:
    """Return every nationality ACIS accepts, sorted by code."""
    by_code, _ = _tables()
    return tuple(sorted(by_code.values(), key=lambda n: n.code))


def get_by_code(code: str) -> Nationality:
    """Look up strictly by code."""
    by_code, _ = _tables()
    try:
        return by_code[code.strip().upper()]
    except KeyError:
        raise UnknownNationalityError(f"Unknown nationality code: {code!r}") from None


def resolve(value: str) -> Nationality:
    """Resolve a code (``MX``) or a name (``mexico``) to a Nationality."""
    candidate = (value or "").strip().upper()
    if not candidate:
        raise UnknownNationalityError("Nationality is required")
    by_code, by_name = _tables()
    if candidate in by_code:
        return by_code[candidate]
    matches = by_name.get(candidate, [])
    if len(matches) > 1:
        codes = ", ".join(n.code for n in matches)
        raise UnknownNationalityError(
            f"Ambiguous nationality {value!r}; use one of the codes: {codes}"
        )
    if matches:
        return matches[0]
    raise UnknownNationalityError(f"Unknown nationality: {value!r}")
