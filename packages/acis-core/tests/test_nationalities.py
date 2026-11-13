from __future__ import annotations

import pytest

from acis_core.nationalities import (
    UnknownNationalityError,
    all_nationalities,
    get_by_code,
    resolve,
)


def test_resolve_by_code():
    assert resolve("MX").name == "MEXICO"
    assert resolve("mx").name == "MEXICO"
    assert resolve(" mx ").name == "MEXICO"


def test_resolve_by_name():
    assert resolve("MEXICO").code == "MX"
    assert resolve("mexico").code == "MX"
    assert resolve("El Salvador").code == "ES"


@pytest.mark.parametrize("code", ["??", "XX"])
def test_placeholder_entries_are_rejected(code):
    with pytest.raises(UnknownNationalityError):
        resolve(code)


@pytest.mark.parametrize("code", ["CZ", "GC", "UR", "YO", "YS"])
def test_former_countries_resolve_by_code(code):
    assert resolve(code).code == code


def test_name_shared_by_several_codes_is_rejected():
    with pytest.raises(UnknownNationalityError, match="CZ, GC, UR, YO, YS"):
        resolve("Former Countries")


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


def test_all_nationalities_lists_only_valid_codes_sorted():
    codes = [n.code for n in all_nationalities()]
    assert "MX" in codes
    assert {"GC", "UR", "YO"} <= set(codes)
    assert not {"??", "XX"} & set(codes)
    assert codes == sorted(codes)
