from __future__ import annotations

from typing import get_type_hints

import pytest

from acis_core.payload import ACISPayload


def undocumented_keys(payload: dict) -> set[str]:
    sections = get_type_hints(ACISPayload)
    unknown = set(payload) - set(sections)
    for name, value in payload.items():
        if isinstance(value, dict) and name in sections:
            unknown |= {
                f"{name}.{key}"
                for key in set(value) - set(get_type_hints(sections[name]))
            }
    return unknown


@pytest.mark.parametrize("fixture", ["master_hearing", "removal_ordered"])
def test_payload_documents_every_fixture_key(fixture, request):
    assert undocumented_keys(request.getfixturevalue(fixture)) == set()
