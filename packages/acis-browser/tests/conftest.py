from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from acis_browser import AcisBrowser

pytestmark = pytest.mark.anyio

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def master_hearing() -> dict[str, Any]:
    return json.loads(
        (FIXTURES / "master_hearing_scheduled.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def acis_browser(tmp_path) -> AcisBrowser:
    return AcisBrowser(profile_dir=tmp_path / "profile")
