from __future__ import annotations

import pytest

from eoir_api.exceptions import UnknownNationalityError
from eoir_api.nationalities import get_by_code, resolve


def test_resolve_by_code():
    assert resolve("MX").name == "MEXICO"
    assert resolve("mx").name == "MEXICO"
    assert resolve(" mx ").name == "MEXICO"


def test_resolve_by_name():
    assert resolve("MEXICO").code == "MX"
    assert resolve("mexico").code == "MX"
    assert resolve("El Salvador").code == "ES"


@pytest.mark.parametrize("code", ["??", "GC", "UR", "XX", "YO"])
def test_inactive_entries_are_rejected(code):
    with pytest.raises(UnknownNationalityError):
        resolve(code)


def test_empty_is_rejected():
    with pytest.raises(UnknownNationalityError):
        resolve("")


def test_unknown_value_is_rejected():
    with pytest.raises(UnknownNationalityError):
        resolve("ATLANTIS")


def test_get_by_code_is_strict():
    assert get_by_code("MX").name == "MEXICO"
    with pytest.raises(UnknownNationalityError):
        get_by_code("MEXICO")
