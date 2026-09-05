"""Redaction for request paths that carry A-Numbers."""

from __future__ import annotations

import re

from acis_core.a_numbers import redact

_CASE_PATH = re.compile(r"/cases/[^/?#]*\d[^/?#]*")


def redact_path(path: str) -> str:
    return _CASE_PATH.sub(
        lambda match: "/cases/" + redact(match.group().removeprefix("/cases/")), path
    )
