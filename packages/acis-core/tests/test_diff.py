from __future__ import annotations

import datetime as dt

import pytest

from acis_core.case import Appeal, Case, Decision, Hearing, Motion
from acis_core.diff import ChangeKind, diff


def make_case(
    *,
    date="2026-08-06",
    time="08:30",
    judge="Roe, Alex",
    location="26 Federal Plz",
    type="master",
    medium="in_person",
    decision=None,
    appeal=None,
    motion_to_reopen=None,
    motion_at_bia=None,
) -> Case:
    hearing = None
    if date is not None:
        hearing = Hearing(
            date=dt.date.fromisoformat(date),
            time=dt.time.fromisoformat(time) if time else None,
            judge=judge,
            location=location,
            type=type,
            medium=medium,
        )
    return Case(
        name="DOE, JANE",
        hearing=hearing,
        decision=decision,
        appeal=appeal or Appeal(),
        motion_to_reopen=motion_to_reopen,
        motion_at_bia=motion_at_bia,
    )


def decided(outcome="removal_ordered", date="2026-07-07") -> Decision:
    return Decision(date=dt.date.fromisoformat(date), outcome=outcome)


def motion(outcome="pending", decided="2026-07-01", filed="2026-06-01") -> Motion:
    return Motion(
        outcome=outcome,
        filed=dt.date.fromisoformat(filed) if filed else None,
        decided=None if outcome == "pending" else dt.date.fromisoformat(decided),
    )


class TestNoChange:
    def test_identical_state(self):
        assert diff(make_case(), make_case()) == []

    def test_no_hearing_on_both_sides(self):
        assert diff(make_case(date=None), make_case(date=None)) == []


class TestDateMoves:
    def test_moved_earlier(self):
        [change] = diff(make_case(date="2026-08-06"), make_case(date="2026-08-01"))
        assert change.kind == ChangeKind.MOVED_EARLIER

    def test_moved_later(self):
        [change] = diff(make_case(date="2026-08-06"), make_case(date="2026-09-01"))
        assert change.kind == ChangeKind.MOVED_LATER

    def test_same_day_earlier_time_is_moved_earlier(self):
        [change] = diff(make_case(time="10:00"), make_case(time="08:30"))
        assert change.kind == ChangeKind.MOVED_EARLIER

    def test_same_day_later_time_is_moved_later(self):
        [change] = diff(make_case(time="08:30"), make_case(time="13:00"))
        assert change.kind == ChangeKind.MOVED_LATER

    def test_unknown_time_on_either_side_is_not_a_move(self):
        assert diff(make_case(time=None), make_case(time="08:30")) == []

    def test_date_move_includes_detail_changes(self):
        [change] = diff(
            make_case(date="2026-08-06", judge="Roe, Alex"),
            make_case(date="2026-08-01", judge="Smith, Pat"),
        )
        assert change.kind == ChangeKind.MOVED_EARLIER
        assert change.details["judge"] == ("Roe, Alex", "Smith, Pat")


class TestHearingAppearsAndDisappears:
    def test_new_hearing(self):
        [change] = diff(make_case(date=None), make_case())
        assert change.kind == ChangeKind.NEW_HEARING

    def test_hearing_removed(self):
        [change] = diff(make_case(), make_case(date=None))
        assert change.kind == ChangeKind.HEARING_REMOVED


class TestDetailChanges:
    @pytest.mark.parametrize(
        ("field", "new_value"),
        [
            ("judge", "Smith, Pat"),
            ("location", "290 Broadway"),
            ("type", "individual"),
            ("medium", "internet"),
        ],
    )
    def test_detail_change(self, field, new_value):
        [change] = diff(make_case(), make_case(**{field: new_value}))
        assert change.kind == ChangeKind.DETAILS_CHANGED
        assert len(change.details) == 1

    def test_details_carry_raw_values(self):
        [change] = diff(make_case(), make_case(medium="internet"))
        assert change.details == {"medium": ("in_person", "internet")}

    @pytest.mark.parametrize("field", ["judge", "location", "type", "medium"])
    def test_previously_unknown_detail_is_not_a_change(self, field):
        assert diff(make_case(**{field: None}), make_case()) == []


