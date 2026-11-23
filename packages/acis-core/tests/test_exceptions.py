import pytest

from acis_core import exceptions


def test_acis_error_alias_warns_and_resolves_to_acis_error():
    with pytest.warns(DeprecationWarning, match="ACISError"):
        assert exceptions.AcisError is exceptions.ACISError
