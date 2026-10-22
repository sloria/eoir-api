from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

HearingType: TypeAlias = Literal["master", "individual"]
HearingMedium: TypeAlias = Literal["internet", "in_person"]

DecisionOutcome: TypeAlias = Literal[
    "removal_ordered",
    "deportation_ordered",
    "excluded",
    "voluntary_departure_granted",
    "removal_cancelled",
    "deportation_suspended",
    "relief_granted",
    "ina_withholding_granted",
    "cat_withholding_granted",
    "cat_deferral_granted",
    "application_denied",
    "adjustment_denied",
    "withholding_denied",
    "application_withdrawn",
    "case_dismissed",
    "dismissal_ordered",
    "terminated",
    "proceedings_closed",
    "admin_closed",
    "failure_to_prosecute",
    "venue_changed",
    "transferred_to_bia",
    "affirmed",
    "admitted",
    "sustained",
    "vacated",
    "status_rescinded",
    "tps_granted",
    "decision_issued",
    "bond_contact_court",
]

BiaOutcome: TypeAlias = Literal[
    "dismissed",
    "denied",
    "granted",
    "sustained",
    "remanded",
    "terminated",
    "withdrawn",
    "rejected",
    "admin_closed",
    "completed",
]

MotionOutcome: TypeAlias = Literal[
    "granted",
    "denied",
    "other",
    "unrecognized",
    "transferred_to_bia",
    "completed",
    "pending",
]

MotionResult: TypeAlias = MotionOutcome | BiaOutcome

MotionType: TypeAlias = Literal["reopen", "reconsider", "reinstate"]
AppealType: TypeAlias = Literal["case", "circuit_court_remand"]

# The same thing under three statutory regimes. Voluntary departure is not one,
# though it carries an alternate order of removal if the person doesn't depart.
REMOVAL_ORDERS: frozenset[DecisionOutcome] = frozenset(
    {"removal_ordered", "deportation_ordered", "excluded"}
)


##### Field parsing #####

HEARING_MEDIUMS: dict[str, HearingMedium] = {
    **dict.fromkeys("ACTW", "internet"),
    **dict.fromkeys("PV", "in_person"),
}
HEARING_TYPES: dict[str, HearingType] = {"M": "master", "I": "individual"}

# AdjTime is a display string ("8:30 AM"), not ISO.
_TIME_FORMATS = ("%I:%M %p", "%I:%M:%S %p", "%H:%M", "%H:%M:%S")


def parse_date(value: Any) -> dt.date | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return dt.datetime.fromisoformat(value.strip()).date()
    except ValueError:
        return None


def parse_time(value: Any) -> dt.time | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = " ".join(value.strip().upper().split())
    for fmt in _TIME_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


def split_pipe(value: Any) -> list[str]:
    if not isinstance(value, str) or not value.strip():
        return []
    return [part.strip() for part in value.split("|") if part.strip()]


def parse_hearing_location(value: Any) -> str | None:
    segments = split_pipe(value)
    if len(segments) > 1:
        segments = segments[1:]
    return ", ".join(segments) or None


def _text(value: Any) -> str | None:
    return (value.strip() or None) if isinstance(value, str) else None


def _code(value: Any) -> str:
    return value.strip().upper() if isinstance(value, str) else ""


def hearing_medium(code: Any) -> HearingMedium | None:
    return HEARING_MEDIUMS.get(_code(code))


def hearing_type(code: Any) -> HearingType | None:
    return HEARING_TYPES.get(_code(code))


##### Decision tables #####

# DecisionCode -> (per-CaseType overrides, fallback). A None fallback means the
# code is only meaningful for the case types listed. `# _N` tags are keys in
# reference/decision-types.json, the text ACIS shows.
_DECISIONS: dict[str, tuple[dict[str, DecisionOutcome], DecisionOutcome | None]] = {
    "D": (
        {
            "DEP": "deportation_ordered",  # _3
            "AOC": "application_denied",  # _4
            "NAC": "adjustment_denied",  # _5
            "WHO": "withholding_denied",  # _6
            "CDR": "case_dismissed",  # _40
        },
        None,
    ),
    "V": (
        {
            "DEP": "voluntary_departure_granted",  # _14
            "RMV": "voluntary_departure_granted",
        },
        "vacated",  # _13
    ),
    "R": ({"DEP": "relief_granted", "RMV": "relief_granted"}, "status_rescinded"),
    "T": ({}, "terminated"),  # _12
    "I": ({}, "terminated"),  # _12
    "A": ({"EXC": "admitted"}, "affirmed"),  # _2 / _1
    "E": (
        {"RMV": "ina_withholding_granted", "AOC": "ina_withholding_granted"},  # _44
        "excluded",  # _7
    ),
    "O": ({}, "proceedings_closed"),  # _9
    "S": ({}, "sustained"),  # _11
    "X": ({}, "removal_ordered"),  # _16
    "G": ({"RMV": "cat_deferral_granted"}, "relief_granted"),  # _46 / _8
    "W": ({}, "application_withdrawn"),  # _15
    "J": ({}, "transferred_to_bia"),  # _22
    "C": ({}, "venue_changed"),  # _18
    "Q": ({"RMV": "removal_cancelled"}, "deportation_suspended"),  # _38 / _39
    "Z": ({}, "cat_withholding_granted"),  # _45
    "H": ({}, "cat_deferral_granted"),  # _46
    "U": ({}, "dismissal_ordered"),  # _47
}

