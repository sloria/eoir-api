"""Tests that run a real browser against the live ACIS site."""

from __future__ import annotations

import os

import pytest

from eoir_api.lib.acis import AcisBrowser, CaseNotFoundError
from eoir_api.nationalities import resolve

pytestmark = [pytest.mark.anyio, pytest.mark.live]

TEST_A_NUMBER = os.environ.get("EOIR_TEST_A_NUMBER", "")
TEST_NATIONALITY = os.environ.get("EOIR_TEST_NATIONALITY", "")

# Keys eoir-notify decodes. This service passes the payload through untouched,
# so nothing else in either codebase would notice EOIR renaming one of them.
REQUIRED_KEYS = {
    "Data": (
        "AlienName",
        "OSC_Date",
        "AppealFiled",
        "ReopenExists",
        "MTR_BIA_Appeal",
        "MTR_BIA_Type",
        "PendingAtBIA",
    ),
    "Proceeding": (
        "CaseType",
        "CompDate",
        "DecisionCode",
        "OtherComp",
        "DateAppealDue",
        "HearingLocationAddress",
    ),
    "Schedule": (
        "AdjDate",
        "AdjTime",
        "CalType",
        "HearingMedium",
        "IJ_Name",
        "IJ_WebExURLLink",
        "HearingLocationAddress",
    ),
    "Appeal": ("FiledDate", "AppealType", "BIADecision", "BIADecisionDate"),
    "Reopen": ("CompDate", "Decision", "MotionReceivedDate"),
    "MTR": ("MTRDecision", "MTRDecisionDate", "MTRAppealFiledDate"),
}


@pytest.fixture
def live_browser(tmp_path) -> AcisBrowser:
    return AcisBrowser(profile_dir=tmp_path / "profile")


async def test_captcha_token_is_accepted(live_browser):
    async with live_browser as browser:
        with pytest.raises(CaseNotFoundError):
            await browser.lookup("123456789", "MX", "MEXICO")


@pytest.mark.skipif(
    not (TEST_A_NUMBER and TEST_NATIONALITY),
    reason="set EOIR_TEST_A_NUMBER and EOIR_TEST_NATIONALITY",
)
async def test_payload_shape_is_unchanged(live_browser):
    nationality = resolve(TEST_NATIONALITY)
    async with live_browser as browser:
        payload = await browser.lookup(
            TEST_A_NUMBER, nationality.code, nationality.name
        )

    # Presence, not truthiness: most of these are null for any given case.
    for section, keys in REQUIRED_KEYS.items():
        assert section in payload, f"payload is missing the {section!r} section"
        missing = [key for key in keys if key not in payload[section]]
        assert not missing, f"{section} is missing {missing}"
