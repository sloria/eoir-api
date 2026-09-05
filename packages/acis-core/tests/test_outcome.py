from __future__ import annotations

import pytest

from acis_core.outcome import MESSAGES, Outcome


@pytest.mark.parametrize(("fragment", "expected"), MESSAGES)
def test_from_payload_classifies_each_message_fragment(fragment, expected):
    assert Outcome.from_payload({"message": f"...{fragment}..."}) is expected


def test_complete_data_payload_is_ok():
    payload = {"Data": {"AlienName": "DOE, JOHN", "CaseID": "1234567"}}
    assert Outcome.from_payload(payload) is Outcome.OK


@pytest.mark.parametrize(
    "data",
    [
        {"CaseID": "1234567"},
        {"AlienName": "DOE, JOHN"},
        {"AlienName": "", "CaseID": "1234567"},
        {},
    ],
)
def test_incomplete_data_payload_is_other(data):
    assert Outcome.from_payload({"Data": data}) is Outcome.OTHER


def test_unknown_message_is_other():
    assert Outcome.from_payload({"message": "Something else went wrong"}) is (
        Outcome.OTHER
    )


def test_empty_payload_is_other():
    assert Outcome.from_payload({}) is Outcome.OTHER
