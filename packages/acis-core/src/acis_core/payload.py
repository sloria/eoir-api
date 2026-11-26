"""Best-effort documentation of the ACIS payload. There's no
guarantee that these match the types of the upstream payload.

This module is private API. Changes to it may be made without a
major version bump.
"""

from __future__ import annotations

from typing import Annotated, TypeAlias, TypedDict

Date: TypeAlias = Annotated[str | None, "Datetime in ISO 8601 format."]
Address: TypeAlias = Annotated[str | None, "Address in pipe-separated line format."]
BIADecisionCode: TypeAlias = Annotated[str | None, "BIA decision code."]
CalendarType: TypeAlias = Annotated[
    str | None, "`M` for master calendar hearing or `I` for individual hearing."
]
Time: TypeAlias = Annotated[str | None, 'Display string, e.g. `"8:30 AM"`.']


class ACISData(TypedDict, total=False):
    ValidAlienNumber: bool
    ReopenExists: bool
    AppealFiled: bool
    CaseAppealExists: bool
    MTR_BIA_Appeal: Annotated[bool, "Whether there is a motion is before the BIA."]
    MTR_BIA_Type: Annotated[
        str | None, "`REO` (reopen), `REC` (reconsider) or `REI` (reinstate)."
    ]
    AlienName: Annotated[str, "Name in the format: `LAST, FIRST`."]
    CaseID: int
    OSC_Date: Date
    ClockStatus: Annotated[
        str | None, "`R` if asylum clock is still running. `S` or `X` if stopped."
    ]
    ElapsedDays: Annotated[str | None, "An integer, as a string."]
    LatestHearingDate: Date
    LatestHearingTime: Time
    LatestCalType: CalendarType
    DocketDate: Date
    CaseContactInfo: Address
    CaseDecisionString: str | None
    MTRDecisionString: str | None
    ReopenDecisionString: str | None
    AppealDecisionString: str | None
    PendingAtBIA: bool


class ACISProceeding(TypedDict, total=False):
    DateAppealDue: Date
    BaseCityCode: str
    Generation: str
    Subgeneration: str | None
    HearingLocationCode: str
    HearingLocationAddress: Address
    ContactAddress: Address
    CompDate: Date
    IJCode: str | None
    IJName: str | None
    CaseType: str
    DecisionCode: str | None
    OtherComp: str | None
    OtherReceived1: str | None
    OtherReceived2: str | None
    BatteredSpouse: bool
    ReleaseInfo: str


class ACISReopen(TypedDict, total=False):
    CompDate: Date
    Decision: Annotated[
        str | None,
        "`G` (granted), `D` (denied), `X` (other), `P` (unrecognized) "
        "or `J` (transferred to the BIA).",
    ]
    MotionReceivedDate: Date


class ACISAppeal(TypedDict, total=False):
    AlienBriefDue: Date
    AlienBriefFiled: Date
    BIADecision: BIADecisionCode
    BIADecisionDate: Date
    DHSBriefDue: Date
    DHSBriefFiled: Date
    FiledDate: Date
    AppealType: str | None


class ACISMTR(TypedDict, total=False):
    MTRDecision: BIADecisionCode
    MTRDecisionDate: Date
    MTRAppealFiledDate: Date


class ACISSchedule(TypedDict, total=False):
    ProceedingID: int
    AdjDate: Date
    IJ_Code: str | None
    IJ_Name: Annotated[str | None, "Name of the judge in the format: `Last, First`."]
    IJ_WebExURLLink: str | None
    AdjTime: Time
    CalType: CalendarType
    ScheduleType: str | None
    HearingMedium: Annotated[
        str | None, "`A`, `C`, `T` or `W` (internet); `P` or `V` (in person)."
    ]
    HearingLocationCode: str | None
    HearingLocationAddress: Address
    ContactAddress: Address


class ACISPayload(TypedDict, total=False):
    Language: str
    AlienNumber: str
    Data: ACISData
    Proceeding: ACISProceeding
    Reopen: ACISReopen
    Appeal: ACISAppeal
    MTR: ACISMTR
    Schedule: ACISSchedule
