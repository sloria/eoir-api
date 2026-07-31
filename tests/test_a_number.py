from __future__ import annotations

import pytest

from eoir_api.a_number import normalize_a_number, redact
from eoir_api.exceptions import InvalidANumberError


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("999999999", "999999999"),
        ("999-999-999", "999999999"),
        ("999 999 999", "999999999"),
        (" 999999999 ", "999999999"),
        ("A999999999", "999999999"),
        ("a999999999", "999999999"),
        ("A-999-999-999", "999999999"),
    ],
)
def test_normalize_a_number(raw, expected):
    assert normalize_a_number(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "12345678", "1234567890", "abcdefghi", "12345678a"]
)
def test_normalize_a_number_rejects_bad_input(raw):
    with pytest.raises(InvalidANumberError):
        normalize_a_number(raw)


def test_redact_keeps_only_a_suffix():
    assert redact("123456789") == "***6789"
    assert "123456789" not in redact("123456789")
    assert "12345" not in redact("123456789")
