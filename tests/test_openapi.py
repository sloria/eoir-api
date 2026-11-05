from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def test_schema_documents_responses(client):
    spec = (await client.get("/schema/openapi.json")).json()
    responses = spec["paths"]["/cases/lookup"]["post"]["responses"]
    assert "200" in responses
    assert "422" in responses
    assert "429" in responses
    assert "503" in responses


async def test_schema_documents_lookup_body(client):
    spec = (await client.get("/schema/openapi.json")).json()
    body = spec["paths"]["/cases/lookup"]["post"]["requestBody"]["content"]
    ref = body["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
    schema = spec["components"]["schemas"][ref]
    assert set(schema["properties"]) == {"a_number", "nationality", "refresh"}
    assert set(schema["required"]) == {"a_number", "nationality"}