class TestCaseDecided:
    def test_new_decision_is_reported(self):
        [change] = diff(make_case(), make_case(decision=decided()))
        assert change.kind == ChangeKind.CASE_DECIDED

    def test_decision_covers_the_hearing_disappearing(self):
        [change] = diff(make_case(), make_case(date=None, decision=decided()))
        assert change.kind == ChangeKind.CASE_DECIDED

    def test_known_decision_is_not_reported_again(self):
        changes = diff(
            make_case(date=None, decision=decided()),
            make_case(date=None, decision=decided()),
        )
        assert changes == []

    def test_a_redecided_case_reports_again(self):
        [change] = diff(
            make_case(date=None, decision=decided(date="2023-05-01")),
            make_case(date=None, decision=decided(date="2026-07-07")),
        )
        assert change.kind == ChangeKind.CASE_DECIDED


class TestMotionAndAppealChanges:
    def test_appeal_filed(self):
        [change] = diff(make_case(), make_case(appeal=Appeal(filed=True)))
        assert change.kind == ChangeKind.APPEAL_FILED

    def test_known_appeal_is_not_reported_again(self):
        filed = Appeal(filed=True)
        assert diff(make_case(appeal=filed), make_case(appeal=filed)) == []

    def test_bia_decided(self):
        [change] = diff(
            make_case(appeal=Appeal(filed=True, pending_at_bia=True)),
            make_case(appeal=Appeal(filed=True, bia_outcome="dismissed")),
        )
        assert change.kind == ChangeKind.BIA_DECIDED

    def test_bia_decision_covers_the_appeal_being_filed(self):
        [change] = diff(
            make_case(),
            make_case(appeal=Appeal(filed=True, bia_outcome="remanded")),
        )
        assert change.kind == ChangeKind.BIA_DECIDED

    @pytest.mark.parametrize("slot", ["motion_to_reopen", "motion_at_bia"])
    def test_motion_filed(self, slot):
        filed = motion()
        [change] = diff(make_case(), make_case(**{slot: filed}))
        assert change.kind == ChangeKind.MOTION_FILED
        assert change.motion is filed

    @pytest.mark.parametrize("slot", ["motion_to_reopen", "motion_at_bia"])
    def test_pending_motion_decided(self, slot):
        granted = motion("granted")
        [change] = diff(make_case(**{slot: motion()}), make_case(**{slot: granted}))
        assert change.kind == ChangeKind.MOTION_DECIDED
        assert change.motion is granted

    def test_decided_motion_is_the_one_that_was_decided(self):
        denied = motion("denied", decided="2026-07-02")
        [change] = diff(
            make_case(motion_to_reopen=motion()),
            make_case(motion_to_reopen=motion(), motion_at_bia=denied),
        )
        assert change.kind == ChangeKind.MOTION_DECIDED
        assert change.motion is denied

    def test_motion_first_seen_decided_is_decided(self):
        [change] = diff(make_case(), make_case(motion_to_reopen=motion("denied")))
        assert change.kind == ChangeKind.MOTION_DECIDED

    @pytest.mark.parametrize("slot", ["motion_to_reopen", "motion_at_bia"])
    def test_refiled_motion_is_filed(self, slot):
        refiled = motion(filed="2026-08-01")
        [change] = diff(
            make_case(**{slot: motion("denied")}), make_case(**{slot: refiled})
        )
        assert change.kind == ChangeKind.MOTION_FILED
        assert change.motion is refiled

    @pytest.mark.parametrize("slot", ["motion_to_reopen", "motion_at_bia"])
    def test_refiled_motion_decided(self, slot):
        granted = motion("granted", decided="2026-09-01", filed="2026-08-01")
        [change] = diff(
            make_case(**{slot: motion("denied")}), make_case(**{slot: granted})
        )
        assert change.kind == ChangeKind.MOTION_DECIDED
        assert change.motion is granted

    @pytest.mark.parametrize("slot", ["motion_to_reopen", "motion_at_bia"])
    def test_redecided_motion_is_decided(self, slot):
        redecided = motion("denied", decided="2026-09-01")
        [change] = diff(
            make_case(**{slot: motion("granted")}), make_case(**{slot: redecided})
        )
        assert change.kind == ChangeKind.MOTION_DECIDED
        assert change.motion is redecided

    @pytest.mark.parametrize(
        ("old", "new"), [(None, "2026-08-01"), ("2026-06-01", None)]
    )
    def test_unknown_filing_date_is_not_a_refiling(self, old, new):
        prior = make_case(motion_to_reopen=motion("denied", filed=old))
        current = make_case(motion_to_reopen=motion("denied", filed=new))
        assert diff(prior, current) == []

    def test_second_bia_decision(self):
        first = Appeal(
            filed=True, bia_outcome="remanded", bia_decision_date=dt.date(2025, 1, 1)
        )
        second = Appeal(
            filed=True, bia_outcome="dismissed", bia_decision_date=dt.date(2026, 7, 1)
        )
        [change] = diff(make_case(appeal=first), make_case(appeal=second))
        assert change.kind == ChangeKind.BIA_DECIDED

    def test_known_bia_decision_is_not_reported_again(self):
        decided_appeal = Appeal(
            filed=True, bia_outcome="dismissed", bia_decision_date=dt.date(2026, 7, 1)
        )
        assert (
            diff(make_case(appeal=decided_appeal), make_case(appeal=decided_appeal))
            == []
        )

    def test_refiled_appeal(self):
        first = Appeal(
            filed=True,
            filed_date=dt.date(2025, 1, 1),
            bia_outcome="remanded",
            bia_decision_date=dt.date(2025, 6, 1),
        )
        second = Appeal(filed=True, filed_date=dt.date(2026, 7, 1))
        [change] = diff(make_case(appeal=first), make_case(appeal=second))
        assert change.kind == ChangeKind.APPEAL_FILED

    def test_known_motion_is_not_reported_again(self):
        decided_motion = motion("granted")
        assert (
            diff(
                make_case(motion_to_reopen=decided_motion),
                make_case(motion_to_reopen=decided_motion),
            )
            == []
        )

    def test_both_motions_are_reported(self):
        changes = diff(
            make_case(motion_at_bia=motion()),
            make_case(motion_to_reopen=motion(), motion_at_bia=motion("denied")),
        )
        assert [c.kind for c in changes] == [
            ChangeKind.MOTION_DECIDED,
            ChangeKind.MOTION_FILED,
        ]


class TestRanking:
    def test_hearing_change_comes_before_a_motion_or_appeal_change(self):
        changes = diff(
            make_case(date="2026-08-06"),
            make_case(date="2026-08-01", appeal=Appeal(filed=True)),
        )
        assert [c.kind for c in changes] == [
            ChangeKind.MOVED_EARLIER,
            ChangeKind.APPEAL_FILED,
        ]

    def test_details_come_before_a_motion_or_appeal_change(self):
        changes = diff(
            make_case(),
            make_case(judge="Smith, Pat", motion_to_reopen=motion()),
        )
        assert [c.kind for c in changes] == [
            ChangeKind.DETAILS_CHANGED,
            ChangeKind.MOTION_FILED,
        ]

    def test_decision_comes_before_a_motion_or_appeal_change(self):
        changes = diff(
            make_case(),
            make_case(decision=decided(), appeal=Appeal(filed=True)),
        )
        assert [c.kind for c in changes] == [
            ChangeKind.CASE_DECIDED,
            ChangeKind.APPEAL_FILED,
        ]
