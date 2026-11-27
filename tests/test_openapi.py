from __future__ import annotations

import pytest

pytestmark = pytest.mark.anyio


async def test_schema_documents_responses(client):
    spec = (await client.get("/schema/openapi.json")).json()
    responses = spec["paths"]["/cases/lookup"]["post"]["responses"]
    assert "200" in responses
    assert "401" in responses
    assert "422" in responses
    assert "429" in responses
    assert "503" in responses


async def test_schema_documents_errors_as_problems_with_a_code(client):
    spec = (await client.get("/schema/openapi.json")).json()
    response = spec["paths"]["/cases/lookup"]["post"]["responses"]["404"]
    ref = response["content"]["application/problem+json"]["schema"]["$ref"]
    schema = spec["components"]["schemas"][ref.rsplit("/", 1)[-1]]
    assert {"status", "title", "detail", "code"} <= set(schema["properties"])


async def test_schema_documents_lookup_body(client):
    spec = (await client.get("/schema/openapi.json")).json()
    body = spec["paths"]["/cases/lookup"]["post"]["requestBody"]["content"]
    ref = body["application/json"]["schema"]["$ref"].rsplit("/", 1)[-1]
    schema = spec["components"]["schemas"][ref]
    assert set(schema["properties"]) == {"a_number", "nationality", "refresh"}
    assert set(schema["required"]) == {"a_number", "nationality"}


async def test_schema_documents_acis_payload(client):
    schemas = (await client.get("/schema/openapi.json")).json()["components"]["schemas"]
    assert {"Data", "Proceeding", "Schedule"} <= set(
        schemas["ACISPayload"]["properties"]
    )
    assert schemas["ACISSchedule"]["properties"]["AdjTime"]["description"]
    assert schemas["ACISAppeal"]["properties"]["FiledDate"]["description"]


async def test_schema_excludes_portal(client):
    paths = (await client.get("/schema/openapi.json")).json()["paths"]
    assert not any(p.startswith("/portal") for p in paths)


async def test_schema_description_uses_request_base_url(client):
    spec = (
        await client.get(
            "/schema/openapi.json",
            headers={"host": "eoir.example.org"},
        )
    ).json()
    assert '"http://eoir.example.org"' in spec["info"]["description"]
    assert "{base_url}" not in spec["info"]["description"]


async def test_schema_root_serves_scalar(client):
    response = await client.get("/schema")
    assert response.headers["content-type"].startswith("text/html")
    assert "scalar" in response.text.lower()
