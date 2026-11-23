from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING

from acis_core.case import Case

if TYPE_CHECKING:
    import datetime as dt

    from acis_core.nationalities import Nationality
    from acis_core.payload import ACISPayload


@dataclass(frozen=True)
class Quota:
    limit: int
    remaining: int
    reset_at: dt.datetime


@dataclass(frozen=True)
class LookupResult:
    a_number: str
    nationality: Nationality
    retrieved_at: dt.datetime
    cached: bool
    acis: ACISPayload
    quota: Quota | None = None
    request_id: str | None = None

    @cached_property
    def case(self) -> Case:
        return Case.from_payload(self.acis)
