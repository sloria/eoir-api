from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, kw_only=True)
class CacheEntry[T]:
    value: T
    stored_at: dt.datetime


class TTLCache[T]:
    def __init__(self, ttl: float) -> None:
        self.ttl = ttl
        self._entries: dict[Any, CacheEntry[T]] = {}

    def get(self, key: Any) -> CacheEntry[T] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if dt.datetime.now(dt.UTC) - entry.stored_at >= dt.timedelta(seconds=self.ttl):
            del self._entries[key]
            return None
        return entry

    def set(self, key: Any, value: T) -> CacheEntry[T]:
        entry = CacheEntry(value=value, stored_at=dt.datetime.now(dt.UTC))
        self._entries[key] = entry
        return entry
