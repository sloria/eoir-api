from __future__ import annotations

import datetime as dt

import pytest

from acis_core import case


def payload(
    *,
    decision_code=None,
    case_type=None,
    other_comp=None,
    osc_date="2023-01-05T00:00:00",
):
    return {
        "Data": {"OSC_Date": osc_date},
        "Proceeding": {
            "DecisionCode": decision_code,
            "CaseType": case_type,
            "OtherComp": other_comp,
            "CompDate": "2026-07-07T00:00:00",
        },
    }


##### Field parsing #####


def test_parse_date():
    assert case.parse_date("2026-08-06T00:00:00") == dt.date(2026, 8, 6)


@pytest.mark.parametrize("value", [None, "", "   ", "not-a-date", 42])
def test_parse_date_returns_none_for_junk(value):
    assert case.parse_date(value) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("8:30 AM", dt.time(8, 30)),
        ("8:30 am", dt.time(8, 30)),
        ("12:00 PM", dt.time(12, 0)),
        ("12:00 AM", dt.time(0, 0)),
        ("1:05 PM", dt.time(13, 5)),
        ("13:05", dt.time(13, 5)),
    ],
)
def test_parse_time(raw, expected):
    assert case.parse_time(raw) == expected


@pytest.mark.parametrize("value", [None, "", "nonsense", 42])
def test_parse_time_returns_none_for_junk(value):
    assert case.parse_time(value) is None


def test_parse_hearing_location_drops_the_city_label():
    value = "NEW YORK CITY, NEW YORK|26 FEDERAL PLZ|NEW YORK, NY 10278"
    assert case.parse_hearing_location(value) == "26 FEDERAL PLZ, NEW YORK, NY 10278"


def test_parse_hearing_location_keeps_a_lone_segment():
    assert case.parse_hearing_location("26 FEDERAL PLZ") == "26 FEDERAL PLZ"


@pytest.mark.parametrize("value", [None, "", " | "])
def test_parse_hearing_location_returns_none_when_empty(value):
    assert case.parse_hearing_location(value) is None


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("A", "internet"),
        ("C", "internet"),
        ("T", "internet"),
        ("W", "internet"),
        ("P", "in_person"),
        ("V", "in_person"),
        ("Z", None),
        (None, None),
    ],
)
def test_hearing_medium(code, expected):
    assert case.hearing_medium(code) == expected


@pytest.mark.parametrize(
    ("code", "expected"),
    [("M", "master"), ("I", "individual"), ("m", "master"), ("X", None), (None, None)],
)
def test_hearing_type(code, expected):
    assert case.hearing_type(code) == expected


##### Decision outcomes #####


@pytest.mark.parametrize(
    ("code", "case_type", "expected"),
    [
        ("D", "DEP", "deportation_ordered"),
        ("D", "AOC", "application_denied"),
        ("D", "NAC", "adjustment_denied"),
        ("D", "WHO", "withholding_denied"),
        ("D", "CDR", "case_dismissed"),
        ("D", "RMV", None),
        ("V", "DEP", "voluntary_departure_granted"),
        ("V", "RMV", "voluntary_departure_granted"),
        ("V", "EXC", "vacated"),
        ("R", "DEP", "relief_granted"),
        ("R", "RMV", "relief_granted"),
        ("R", "EXC", "status_rescinded"),
        ("T", "RMV", "terminated"),
        ("I", "RMV", "terminated"),
        ("A", "EXC", "admitted"),
        ("A", "RMV", "affirmed"),
        ("E", "RMV", "ina_withholding_granted"),
        ("E", "AOC", "ina_withholding_granted"),
        ("E", "EXC", "excluded"),
        ("O", "RMV", "proceedings_closed"),
        ("S", "RMV", "sustained"),
        ("X", "RMV", "removal_ordered"),
        ("X", "DEP", "removal_ordered"),
        ("G", "RMV", "cat_deferral_granted"),
        ("G", "AOC", "relief_granted"),
        ("W", "RMV", "application_withdrawn"),
        ("J", "RMV", "transferred_to_bia"),
        ("C", "RMV", "venue_changed"),
        ("Q", "RMV", "removal_cancelled"),
        ("Q", "DEP", "deportation_suspended"),
        ("Z", "RMV", "cat_withholding_granted"),
        ("H", "RMV", "cat_deferral_granted"),
        ("U", "RMV", "dismissal_ordered"),
    ],
)
def test_decision_outcome(code, case_type, expected):
    assert (
        case.decision_outcome(payload(decision_code=code, case_type=case_type))
        == expected
    )


def test_decision_code_is_case_insensitive():
    assert (
        case.decision_outcome(payload(decision_code="x", case_type="rmv"))
        == "removal_ordered"
    )


