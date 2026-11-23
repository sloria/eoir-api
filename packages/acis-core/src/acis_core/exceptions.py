from __future__ import annotations

import warnings
from typing import Any


class ACISError(Exception):
    """Base class for failures talking to ACIS."""

    def __init__(self, *args: object, payload: dict[str, Any] | None = None) -> None:
        super().__init__(*args)
        self.payload = payload


def __getattr__(name: str) -> Any:
    if name == "AcisError":
        warnings.warn(
            "AcisError is deprecated; use ACISError",
            DeprecationWarning,
            stacklevel=2,
        )
        return ACISError
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
