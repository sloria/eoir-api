from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def master_hearing() -> dict[str, Any]:
    return load_fixture("master_hearing_scheduled.json")


@pytest.fixture
def removal_ordered() -> dict[str, Any]:
    return load_fixture("removal_ordered.json")