@pytest.mark.parametrize(
    ("other_comp", "expected"),
    [
        ("K", "admin_closed"),
        ("A", "admin_closed"),
        ("O", "admin_closed"),
        ("Y", "admin_closed"),
        ("M", "admin_closed"),
        ("H", "admin_closed"),
        ("X", "admin_closed"),
        ("C", "venue_changed"),
        ("T", "transferred_to_bia"),
        ("P", "tps_granted"),
        ("F", "failure_to_prosecute"),
        ("", None),
        (None, None),
        ("?", None),
    ],
)
def test_other_comp_fallback_when_decision_code_is_missing(other_comp, expected):
    result = case.decision_outcome(
        payload(decision_code=None, case_type="RMV", other_comp=other_comp),
    )
    assert result == expected


def test_unrecognised_decision_code_falls_back_to_other_comp():
    assert (
        case.decision_outcome(
            payload(decision_code="?", case_type="RMV", other_comp="F"),
        )
        == "failure_to_prosecute"
    )


@pytest.mark.parametrize(
    ("case_type", "code", "expected"),
    [
        ("CFR", "L", "proceedings_closed"),
        ("RFR", "L", "proceedings_closed"),
        ("CFR", "X", "decision_issued"),
        ("RFR", None, "decision_issued"),
    ],
)
def test_fear_review_overrides_the_table(case_type, code, expected):
    assert (
        case.decision_outcome(payload(decision_code=code, case_type=case_type))
        == expected
    )


def test_missing_osc_date_means_a_bond_proceeding():
    assert (
        case.decision_outcome(
            payload(decision_code="X", case_type="RMV", osc_date=None),
        )
        == "bond_contact_court"
    )


def test_bond_wins_over_fear_review():
    assert (
        case.decision_outcome(
            payload(decision_code="L", case_type="CFR", osc_date=None),
        )
        == "bond_contact_court"
    )


##### BIA and motions #####


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("DIS", "dismissed"),
        ("SDG", "dismissed"),
        ("ABC", "admin_closed"),
        ("WDL", "withdrawn"),
        ("SUS", "sustained"),
        ("REM", "remanded"),
        ("DNS", "denied"),
        ("GRS", "granted"),
        ("TER", "terminated"),
        ("REJ", "rejected"),
        ("OTH", "completed"),
        ("whatever", "completed"),
        (None, None),
        ("", None),
    ],
)
def test_bia_outcome_on_an_appeal(code, expected):
    assert case.bia_outcome(code) == expected


@pytest.mark.parametrize(
    ("code", "on_appeal", "on_motion"),
    [("GRN", "remanded", "granted"), ("DEN", "completed", "denied")],
)
def test_two_codes_bucket_differently_on_a_motion(code, on_appeal, on_motion):
    # Upstream's own inconsistency. Matching the site beats being tidy.
    assert case.bia_outcome(code) == on_appeal
    assert case.bia_outcome(code, for_motion=True) == on_motion


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        ("G", "granted"),
        ("D", "denied"),
        ("X", "other"),
        ("P", "unrecognized"),
        ("J", "transferred_to_bia"),
        ("?", "completed"),
        (None, "completed"),
    ],
)
def test_reopen_outcome(code, expected):
    assert case.reopen_outcome(code) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("REO", "reopen"),
        ("REC", "reconsider"),
        ("REI", "reinstate"),
        (None, "reopen"),
        ("??", "reopen"),
    ],
)
def test_motion_type(value, expected):
    assert case.motion_type(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Case Appeal", "case"),
        ("Circuit Court Remand", "circuit_court_remand"),
        (None, None),
        ("something else", None),
    ],
)
def test_appeal_type(value, expected):
    assert case.appeal_type(value) == expected


##### Building from real payloads #####


def test_hearing_from_a_scheduled_case(master_hearing):
    hearing = case.Case.from_payload(master_hearing).hearing
    assert hearing is not None
    assert hearing.date == dt.date(2026, 8, 6)
    assert hearing.time == dt.time(8, 30)
    assert hearing.type == "master"
    assert hearing.medium == "in_person"
    assert hearing.judge == "Roe, Alex"
    assert hearing.location == "26 FEDERAL PLZ, 12TH FL RM1237, NEW YORK, NY 10278"


def test_no_hearing_once_a_case_is_decided(removal_ordered):
    assert case.Case.from_payload(removal_ordered).hearing is None


def test_no_decision_while_a_case_is_pending(master_hearing):
    assert case.Case.from_payload(master_hearing).decision is None


def test_decision_requires_a_completion_date():
    live = {
        "Data": {"OSC_Date": "2023-01-05T00:00:00"},
        # A DecisionCode alone is not a decision; ACIS ignores it without CompDate.
        "Proceeding": {"DecisionCode": "X", "CaseType": "RMV", "CompDate": None},
    }
    assert case.Case.from_payload(live).decision is None


