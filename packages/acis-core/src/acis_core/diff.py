from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import datetime as dt

    from acis_core.case import Case, Hearing, Motion


class ChangeKind(Enum):
    MOVED_EARLIER = auto()
    MOVED_LATER = auto()
    NEW_HEARING = auto()
    HEARING_REMOVED = auto()
    DETAILS_CHANGED = auto()
    CASE_DECIDED = auto()
    BIA_DECIDED = auto()
    MOTION_DECIDED = auto()
    APPEAL_FILED = auto()
    MOTION_FILED = auto()

    @property
    def is_motion_or_appeal(self) -> bool:
        return self in MOTION_AND_APPEAL_KINDS


MOVES = frozenset({ChangeKind.MOVED_EARLIER, ChangeKind.MOVED_LATER})

MOTION_AND_APPEAL_KINDS = frozenset(
    {
        ChangeKind.BIA_DECIDED,
        ChangeKind.MOTION_DECIDED,
        ChangeKind.APPEAL_FILED,
        ChangeKind.MOTION_FILED,
    }
)


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    # Hearing field -> (old, new), raw values
    details: dict[str, tuple[str, str]] = field(default_factory=dict)
    motion: Motion | None = None


def diff(prior: Case, current: Case) -> list[Change]:
    """Return changes from ``prior`` to ``current``, ordered by significance."""
    changes = []
    decision = current.decision
    prior_decided = prior.decision.date if prior.decision else None
    if decision is not None and decision.date != prior_decided:
        changes.append(Change(kind=ChangeKind.CASE_DECIDED))
    elif change := _hearing_change(prior, current):
        changes.append(change)
    return changes + _motion_and_appeal_changes(prior, current)


def _hearing_change(prior: Case, current: Case) -> Change | None:
    prior_hearing, hearing = prior.hearing, current.hearing
    if prior_hearing is None and hearing is None:
        return None
    if prior_hearing is None:
        return Change(kind=ChangeKind.NEW_HEARING)
    if hearing is None:
        return Change(kind=ChangeKind.HEARING_REMOVED)

    details = _detail_changes(prior_hearing, hearing)
    if hearing.date != prior_hearing.date:
        earlier = hearing.date < prior_hearing.date
    elif (
        hearing.time is not None
        and prior_hearing.time is not None
        and hearing.time != prior_hearing.time
    ):
        earlier = hearing.time < prior_hearing.time
    elif details:
        return Change(kind=ChangeKind.DETAILS_CHANGED, details=details)
    else:
        return None
    kind = ChangeKind.MOVED_EARLIER if earlier else ChangeKind.MOVED_LATER
    return Change(kind=kind, details=details)


def _detail_changes(prior: Hearing, current: Hearing) -> dict[str, tuple[str, str]]:
    changes = {}
    for name, old, new in [
        ("judge", prior.judge, current.judge),
        ("location", prior.location, current.location),
        ("type", prior.type, current.type),
        ("medium", prior.medium, current.medium),
    ]:
        # Only flag when both sides are known; a previously-empty value isn't a change
        if old is not None and new is not None and old != new:
            changes[name] = (old, new)
    return changes


def _motion_and_appeal_changes(prior: Case, current: Case) -> list[Change]:
    prior_appeal, appeal = prior.appeal, current.appeal
    motions = (
        (prior.motion_to_reopen, current.motion_to_reopen),
        (prior.motion_at_bia, current.motion_at_bia),
    )
    bia_decided = appeal.bia_outcome is not None and (
        prior_appeal.bia_outcome is None
        or _is_replaced(prior_appeal.bia_decision_date, appeal.bia_decision_date)
    )
    appeal_filed = appeal.filed and (
        not prior_appeal.filed
        or _is_replaced(prior_appeal.filed_date, appeal.filed_date)
    )
    decided_motions, filed_motions = [], []
    for prior_motion, motion in motions:
        if _is_decided(prior_motion, motion):
            decided_motions.append(motion)
        elif _is_new(prior_motion, motion):
            filed_motions.append(motion)
    changes = []
    if bia_decided:
        changes.append(Change(kind=ChangeKind.BIA_DECIDED))
    changes += [
        Change(kind=ChangeKind.MOTION_DECIDED, motion=m) for m in decided_motions
    ]
    if appeal_filed and not bia_decided:
        changes.append(Change(kind=ChangeKind.APPEAL_FILED))
    changes += [Change(kind=ChangeKind.MOTION_FILED, motion=m) for m in filed_motions]
    return changes


def _is_replaced(old: dt.date | None, new: dt.date | None) -> bool:
    return old is not None and new is not None and old != new


def _is_new(prior: Motion | None, current: Motion | None) -> bool:
    if current is None:
        return False
    return prior is None or _is_replaced(prior.filed, current.filed)


def _is_decided(prior: Motion | None, current: Motion | None) -> bool:
    if current is None or current.outcome == "pending":
        return False
    return (
        prior is None
        or prior.outcome == "pending"
        or _is_new(prior, current)
        or _is_replaced(prior.decided, current.decided)
    )
