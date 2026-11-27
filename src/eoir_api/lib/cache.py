"""A simple in-memory TTL cache."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, kw_only=True)
class Entry[T]:
    value: T
    stored_at: dt.datetime


@dataclass(kw_only=True)
class TTLCache[T]:
    ttl: float  # seconds
    _entries: dict[Any, Entry[T]] = field(default_factory=dict, init=False, repr=False)

    def _is_fresh(self, entry: Entry[T], now: dt.datetime) -> bool:
        return now - entry.stored_at < dt.timedelta(seconds=self.ttl)

    def get(self, key: Any) -> Entry[T] | None:
        entry = self._entries.get(key)
        if entry is None or not self._is_fresh(entry, dt.datetime.now(dt.UTC)):
            return None
        return entry

    def set(self, key: Any, value: T) -> Entry[T]:
        """Store ``value``, dropping every expired entry."""
        now = dt.datetime.now(dt.UTC)
        self._entries = {
            k: e for k, e in self._entries.items() if self._is_fresh(e, now)
        }
        entry = self._entries[key] = Entry(value=value, stored_at=now)
        return entry