_OTHER_COMP: dict[str, DecisionOutcome] = {
    **dict.fromkeys("KAOYMHX", "admin_closed"),  # _37
    "C": "venue_changed",  # _18
    "T": "transferred_to_bia",  # _22
    "P": "tps_granted",  # _21
    "F": "failure_to_prosecute",  # _19
}

_FEAR_REVIEW_TYPES = frozenset({"CFR", "RFR"})


def decision_outcome(payload: dict[str, Any]) -> DecisionOutcome | None:
    """Map a payload's decision codes to an outcome, or None if unmapped."""
    data = payload.get("Data") or {}
    proceeding = payload.get("Proceeding") or {}
    code = _code(proceeding.get("DecisionCode"))
    case_type = _code(proceeding.get("CaseType"))

    if not data.get("OSC_Date"):
        return "bond_contact_court"  # _41: bond-only proceeding, not a merits case
    if case_type in _FEAR_REVIEW_TYPES:
        return "proceedings_closed" if code == "L" else "decision_issued"  # _9 / _20

    entry = _DECISIONS.get(code)
    if entry is None:
        return _OTHER_COMP.get(_code(proceeding.get("OtherComp")))
    by_case_type, fallback = entry
    return by_case_type.get(case_type, fallback)


_BIA_OUTCOMES: dict[str, BiaOutcome] = {
    **dict.fromkeys(
        (
            "D30",
            "DIS",
            "DVD",
            "DSO",
            "DUT",
            "SAD",
            "SED",
            "SND",
            "SOD",
            "SUD",
            "SAF",
            "SAV",
            "SDG",
        ),
        "dismissed",  # _25
    ),
    **dict.fromkeys(
        ("ABC", "ADM", "APD", "CON", "CTM", "DED", "TPS"),
        "admin_closed",  # _51
    ),
    **dict.fromkeys(("WDL", "WPD"), "withdrawn"),  # _29
    **dict.fromkeys(("CFV", "SUS"), "sustained"),  # _27
    "REM": "remanded",  # _26
    "GRN": "remanded",  # _26
    "DNS": "denied",  # _30
    **dict.fromkeys(("GRS", "CPG", "CFG"), "granted"),  # _24
    **dict.fromkeys(("TER", "TPD"), "terminated"),  # _28
    "REJ": "rejected",  # _42
}

# Upstream buckets these two differently on a motion than on an appeal.
_MOTION_OVERRIDES: dict[str, BiaOutcome] = {"GRN": "granted", "DEN": "denied"}

_REOPEN_OUTCOMES: dict[str, MotionOutcome] = {
    "G": "granted",  # _31
    "D": "denied",  # _32
    "X": "other",  # _33
    "P": "unrecognized",  # _36
    "J": "transferred_to_bia",  # _34
}

_MOTION_TYPES: dict[str, MotionType] = {
    "REO": "reopen",
    "REC": "reconsider",
    "REI": "reinstate",
}

_APPEAL_TYPES: dict[str, AppealType] = {
    "CASE APPEAL": "case",
    "CIRCUIT COURT REMAND": "circuit_court_remand",
}


def bia_outcome(code: Any, *, for_motion: bool = False) -> BiaOutcome | None:
    key = _code(code)
    if not key:
        return None
    if for_motion and key in _MOTION_OVERRIDES:
        return _MOTION_OVERRIDES[key]
    return _BIA_OUTCOMES.get(key, "completed")  # _23


def reopen_outcome(code: Any) -> MotionOutcome:
    return _REOPEN_OUTCOMES.get(_code(code), "completed")  # _43


def motion_type(value: Any) -> MotionType:
    return _MOTION_TYPES.get(_code(value), "reopen")


def appeal_type(value: Any) -> AppealType | None:
    return _APPEAL_TYPES.get(_code(value))


##### Data types #####


