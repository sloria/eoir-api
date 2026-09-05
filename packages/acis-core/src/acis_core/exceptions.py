from __future__ import annotations

from typing import Any


class AcisError(Exception):
    """Base class for failures talking to ACIS."""

    def __init__(self, *args: object, payload: dict[str, Any] | None = None) -> None:
        super().__init__(*args)
        self.payload = payload