def test_decision_from_a_removal_case(removal_ordered):
    decision = case.Case.from_payload(removal_ordered).decision
    assert decision is not None
    assert decision.date == dt.date(2026, 7, 7)
    assert decision.outcome == "removal_ordered"
    assert decision.code == "X"
    assert decision.case_type == "RMV"
    assert decision.is_removal_order


@pytest.mark.parametrize(
    ("outcome", "is_order"),
    [
        ("removal_ordered", True),
        ("deportation_ordered", True),
        ("excluded", True),
        ("voluntary_departure_granted", False),
        ("terminated", False),
        (None, False),
    ],
)
def test_is_removal_order(outcome, is_order):
    decision = case.Decision(date=dt.date(2026, 7, 7), outcome=outcome)
    assert decision.is_removal_order is is_order


def test_motion_to_reopen_from_a_real_payload(removal_ordered):
    motion = case.Case.from_payload(removal_ordered).motion_to_reopen
    assert motion is not None
    assert motion.outcome == "granted"
    assert motion.date == dt.date(2023, 10, 12)
    assert motion.filed == dt.date(2023, 10, 6)
    assert motion.type == "reopen"


def test_no_motion_when_none_exists(master_hearing):
    assert case.Case.from_payload(master_hearing).motion_to_reopen is None
    assert case.Case.from_payload(master_hearing).motion_at_bia is None


def test_undecided_motion_is_pending():
    pending = {
        "Data": {"ReopenExists": True},
        "Reopen": {
            "CompDate": None,
            "Decision": None,
            "MotionReceivedDate": "2023-10-06T00:00:00",
        },
    }
    motion = case.Case.from_payload(pending).motion_to_reopen
    assert motion is not None
    assert motion.outcome == "pending"
    assert motion.date == dt.date(2023, 10, 6)


def test_motion_at_bia_uses_the_motion_bucketing():
    payload_at_bia = {
        "Data": {"MTR_BIA_Appeal": True, "MTR_BIA_Type": "REC"},
        "MTR": {
            "MTRDecision": "GRN",
            "MTRDecisionDate": "2026-02-01T00:00:00",
            "MTRAppealFiledDate": "2025-11-03T00:00:00",
        },
    }
    motion = case.Case.from_payload(payload_at_bia).motion_at_bia
    assert motion is not None
    assert motion.type == "reconsider"
    assert motion.outcome == "granted"
    assert motion.filed == dt.date(2025, 11, 3)


def test_appeal_from_a_removal_case(removal_ordered):
    appeal = case.Case.from_payload(removal_ordered).appeal
    assert appeal.filed is False
    assert appeal.due == dt.date(2026, 8, 7)
    assert appeal.bia_outcome is None
    assert appeal.pending_at_bia is False
    assert appeal.brief_due is None


def test_appeal_brief_due_is_separate_from_the_filing_deadline():
    payload = {
        "Proceeding": {"DateAppealDue": "2026-08-07T00:00:00"},
        "Appeal": {"AlienBriefDue": "2026-09-15T00:00:00"},
    }
    appeal = case.Case.from_payload(payload).appeal
    assert appeal.due == dt.date(2026, 8, 7)
    assert appeal.brief_due == dt.date(2026, 9, 15)


##### Case #####


def test_case_from_a_scheduled_payload(master_hearing):
    decoded = case.Case.from_payload(master_hearing)
    assert decoded.name == master_hearing["Data"]["AlienName"]
    assert decoded.hearing is not None
    assert decoded.decision is None
    assert decoded.appeal.filed is False
    assert decoded.motion_to_reopen is None
    assert decoded.motion_at_bia is None


@pytest.mark.parametrize("value", [None, "", "   ", 42])
def test_blank_judge_is_unknown(master_hearing, value):
    master_hearing["Schedule"]["IJ_Name"] = value
    decoded = case.Case.from_payload(master_hearing)
    assert decoded.hearing is not None
    assert decoded.hearing.judge is None


def test_case_tolerates_a_missing_time(master_hearing):
    master_hearing["Schedule"]["AdjTime"] = None
    decoded = case.Case.from_payload(master_hearing)
    assert decoded.hearing is not None
    assert decoded.hearing.time is None


def test_case_from_a_decided_payload(removal_ordered):
    decoded = case.Case.from_payload(removal_ordered)
    assert decoded.hearing is None
    assert decoded.decision is not None
    assert decoded.decision.outcome == "removal_ordered"
    assert decoded.decision.date == dt.date(2026, 7, 7)
    assert decoded.motion_to_reopen is not None
    assert decoded.motion_to_reopen.outcome == "granted"


def test_empty_case_has_nothing_on_file():
    assert case.Case() == case.Case.from_payload({"Data": {"OSC_Date": "x"}})
