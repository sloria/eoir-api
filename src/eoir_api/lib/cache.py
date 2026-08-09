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

    def get(self, key: Any) -> Entry[T] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if dt.datetime.now(dt.UTC) - entry.stored_at >= dt.timedelta(seconds=self.ttl):
            del self._entries[key]
            return None
        return entry

    def set(self, key: Any, value: T) -> Entry[T]:
        entry = Entry(value=value, stored_at=dt.datetime.now(dt.UTC))
        self._entries[key] = entry
        return entry