@dataclass(frozen=True)
class Hearing:
    date: dt.date
    time: dt.time | None = None
    type: HearingType | None = None
    medium: HearingMedium | None = None
    judge: str | None = None
    location: str | None = None


@dataclass(frozen=True)
class Decision:
    date: dt.date
    outcome: DecisionOutcome | None
    code: str | None = None
    case_type: str | None = None

    @property
    def is_removal_order(self) -> bool:
        return self.outcome in REMOVAL_ORDERS


@dataclass(frozen=True)
class Motion:
    outcome: MotionResult
    type: MotionType = "reopen"
    filed: dt.date | None = None
    decided: dt.date | None = None

    @property
    def date(self) -> dt.date | None:
        return self.decided or self.filed


@dataclass(frozen=True)
class Appeal:
    filed: bool = False
    filed_date: dt.date | None = None
    due: dt.date | None = None
    brief_due: dt.date | None = None
    type: AppealType | None = None
    pending_at_bia: bool = False
    bia_outcome: BiaOutcome | None = None
    bia_decision_date: dt.date | None = None


def _parse_hearing(payload: dict[str, Any]) -> Hearing | None:
    schedule = payload.get("Schedule") or {}
    date = parse_date(schedule.get("AdjDate"))
    if date is None:
        return None
    return Hearing(
        date=date,
        time=parse_time(schedule.get("AdjTime")),
        type=hearing_type(schedule.get("CalType")),
        medium=hearing_medium(schedule.get("HearingMedium")),
        judge=_text(schedule.get("IJ_Name")),
        location=parse_hearing_location(schedule.get("HearingLocationAddress")),
    )


@dataclass(frozen=True)
class Case:
    name: str | None = None
    hearing: Hearing | None = None
    decision: Decision | None = None
    appeal: Appeal = Appeal()
    motion_to_reopen: Motion | None = None
    motion_at_bia: Motion | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Case:
        return cls(
            name=(payload.get("Data") or {}).get("AlienName"),
            hearing=_parse_hearing(payload),
            decision=_parse_decision(payload),
            appeal=_parse_appeal(payload),
            motion_to_reopen=_parse_motion_to_reopen(payload),
            motion_at_bia=_parse_motion_at_bia(payload),
        )


##### Parser functions #####


def _parse_decision(payload: dict[str, Any]) -> Decision | None:
    proceeding = payload.get("Proceeding") or {}
    date = parse_date(proceeding.get("CompDate"))
    if date is None:
        return None
    return Decision(
        date=date,
        outcome=decision_outcome(payload),
        code=proceeding.get("DecisionCode"),
        case_type=proceeding.get("CaseType"),
    )


def _parse_motion_to_reopen(payload: dict[str, Any]) -> Motion | None:
    data = payload.get("Data") or {}
    if not data.get("ReopenExists"):
        return None
    reopen = payload.get("Reopen") or {}
    filed = parse_date(reopen.get("MotionReceivedDate"))
    completed = parse_date(reopen.get("CompDate"))
    if completed is None:
        return Motion(outcome="pending", filed=filed)
    return Motion(
        outcome=reopen_outcome(reopen.get("Decision")), filed=filed, decided=completed
    )


def _parse_motion_at_bia(payload: dict[str, Any]) -> Motion | None:
    data = payload.get("Data") or {}
    if not data.get("MTR_BIA_Appeal"):
        return None
    mtr = payload.get("MTR") or {}
    mtype = motion_type(data.get("MTR_BIA_Type"))
    filed = parse_date(mtr.get("MTRAppealFiledDate"))
    decided = parse_date(mtr.get("MTRDecisionDate"))
    outcome = bia_outcome(mtr.get("MTRDecision"), for_motion=True)
    if decided is None or outcome is None:
        return Motion(outcome="pending", type=mtype, filed=filed)
    return Motion(outcome=outcome, type=mtype, filed=filed, decided=decided)


def _parse_appeal(payload: dict[str, Any]) -> Appeal:
    data = payload.get("Data") or {}
    proceeding = payload.get("Proceeding") or {}
    appeal_data = payload.get("Appeal") or {}
    return Appeal(
        filed=bool(data.get("AppealFiled")),
        filed_date=parse_date(appeal_data.get("FiledDate")),
        due=parse_date(proceeding.get("DateAppealDue")),
        brief_due=parse_date(appeal_data.get("AlienBriefDue")),
        type=appeal_type(appeal_data.get("AppealType")),
        pending_at_bia=bool(data.get("PendingAtBIA")),
        bia_outcome=bia_outcome(appeal_data.get("BIADecision")),
        bia_decision_date=parse_date(appeal_data.get("BIADecisionDate")),
    )
