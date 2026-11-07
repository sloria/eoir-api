from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import msgspec
from sqlspec import SQLFileLoader
from sqlspec.adapters.aiosqlite import AiosqliteConfig, AiosqliteDriver
from sqlspec.service import SQLSpecAsyncService

from eoir_api.settings import Tenant

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
QUOTA_WINDOW = dt.timedelta(hours=24)

LookupOutcome = Literal[
    "ok",
    "not_found",
    "invalid_nationality",
    "unavailable",
    "captcha",
    "upstream_error",
]

UNCOUNTED: set[LookupOutcome] = {"captcha", "upstream_error"}

queries = SQLFileLoader()
queries.load_sql(Path(__file__).parent / "sql" / "usage.sql")


class LookupItem(msgspec.Struct):
    ts: dt.datetime
    a_number_last_4: str
    outcome: LookupOutcome
    cached: bool
    duration_ms: int | None


class Quota(msgspec.Struct):
    limit: int
    remaining: int
    reset_at: dt.datetime

    def reset_in(self) -> int:
        """Return whole seconds until ``reset_at``."""
        return max(
            1, math.ceil((self.reset_at - dt.datetime.now(dt.UTC)).total_seconds())
        )


class UsageSummary(msgspec.Struct):
    quota: Quota | None
    used: int
    """Lookups in the rolling 24h that count against quota."""


class LookupCount(msgspec.Struct):
    total: int
    newer: int
    """Of ``total``, how many are newer than the given timestamp."""


class OutcomeCount(msgspec.Struct):
    outcome: LookupOutcome
    count: int
    oldest: dt.datetime


def create_config(db_path: Path) -> AiosqliteConfig:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return AiosqliteConfig(
        connection_config={"database": str(db_path)},
        migration_config={"script_location": str(MIGRATIONS_DIR)},
    )


def iso(ts: dt.datetime | None) -> str | None:
    return ts.astimezone(dt.UTC).isoformat() if ts else None


class UsageService(SQLSpecAsyncService[AiosqliteDriver]):
    def __init__(self, config: AiosqliteConfig, retention_days: int) -> None:
        super().__init__(config=config, loader=queries)
        self.retention_days = retention_days

    async def record(
        self,
        *,
        tenant: str,
        ts: dt.datetime,
        a_number: str,
        outcome: LookupOutcome,
        cached: bool,
        duration_ms: int | None = None,
    ) -> None:
        async with self.begin_transaction() as db:
            await db.execute(
                queries.get_sql("record_lookup"),
                tenant,
                iso(ts),
                a_number[-4:],
                outcome,
                int(cached),
                duration_ms,
            )

    async def outcomes_since(
        self, tenant: str, since: dt.datetime
    ) -> list[OutcomeCount]:
        async with self.provide_session() as db:
            return await db.select(
                queries.get_sql("outcomes_since"),
                tenant,
                iso(since),
                schema_type=OutcomeCount,
            )

    async def lookups(
        self,
        tenant: str,
        *,
        limit: int,
        before: dt.datetime | None = None,
        after: dt.datetime | None = None,
    ) -> list[LookupItem]:
        async with self.provide_session() as db:
            rows = await db.select(
                queries.get_sql("lookups"),
                tenant,
                iso(before),
                iso(after),
                limit,
            )
        # Non-strict so SQLite's 0/1 becomes a bool
        return msgspec.convert(rows, list[LookupItem], strict=False)

    async def lookups_after(
        self,
        tenant: str,
        cursor: dt.datetime,
        *,
        limit: int,
        before: dt.datetime | None = None,
    ) -> list[LookupItem]:
        """Return the ``limit`` lookups just newer than ``cursor``, oldest first."""
        async with self.provide_session() as db:
            rows = await db.select(
                queries.get_sql("lookups_after"),
                tenant,
                iso(cursor),
                iso(before),
                limit,
            )
        return msgspec.convert(rows, list[LookupItem], strict=False)

    async def count(
        self,
        tenant: str,
        *,
        before: dt.datetime | None = None,
        after: dt.datetime | None = None,
        newer_than: dt.datetime | None = None,
    ) -> LookupCount:
        """Count lookups in ``[after, before)``, and those newer than ``newer_than``."""
        async with self.provide_session() as db:
            return await db.select_one(
                queries.get_sql("count_lookups"),
                iso(newer_than),
                tenant,
                iso(before),
                iso(after),
                schema_type=LookupCount,
            )

    async def prune(self) -> int:
        """Delete lookups past the retention period; return how many."""
        before = dt.datetime.now(dt.UTC) - dt.timedelta(days=self.retention_days)
        async with self.begin_transaction() as db:
            result = await db.execute(queries.get_sql("prune_lookups"), iso(before))
        return result.rows_affected


@dataclass
class TenantUsage:
    service: UsageService
    tenant: Tenant

    async def record(
        self,
        *,
        a_number: str,
        outcome: LookupOutcome,
        cached: bool,
        duration_ms: int | None = None,
    ) -> None:
        await self.service.record(
            tenant=self.tenant.name,
            ts=dt.datetime.now(dt.UTC),
            a_number=a_number,
            outcome=outcome,
            cached=cached,
            duration_ms=duration_ms,
        )

    async def quota(self) -> Quota | None:
        if self.tenant.quota_per_day is None:
            return None
        return (await self.summary()).quota

    async def summary(self) -> UsageSummary:
        now = dt.datetime.now(dt.UTC)
        rows = await self.service.outcomes_since(self.tenant.name, now - QUOTA_WINDOW)
        counted_rows = [r for r in rows if r.outcome not in UNCOUNTED]
        used = sum(r.count for r in counted_rows)
        limit = self.tenant.quota_per_day
        quota = None
        if limit is not None:
            oldest = min((r.oldest for r in counted_rows), default=None)
            quota = Quota(
                limit=limit,
                remaining=max(0, limit - used),
                reset_at=oldest + QUOTA_WINDOW if oldest else now,
            )
        return UsageSummary(quota=quota, used=used)

    async def lookups(
        self,
        *,
        limit: int,
        before: dt.datetime | None = None,
        after: dt.datetime | None = None,
    ) -> list[LookupItem]:
        return await self.service.lookups(
            self.tenant.name, limit=limit, before=before, after=after
        )

    async def count(
        self,
        *,
        before: dt.datetime | None = None,
        after: dt.datetime | None = None,
        newer_than: dt.datetime | None = None,
    ) -> LookupCount:
        return await self.service.count(
            self.tenant.name, before=before, after=after, newer_than=newer_than
        )

    async def lookups_after(
        self, cursor: dt.datetime, *, limit: int, before: dt.datetime | None = None
    ) -> list[LookupItem]:
        return await self.service.lookups_after(
            self.tenant.name, cursor, limit=limit, before=before
        )
