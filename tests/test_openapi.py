from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def test_schema_documents_responses(client):
    spec = (await client.get("/schema/openapi.json")).json()
    responses = spec["paths"]["/cases/{a_number}"]["get"]["responses"]
    assert "200" in responses
    assert "422" in responses
    assert "429" in responses
    assert "503" in responses
