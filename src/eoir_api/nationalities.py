"""EOIR nationality codes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from eoir_api.exceptions import UnknownNationalityError

HERE = Path(__file__).parent
REFERENCE_FILE = HERE / "reference" / "nationality-codes.json"

# Placeholder entry in the upstream table; never a valid lookup value.
UNKNOWN_CODE = "??"


@dataclass(frozen=True, kw_only=True)
class Nationality:
    code: str
    name: str


@cache
def _tables() -> tuple[dict[str, Nationality], dict[str, Nationality]]:
    """Return (by_code, by_name) lookup tables of active nationalities."""
    raw = json.loads(REFERENCE_FILE.read_text(encoding="utf-8"))
    by_code: dict[str, Nationality] = {}
    by_name: dict[str, Nationality] = {}
    for entry in raw:
        code = entry["Code"].strip().upper()
        if not entry.get("IsActive") or code == UNKNOWN_CODE:
            continue
        nationality = Nationality(code=code, name=entry["Name"].strip().upper())
        by_code[nationality.code] = nationality
        by_name[nationality.name] = nationality
    return by_code, by_name


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
    if candidate in by_name:
        return by_name[candidate]
    raise UnknownNationalityError(f"Unknown nationality: {value!r}")
